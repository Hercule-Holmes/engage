# -*- coding: utf-8 -*-
"""确定性计算引擎——本地侧全部"可运行代码重算的事实"。

契约: 本模块只输出事实与可溯源计算结果, 不做主观评价。
所有近似规则在返回值里带 _assumptions 字段声明。
"""
import difflib
import json

from . import db
from .textnorm import norm

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


# ---------- 名称解析(分层容错) ----------
# 层序: 规范化精确 → 包含 → 拼音(语音同音字) → 模糊音(方言口音) → 编辑距离(打字手误)。
# 唯一命中直接返回; 同层多实体命中返回 candidates 交调用方裁决——
# 宁可多问一句, 不静默错配(错配会把错误实体写进证据卡, 比"未识别"危害大)。

_LAYERS = (("exact", 1.0), ("contains", 0.9), ("pinyin", 0.85), ("fuzzy_pinyin", 0.7))


def _pinyin_map() -> dict:
    """汉字 → (拼音, 模糊音) 全字映射, 进程内缓存。构建期由 build_silver 用 pypinyin 生成,
    运行时只查表, 零第三方依赖。"""
    if "py_map" not in _cache:
        con = db.connect()
        rows = con.execute("SELECT char, py, py_fuzzy FROM silver_pinyin_map").fetchall()
        con.close()
        _cache["py_map"] = {r[0]: (r[1], r[2]) for r in rows}
    return _cache["py_map"]


def _to_pinyin(text: str, fuzzy: bool = False) -> str:
    pm = _pinyin_map()
    out = []
    for ch in text:
        if ch in pm:
            out.append(pm[ch][1] if fuzzy else pm[ch][0])
        elif ch.isascii() and ch.isalnum():
            out.append(ch.lower())
    return "".join(out)


def _aliases() -> list[dict]:
    """别名 + 规范化列 + 派生拼音, 进程内缓存(数据冻结无需失效)。"""
    if "aliases_v2" not in _cache:
        con = db.connect()
        rows = db.query(con, "SELECT * FROM silver_aliases")
        con.close()
        for r in rows:
            r["norm"] = r["alias_norm"] or norm(r["alias"])
            r["py"] = _to_pinyin(r["norm"])
            r["py_f"] = _to_pinyin(r["norm"], fuzzy=True)
        _cache["aliases_v2"] = rows
    return _cache["aliases_v2"]


def _dedup_entities(hits: list[dict]) -> list[dict]:
    """同一实体(kind, ref_id)的多个别名变体折叠为一条(如 chloé/chloe)。"""
    seen, out = set(), []
    for a in hits:
        key = (a["kind"], a["ref_id"])
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out


def _entry(score: float, row: dict, matched_by: str) -> dict:
    table = "characters" if row["kind"] == "character" else "classes"
    rec = _index(table).get(row["ref_id"], {})
    return {"kind": row["kind"], "id": row["ref_id"],
            "name_cn": rec.get("name_cn"), "name_en": rec.get("name_en"),
            "matched_by": matched_by, "score": round(score, 3)}


def resolve_name(text: str):
    """别名 → 实体。规范化→精确→包含→拼音→模糊音→编辑距离, 五层依次兜底。

    返回:
      唯一命中  {kind, id, name_cn, name_en, matched_by, score}
      多候选    {query, candidates: [上型 ≤5]}  ——调用方须结合上下文选择或向用户确认
      无命中    None
    """
    t = (text or "").strip()
    q = norm(t)
    if not q:
        return None
    als = _aliases()
    has_cjk = any(0x3400 <= ord(c) <= 0x9FFF for c in q)
    q_py = _to_pinyin(q) if has_cjk else ""
    q_pyf = _to_pinyin(q, fuzzy=True) if has_cjk else ""

    found = None  # (matched_by, [(score, row)])
    for name, base in _LAYERS:
        if name == "exact":
            rows = [a for a in als if a["norm"] == q]
        elif name == "contains":
            rows = [a for a in als if q in a["norm"]]
        elif name == "pinyin":
            rows = [a for a in als if a["py"] == q_py] if q_py else []
        else:
            rows = [a for a in als if a["py_f"] == q_pyf] if q_pyf else []
        rows = _dedup_entities(rows)
        if rows:
            found = (name, [(base, r) for r in rows])
            break

    if found is None:
        scored = sorted(((difflib.SequenceMatcher(None, q, a["norm"]).ratio(), a)
                         for a in als), key=lambda x: (-x[0], x[1]["ref_id"]))
        best = {}
        for s, a in scored:
            if s < 0.6:
                break
            k = (a["kind"], a["ref_id"])
            if k not in best:
                best[k] = (s, a)
        found = ("edit", sorted(best.values(), key=lambda x: (-x[0], x[1]["ref_id"]))[:5])

    matched_by, items = found
    entries = [_entry(s, r, matched_by) for s, r in items]
    if not entries:
        return None
    if len(entries) == 1:
        return entries[0]
    return {"query": t, "candidates": entries[:5]}


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


