# -*- coding: utf-8 -*-
"""P4/P5 测试: 个人技价值/tier事实卡/emblem_fit v2 的手算对拍与形状校验"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engage_core import engine  # noqa: E402


def test_personal_skill_value_yunaka_no_double_count():
    """P5修复后: 尤娜卡的+15只归属crit(最近关键词), 不再重复计入avoid
    → 15×0.5×0.5(地形折扣) = 3.75"""
    vc = engine._value_constants()
    v = engine.personal_skill_value("yunaka")
    expect = 15 * vc["效果单价"]["crit"] * vc["触发折扣"]["特定地形"]
    assert abs(v["机械估小计"] - expect) < 0.01, f"got {v['机械估小计']} expect {expect}"
    types = [i["类型"] for i in v["明细"]]
    assert "crit" in types and "avoid" not in types  # 重复计价已消除


def test_personal_skill_value_gold_repriced():
    """金币单价0.02后, 安娜的个人技价值不得再出现100量级"""
    v = engine.personal_skill_value("anna")["机械估小计"]
    assert v < 30


def test_base_strength_no_more_zero_lookups():
    """7个此前查不到初始兵种的角色(家族名匹配修复)必须非零"""
    for cid in ("celine", "ivy", "alcryst", "diamant", "veyle", "hortensia", "rafal"):
        r = engine.base_strength(cid)
        assert "error" not in r, f"{cid}: {r.get('error')}"
        assert r["即时战力分"] > 0


def test_chapter_enemy_curve():
    e10 = engine._chapter_enemy(10)
    e20 = engine._chapter_enemy(20)
    assert e10["def"] == 9 and e20["def"] == 15      # 校准点对齐静态基准
    assert e20["hp"] > e10["hp"]


def test_tier_assessment_is_fact_only():
    """P5反锚定: tier卡不得包含综合分/综合排名/权重, 必须包含三分项事实+独立排名"""
    t = engine.tier_assessment("yunaka")
    assert "综合分" not in t and "权重" not in t
    assert "综合排名" not in str(t.get("排名", ""))
    for k in ("初始即时战力", "成长潜力", "个人技价值"):
        assert k in t["分项事实"]
        assert "/41" in t["分项事实"][k]["全游戏排名"]
    assert "自行论证" in t["说明"]


def test_emblem_fit_v2_components():
    """emblem_fit v2: 组件拆开(精准匹配/额外重合/同步技协同), 无牵绊加值项"""
    fit = engine.emblem_fit("chloe", "griffin_knight")
    for r in fit["ranking"]:
        assert "精准匹配" in r and "额外重合" in r and "同步技协同" in r
        assert "牵绊" not in json.dumps(r, default=str)
    # 剑系路线: 精准匹配30的纹章士应出现在前排(玛尔斯/罗伊/艾克/琳等)
    top_ids = [r["emblem_id"] for r in fit["ranking"]]
    sword_emblems = {"marth", "roy", "ike", "lyn"}
    assert any(e in top_ids for e in sword_emblems), f"剑系本命纹章未进前排: {top_ids}"


def test_tier_calibration_regression():
    """校准回归: 内部工程组合分 Spearman ≥ 0.38(网格最优0.41, 留容差)"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from regression_tier import EXAM_TIERS, spearman, tier_of
    chars = engine._table("characters")
    rows = []
    for c in chars:
        t = engine.tier_assessment(c["id"])
        rows.append((t["分项事实"]["初始即时战力"]["值"],
                     t["分项事实"]["成长潜力"]["值"],
                     max(0.0, t["分项事实"]["个人技价值"]["机械估小计"]) ** 0.5,
                     tier_of(c["id"], c["id"])))
    def norm(vals):
        lo, hi = min(vals), max(vals)
        return [50.0] * len(vals) if hi == lo else [(v - lo) / (hi - lo) * 100 for v in vals]
    nb = norm([r[0] for r in rows]); ng = norm([r[1] for r in rows]); np_ = norm([r[2] for r in rows])
    scores = [nb[i] * 0.25 + ng[i] * 0.50 + np_[i] * 0.15 + 5 for i in range(len(rows))]
    tiers = [r[3] for r in rows]
    assert spearman(scores, tiers) >= 0.38
