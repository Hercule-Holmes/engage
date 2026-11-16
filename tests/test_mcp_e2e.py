# -*- coding: utf-8 -*-
"""MCP 协议级端到端测试: 真实起 server 子进程 → stdio 握手 → list_tools → 实际调用工具
运行: python tests/test_mcp_e2e.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

SERVER = str(ROOT / "shells" / "mcp_server.py")


async def main():
    params = StdioServerParameters(command=sys.executable, args=[SERVER])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"[1] 握手成功, 工具数={len(names)}")
            assert len(names) == 11, f"期望11个工具, 实得{names}"

            # 模拟宿主LLM的完整工具链: 口语问题→resolve→compute→emblem_fit
            r1 = await session.call_tool("resolve_name", {"text": "克萝艾"})
            cid = None
            for c in r1.content:
                if hasattr(c, "text") and '"chloe"' in c.text:
                    cid = "chloe"
            assert cid == "chloe", f"resolve 失败: {r1}"
            print(f"[2] resolve_name(克萝艾) → {cid}")

            r2 = await session.call_tool(
                "compute_build", {"char_id": "chloe", "class_id": "sword_fighter", "level": 20})
            txt = "".join(c.text for c in r2.content if hasattr(c, "text"))
            assert '"spd"' in txt and "75" in txt, "compute_build 缺关键数据"
            print("[3] compute_build(克萝艾,剑士,20) → 含合计成长75 ✓")

            r3 = await session.call_tool(
                "emblem_fit", {"char_id": "alear", "class_id": "sword_fighter"})
            assert "ranking" in "".join(c.text for c in r3.content if hasattr(c, "text"))
            print("[4] emblem_fit ✓")

            r4 = await session.call_tool("get_knowledge", {"query": "追击"})
            assert "formulas.md" in "".join(c.text for c in r4.content if hasattr(c, "text"))
            print("[5] get_knowledge ✓")

            r5 = await session.call_tool(
                "query_weapons", {"weapon_type": "bow", "keyword": "Killer"})
            assert "Killer Bow" in "".join(c.text for c in r5.content if hasattr(c, "text"))
            print("[6] query_weapons ✓")

            print("\n✅ MCP 协议级端到端全部通过")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