def compute_build(char_id: str, class_id: str, level: int | None = 20,
                  promote_at: int | None = None) -> dict:
    """路线评估证据卡(P6事件式): 资格+合计成长+分段预测+排名+作战证据。
    promote_at: 转职点(当前兵种显示等级); None=立即转职。"""
    c = _index("characters").get(char_id)
    k = _index("classes").get(class_id)
    if not (c and k):
        return {"error": "未知角色或兵种"}
    elig = can_reclass(char_id, class_id)
    tg = total_growth(char_id, class_id)
    lvl = level or 20
    proj = _projection_stats(char_id, class_id, lvl, promote_at)
    steps = proj.pop("_steps", {})
    projection = {STAT_CN[s]: {"预测": proj[s]["预测"], "兵种上限": proj[s]["上限"],
                               "触上限": proj[s]["触顶"]}
                  for s in STAT_KEYS}
    return {
        "character": {"id": char_id, "cn": c["name_cn"], "en": c["name_en"]},
        "query_class": {"id": class_id, "cn": k["name_cn"], "tier": k["tier"],
                        "移动类型": k["movement_type"]},
        "eligibility": elig,
        "total_growth": tg["成长率"],
        "growth_notes": tg["备注"],
        "projection": {"level": lvl,
                       "转职规则": steps.get("规则"),
                       "转职点T": steps.get("转职点T"),
                       "段3升级次数": steps.get("段3升级次数"),
                       "values": projection,
                       "分段明细": steps.get("分段")},
        "rank_in_class": {s: _class_total_rank(char_id, class_id, s, tg["成长率"][s]["合计"])
                          for s in STAT_KEYS},
        "combat": combat_evidence(char_id, class_id, lvl, promote_at),
        "_assumptions": [
            "事件式预测(口径=社区逆向, 见knowledge/formulas.md): "
            "段1旧兵种合计成长→转职点T; 段2只换兵种基础偏移(个人部分保留); 段3新兵种合计成长",
            "晋升(初级→上级)等级重置为1, 平转保持(用户确认+fireemblemwiki Level条目); "
            "晋升最早Lv10可行(Master Seal下限), promote_at未传时转职点取最早可行时点",
            "仅建模 单次转职(加入兵种→目标兵种), 多次转职链未建模; "
            "段2按静态偏移差值, 兵种基础不随内部等级缩放(Reddit数据挖掘调查2023-02确认)",
            "上限=兵种上限+个人上限修正(符号约定待校准); 中途触顶截断未建模(只报最终触顶)",
        ] + ([elig["_assumption"]] if "_assumption" in elig else []),
    }


def compare_builds(char_id: str, class_ids: list[str], level: int | None = 20,
                   promote_at: int | None = None) -> list[dict]:
    return [compute_build(char_id, cid, level, promote_at) for cid in class_ids]


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


def _class_by_start(c: dict):
    """按角色的初始兵种名找 silver_classes 行(精确→家族名→按角色名消歧)"""
    fk = c["class_start"].lower().strip()
    exact = [k for k in _table("classes") if k["name_en"] == c["class_start"]]
    if exact:
        return exact[0]
    fam = [k for k in _table("classes")
           if k["name_en"].lower().split(" (")[0].strip() == fk]
    if len(fam) == 1:
        return fam[0]
    own = c["name_en"].lower()
    for cand in fam:
        if own[:4] in cand["name_en"].lower():
            return cand
    return fam[0] if fam else None


