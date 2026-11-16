# -*- coding: utf-8 -*-
"""确定性计算引擎——本地侧全部"可运行代码重算的事实"。

契约: 本模块只输出事实与可溯源计算结果, 不做主观评价。
所有近似规则在返回值里带 _assumptions 字段声明。
"""
import difflib
import json

from . import db

STAT_KEYS = ["hp", "str", "mag", "dex", "spd", "def", "res", "lck"]
STAT_CN = {"hp": "HP", "str": "力", "mag": "魔", "dex": "技", "spd": "速",
           "def": "守", "res": "魔守", "lck": "幸"}
WEAPON_CN = {"sword": "剑", "lance": "枪", "axe": "斧", "bow": "弓",
             "knife": "匕首", "tome": "魔法书", "staff": "杖", "arts": "体术"}

# 查询缓存(进程内, 数据冻结无需失效)
_cache = {}


def _table(name):
    if name not in _cache:
        con = db.connect()
        _cache[name] = db.query(con, f"SELECT * FROM silver_{name}")
        con.close()
    return _cache[name]


def _index(name, key="id"):
    if f"_idx_{name}" not in _cache:
        _cache[f"_idx_{name}"] = {r[key]: r for r in _table(name)}
    return _cache[f"_idx_{name}"]


# ---------- 名称解析 ----------

def resolve_name(text: str):
    """别名 → {kind, id, ...}。精确 → 包含 → difflib 模糊。"""
    t = text.strip().lower()
    if not t:
        return None
    con = db.connect()
    row = db.query_one(con, "SELECT * FROM silver_aliases WHERE alias=?", (t,))
    if not row:
        rows = db.query(con, "SELECT * FROM silver_aliases WHERE alias LIKE ?", (f"%{t}%",))
        if len(rows) == 1:
            row = rows[0]
        elif rows:
            row = min(rows, key=lambda r: len(r["alias"]))
        else:
            all_a = db.query(con, "SELECT * FROM silver_aliases")
            names = [r["alias"] for r in all_a]
            close = difflib.get_close_matches(t, names, n=1, cutoff=0.6)
            row = next((r for r in all_a if r["alias"] == close[0]), None) if close else None
    con.close()
    if not row:
        return None
    # kind: character → silver_characters; class → silver_classes
    table = "characters" if row["kind"] == "character" else "classes"
    rec = _index(table).get(row["ref_id"], {})
    return {"kind": row["kind"], "id": row["ref_id"],
            "name_cn": rec.get("name_cn"), "name_en": rec.get("name_en")}


# ---------- 卡片 ----------

def _growth_rank(char_id: str, stat: str) -> int:
    """该角色某属性个人成长在全角色中的排名(1起)"""
    chars = _table("characters")
    vals = sorted(((c[stat + "_growth"], c["id"]) for c in chars),
                  key=lambda x: (-x[0], x[1]))
    return [cid for _, cid in vals].index(char_id) + 1


def character_card(char_id: str) -> dict:
    c = _index("characters").get(char_id)
    if not c:
        return {}
    innate = [p["weapon"] for p in json.loads(c["proficiencies"]) if p["innate"]]
    innate_all = [p for p in json.loads(c["proficiencies"])]
    growths = {}
    for s in STAT_KEYS:
        g = c[s + "_growth"]
        growths[s] = {"个人": g, "排名": f"{_growth_rank(char_id, s)}/41"}
    return {
        "id": c["id"], "name_cn": c["name_cn"], "name_en": c["name_en"],
        "join": {"章节": c["join_chapter"], "方式": c["join_how"]},
        "初始": {"等级": c["level_start"], "兵种": c["class_start"]},
        "基础值": {s: c[s + "_base"] for s in STAT_KEYS} | {"体格": c["bld_base"], "移动": c["mov_start"]},
        "个人成长率": growths,
        "个人特技": {"名称": c["personal_skill"], "效果": c["personal_skill_desc"]},
        "天资(自带资质)": [{"武器": WEAPON_CN.get(p["weapon"], p["weapon"]),
                            "天生": p["innate"]} for p in innate_all],
        "上限修正": json.loads(c["max_modifiers"]),
        "SP": c["sp"], "is_dlc": bool(c["is_dlc"]), "备注": c["note"],
    }


