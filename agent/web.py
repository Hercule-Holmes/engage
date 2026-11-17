# -*- coding: utf-8 -*-
"""Web 界面桥接: stdlib HTTP 服务器 → 现有事件循环。
路由: GET / (聊天页) · POST /api/chat {message} → {answer, trace, stats, session}
· POST /api/reset → {ok, session}
stats=本轮运行统计(token/耗时/调用次数), session=会话累计(reset清零)。
单会话(本地个人工具), 线程锁串行化。运行: python -m agent.web"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from openai import OpenAI

from .config import load
from .context import new_session
from .loop import run_turn, slice_last_turn

STATIC = Path(__file__).resolve().parent / "static"
INDEX_HTML = (STATIC / "index.html").read_bytes()


class AgentWeb:
    def __init__(self):
        self.cfg = load()
        self.client = OpenAI(base_url=self.cfg.base_url, api_key=self.cfg.api_key)
        self.messages = new_session()
        self.lock = threading.Lock()
        self._session = {"turns": 0, "prompt_tokens": 0, "completion_tokens": 0,
                         "total_tokens": 0, "llm_calls": 0, "tool_calls": 0}
        self._last_ctx_tokens = None

    def _session_view(self) -> dict:
        return {**self._session, "messages": len(self.messages),
                "context_tokens_last": self._last_ctx_tokens,
                "budget_chars": self.cfg.context_char_budget,
                "model": self.cfg.model}

    def chat(self, message: str) -> dict:
        with self.lock:  # 单会话串行, 避免并发穿插上下文
            self.messages.append({"role": "user", "content": message})
            stats: dict = {}
            try:
                _, stats = run_turn(self.client, self.cfg, self.messages, message, stats)
            except Exception as e:  # 网络/鉴权等顶层错误结构化返回
                # run_turn 内部已回滚到本轮输入前, 此处无需再动会话;
                # stats 传入外部dict, 异常路径仍能带出已完成调用的部分统计
                if stats.get("context_tokens_last"):
                    self._last_ctx_tokens = stats["context_tokens_last"]
                return {"error": f"{type(e).__name__}: {e}",
                        "hint": "检查 .env 的 OPENAI_API_KEY / OPENAI_BASE_URL / 网络;"
                                "详细序列已存 logs/last_error.json",
                        "stats": stats, "session": self._session_view()}
            answer, trace = slice_last_turn(self.messages)
            self._session["turns"] += 1
            for k in ("prompt_tokens", "completion_tokens", "total_tokens",
                      "llm_calls", "tool_calls"):
                self._session[k] += stats.get(k) or 0
            if stats.get("context_tokens_last"):
                self._last_ctx_tokens = stats["context_tokens_last"]
            return {"answer": answer, "trace": trace,
                    "stats": stats, "session": self._session_view()}

    def reset(self) -> None:
        with self.lock:
            self.messages = new_session()
            self._session = {"turns": 0, "prompt_tokens": 0, "completion_tokens": 0,
                             "total_tokens": 0, "llm_calls": 0, "tool_calls": 0}
            self._last_ctx_tokens = None


APP = AgentWeb()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, INDEX_HTML, "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) or b"{}"
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._json(400, {"error": "请求体必须是UTF-8编码的合法JSON"})
        if self.path == "/api/chat":
            msg = (body.get("message") or "").strip()
            if not msg:
                return self._json(400, {"error": "message 为空"})
            return self._json(200, APP.chat(msg))
        if self.path == "/api/reset":
            APP.reset()
            return self._json(200, {"ok": True, "session": APP._session_view()})
        self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):  # 静默默认访问日志
        pass


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    port = int(os.environ.get("AGENT_WEB_PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Engage 培养助手 Web 界面: http://127.0.0.1:{port}  (Ctrl+C 退出)")
    server.serve_forever()


if __name__ == "__main__":
    main()