def _tier_rules(tier_old: str, tier_new: str) -> dict:
    """转职等级规则(P6口径, 用户确认2026-11-17):
    晋升(初级/专属起点 → 上级/DLC): 显示等级重置为1
    平转(同阶级): 等级保持; 降级: 保持(草案)"""
    up = tier_old in ("basic", "starting") and tier_new in ("advanced", "dlc")
    return {"重置等级为1": up, "类型": "晋升" if up else "平转/降级(等级保持)"}


def _projection_stats(char_id: str, class_id: str, level: int,
                      promote_at: int | None = None) -> dict:
    """事件式等级预测(P6, 口径对齐社区逆向):
    游戏内部模型(社区数据挖掘确认): 个人部分与兵种基础分离——
      显示值 = 兵种基础(静态偏移) + 个人部分,
      个人部分 = 真实个人基础 + 个人成长×(加入等级−1)(加入时自动升级, 只用个人成长),
      入队后每级升级按合计成长(个人+当前兵种)累进个人部分。
    三段事件模型:
      段1: 加入显示值 + 合计成长(个人+旧兵种) × (T−加入等级)
      段2: 转职瞬间只换兵种基础偏移: + (新兵种基础 − 旧兵种基础)   [个人部分保留]
      段3: 合计成长(个人+新兵种) × 剩余升级数
           晋升(初级/起点→上级/DLC): 显示等级重置为1 → 次数=目标显示等级−1
           平转(同阶级): 等级保持 → 次数=目标显示等级−T
    promote_at: 转职点(当前兵种显示等级); None=最早可行时点
              (平转=加入等级[Second Seal无等级要求]; 晋升=Lv10[Master Seal下限])
    返回: {stat: {预测, 上限}, ..., "_steps": 分段明细}"""
    c = _index("characters").get(char_id)
    k_new = _index("classes").get(class_id)
    if not (c and k_new):
        return {}
    k_old = _class_by_start(c) or k_new
    L0 = c["level_start"]
    T = max(promote_at or 0, L0)          # 平转: Second Seal 无等级要求(Lv1即可), 不早于加入等级
    rules = _tier_rules(k_old["tier"], k_new["tier"])
    reset = rules["重置等级为1"]
    clamped = False
    if reset:
        # 晋升(Master Seal): 最低Lv10(fireemblemwiki Master Seal/Second Seal 条目)
        if T < 10:
            T, clamped = 10, True
    start_new_lv = 1 if reset else T
    levels3 = max(0, level - start_new_lv)
    mod = json.loads(c["max_modifiers"])
    expertise = 2 if c["name_en"] == "Jean" else 1   # 吉恩个人技: 兵种成长×2
    keys = STAT_KEYS + ["bld"]
    proj, steps = {}, []
    for s in keys:
        is_bld = s == "bld"
        join_disp = c[s + "_base"] if not is_bld else c["bld_base"]   # 加入时显示值
        old_base = (k_old[s + "_base"] if not is_bld else k_old["bld_base"])
        new_base = (k_new[s + "_base"] if not is_bld else k_new["bld_base"])
        pg = c[s + "_growth"] if not is_bld else c["bld_growth"]      # 个人成长
        g_old = pg + k_old[(s if not is_bld else "bld") + "_growth"] * expertise   # 合计
        g_new = pg + k_new[(s if not is_bld else "bld") + "_growth"] * expertise   # 合计
        v1 = join_disp + g_old / 100.0 * (T - L0)                       # 段1
        v2 = v1 + (new_base - old_base)                                 # 段2: 基础差值
        v3 = v2 + g_new / 100.0 * levels3                               # 段3
        cap = (k_new["bld_max"] if is_bld else k_new[s + "_max"])
        if cap is not None and not is_bld:
            cap += mod.get(s, 0)
        proj[s] = {"预测": int(v3 + 0.5), "上限": cap, "触顶": v3 >= cap}   # 四舍五入(半值进位)
        steps.append({"属性": STAT_CN.get(s, "体格"),
                      "加入显示值": join_disp,
                      "段1(旧兵种练到转职点)": round(v1, 1),
                      "段2(兵种基础差)": new_base - old_base,
                      "段3(新兵种成长)": round(v3, 1),
                      "最终": round(v3)})
    return {**proj, "_steps": {"起点兵种": k_old["name_en"], "转职点T": T,
                               "规则": rules,
                               "转职点钳制说明": "晋升需Lv10(Master Seal下限), 转职点已钳制" if clamped else "",
                               "新兵种起始显示等级": start_new_lv,
                               "段3升级次数": levels3,
                               "分段": steps}}