def class_card(class_id: str) -> dict:
    k = _index("classes").get(class_id)
    if not k:
        return {}
    skills = [s for s in _table("class_skills") if s["class_id"] == class_id]
    req = json.loads(k["req_proficiency"])
    return {
        "id": k["id"], "name_cn": k["name_cn"], "name_en": k["name_en"],
        "tier": k["tier"], "移动类型": k["movement_type"],
        "主武器": WEAPON_CN.get(k["primary_weapon"]) if k["primary_weapon"] else "无(特殊)",
        "可武器": json.loads(k["primary_weapon_alt"]) if k["primary_weapon_alt"] else [],
        "基础值": {s: k[s + "_base"] for s in STAT_KEYS} | {"体格": k["bld_base"], "移动": k["mov"]},
        "兵种成长率": {s: k[s + "_growth"] for s in STAT_KEYS} | {"体格": k["bld_growth"]},
        "兵种上限": {s: k[s + "_max"] for s in STAT_KEYS} | {"体格": k["bld_max"]},
        "资质要求": req,
        "兵种技能": [{"名称": s["name"], "效果": s["desc"]} for s in skills],
        "克制": k["weak"], "cn_unverified": bool(k["cn_unverified"]),
    }


# ---------- 转职资格(近似规则, 已声明假设) ----------

def can_reclass(char_id: str, class_id: str) -> dict:
    c = _index("characters").get(char_id)
    k = _index("classes").get(class_id)
    if not (c and k):
        return {"eligible": False, "reason": "未知角色或兵种"}
    innate = {p["weapon"] for p in json.loads(c["proficiencies"]) if p["innate"]}
    pw = k["primary_weapon"]
    if pw is None:
        return {"eligible": True, "reason": "该兵种无资质要求", "_assumption": "舞娘类特殊兵种"}
    if c["class_start"] == k["name_en"]:
        return {"eligible": True, "reason": "当前初始兵种"}
    if pw in innate:
        return {"eligible": True, "reason": f"天资自带{WEAPON_CN[pw]}资质"}
    return {
        "eligible": False,
        "reason": f"缺{WEAPON_CN[pw]}资质——游戏中可通过提升纹章士牵绊等级获得, 本库未建模牵绊资质",
        "_assumption": "近似规则: 仅判天资; 实际游戏牵绊Lv达标即可转, 结论偏保守",
    }


# ---------- 成长计算 ----------

def total_growth(char_id: str, class_id: str) -> dict:
    """个人+兵种=合计成长率; Jean(吉恩)个人特技使兵种部分x2"""
    c = _index("characters").get(char_id)
    k = _index("classes").get(class_id)
    if not (c and k):
        return {}
    expertise = "Jean" == c["name_en"]
    mult = 2 if expertise else 1
    out = {}
    for s in STAT_KEYS:
        pg, kg = c[s + "_growth"], k[s + "_growth"]
        out[s] = {"个人": pg, "兵种": kg * mult, "合计": pg + kg * mult}
    bld_pg, bld_kg = c["bld_growth"], k["bld_growth"]
    out["bld"] = {"个人": bld_pg, "兵种": bld_kg * mult, "合计": bld_pg + bld_kg * mult}
    notes = []
    if expertise:
        notes.append("吉恩个人特技[英才]: 兵种成长率x2已应用")
    return {"成长率": out, "备注": notes}


def _class_total_rank(char_id: str, class_id: str, stat: str, total: int) -> str:
    """该角色转该兵种后的合计成长, 在全部角色转同一兵种中的排名"""
    chars = _table("characters")
    k = _index("classes").get(class_id)
    mult_for = lambda c: 2 if c["name_en"] == "Jean" else 1
    vals = sorted(((c[stat + "_growth"] + k[stat + "_growth"] * mult_for(c), c["id"])
                   for c in chars), key=lambda x: (-x[0], x[1]))
    return f"{[cid for _, cid in vals].index(char_id) + 1}/{len(chars)}"


