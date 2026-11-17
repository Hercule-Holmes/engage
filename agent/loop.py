# -*- coding: utf-8 -*-
"""事件循环: 用户输入 → LLM(带工具schema) → tool_calls? → 执行 → 回喂 → 再调LLM → 输出文本。"""
import json
import sys
import time
from pathlib import Path

from openai import OpenAI

from .config import load
from .context import new_session, trim, validate_and_heal
from .prompt import SYSTEM_PROMPT
from .tools import TOOL_SCHEMAS, dispatch

def slice_last_turn(messages: list) -> tuple[str, list]:
    """提取最后一轮的轨迹(纯函数): (最终回答, [{name,args,result}, ...])。
    Web 层用它把工具链渲染成可折叠卡片。"""
    last_user = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=-1)
    pending, order = {}, []
    answer = ""
    for m in messages[last_user + 1:]:
        if m["role"] == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                pending[tc["id"]] = {"name": tc["function"]["name"],
                                     "args": tc["function"]["arguments"]}
                order.append(tc["id"])
        elif m["role"] == "tool":
            tid = m.get("tool_call_id")
            if tid in pending:
                pending[tid]["result"] = m.get("content", "")
        elif m["role"] == "assistant":
            answer = m.get("content", "")
    return answer, [pending[tid] for tid in order if tid in pending]


BANNER = """火焰纹章Engage培养助手 (agent v1)
模型: {model} @ {base_url}
配置: .env 文件(项目根, 参考 .env.example)或环境变量
命令: /new 重置会话 | /tools 工具列表 | /exit 退出
直接用中文提问, 如: 克萝艾当剑士怎么样 / 尤娜卡强不强 / 花月配什么纹章士"""


