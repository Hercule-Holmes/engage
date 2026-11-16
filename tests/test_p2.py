# -*- coding: utf-8 -*-
"""P2 测试: 作战证据表手算对拍 + 纹章适配 + 武器数据 + 技能语义"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engage_core import engine  # noqa: E402


def test_combat_evidence_hand_math():
    """克萝艾→狮鹫 Lv20: 力预测13(8+0.35×14=12.9→13); 铁剑mt5 vs 杂兵def9 → 伤害9;
    命中=90−(2×10+5//2)=68; 锻造+5 → 伤害14/命中93"""
    ev = engine.combat_evidence("chloe", "griffin_knight", 20)
    assert ev["atk_projected"] == 13
    iron = next(w for w in ev["evidence"] if w["weapon"] == "Iron Sword")
    assert iron["mob"]["单击伤害"] == 13 + 5 - 9
    assert iron["mob"]["命中%"] == 90 - (2 * 10 + 5 // 2)
    iron5 = next(w for w in ev["evidence"] if w["weapon"] == "Iron Sword+5")
    assert iron5["mt"] == iron["mt"] + 5 and iron5["hit"] == iron["hit"] + 25


def test_representative_weapons_exclude_specials():
    """剑系代表武器必须是常规系列, 不含重剑(Blade)/特效剑"""
    reps = engine._representative_weapons("sword")
    names = [w["name_en"] for w in reps]
    assert "Iron Sword" in names and "Iron Blade" not in names
    labels = [w["label"] for w in reps]
    assert "base+5" in labels and "high+5" in labels


def test_pattern_one_shot_logic():
    """银剑+5打杂兵: 21伤害 ≥ 28×0.9=25.2? 否 → 不应含 one_shot_mob(当前预测下)"""
    ev = engine.combat_evidence("chloe", "griffin_knight", 20)
    s5 = next(w for w in ev["evidence"] if w["weapon"] == "Silver Sword+5")
    expect = s5["mob"]["单击伤害"] >= 0.9 * 28
    assert ("one_shot_mob" in ev["patterns_hit"]) == expect


def test_pattern_bow_counter_safe():
    """弓系打近战基准敌 → 反击安全=True"""
    ev = engine.combat_evidence("etie", "sniper", 20)
    assert any(w["rng"] >= 2 for w in ev["evidence"])
    assert all(w["boss"]["反击安全"] for w in ev["evidence"] if w["rng"] >= 2)


def test_emblem_fit_shape():
    fit = engine.emblem_fit("alear", "sword_fighter")
    assert fit["ranking"] and "排序参考" in fit["ranking"][0]
    assert all("精准匹配" in r and "同步技协同" in r for r in fit["ranking"])


def test_weapons_real_values():
    """抽样真实数值(Serenes): 必杀剑/雷神剑/银剑"""
    ks = {w["name_en"]: w for w in engine.query_weapons("sword")}
    assert ks["Killing Edge"]["mt"] == 9 and ks["Killing Edge"]["crit"] == 30
    assert ks["Levin Sword"]["rng_max"] == 2 and ks["Levin Sword"]["mt"] == 13


def test_skill_semantic_populated():
    """技能语义层已入库且覆盖率高"""
    from engage_core import db
    con = db.connect()
    total = db.query_one(con, "SELECT COUNT(*) c FROM silver_skills_semantic")["c"]
    partial = db.query_one(con, "SELECT COUNT(*) c FROM silver_skills_semantic WHERE coverage='partial'")["c"]
    con.close()
    assert total > 500 and partial / total < 0.2


def test_knowledge_search():
    r = engine.get_knowledge("追击")
    assert "formulas.md" in r["files"]
