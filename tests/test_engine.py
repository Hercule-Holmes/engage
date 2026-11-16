# -*- coding: utf-8 -*-
"""引擎单元测试——手算用例对拍（pytest 风格，python -m pytest tests/ 运行）"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engage_core import engine  # noqa: E402


def test_resolve_alias():
    assert engine.resolve_name("克萝艾")["id"] == "chloe"
    assert engine.resolve_name("Chloé")["id"] == "chloe"
    assert engine.resolve_name("花月")["id"] == "kagetsu"
    assert engine.resolve_name("剑士")["id"] == "sword_fighter"
    assert engine.resolve_name("狮鹫骑士")["id"] == "griffin_knight"
    assert engine.resolve_name("克劳艾")["id"] == "chloe"  # 模糊匹配
    assert engine.resolve_name("不存在的名字xyz") is None


def test_character_card_chloe():
    card = engine.character_card("chloe")
    assert card["name_cn"] == "克萝艾"
    assert card["个人成长率"]["spd"]["个人"] == 55
    assert card["个人成长率"]["hp"]["个人"] == 75
    # 速度成长55, 全41人并列第1 (Framme/Chloé/Lapis/Fogado 同为55, 按id序)
    rank = card["个人成长率"]["spd"]["排名"]
    assert rank.split("/")[0] in ("1", "2", "3", "4")


def test_total_growth_chloe_swordfighter():
    tg = engine.total_growth("chloe", "sword_fighter")["成长率"]
    assert tg["spd"]["合计"] == 75          # 55 + 20
    assert tg["hp"]["合计"] == 85           # 75 + 10
    assert tg["bld"]["合计"] == 5           # 5 + 0


def test_jean_expertise_doubles_class_growth():
    """吉恩: 兵种成长x2。用 Mage(mag成长25?) 动态对拍"""
    from engage_core import db
    con = db.connect()
    mage = db.query_one(con, "SELECT mag_growth FROM silver_classes WHERE id='mage'")
    con.close()
    normal = engine.total_growth("chloe", "mage")["成长率"]["mag"]
    jean = engine.total_growth("jean", "mage")["成长率"]["mag"]
    assert jean["个人"] == 20 and normal["个人"] == 35     # Jean mag 20 / Chloé mag 35
    assert jean["合计"] == jean["个人"] + mage["mag_growth"] * 2
    assert normal["合计"] == normal["个人"] + mage["mag_growth"]  # 普通角色不翻倍


def test_projection_arithmetic():
    """克萝艾 初始速13(Lv6) → 剑士(合计速成长75%) Lv20: 13+0.75*14=23.5→24"""
    ev = engine.compute_build("chloe", "sword_fighter", 20)
    p = ev["projection"]["values"]["速"]
    assert p["预测"] == round(13 + 0.75 * (20 - 6))
    # 克萝艾天资=枪(非剑), 近似规则下剑士不可转(牵绊资质未建模) → False
    assert ev["eligibility"]["eligible"] is False


def test_can_reclass_logic():
    """克萝艾天资=枪(+非天生杖); 剑士需剑 → 近似规则判不可转; 枪兵可转"""
    r1 = engine.can_reclass("chloe", "sword_fighter")
    assert r1["eligible"] is False and "剑" in r1["reason"]
    r2 = engine.can_reclass("chloe", "lance_flier")
    assert r2["eligible"] is True
    r3 = engine.can_reclass("alear", "sword_fighter")
    assert r3["eligible"] is True  # 琉尔天资剑


def test_recommend_returns_sorted():
    rec = engine.recommend_builds("kagetsu", top_n=5)
    scores = [r["score"] for r in rec["ranking"]]
    assert scores == sorted(scores, reverse=True)
    assert len(rec["ranking"]) == 5


def test_evidence_card_contract():
    """证据卡契约字段齐全(LLM 消费的标准格式)"""
    ev = engine.compute_build("alear", "divine_dragon", 20)
    for key in ("character", "query_class", "eligibility", "total_growth",
                "projection", "rank_in_class", "_assumptions"):
        assert key in ev, f"缺字段: {key}"