def compute_build(char_id: str, class_id: str, level: int | None = None) -> dict:
    """证据卡(P1版): 资格+合计成长+排名+等级预测。作战证据表在P2接入武器后补。"""
    c = _index("characters").get(char_id)
    k = _index("classes").get(class_id)
    if not (c and k):
        return {"error": "未知角色或兵种"}
    elig = can_reclass(char_id, class_id)
    tg = total_growth(char_id, class_id)
    lvl = level or 20
    base_lvl = c["level_start"]
    eff_lvl = max(level or 20, base_lvl)
    mod = json.loads(c["max_modifiers"])
    projection = {}
    for s in STAT_KEYS:
        g = tg["成长率"][s]["合计"] / 100.0
        est = c[s + "_base"] + g * (eff_lvl - base_lvl)
        cap = k[s + "_max"] + mod.get(s, 0)
        projection[STAT_CN[s]] = {"预测": round(est), "兵种上限": cap,
                                  "触上限": est >= cap}
    return {
        "character": {"id": char_id, "cn": c["name_cn"], "en": c["name_en"]},
        "query_class": {"id": class_id, "cn": k["name_cn"], "tier": k["tier"],
                        "移动类型": k["movement_type"]},
        "eligibility": elig,
        "total_growth": tg["成长率"],
        "growth_notes": tg["备注"],
        "projection": {"level": eff_lvl, "values": projection},
        "rank_in_class": {s: _class_total_rank(char_id, class_id, s, tg["成长率"][s]["合计"])
                          for s in STAT_KEYS},
        "combat": combat_evidence(char_id, class_id, eff_lvl),
        "_assumptions": [
            "预测=角色初始值+合计成长率x升级数(期望值,四舍五入); 转职精确内部等级规则未建模",
            "上限=兵种上限+个人上限修正(符号约定待校准)",
            "作战证据表(伤害/命中/射程)P2接入武器数据后提供",
        ] + ([elig["_assumption"]] if "_assumption" in elig else []),
    }


def compare_builds(char_id: str, class_ids: list[str], level: int | None = None) -> list[dict]:
    return [compute_build(char_id, cid, level) for cid in class_ids]


# ---------- 武器/作战证据(P2) ----------

_bench_cache = {}


def _benchmarks():
    if "bench" not in _bench_cache:
        import json as _json
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "data" / "benchmarks.json"
        _bench_cache["bench"] = _json.loads(p.read_text(encoding="utf-8"))
    return _bench_cache["bench"]


def _weapons(family: str) -> list[dict]:
    if "weapons" not in _cache:
        con = db.connect()
        _cache["weapons"] = db.query(con, "SELECT * FROM silver_weapons")
        con.close()
    return [w for w in _cache["weapons"] if w["type"] == family]


def _representative_weapons(family: str) -> list[dict]:
    """代表武器: benchmarks.json 显式配置(base/mid/high/crit), base/high 各出 +5 锻造版"""
    ws = _weapons(family)
    if not ws:
        return []
    conf = _benchmarks()["representative_weapons"].get(family, {})
    by_name = {w["name_en"]: w for w in ws}
    out = []
    forge_c = _benchmarks()["constants"]["forge_per_level"]
    for tier_key, label in (("base", "base"), ("mid", "mid"),
                            ("high", "high"), ("crit", "crit")):
        w = by_name.get(conf.get(tier_key) or "")
        if not w:
            continue
        out.append({**w, "label": label, "forge": 0})
        if tier_key in ("base", "high"):
            out.append({**w, "label": f"{label}+5", "forge": 5,
                        "mt": w["mt"] + 5 * forge_c["mt"],
                        "hit": w["hit"] + 5 * forge_c["hit"]})
    return out


def _projection_stats(char_id: str, class_id: str, level: int) -> dict:
    """等级预测值(内部辅助): 返回含体格的预测dict + 上限"""
    c, k = _index("characters").get(char_id), _index("classes").get(class_id)
    tg = total_growth(char_id, class_id)["成长率"]
    base_lvl = c["level_start"]
    eff = max(level, base_lvl)
    mod = json.loads(c["max_modifiers"])
    out = {}
    keys = STAT_KEYS + ["bld"]
    for s in keys:
        est = c[s + "_base"] + tg[s]["合计"] / 100.0 * (eff - base_lvl)
        cap_key = s + "_max"
        cap = k.get(cap_key, k["bld_max"] if s == "bld" else None)
        if cap is not None:
            cap += mod.get(s, 0) if s != "bld" else 0
        out[s] = {"预测": round(est), "上限": cap}
    return out


