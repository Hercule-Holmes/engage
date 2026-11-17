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
    """P6事件式投影(F8社区逆向口径): 克萝艾(枪飞兵Lv6)立即转剑士→Lv20
    段1(0次升级, T=加入等级) → 段2基础差(剑士基础−枪飞基础) → 段3合计成长×14(平转保级)"""
    ev = engine.compute_build("chloe", "sword_fighter", 20)
    from engage_core import db
    con = db.connect()
    ch = db.query_one(con, "SELECT spd_base, level_start FROM silver_characters WHERE id='chloe'")
    lf = db.query_one(con, "SELECT spd_base, spd_growth FROM silver_classes WHERE id='lance_flier'")
    sw = db.query_one(con, "SELECT spd_base, spd_growth FROM silver_classes WHERE id='sword_fighter'")
    con.close()
    # 速度: 加入显示值 + 段1(0级) + 基础差(sw_base−lf_base) + (个人55+剑士)成长×(20−6)
    g_new = 55 + sw["spd_growth"]
    expect_spd = int(ch["spd_base"] + (sw["spd_base"] - lf["spd_base"]) + g_new / 100 * (20 - 6) + 0.5)
    p = ev["projection"]["values"]["速"]
    assert p["预测"] == expect_spd, f"got {p['预测']} expect {expect_spd}"
    # 转职规则: basic→basic = 平转, 等级保持(不重置)
    assert ev["projection"]["转职规则"]["重置等级为1"] is False
    assert ev["projection"]["转职点T"] == 6  # promote_at未传 → 立即转职(T=加入等级)
    # 克萝艾天资=枪(非剑), 近似规则下剑士不可转(牵绊资质未建模) → False
    assert ev["eligibility"]["eligible"] is False


def test_projection_promotion_arithmetic():
    """晋升口径: 克萝艾枪飞Lv10→狮鹫骑士(advanced)→Lv20。
    段1=加入值+合计(个人55+枪飞)×4; 段2=基础差; 段3=19次×合计(个人55+狮鹫)"""
    from engage_core import db
    con = db.connect()
    ch = db.query_one(con, "SELECT spd_base FROM silver_characters WHERE id='chloe'")
    lf = db.query_one(con, "SELECT spd_base, spd_growth FROM silver_classes WHERE id='lance_flier'")
    gb = db.query_one(con, "SELECT spd_base, spd_growth FROM silver_classes WHERE id='griffin_knight'")
    con.close()
    ev = engine.compute_build("chloe", "griffin_knight", 20, promote_at=10)
    v1 = ch["spd_base"] + (55 + lf["spd_growth"]) / 100 * 4      # Lv6→Lv10
    v2 = v1 + (gb["spd_base"] - lf["spd_base"])                  # 晋升瞬间
    expect = int(v2 + (55 + gb["spd_growth"]) / 100 * 19 + 0.5)  # 重置1→20
    got = ev["projection"]["values"]["速"]["预测"]
    assert got == expect, f"got {got} expect {expect}"
    assert ev["projection"]["转职规则"]["重置等级为1"] is True    # basic→advanced
    assert ev["projection"]["段3升级次数"] == 19


def test_projection_promote_at_comparison():
    """promote_at 对比: Lv12转 vs 未传(晋升钳制到最早Lv10), 轨迹不同且均可用"""
    ev_late = engine.compute_build("chloe", "griffin_knight", 20, promote_at=12)
    ev_now = engine.compute_build("chloe", "griffin_knight", 20)
    assert ev_late["projection"]["转职点T"] == 12
    assert ev_now["projection"]["转职点T"] == 10  # 晋升未传promote_at → 钳制到Master Seal下限Lv10
    # 段3升级次数: 晋升重置→都是 level−1=19, 但段1次数不同
    assert ev_late["projection"]["段3升级次数"] == 19
    # 晚转者段1多练2级(合计速成长65%×2=+1.3), 速度预测应更高
    spd_late = ev_late["projection"]["values"]["速"]["预测"]
    spd_now = ev_now["projection"]["values"]["速"]["预测"]
    assert spd_late > spd_now
    # 分段明细存在且可读
    assert ev_late["projection"]["分段明细"][0]["属性"] == "HP"


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


# ---------- 名称解析容错层(P6: 语音同音/规范化/多候选) ----------

def test_resolve_voice_homophone():
    """语音同音字: 拼音层兜底(花悦→花月, 优娜卡→尤娜卡)"""
    r = engine.resolve_name("花悦")
    assert r and r["id"] == "kagetsu" and r["matched_by"] == "pinyin"
    r2 = engine.resolve_name("优娜卡")
    assert r2 and r2["id"] == "yunaka" and r2["matched_by"] == "pinyin"


def test_resolve_fuzzy_pinyin():
    """方言模糊音: n/l 归并(尤娜卡 younaka ↔ 由拉卡 younaka 同为模糊口径)"""
    r = engine.resolve_name("由拉卡")
    assert r and r["id"] == "yunaka"


def test_resolve_normalization():
    """规范化: 空格/大小写/全角/重音折叠(é→e), chloé 与 chloe 双别名归同实体"""
    assert engine.resolve_name("花 月")["id"] == "kagetsu"
    r = engine.resolve_name("CHLOE")
    assert r and r["id"] == "chloe" and r["matched_by"] == "exact"
    assert engine.resolve_name("ｃｈｌｏé")["id"] == "chloe"


def test_resolve_multi_candidates():
    """同层多实体命中 → 返回 candidates 交调用方裁决, 不静默取第一个"""
    r = engine.resolve_name("娜")
    assert r and "candidates" in r
    ids = {c["id"] for c in r["candidates"]}
    assert {"anna", "yunaka"} <= ids
    assert all("score" in c and "matched_by" in c for c in r["candidates"])


def test_resolve_edge_inputs():
    """空/None/无命中 → None; 原编辑距离用例保持"""
    assert engine.resolve_name("不存在的名字xyz") is None
    assert engine.resolve_name("") is None
    assert engine.resolve_name(None) is None
    assert engine.resolve_name("克劳艾")["id"] == "chloe"  # 原模糊匹配回归


def test_pinyin_map_runtime_zero_dep():
    """拼音全字表已入库且引擎查询零第三方依赖(只查表)"""
    from engage_core import db as _db
    con = _db.connect()
    n = con.execute("SELECT COUNT(*) FROM silver_pinyin_map").fetchone()[0]
    con.close()
    assert n > 15000  # CJK 基本区+扩展A 全量映射
    pm = engine._pinyin_map()
    assert pm["花"] == ("hua", pm["花"][1])  # py 与 py_fuzzy 结构齐全
