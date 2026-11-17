# -*- coding: utf-8 -*-
"""Agent 配置——全部来自环境变量, 无配置文件"""
import os
from dataclasses import dataclass


@dataclass
class Config:
    base_url: str          # OpenAI兼容接口地址
    api_key: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 2000
    max_iterations: int = 8          # 单轮用户输入内, LLM↔工具循环上限
    context_char_budget: int = 60000  # 上下文字符预算(超出裁剪最旧工具结果)
    verbose: bool = False


def load() -> Config:
    return Config(
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        model=os.environ.get("AGENT_MODEL", "gpt-4o-mini"),
        max_iterations=int(os.environ.get("AGENT_MAX_ITERATIONS", "8")),
        context_char_budget=int(os.environ.get("AGENT_CONTEXT_BUDGET", "60000")),
        verbose=os.environ.get("AGENT_VERBOSE", "") == "1",
    )