def forge_hit(w) -> int:
    """锻造命中加成(+5/级)"""
    return w.get("forge", 0) * _benchmarks()["constants"]["forge_per_level"]["hit"]


def role_check(char_id: str, class_id: str, level: int = 20,
               promote_at: int | None = None) -> dict:
    """定位核查: 输出该路线在各定位词表下关键指标的连续实际值 + 同兵种排名。
    引擎不判定定位归属——'算不算合格的X'由 LLM 结合定义、分布与玩法语境论证。
    命中零定位属合法结果(见词表'泛用型/过渡型')。"""
    c, k = _index("characters").get(char_id), _index("classes").get(class_id)
    if not (c and k):
        return {"error": "未知角色或兵种"}
    ev = combat_evidence(char_id, class_id, level, promote_at)
    if "error" in ev:
        return ev
    from pathlib import Path as _P
    roles = json.loads((_P(__file__).resolve().parent.parent
                        / "knowledge" / "roles.json").read_text(encoding="utf-8"))["roles"]

    # 指标集: 连续值 + 同兵种41人排名(数据驱动锚点)
    surv = ev["生存与承伤"]
    base_row = next((w for w in ev["evidence"] if w["label"] == "base"), ev["evidence"][0])
    psv = personal_skill_value(char_id)
    measures = {
        "被命中率(mob)": {"值": surv["mob"]["被命中率(基础)"], "方向": "越低越回避"},
        "承伤(mob)": {"值": surv["mob"]["承伤(基础)"], "方向": "越低越坦"},
        "单击伤害(mob)": {"值": base_row["mob"]["单击伤害"], "方向": "越高越输出"},
        "单击伤害(mage)": {"值": base_row["mage"]["单击伤害"], "方向": "对魔防目标的输出"},
        "追击(mob)": {"值": base_row["mob"]["追击"]},
        "追击(boss)": {"值": base_row["boss"]["追击"]},
        "反击安全(mob)": {"值": base_row["mob"]["反击安全"]},
        "射程": {"值": base_row["rng"]},
        "移动类型": {"值": k["movement_type"]},
        "兵种主武器": {"值": k["primary_weapon"]},
        "个人技效果类型": {"值": [i["类型"] for i in psv.get("明细", [])]},
        "成长Top5和": {"值": sum(sorted((c[s + "_growth"] for s in STAT_KEYS), reverse=True)[:5])},
        "初始即时战力": {"值": base_strength(char_id).get("即时战力分") or 0},
    }
    # 同兵种排名: 对部分连续指标计算41人分布位次
    rankings = {}
    for mkey, rkey in (("被命中率(mob)", None), ("承伤(mob)", None), ("单击伤害(mob)", None)):
        vals = []
        for other in _table("characters"):
            r = combat_evidence(other["id"], class_id, level)
            if "error" in r:
                continue
            field = "被命中率(基础)" if mkey == "被命中率(mob)" else \
                    "承伤(基础)" if mkey == "承伤(mob)" else "单击伤害"
            vals.append(r["生存与承伤"]["mob"][field] if mkey != "单击伤害(mob)"
                        else next((w["mob"]["单击伤害"] for w in r["evidence"]
                                   if w["label"] == "base"), 0))
        lower_better = mkey.startswith("被命中率") or mkey.startswith("承伤")
        svals = sorted(vals, reverse=not lower_better)
        v = {"被命中率(mob)": surv["mob"]["被命中率(基础)"],
             "承伤(mob)": surv["mob"]["承伤(基础)"],
             "单击伤害(mob)": base_row["mob"]["单击伤害"]}[mkey]
        rankings[mkey] = f"{svals.index(v) + 1}/{len(svals)}"

    return {
        "character": {"id": char_id, "cn": c["name_cn"]},
        "route": {"class_id": class_id, "cn": k["name_cn"],
                  "移动类型": k["movement_type"], "level": level},
        "指标": measures,
        "同兵种排名": rankings,
        "定位词表": roles,
        "说明": ("引擎输出指标实际值与分布位次, 不判定定位归属; "
                 "'算不算合格的X'由 LLM 按词表定义与数据分布论证; "
                 "命中零定位属合法结果(泛用型/过渡型), 用户的自定义玩法可追加词表"),
        "_assumptions": ["被命中率/承伤基于基准敌真武器+口径草案属性",
                         "指标阈值不设及格线(火纹数值线性无断点), 用分布锚点替代"],
    }


