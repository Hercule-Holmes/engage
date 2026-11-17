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
    """超预算时从最旧开始把工具结果替换为占位符; system 与最后4条消息永不裁剪。"""
    total = sum(_msg_len(m) for m in messages)
    if total <= budget:
        return messages
    msgs = [dict(m) for m in messages]
    protected = set(range(len(msgs) - 4)) | {0}
    for i in range(1, len(msgs) - 4):        # 跳过system, 从最旧开始
        if total <= budget:
            break
        if i in protected:
            continue
        m = msgs[i]
        if m["role"] == "tool" and isinstance(m.get("content"), str) and len(m["content"]) > 80:
            total -= len(m["content"])
            m["content"] = "[历史工具结果已裁剪]"
        elif m["role"] == "user" and isinstance(m.get("content"), str) and len(m["content"]) > 200:
            total -= len(m["content"]) - 40
            m["content"] = m["content"][:40] + "…[已裁剪]"
    return msgs