def run_turn(client, cfg, messages, user_input: str,
             stats: dict | None = None) -> tuple[str, dict]:
    """处理一轮用户输入: 返回 (最终文本, stats 运行统计)。
    stats 可传外部 dict——异常中断时调用方仍能拿到已完成调用的部分统计。
    统计项: model / llm_calls / tool_calls / empty_retries /
    prompt_tokens / completion_tokens / total_tokens(本轮API实报累加) /
    context_tokens_last(最后一次请求的prompt_tokens=真实上下文占用) /
    context_chars_last / finish_reason_last / elapsed_ms / calls(逐次明细)。
    护栏: 工具循环上限 + 工具调用总数上限(超限强制收尾) + 空响应检测重试。
    异常安全: 异常时回滚到本轮输入前, 防止残段毒化历史; 每次LLM调用前做消息结构自愈;
    出错时把发送的完整消息序列落盘到 logs/, 供事后定位。"""
    import json as _json

    def _dump_error(kind: str, detail: str, sent_messages: list):
        try:
            log_dir = Path(__file__).resolve().parent.parent / "logs"
            log_dir.mkdir(exist_ok=True)
            (log_dir / "last_error.json").write_text(_json.dumps(
                {"kind": kind, "detail": detail, "model": cfg.model,
                 "sent_messages": sent_messages}, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except Exception:
            pass

    if stats is None:
        stats = {}
    stats.update({"model": cfg.model, "llm_calls": 0, "tool_calls": 0,
                  "empty_retries": 0, "prompt_tokens": 0, "completion_tokens": 0,
                  "total_tokens": 0, "context_tokens_last": None,
                  "context_chars_last": None, "finish_reason_last": None,
                  "elapsed_ms": None, "calls": []})
    n0 = len(messages)
    answer = None
    empty_retries = 0
    tool_calls_made = 0
    budget_noted = False
    t0 = time.perf_counter()
    try:
        messages.append({"role": "user", "content": user_input})

        for _ in range(cfg.max_iterations):
            use_tools = TOOL_SCHEMAS if tool_calls_made < cfg.max_tool_calls else None
            if use_tools is None and not budget_noted:
                messages.append({"role": "user",
                                 "content": "(系统提示: 工具调用预算已用完。请立即基于已获得的"
                                            "证据直接回答用户的问题, 不要再尝试调用工具。)"})
                budget_noted = True

            # --- LLM 调用(发送前结构自愈 + 空响应检测/重试) ---
            msg = finish = None
            got = False
            sent = None
            for attempt in range(3):
                sent = validate_and_heal(trim(messages, cfg.context_char_budget))
                kwargs = dict(model=cfg.model, messages=sent,
                              temperature=cfg.temperature, max_tokens=cfg.max_tokens)
                if use_tools:
                    kwargs["tools"] = use_tools
                try:
                    resp = client.chat.completions.create(**kwargs)
                except Exception as e:
                    _dump_error("http_error", f"{type(e).__name__}: {e}", sent)
                    raise
                # --- 用量统计(空响应同样消耗token, 一并计入) ---
                usage = getattr(resp, "usage", None)
                pt = getattr(usage, "prompt_tokens", 0) or 0
                ct = getattr(usage, "completion_tokens", 0) or 0
                stats["prompt_tokens"] += pt
                stats["completion_tokens"] += ct
                stats["total_tokens"] += pt + ct
                stats["context_tokens_last"] = pt
                stats["context_chars_last"] = sum(
                    len(m.get("content") or "") for m in sent)
                stats["llm_calls"] += 1
                stats["calls"].append({"prompt_tokens": pt,
                                       "completion_tokens": ct, "finish": None})
                choice = resp.choices[0]
                msg, finish = choice.message, choice.finish_reason
                stats["calls"][-1]["finish"] = finish
                stats["finish_reason_last"] = finish
                calls = getattr(msg, "tool_calls", None)
                content = (msg.content or "").strip()
                if content or calls:
                    got = True
                    break
                empty_retries += 1
                stats["empty_retries"] = empty_retries
                if cfg.verbose:
                    print(f"  [诊断] 空响应#{empty_retries} finish={finish} "
                          f"model={cfg.model}(重试中…)")
                if finish == "length":
                    _dump_error("empty_response_length",
                                f"finish={finish}", sent)
                    break  # 长度截断的重试无意义, 直接报错

            if not got:
                _dump_error("empty_response", f"finish={finish}", sent or messages)
                if finish == "length":
                    return (f"❌ 模型响应被截断(finish=length, max_tokens={cfg.max_tokens})。"
                            f"常见原因: 推理模型先消耗token思考。"
                            f"建议: 调大 AGENT_MAX_TOKENS 或换非推理模型。", stats)
                return (f"❌ 连续{empty_retries}次空响应(finish={finish}, model={cfg.model})。"
                        f"常见原因: 模型不支持工具调用/端点兼容性/网络中断。"
                        f"建议: 换普通对话模型; 详细序列已存 logs/last_error.json。", stats)

            content = (msg.content or "").strip()
            if not msg.tool_calls:
                messages.append({"role": "assistant", "content": content})
                answer = content
                break

            # 结构化回填 assistant(tool_calls), 逐个执行并回喂
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name,
                                  "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                result = dispatch(tc.function.name, tc.function.arguments)
                tool_calls_made += 1
                if cfg.verbose:
                    preview = result[:160].replace("\n", " ")
                    print(f"  [工具] {tc.function.name}({tc.function.arguments[:60]}) → {preview}…")
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": result})

        if answer is None:
            answer = (f"已达单轮最大工具调用次数({cfg.max_iterations})。"
                      f"问题较复杂——请拆成小问题, 或直接说\"详细\"让我基于已有证据总结。")
        return answer, stats
    except Exception:
        # 异常安全: 回滚到本轮输入前, 防止残段毒化后续会话
        del messages[n0:]
        raise
    finally:
        stats["tool_calls"] = tool_calls_made
        stats["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load()
    if not cfg.api_key:
        print("缺少 OPENAI_API_KEY。请在项目根的 .env 文件中填入"
              "(模板见 .env.example), 或设置同名环境变量。")
        sys.exit(1)

    client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)
    messages = new_session()
    print(BANNER.format(model=cfg.model, base_url=cfg.base_url))

    while True:
        try:
            line = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("/exit", "/q", "退出"):
            break
        if line == "/new":
            messages = new_session()
            messages.append({"role": "system", "content": SYSTEM_PROMPT})
            print("(会话已重置)")
            continue
        if line == "/tools":
            print("工具:", ", ".join(sorted({t["function"]["name"] for t in TOOL_SCHEMAS})))
            continue
        try:
            ans, st = run_turn(client, cfg, messages, line)
            print(ans)
            print(f"  [stats] ↑{st['prompt_tokens']} ↓{st['completion_tokens']} tok · "
                  f"LLM×{st['llm_calls']} 工具×{st['tool_calls']}"
                  f"{' 重试×'+str(st['empty_retries']) if st['empty_retries'] else ''}"
                  f" · {st['elapsed_ms'] / 1000:.1f}s"
                  + (f" · 上下文{st['context_tokens_last']}tok"
                     if st['context_tokens_last'] else ""))
        except Exception as e:
            print(f"[错误] {type(e).__name__}: {e}\n(检查网络/API配置, 或 /new 重置会话)")


if __name__ == "__main__":
    main()
