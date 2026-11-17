# -*- coding: utf-8 -*-
"""上下文组装与预算管理(会话内, 无记忆——退出即弃)。
裁剪策略: 超预算时, 把最旧的工具结果内容替换为占位符, 保持消息结构完整
(OpenAI协议要求 tool 消息必须跟在带 tool_calls 的 assistant 消息之后, 不能删)。"""
import json

from .prompt import SYSTEM_PROMPT


def new_session() -> list:
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def _msg_len(m: dict) -> int:
    c = m.get("content")
    if isinstance(c, str):
        return len(c)
    if c is None:
        # assistant 消息的 tool_calls 长度
        tcs = m.get("tool_calls") or []
        return sum(len(json.dumps(tc, ensure_ascii=False)) for tc in tcs)
    return len(json.dumps(c, ensure_ascii=False))


def trim(messages: list, budget: int) -> list:
    """超预算时从最旧开始把工具结果替换为占位符。
    结构保护: system 与最后6条消息不动; assistant(tool_calls)及其tool响应保持完整。"""
    total = sum(_msg_len(m) for m in messages)
    if total <= budget:
        return messages
    msgs = [dict(m) for m in messages]
    protected_tail = max(0, len(msgs) - 6)
    for i in range(1, protected_tail):       # 跳过system(0), 从最旧向新裁剪
        if total <= budget:
            break
        m = msgs[i]
        if m["role"] == "tool" and isinstance(m.get("content"), str) and len(m["content"]) > 80:
            total -= len(m["content"]) - 30
            m["content"] = "[历史工具结果已裁剪]"
        elif m["role"] == "user" and isinstance(m.get("content"), str) and len(m["content"]) > 200:
            total -= len(m["content"]) - 40
            m["content"] = m["content"][:40] + "…[已裁剪]"
    return msgs


def validate_and_heal(messages: list) -> list:
    """结构自愈: 每条带 tool_calls 的 assistant 消息, 其每个 tool_call_id 必须
    在下一个 assistant 消息前有对应的 tool 响应; 缺失则就地补上合成响应。
    修复历史会话因进程异常中断留下的残段(否则所有后续请求都会被400拒绝)。"""
    out = [dict(m) for m in messages]
    healed = 0
    i = 0
    while i < len(out):
        m = out[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            need = {tc["id"] for tc in m["tool_calls"]}
            j = i + 1
            while j < len(out) and out[j].get("role") == "tool":
                need.discard(out[j].get("tool_call_id"))
                j += 1
            if need:  # 有缺失 → 在最后一条连续tool消息后补合成响应
                insert_at = j
                for tid in sorted(need):
                    out.insert(insert_at, {"role": "tool", "tool_call_id": tid,
                                           "content": '{"error": "工具结果缺失(历史会话损坏, 已自动补齐)"}'})
                    insert_at += 1
                    healed += 1
                i = insert_at
                continue
        i += 1
    if healed:
        # 自愈后输出一条提示(不进对话流, 供日志观察)
        import sys
        print(f"  [自愈] 修复了 {healed} 条缺失的工具响应", file=sys.stderr)
    return out
