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
                  "engage_detail", "query_weapons", "tier_assessment", "get_knowledge"}


def test_schema_registry():
    """12个工具与MCP对齐; schema结构合法; 名称唯一"""
    assert TOOL_NAMES == EXPECTED_TOOLS
    names = [t["function"]["name"] for t in TOOL_SCHEMAS]
    assert len(names) == len(set(names)) == 12
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
