# -*- coding: utf-8 -*-
"""Agent 工具层测试(schema 合法性/dispatch/错误归一)——不触网, 不依赖 openai SDK"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.tools import TOOL_NAMES, TOOL_SCHEMAS, dispatch  # noqa: E402

EXPECTED_TOOLS = {"resolve_name", "character_card", "class_card", "can_reclass",
                  "compute_build", "compare_builds", "recommend_builds", "emblem_fit",
                  "engage_detail", "query_weapons", "tier_assessment", "get_knowledge",
                  "role_check"}


def test_schema_registry():
    """13个工具与MCP对齐; schema结构合法; 名称唯一"""
    assert TOOL_NAMES == EXPECTED_TOOLS
    names = [t["function"]["name"] for t in TOOL_SCHEMAS]
    assert len(names) == len(set(names)) == 13
    for t in TOOL_SCHEMAS:
        f = t["function"]
        assert t["type"] == "function"
        assert f["description"], f"{f['name']} 缺描述"
        p = f["parameters"]
        assert p["type"] == "object" and "properties" in p


def test_dispatch_happy_path():
    """resolve_name 正常调用"""
    r = json.loads(dispatch("resolve_name", '{"text": "克萝艾"}'))
    assert r["id"] == "chloe"


def test_dispatch_bad_json():
    r = json.loads(dispatch("resolve_name", "{broken"))
    assert "error" in r and "hint" in r


def test_dispatch_unknown_tool():
    r = json.loads(dispatch("no_such_tool", "{}"))
    assert "未知工具" in r["error"] and "可用工具" in r["hint"]


def test_dispatch_missing_required():
    r = json.loads(dispatch("compute_build", '{"char_id": "chloe"}'))  # 缺 class_id
    assert "error" in r


def test_dispatch_engine_error_normalized():
    """引擎层的未知id错误也被结构化包装, 不抛异常中断循环"""
    r = json.loads(dispatch("character_card", '{"char_id": "nonexist_xyz"}'))
    assert isinstance(r, (dict, list))  # 引擎返回{error:{}}或空卡, 不抛异常


def test_dispatch_compute_build_full_contract():
    r = json.loads(dispatch("compute_build",
                            '{"char_id": "alear", "class_id": "sword_fighter", "level": 20}'))
    for key in ("character", "eligibility", "total_growth", "combat"):
        assert key in r


def test_env_loader_parses_and_priority():
    """.env 解析: 注释/空行/引号/export; 环境变量优先于文件值"""
    import os
    import tempfile
    from agent.config import _parse_env_file, load_env_file
    content = "# 注释\n\nexport A=1\nB = \"hello world\"\nC='x y'\n坏行\n"
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as f:
        f.write(content)
        p = f.name
    parsed = _parse_env_file(Path(p))
    os.unlink(p)
    assert parsed == {"A": "1", "B": "hello world", "C": "x y"}
    # 优先级: 已存在的环境变量不被文件覆盖
    os.environ["ENGAGE_TEST_K"] = "from_env"
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as f:
        f.write("ENGAGE_TEST_K=from_file\n")
        p = f.name
    load_env_file(Path(p))
    os.unlink(p)
    assert os.environ["ENGAGE_TEST_K"] == "from_env"
    del os.environ["ENGAGE_TEST_K"]


def test_slice_last_turn_trace():
    """Web轨迹提取: 最后一轮的工具链按序还原, 最终回答正确"""
    from agent.loop import slice_last_turn
    msgs = [
        {"role": "user", "content": "旧问题"},
        {"role": "assistant", "content": "旧回答"},
        {"role": "user", "content": "克萝艾当剑士怎么样"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "t1", "type": "function",
                         "function": {"name": "resolve_name",
                                      "arguments": '{"text": "克萝艾"}'}}]},
        {"role": "tool", "tool_call_id": "t1", "content": '{"id": "chloe"}'},
        {"role": "assistant", "content": "可行"},
    ]
    answer, trace = slice_last_turn(msgs)
    assert answer == "可行"
    assert [t["name"] for t in trace] == ["resolve_name"]
    assert trace[0]["result"] == '{"id": "chloe"}'
