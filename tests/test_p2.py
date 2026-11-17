# -*- coding: utf-8 -*-
"""P2 测试: 作战证据表手算对拍 + 纹章适配 + 武器数据 + 技能语义"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engage_core import engine  # noqa: E402


def test_combat_evidence_hand_math():
    """克萝艾→狮鹫 Lv20(事件式立即转职): 投影值由引擎事件模型给出,
    此测试验证公式应用链: 伤害=atk+mt−防; 命中=武器命中+技×2+幸/2−敌回避(钳制100)"""
    ev = engine.combat_evidence("chloe", "griffin_knight", 20)
    atk, dex, lck = ev["atk_projected"], ev["dex_projected"], ev["lck_projected"]
    iron = next(w for w in ev["evidence"] if w["weapon"] == "Iron Sword")
    assert iron["mob"]["单击伤害"] == atk + 5 - 9
    raw = 90 + dex * 2 + int(lck / 2) - (2 * 10 + 5 // 2)
    assert iron["mob"]["命中%"] == min(100, max(0, raw))
    iron5 = next(w for w in ev["evidence"] if w["weapon"] == "Iron Sword+5")
    assert iron5["mt"] == iron["mt"] + 5 and iron5["hit"] == iron["hit"] + 25


def test_survival_enemy_real_weapon():
    """生存侧: 敌武器=真实数据。尤娜卡×盗贼: 基准mob=Iron Lance(mt7命中85)
    被命中率=85−(2×速+幸/2); 承伤=基准atk11+mt7−我守"""
    ev = engine.combat_evidence("yunaka", "thief", 20)
    s = ev["生存与承伤"]["mob"]
    assert "Iron Lance" in s["敌武器"]
    expected_hit = min(100, max(0, 85 - (2 * ev["spd_projected"] + int(ev["lck_projected"] / 2))))
    assert s["被命中率(基础)"] == expected_hit
    assert s["承伤(基础)"] == max(0, 11 + 7 - ev["def_projected"])


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
    """v4契约: 纯组件事实, 无band/无排序参考/无复合分; 默认按id稳定全量返回"""
    fit = engine.emblem_fit("alear", "sword_fighter")
    assert fit["count"] == len(fit["emblems"]) and fit["count"] >= 15
    ids = [r["emblem_id"] for r in fit["emblems"]]
    assert ids == sorted(ids)  # 默认id稳定序
    for r in fit["emblems"]:
        assert "排序参考" not in r and "band" not in r
        assert "精准匹配" in r and "同步技协同" in r and "入手章节" in r
    assert "不排序不分组不推荐" in fit["说明"]


def test_emblem_fit_max_chapter_and_sort():
    """效用过滤: max_chapter=3 只留第3章前可得且无DLC; sort_by='chapter'章节升序"""
    full = engine.emblem_fit("alear", "sword_fighter")
    early = engine.emblem_fit("alear", "sword_fighter", max_chapter=3)
    assert all(not x["is_dlc"] and x["入手章节"] <= 3 for x in early["emblems"])
    assert len(early["emblems"]) < len(full["emblems"])  # 过滤生效
    by_ch = engine.emblem_fit("alear", "sword_fighter", sort_by="chapter")
    chapters = [x["入手章节"] for x in by_ch["emblems"] if not x["is_dlc"]]
    assert chapters == sorted(chapters)
    by_precise = engine.emblem_fit("alear", "sword_fighter", sort_by="precise")
    types = [x["精准匹配"]["类型"] for x in by_precise["emblems"]]
    assert types.index("兵种主武器") < types.index("无")


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
