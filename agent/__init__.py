# -*- coding: utf-8 -*-
"""专属 Agent: 火焰纹章Engage培养助手。
事件循环 + 工具调用(直连engage_core, 显式schema) + 上下文填充; 无记忆(会话内)。"""
from .config import Config, load  # noqa: F401
from .tools import TOOL_SCHEMAS, TOOL_NAMES, dispatch  # noqa: F401
