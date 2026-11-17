# -*- coding: utf-8 -*-
"""事件循环: 用户输入 → LLM(带工具schema) → tool_calls? → 执行 → 回喂 → 再调LLM → 输出文本。"""
import json
import sys

from openai import OpenAI

from .config import load
from .context import new_session, trim
from .prompt import SYSTEM_PROMPT
from .tools import TOOL_SCHEMAS, dispatch

BANNER = """火焰纹章Engage培养助手 (agent v1)
模型: {model} @ {base_url}
命令: /new 重置会话 | /tools 工具列表 | /exit 退出
直接用中文提问, 如: 克萝艾当剑士怎么样 / 尤娜卡强不强 / 花月配什么纹章士"""


def run_turn(client, cfg, messages, user_input: str) -> str:
    """处理一轮用户输入: 返回最终文本输出。工具循环含上限护栏。"""
    messages.append({"role": "user", "content": user_input})
    answer = None
    for _ in range(cfg.max_iterations):
        trimmed = trim(messages, cfg.context_char_budget)
        resp = client.chat.completions.create(
            model=cfg.model,
            messages=trimmed,
            tools=TOOL_SCHEMAS,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            messages.append({"role": "assistant", "content": msg.content or ""})
            answer = msg.content or "(空响应)"
            break
        # 结构化回填 assistant 消息(含tool_calls), 保持协议完整
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
            if cfg.verbose:
                preview = result[:160].replace("\n", " ")
                print(f"  [工具] {tc.function.name}({tc.function.arguments[:60]}) → {preview}…")
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": result})
    if answer is None:
        answer = (f"已达单轮最大工具调用次数({cfg.max_iterations}), "
                  f"问题较复杂——请拆成小问题(如先问'某某怎么样'再问'配什么纹章士')。")
    return answer


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load()
    if not cfg.api_key:
        print("缺少 OPENAI_API_KEY 环境变量。示例:\n"
              "  set OPENAI_API_KEY=sk-xxx\n"
              "  set OPENAI_BASE_URL=https://api.deepseek.com/v1   (可选, 默认OpenAI官方)\n"
              "  set AGENT_MODEL=deepseek-chat                     (可选)")
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
            print(run_turn(client, cfg, messages, line))
        except Exception as e:
            print(f"[错误] {type(e).__name__}: {e}\n(检查网络/API配置, 或 /new 重置会话)")


if __name__ == "__main__":
    main()
