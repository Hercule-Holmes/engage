# -*- coding: utf-8 -*-
"""Agent 配置——支持 .env 文件(项目根)与环境变量, 环境变量优先。
.env 由 .gitignore 排除, 密钥不会入库; 模板见 .env.example。"""
import os
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _parse_env_file(path: Path) -> dict:
    """极简 .env 解析: 支持 #注释 / 空行 / KEY=VALUE / 可选引号 / export 前缀。"""
    out = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            out[key] = val
    return out


def load_env_file(path: Path = _ROOT / ".env", overwrite: bool = False) -> None:
    """把 .env 条目注入 os.environ(默认不覆盖已存在的真实环境变量)。"""
    for k, v in _parse_env_file(path).items():
        if overwrite or k not in os.environ:
            os.environ[k] = v


@dataclass
class Config:
    base_url: str          # OpenAI兼容接口地址
    api_key: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 4000
    max_iterations: int = 12         # 防死循环护栏(非质量规则), 按模型窗口调整
    max_tool_calls: int = 30         # 防死循环护栏: 同信息重复调用会被预算拦下
    context_char_budget: int = 200000  # 上下文字符预算(1M窗口模型可再调大; 小窗口模型请调低)
    verbose: bool = False


def load() -> Config:
    load_env_file()
    return Config(
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        model=os.environ.get("AGENT_MODEL", "gpt-4o-mini"),
        max_iterations=int(os.environ.get("AGENT_MAX_ITERATIONS", "12")),
        max_tool_calls=int(os.environ.get("AGENT_MAX_TOOL_CALLS", "30")),
        context_char_budget=int(os.environ.get("AGENT_CONTEXT_BUDGET", "200000")),
        verbose=os.environ.get("AGENT_VERBOSE", "") == "1",
    )