def _trigger_condition(desc: str) -> str:
    """从技能描述原文识别触发条件(仅作标签, 不做价值判断)"""
    d = (desc or "").lower()
    mapping = _value_constants().get(
        "触发条件识别",
        {"terrain": "特定地形", "full hp": "满血", "adjacent": "相邻友军",
         "initiates combat": "先攻", "once per turn": "每回合一次"})
    for kw, name in mapping.items():
        if kw in d:
            return name
    return "无条件"


def combat_evidence(char_id: str, class_id: str, level: int = 20,
                    promote_at: int | None = None) -> dict:
    """作战证据表 v3: 单击输出(按武器) + 生存与承伤(基准敌真武器) + 条件式技活事实。
    个人技为条件触发效果: 本表只输出"条件成立时"的数值影响(不打折不合并),
    条件是否成立/多常成立/值多少权重由 LLM 结合玩法语境判断。"""
    c, k = _index("characters").get(char_id), _index("classes").get(class_id)
    if not (c and k):
        return {"error": "未知角色或兵种"}
    pw = k["primary_weapon"]
    if not pw or pw not in ("sword", "lance", "axe", "bow", "knife", "tome", "arts"):
        return {"error": f"该兵种主武器({pw})不入作战证据表"}
    proj = _projection_stats(char_id, class_id, level, promote_at)
    atk_key = "mag" if pw == "tome" else "str"
    atk = proj[atk_key]["预测"]
    bld = proj["bld"]["预测"]
    spd = proj["spd"]["预测"]
    dex = proj["dex"]["预测"]
    lck = proj["lck"]["预测"]
    my_avoid = 2 * spd + int(lck / 2)          # 我方回避(基础)
    follow_gap = _benchmarks()["constants"]["follow_gap"]

    def _weapon_by_name(name):
        ws = _weapons("sword") + _weapons("lance") + _weapons("axe") + _weapons("bow") \
            + _weapons("knife") + _weapons("tome") + _weapons("arts") + _weapons("special")
        return next((w for w in ws if w["name_en"] == name), None)

    rows, patterns = [], set()
    survival = {}
    base_hit_by_bid = {}
    rep_base = next((x for x in _representative_weapons(pw) if x["label"] == "base"), None)
    for bid, enemy in _benchmarks()["enemies"].items():
        ew = _weapon_by_name(enemy["weapon"])
        ew_txt = (f"{ew['name_en']}(mt{ew['mt']} 命中{ew['hit']})" if ew else enemy["weapon"])
        # 生存侧: 敌武器=真实数据, 敌属性=基准值
        being_hit = min(100, max(0, (ew["hit"] if ew else 80) - my_avoid))
        my_def_res = (proj["res"]["预测"] if enemy.get("atk_type") == "魔法"
                      else proj["def"]["预测"])
        incoming = max(0, enemy["atk"] + (ew["mt"] if ew else 5) - my_def_res)
        enemy_as = enemy["spd"]                   # 敌AS近似=敌速(敌武器重量未建模)
        my_as = spd - max(0, (rep_base["wt"] if rep_base else 5) - bld)
        followed = (enemy_as - my_as) >= follow_gap
        survival[bid] = {"敌武器": ew_txt,
                         "被命中率(基础)": being_hit,
                         "承伤(基础)": incoming,
                         "被追击": followed}
        base_hit_by_bid[bid] = being_hit

    for w in _representative_weapons(pw):
        as_atk = spd - max(0, w["wt"] - bld)
        entry = {"weapon": f"{w['name_en']}{'+%d' % w['forge'] if w['forge'] else ''}",
                 "label": w["label"], "mt": w["mt"], "hit": w["hit"],
                 "wt": w["wt"], "rng": w["rng_max"]}
        for bid, enemy in _benchmarks()["enemies"].items():
            enemy_def = enemy["res"] if pw == "tome" else enemy["def"]
            dmg = atk + w["mt"] - enemy_def
            hit = min(100, max(0, w["hit"] + forge_hit(w) + int(dex * 2 + lck / 2)
                               - (2 * enemy["spd"] + enemy["lck"] // 2)))
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

    # 个人技战斗效果(条件式): 各效果隔离输出"条件成立时"的影响, 不打折不合并
    cond_effects = []
    sem = _personal_semantic(char_id)
    if sem:
        cond = _trigger_condition(sem.get("desc", ""))
        type_cn = {"damage": "伤害", "avoid": "回避", "hit": "命中", "crit": "必杀"}
        for e in sem.get("effects", []):
            etype = e["type"]
            if etype not in type_cn or not e.get("values"):
                continue
            v = int(sum(float(x.rstrip("%")) for x in e["values"]))
            impact = {}
            for bid, enemy in _benchmarks()["enemies"].items():
                if etype == "damage":
                    base = next((w[bid]["单击伤害"] for w in rows if w["label"] == "base"), None)
                    if base is not None:
                        impact[f"{bid}单击伤害"] = f"{base} → {base + v}"
                elif etype == "avoid":
                    b = base_hit_by_bid[bid]
                    impact[f"{bid}被命中率"] = f"{b} → {max(0, b - v)}"
                elif etype == "hit":
                    b = next((w[bid]["命中%"] for w in rows if w["label"] == "base"), None)
                    if b is not None:
                        impact[f"{bid}命中率"] = f"{b} → {min(100, b + v)}"
                elif etype == "crit":
                    impact[f"{bid}必杀"] = f"+{v}(必杀倍率未建模)"
            cond_effects.append({"效果": f"{type_cn[etype]}{v:+d}",
                                 "条件": cond, "影响": impact})
    return {
        "character": {"id": char_id, "cn": c["name_cn"]},
        "class": {"id": class_id, "cn": k["name_cn"]},
        "atk_stat": "魔" if pw == "tome" else "力",
        "atk_projected": atk, "spd_projected": spd, "bld_projected": bld,
        "dex_projected": dex, "lck_projected": lck,
        "def_projected": proj["def"]["预测"], "res_projected": proj["res"]["预测"],
        "evidence": rows,
        "生存与承伤": survival,
        "个人技效果(条件成立时)": cond_effects,
        "patterns_hit": sorted(patterns),
        "source": {"公式": ["F1", "F2", "F3", "F5", "F7"],
                   "基准敌": "data/benchmarks.json(敌武器=真实数据, 属性=口径草案)"},
        "_assumptions": ["追击差值基准5待游戏内确认", "敌方AS用敌速近似(敌武器重量未建模)",
                         "必杀倍率未启用",
                         "技活修正为'条件成立时'的假设事实, 条件价值由LLM结合玩法语境判断"],
    }


def emblem_fit(char_id: str, class_id: str, max_chapter: int | None = None,
               sort_by: str | None = None) -> dict:
    """纹章士适配 v4: 纯组件事实, 无排序无分组无复合分(P5原则: MCP只提供数据不提供判断)。
    max_chapter: 效用过滤——只看该章节前可得的非DLC纹章士(解决开荒期推荐后期纹章的荒谬)
    sort_by: 可选客观单一维度排序 'chapter'(入手章节升序,DLC殿后) / 'precise'(精准匹配降序);
             默认None=按id稳定输出。永不做复合排序。"""
    c, k = _index("characters").get(char_id), _index("classes").get(class_id)
    if not (c and k):
        return {"error": "未知角色或兵种"}
    innate = {p["weapon"] for p in json.loads(c["proficiencies"]) if p["innate"]}
    mine = innate | {k["primary_weapon"]} | set(json.loads(k["primary_weapon_alt"] or "[]"))

    # 路线偏好: 由兵种移动类型/主武器决定(口径: 移动类型启发式, 未校准)
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

    items = []

    def _rng_txt(w):
        return (f"{w['rng_min']}" if w["rng_min"] == w["rng_max"]
                else f"{w['rng_min']}-{w['rng_max']}")

    for e in emblems:
        ws = json.loads(e["weapons"])
        primary = ws[0] if ws else None
        # 精准匹配类型: 客观事实(兵种主武器/角色天资/无), 不折算分数
        if primary and primary == k["primary_weapon"]:
            match_type = "兵种主武器"
        elif primary and primary in innate:
            match_type = "角色天资"
        else:
            match_type = "无"
        extra = sorted((set(ws) - {primary}) & mine)
        # 同步技协同: 仅同步技(type=Sync*)的语义效果 ∩ 路线偏好; Engage技/奥义/可继承技不计入该组件
        con = db.connect()
        sync_names = {r["name"] for r in db.query(
            con, "SELECT name FROM silver_emblem_skills "
                 "WHERE emblem_id=? AND type LIKE 'Sync Skill%'", (e["id"],))}
        sems = db.query(con, "SELECT name, semantic FROM silver_skills_semantic "
                             "WHERE source_kind='emblem' AND source_id=?", (e["id"],))
        eg_skills = db.query(con, "SELECT name, bond_unlock FROM silver_emblem_skills "
                                  "WHERE emblem_id=? AND (type LIKE 'Engage Skill%' "
                                  "OR type LIKE 'Engage Attack%') ORDER BY bond_unlock, name",
                             (e["id"],))
        eg_weapons = db.query(con, "SELECT name_en, mt, hit, rng_min, rng_max "
                                   "FROM silver_emblem_weapons "
                                   "WHERE emblem=? AND name_en NOT LIKE '% (Normal)' "
                                   "ORDER BY name_en", (e["id"],))
        con.close()
        hits = []
        for srow in sems:
            if srow["name"] not in sync_names:
                continue
            sem = json.loads(srow["semantic"])
            for et in sem.get("effect_types", []):
                if et in pref and srow["name"] not in {h[0] for h in hits}:
                    hits.append((srow["name"], et))
        if e["is_dlc"]:
            join_txt = "DLC"
        elif e["chapter"] is not None:
            join_txt = f"第{e['chapter']}章" + ("(剧透)" if e["spoiler"] else "")
        else:
            join_txt = "未知"
        items.append({
            "emblem_id": e["id"], "cn": e["name_cn"],
            "主武器": WEAPON_CN.get(primary, primary), "入手章节": e["chapter"],
            "入手": join_txt, "is_dlc": bool(e["is_dlc"]),
            "精准匹配": {"类型": match_type, "依据": f"{WEAPON_CN.get(primary, primary)}为纹章主武器"},
            "额外重合": {"武器": [WEAPON_CN.get(w, w) for w in extra]},
            "同步技协同": {"命中": [{"技能": n, "类型": WEAPON_CN.get(t, t) if t in WEAPON_CN else t}
                                    for n, t in hits[:4]]},
            "engage技": [f"{r['name']}(牵绊{r['bond_unlock']})" for r in eg_skills],
            "engage武器": [f"{w['name_en']}(mt{w['mt']} 命中{w['hit']} 射程{_rng_txt(w)})"
                           for w in eg_weapons],
        })

    # 效用过滤: max_chapter 只保留该章节前可得(非DLC)
    if max_chapter is not None:
        items = [x for x in items if not x["is_dlc"]
                 and x["入手章节"] is not None and x["入手章节"] <= max_chapter]
    # 排序: 仅客观单一维度; 默认按id稳定输出
    if sort_by == "chapter":
        items.sort(key=lambda x: (x["入手章节"] is None, x["入手章节"] or 99,
                                  x["is_dlc"], x["emblem_id"]))
    elif sort_by == "precise":
        order = {"兵种主武器": 0, "角色天资": 1, "无": 2}
        items.sort(key=lambda x: (order[x["精准匹配"]["类型"]], x["emblem_id"]))
    else:
        items.sort(key=lambda x: x["emblem_id"])

    return {
        "character": {"id": char_id, "cn": c["name_cn"]},
        "query_class": {"id": class_id, "cn": k["name_cn"], "移动类型": k["movement_type"]},
        "可用武器集": [WEAPON_CN.get(w, w) for w in sorted(mine)],
        "路线偏好": {"效果": sorted(pref), "口径": "按移动类型/主武器启发式,未校准"},
        "效用过滤": {"max_chapter": max_chapter, "sort_by": sort_by},
        "说明": "本工具不排序不分组不推荐——组件是事实; 哪个纹章士更适合"
               "须结合效用(开荒/长期/玩法)与未建模维度由调用方自行论证",
        "详情工具": "engage_detail(emblem_id) 返回engage技完整描述与engage武器全参数(含效果注记)",
        "未建模维度": ["同步技/engage技的强度评分", "牵绊升级成本", "刻印(Engrave)系统"],
        "count": len(items),
        "emblems": items,
        "_assumption": "纹章士主武器映射为口径草稿(weapons_unverified项待校对)",
    }


def emblem_engage_detail(emblem_id: str) -> dict:
    """Engage技/奥义完整事实卡(按需详情): 技能名/解锁牵绊/完整描述 + Engage武器全参数(含效果注记)。
    emblem_fit 默认只列要点(名+解锁牵绊), 完整描述用本工具按需取。"""
    con = db.connect()
    sk = db.query(con, "SELECT name, bond_unlock, type, desc FROM silver_emblem_skills "
                       "WHERE emblem_id=? AND (type LIKE 'Engage Skill%' "
                       "OR type LIKE 'Engage Attack%') ORDER BY bond_unlock, name", (emblem_id,))
    wp = db.query(con, "SELECT name_en, type, mt, hit, crit, wt, rng_min, rng_max, notes "
                       "FROM silver_emblem_weapons "
                       "WHERE emblem=? AND name_en NOT LIKE '% (Normal)' ORDER BY name_en",
                  (emblem_id,))
    con.close()
    if not sk and not wp:
        return {"error": f"未知纹章士: {emblem_id}"}
    return {
        "emblem_id": emblem_id,
        "engage技": [{"名称": r["name"], "解锁牵绊": r["bond_unlock"], "类型": r["type"],
                     "描述": r["desc"]} for r in sk],
        "engage武器": [{"名称": r["name_en"], "类型": WEAPON_CN.get(r["type"], r["type"]),
                       "mt": r["mt"], "命中": r["hit"], "必杀": r["crit"], "重量": r["wt"],
                       "射程": f"{r['rng_min']}-{r['rng_max']}", "效果注记": r["notes"]}
                      for r in wp],
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
    """个人技的机械换算小计(仅参考) = Σ(效果数值×单价), 不含条件折扣——
    条件是否成立/多常成立/值多少权重由 LLM 结合玩法语境判断(P5契约)。"""
    sem = _personal_semantic(char_id)
    vc = _value_constants()
    if not sem:
        return {"机械估小计": 0, "说明": "无个人技语义数据"}
    desc = sem.get("desc", "")
    cond = _trigger_condition(desc)
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
        v = min(sum(vals), cap) * price
        total += v
        items.append({"类型": etype, "数值": vals, "单价": price,
                      "条件": cond, "小计": round(v, 2)})
    notes = []
    if "growth" in desc.lower() or "double" in desc.lower():
        notes.append("成长类特技不在此计价(已在成长计算中单独建模, 如吉恩英才)")
    if cond != "无条件":
        notes.append(f"触发条件={cond}: 条件成立频率与价值由 LLM 结合玩法语境判断")
    return {"机械估小计": round(total, 2), "触发条件": cond, "明细": items,
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