def combat_evidence(char_id: str, class_id: str, level: int = 20) -> dict:
    """作战证据表: 该角色转该兵种后, 用代表武器打三档基准敌的单击表现。"""
    c, k = _index("characters").get(char_id), _index("classes").get(class_id)
    if not (c and k):
        return {"error": "未知角色或兵种"}
    pw = k["primary_weapon"]
    if not pw or pw not in ("sword", "lance", "axe", "bow", "knife", "tome", "arts"):
        return {"error": f"该兵种主武器({pw})不入作战证据表"}
    proj = _projection_stats(char_id, class_id, level)
    atk_key = "mag" if pw == "tome" else "str"
    atk = proj[atk_key]["预测"]
    bld = proj["bld"]["预测"]
    spd = proj["spd"]["预测"]
    follow_gap = _benchmarks()["constants"]["follow_gap"]

    rows, patterns = [], set()
    for w in _representative_weapons(pw):
        as_atk = spd - max(0, w["wt"] - bld)
        entry = {"weapon": f"{w['name_en']}{'+%d' % w['forge'] if w['forge'] else ''}",
                 "label": w["label"], "mt": w["mt"], "hit": w["hit"],
                 "wt": w["wt"], "rng": w["rng_max"]}
        for bid, enemy in _benchmarks()["enemies"].items():
            enemy_def = enemy["res"] if pw == "tome" else enemy["def"]
            dmg = atk + w["mt"] - enemy_def
            hit = min(100, max(0, w["hit"] - (2 * enemy["spd"] + enemy["lck"] // 2)))
            can_follow = (as_atk - enemy["spd"]) >= follow_gap
            counter_safe = w["rng_max"] >= 2 and enemy["rng"] == 1
            entry[bid] = {"单击伤害": dmg, "命中%": hit,
                          "追击": can_follow, "反击安全": counter_safe}
            if dmg >= 0.9 * enemy["hp"]:
                patterns.add(f"one_shot_{bid}")
                if w["rng_max"] >= 2:
                    patterns.add("one_shot_ranged")
            if can_follow:
                patterns.add(f"doubles_{bid}")
        rows.append(entry)
    return {
        "character": {"id": char_id, "cn": c["name_cn"]},
        "class": {"id": class_id, "cn": k["name_cn"]},
        "atk_stat": "魔" if pw == "tome" else "力",
        "atk_projected": atk, "spd_projected": spd, "bld_projected": bld,
        "evidence": rows,
        "patterns_hit": sorted(patterns),
        "source": {"公式": ["F1", "F2", "F3", "F5"],
                   "基准敌": "data/benchmarks.json(gold口径,待校准)"},
        "_assumptions": ["追击差值基准5待游戏内确认", "敌方AS用敌速近似(敌武器重量未建模)",
                         "必杀倍率未启用"],
    }


def emblem_fit(char_id: str, class_id: str, top_n: int = 3) -> dict:
    """纹章士适配 v2: 组件化输出(精准匹配/额外重合/同步技协同), 排序仅作参考。
    组件是事实; 哪个纹章士"最好"由 LLM 结合组件自行判断。"""
    c, k = _index("characters").get(char_id), _index("classes").get(class_id)
    if not (c and k):
        return {"error": "未知角色或兵种"}
    innate = {p["weapon"] for p in json.loads(c["proficiencies"]) if p["innate"]}
    mine = innate | {k["primary_weapon"]} | set(json.loads(k["primary_weapon_alt"] or "[]"))

    # 路线偏好: 由兵种移动类型/主武器决定(口径草案)
    if k["movement_type"] == "Covert":
        pref = {"avoid", "crit"}
    elif k["primary_weapon"] == "staff":
        pref = {"heal", "exp"}
    elif k["movement_type"] == "Armor":
        pref = {"stat_def_res"}
    elif k["movement_type"] == "Flying":
        pref = {"spd", "move"}
    else:
        pref = {"damage", "hit"}

    con = db.connect()
    emblems = db.query(con, "SELECT * FROM silver_emblems")
    con.close()

    ranked = []
    for e in emblems:
        ws = json.loads(e["weapons"])
        primary = ws[0] if ws else None
        # 精准匹配: 主武器==兵种主武器(30) 或 ==角色天资(20), 取高
        if primary and primary == k["primary_weapon"]:
            precise, precise_why = 30, f"{WEAPON_CN.get(primary, primary)}==兵种主武器"
        elif primary and primary in innate:
            precise, precise_why = 20, f"{WEAPON_CN.get(primary, primary)}==角色天资"
        else:
            precise, precise_why = 0, "无精准匹配"
        extra = sorted((set(ws) - {primary}) & mine)
        extra_pts = len(extra) * 5
        # 同步技协同: 该纹章士技能语义的效果类型 ∩ 路线偏好
        con = db.connect()
        sems = db.query(con, "SELECT name, semantic FROM silver_skills_semantic "
                             "WHERE source_kind='emblem' AND source_id=?", (e["id"],))
        con.close()
        hits = []
        for srow in sems:
            sem = json.loads(srow["semantic"])
            for et in sem.get("effect_types", []):
                if et in pref and srow["name"] not in {h[0] for h in hits}:
                    hits.append((srow["name"], et))
        synergy = min(len(hits) * 6, 12)
        ref_score = precise + extra_pts + synergy
        ranked.append({
            "emblem_id": e["id"], "cn": e["name_cn"], "主武器": WEAPON_CN.get(primary, primary),
            "精准匹配": {"分": precise, "依据": precise_why},
            "额外重合": {"武器": [WEAPON_CN.get(w, w) for w in extra], "分": extra_pts},
            "同步技协同": {"命中": [{"技能": n, "类型": WEAPON_CN.get(t, t) if t in WEAPON_CN else t}
                                    for n, t in hits[:4]], "分": synergy},
            "排序参考": ref_score,
        })
    ranked.sort(key=lambda x: (-x["排序参考"], x["emblem_id"]))
    return {
        "character": {"id": char_id, "cn": c["name_cn"]},
        "query_class": {"id": class_id, "cn": k["name_cn"], "移动类型": k["movement_type"]},
        "可用武器集": [WEAPON_CN.get(w, w) for w in sorted(mine)],
        "路线偏好效果": sorted(pref),
        "ranking": ranked[:top_n],
        "说明": "排序参考=组件简单相加,仅便于浏览;哪个纹章士更好请结合组件自行判断",
        "_assumption": "纹章士主武器映射与路线偏好均为口径草稿(weapons_unverified项待校对)",
    }


# ---------- P4: 个人技价值 / 初始战力 / tier 证据卡 ----------

_vc_cache = {}


def _value_constants():
    if "vc" not in _vc_cache:
        import json as _json
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "knowledge" / "value_constants.json"
        _vc_cache["vc"] = _json.loads(p.read_text(encoding="utf-8"))
    return _vc_cache["vc"]


def _personal_semantic(char_id: str) -> dict | None:
    """该角色个人技的语义结构(正则直提, 非转述)"""
    con = db.connect()
    row = db.query_one(
        con, "SELECT semantic FROM silver_skills_semantic WHERE source_kind='personal' AND source_id=?",
        (char_id,))
    con.close()
    return json.loads(row["semantic"]) if row else None


def personal_skill_value(char_id: str) -> dict:
    """个人技的机械换算小计(仅参考) = Σ(效果数值×单价)×触发折扣, 逐项可溯源。
    注意: 这是机械口径的参考值, 技能的真实价值(如是否定义玩法)由 LLM 综合判断。"""
    sem = _personal_semantic(char_id)
    vc = _value_constants()
    if not sem:
        return {"机械估小计": 0, "说明": "无个人技语义数据"}
    desc = sem.get("desc", "")
    d = desc.lower()
    discount = 1.0
    discount_name = "无条件"
    for kw, name in vc["触发关键词映射"].items():
        if kw in d:
            discount = vc["触发折扣"][name]
            discount_name = name
            break
    items, total = [], 0.0
    prices = vc["效果单价"]
    for e in sem.get("effects", []):
        etype = e["type"]
        price = prices.get(etype)
        if price is None:
            continue
        vals = [float(v.rstrip("%")) for v in e.get("values", []) if v.rstrip("%").lstrip("+-").replace(".", "").isdigit()]
        if not vals:
            continue
        cap = vc.get("单效果封顶", 15)
        v = min(sum(vals), cap) * price * discount
        total += v
        items.append({"类型": etype, "数值": vals, "单价": price,
                      "折扣": discount_name, "小计": round(v, 2)})
    notes = []
    if "growth" in desc.lower() or "double" in desc.lower():
        notes.append("成长类特技不在此计价(已在成长计算中单独建模, 如吉恩英才)")
    return {"机械估小计": round(total, 2), "折扣档": discount_name, "明细": items,
            "原文": desc, "备注": notes,
            "source": {"表": "silver_skills_semantic", "口径": "knowledge/value_constants.json"}}


def _chapter_enemy(chapter: int) -> dict:
    """章节插值基准敌(口径见 value_constants.章节基准曲线)"""
    c = max(1, min(26, chapter))
    return {"hp": round(18 + 1.2 * c), "def": round(3 + 0.6 * c),
            "res": round(2 + 0.5 * c), "spd": round(4 + 0.5 * c),
            "lck": round(0.4 * c), "rng": 1, "chapter": c}


def base_strength(char_id: str) -> dict:
    """初始即时战力: 加入时点用初始兵种打章节插值杂兵的表现。"""
    c = _index("characters").get(char_id)
    if not c:
        return {"error": "未知角色"}
    ch = c["join_chapter"] or 1
    enemy = _chapter_enemy(ch)
    k = None
    # 初始兵种匹配: 精确 → 家族名(char_base表用无后缀名如'Noble') → 按角色名消歧
    exact = [cand for cand in _table("classes") if cand["name_en"] == c["class_start"]]
    if exact:
        k = exact[0]
    else:
        fk = c["class_start"].lower().strip()
        fam = [cand for cand in _table("classes")
               if cand["name_en"].lower().split(" (")[0].strip() == fk]
        if len(fam) == 1:
            k = fam[0]
        elif len(fam) > 1:
            own = c["name_en"].lower()
            for cand in fam:  # 括号内含角色名者优先(Noble (Céline) ↔ Céline)
                if own[:4] in cand["name_en"].lower():
                    k = cand
                    break
            k = k or fam[0]
    if not k:
        return {"error": f"初始兵种{c['class_start']}未入库"}
    pw = k["primary_weapon"] or "sword"
    fallback_note = None
    if pw == "staff":  # 杖系初始兵种无攻击代表武器 → 回退天资中的攻击武器
        innate = {p["weapon"] for p in json.loads(c["proficiencies"]) if p["innate"]}
        alt = sorted(innate - {"staff"})
        pw = alt[0] if alt else "tome"
        fallback_note = f"初始兵种主武器为杖, 即时战力改用天资武器({WEAPON_CN[pw]})估算"
    atk_key = "mag" if pw == "tome" else "str"
    w = _representative_weapons(pw)
    base_w = next((x for x in w if x["label"] == "base"), w[0] if w else None)
    if not base_w:
        return {"error": "无代表武器"}
    atk = c[atk_key + "_base"]
    dmg = atk + base_w["mt"] - enemy["def"]
    hit = min(100, max(0, base_w["hit"] - (2 * enemy["spd"] + enemy["lck"] // 2)))
    bld = c["bld_base"]
    as_atk = c["spd_base"] - max(0, base_w["wt"] - bld)
    follow = (as_atk - enemy["spd"]) >= _benchmarks()["constants"]["follow_gap"]
    score = round(max(dmg, 1) + 0.3 * hit + (5 if follow else 0), 1)
    return {
        "character": {"id": char_id, "cn": c["name_cn"]},
        "加入": {"章节": ch, "等级": c["level_start"], "兵种": k["name_cn"]},
        "章节敌": enemy,
        "表现": {"单击伤害": dmg, "命中率": hit, "追击": bool(follow)},
        "即时战力分": score,
        "备注": fallback_note,
        "source": {"公式": ["F1", "F2", "F3"], "曲线": "章节基准曲线(草案)"},
    }


def tier_assessment(char_id: str) -> dict:
    """分项事实卡(P5反锚定版): 只输出三个独立分项的原始值与全游戏排名,
    不提供任何加权综合分/综合排名——综合强度判断由 LLM 自行论证。"""
    c = _index("characters").get(char_id)
    if not c:
        return {"error": "未知角色"}
    rows = []
    for other in _table("characters"):
        oid = other["id"]
        bs = base_strength(oid).get("即时战力分") or 0
        g = sorted((other[s + "_growth"] for s in STAT_KEYS), reverse=True)
        rows.append({"id": oid, "cn": other["name_cn"],
                     "base": bs, "growth": sum(g[:5]),
                     "psv": personal_skill_value(oid).get("机械估小计") or 0})

    def rank_of(key, val):
        vals = sorted((r[key] for r in rows), reverse=True)
        return f"{vals.index(val) + 1}/{len(rows)}"

    mine = next(r for r in rows if r["id"] == char_id)
    psv_detail = personal_skill_value(char_id)
    return {
        "character": {"id": char_id, "cn": c["name_cn"]},
        "分项事实": {
            "初始即时战力": {"值": mine["base"], "全游戏排名": rank_of("base", mine["base"]),
                            "依据": "加入时初始值对章节插值基准敌的作战表现(公式F1-F3)"},
            "成长潜力": {"值": mine["growth"], "全游戏排名": rank_of("growth", mine["growth"]),
                        "口径": "个人成长率Top5之和(专精口径)"},
            "个人技价值": {"机械估小计": mine["psv"], "全游戏排名": rank_of("psv", mine["psv"]),
                          "明细": psv_detail.get("明细", []),
                          "口径": "机械换算参考值——技能的真实价值(是否定义玩法)请综合判断"},
        },
        "说明": "引擎只提供分项事实,没有官方综合分;综合强度判断须自行论证并说明权衡逻辑",
        "source": {"表": ["silver_characters", "silver_skills_semantic"],
                   "口径": "knowledge/value_constants.json"},
        "_assumptions": ["章节基准曲线与效果单价均为草案",
                         "DLC角色加入章节缺失时按第12章近似"],
    }


# ---------- 知识检索(P3) ----------

def get_knowledge(query: str, max_chars: int = 1200) -> dict:
    """knowledge/*.md 全文关键词检索(小体量, 无向量库)。"""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "knowledge"
    hits = []
    for f in sorted(root.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        if query.lower() in text.lower():
            i = text.lower().index(query.lower())
            hits.append({"file": f.name, "excerpt": text[max(0, i - 100): i + max_chars // 2]})
    return {"query": query, "files": [h["file"] for h in hits],
            "excerpts": hits[:3]}


def query_weapons(weapon_type: str | None = None, keyword: str | None = None) -> list[dict]:
    """武器查询: 按类型(剑/枪/斧/弓/匕首/魔法书/体术/杖/special)与名称关键词过滤。"""
    con = db.connect()
    rows = db.query(con, "SELECT * FROM silver_weapons")
    staves = db.query(con, "SELECT * FROM silver_staves")
    con.close()
    out = []
    for w in rows:
        if weapon_type and w["type"] != weapon_type:
            continue
        if keyword and keyword.lower() not in w["name_en"].lower():
            continue
        out.append({k2: w[k2] for k2 in
                    ("name_en", "type", "mt", "hit", "crit", "wt", "rng_min", "rng_max", "req_rank", "notes")})
    for s in staves:
        if weapon_type in ("staff", "杖", None) and (not keyword or keyword.lower() in s["name_en"].lower()):
            out.append({"name_en": s["name_en"], "type": "staff",
                        "rng_min": s["rng_min"], "rng_max": s["rng_max"],
                        "req_rank": s["req_rank"], "pow": s["pow"], "notes": s["notes"]})
    return out


def recommend_builds(char_id: str, top_n: int = 5) -> dict:
    """按角色个人成长前三高属性, 累加各兵种对应成长率排序(透明规则, 见score_note)。"""
    c = _index("characters").get(char_id)
    if not c:
        return {"error": "未知角色"}
    # 口径: 非HP战斗属性Top3(HP成长不应主导兵种选择——低HP高闪避/高防兵种同样可主战)
    combat_stats = [s for s in STAT_KEYS if s != "hp"]
    top3 = sorted(combat_stats, key=lambda s: -c[s + "_growth"])[:3]
    scored = []
    for k in _table("classes"):
        if not k["player_usable"] or k["id"] in {c["id"]}:
            continue
        score = sum(k[s + "_growth"] for s in top3)
        innate = {p["weapon"] for p in json.loads(c["proficiencies"]) if p["innate"]}
        weapon_bonus = 5 if k["primary_weapon"] in innate else 0
        scored.append({"class_id": k["id"], "name_cn": k["name_cn"],
                       "tier": k["tier"], "移动类型": k["movement_type"],
                       "score": score + weapon_bonus,
                       "top3成长加总": score, "天资武器加成": weapon_bonus})
    scored.sort(key=lambda x: (-x["score"], x["class_id"]))
    return {
        "character": {"id": char_id, "cn": c["name_cn"]},
        "top3个人成长": [f"{STAT_CN[s]} {c[s+'_growth']}" for s in top3],
        "ranking": scored[:top_n],
        "score_note": "分数=角色个人成长前三属性对应兵种成长加总+天资武器加成5; 仅为排序启发式,非强度结论",
    }
