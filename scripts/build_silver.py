# -*- coding: utf-8 -*-
"""Bronze(raw CSV) → Silver(SQLite) 建库

输出: data/engage.db
  silver_characters  角色事实表
  silver_classes     兵种事实表
  silver_class_skills 兵种技能表
  silver_aliases     别名表(EN/CN/社区别名 → id)
  silver_meta        构建元信息(来源、假设、日期)
"""
import csv
import json
import re
import sqlite3
import sys
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "engage.db"

WEAPONS = {"sword": "剑", "lance": "枪", "axe": "斧", "bow": "弓",
           "knife": "匕首", "tome": "魔法书", "staff": "杖", "arts": "体术"}

STATS = ["hp", "str", "mag", "dex", "spd", "def", "res", "lck"]


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def load_csv(key: str) -> list[list[str]]:
    path = RAW / f"{key}.csv"
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    out = []
    for r in rows:
        if not any(c.strip() for c in r):
            continue  # 真空行
        if any(c.strip() in ("Name", "Class", "Character") for c in r[:4]):
            continue  # 表头/重复表头行
        out.append(r)
    return out


def num(v: str, default=0) -> int:
    v = (v or "").strip()
    return int(v) if re.fullmatch(r"-?\d+", v) else default


def family_key(name: str) -> str:
    """'Fell Child (Veyle)' → 'fell child'；用于跨表家族名回退匹配"""
    return re.sub(r"\(.*?\)", "", name).strip().lower()


def find_row(rows_by_name: dict, en_name: str):
    """精确匹配 → 去括号家族名回退（Fell Child (Veyle)/(DLC) 等跨表命名不一致时使用）"""
    if en_name in rows_by_name:
        return rows_by_name[en_name]
    fk = family_key(en_name)
    for name, row in rows_by_name.items():
        if family_key(name) == fk:
            return row
    return None


def parse_proficiency(raw: str) -> list[dict]:
    """'Sword (Innate), Arts' → [{weapon:'sword', innate:true}, ...]"""
    out = []
    for token in re.split(r",\s*", raw.strip()):
        token = token.strip()
        if not token:
            continue
        innate = "innate" in token.lower()
        w = re.sub(r"\(.*?\)", "", token).strip().lower()
        if w in WEAPONS:
            out.append({"weapon": w, "cn": WEAPONS[w], "innate": innate})
    return out


def parse_class_weapons(raw: str) -> dict:
    """'A C^ A C^' → {tokens:[{rank:'A',marker:''},...], ranks:['A','C'], note:...}
    已知等级字母 C<B<A<S; '^'/'*' 上标含义未定, 原样保留。"""
    tokens = []
    for t in (raw or "").split():
        m = re.fullmatch(r"([ABS])([\^*]?)", t)
        if m:
            tokens.append({"rank": m.group(1), "marker": m.group(2)})
    ranks = sorted({t["rank"] for t in tokens})
    return {"raw": raw, "tokens": tokens, "ranks": ranks,
            "decode_status": "ranks确定,武器归属与^标记待校准"}


def lookup_meta(en_name: str, classes_meta: dict):
    """slug 精确 → 家族名唯一候选 → 括号内容消歧（'Wing Tamer (Hort.)'→Hortensia）"""
    cid = slug(en_name)
    if cid in classes_meta:
        return cid, classes_meta[cid]
    fk = family_key(en_name)
    cands = [(k, v) for k, v in classes_meta.items() if family_key(v["en"]) == fk]
    if len(cands) == 1:
        return cands[0]
    m = re.search(r"\(([^)]+)\)", en_name)
    if m and cands:
        q = m.group(1).strip(".").lower()
        for k, v in cands:
            if q in v["en"].lower():
                return k, v
    return None, None


WEAPON_TYPES = ["sword", "lance", "axe", "bow", "knife", "tome", "arts"]

SKILL_LEXICON = [
    (r"\bAvo\b|Avoid", "avoid"), (r"\bCrit\b", "crit"), (r"\bDdg\b", "dodge"),
    (r"\bHit\b", "hit"), (r"damage", "damage"), (r"heal|Recovers", "heal"),
    (r"\bGold\b", "gold"), (r"\bEXP\b|experience", "exp"),
    (r"engage meter", "gauge"), (r"\bMov\b|\bMove\b", "move"),
    (r"Poison|Burn", "status"), (r"Effective", "effective"),
    (r"attacks twice|extra attack|consecutive", "multi_attack"),
    (r"\bDef\b|\bRes\b", "stat_def_res"), (r"\bSpd\b", "spd"),
    (r"\bStr\b", "str"), (r"\bDex\b", "dex"), (r"\bLck\b", "lck"),
    (r"\bHP\b", "hp"),
]


def extract_skill_semantics(name: str, desc: str) -> dict:
    """词表分类+正则取数(数字不经过转述)。
    P5修复: 每个数值只归属到唯一效果(最近的先行关键词, 或紧随的短距离关键词), 消除重复计价。"""
    desc = desc or ""
    num_matches = list(re.finditer(r"[+-]?\d+%?", desc))
    kws = []  # (start, end, type)
    for pat, etype in SKILL_LEXICON:
        for m in re.finditer(pat, desc):
            kws.append((m.start(), m.end(), etype))
    effects, unattributed = {}, []
    for nm in num_matches:
        before = [k for k in kws if k[1] <= nm.start() and nm.start() - k[1] <= 30]
        after = [k for k in kws if k[0] >= nm.end() and k[0] - nm.end() <= 15]
        if before:
            best = max(before, key=lambda k: k[1])
            effects.setdefault(best[2], []).append(nm.group())
        elif after:
            best = min(after, key=lambda k: k[0])
            effects.setdefault(best[2], []).append(nm.group())
        else:
            unattributed.append(nm.group())
    effect_list = [{"type": t, "values": vs} for t, vs in sorted(effects.items())]
    return {
        "name": name, "desc": desc,
        "effect_types": sorted(effects.keys()),
        "numbers_in_text": [nm.group() for nm in num_matches],
        "unattributed_numbers": unattributed,
        "effects": effect_list,
        "coverage": "full" if not unattributed else "partial",
        "review_flag": bool(unattributed),
    }


def build_p2(cur, cn):
    # ---- 武器(8类常规+特殊) ----
    weapons = []
    seen_w = set()
    for wi, wtype in enumerate(WEAPON_TYPES):
        for r in load_csv(f"w_{wtype}__0"):
            wid = slug(r[1]) + f"_{wtype}"
            if wid in seen_w:
                continue
            seen_w.add(wid)
            rng = r[6]
            m = re.fullmatch(r"(\d+)~(\d+)", rng)
            weapons.append((wid, wtype, "normal", r[1],
                            num(r[2]), num(r[3]), num(r[4]), num(r[5]),
                            num(m.group(1)) if m else num(rng),
                            num(m.group(2)) if m else num(rng),
                            r[7], num(r[8]), r[9]))
    for r in load_csv("w_special__0"):   # 特殊武器表1(邪龙石等)
        wid = slug(r[1]) + "_sp"
        if wid in seen_w:
            continue
        seen_w.add(wid)
        weapons.append((wid, "special", "special", r[1],
                        num(r[2]), num(r[3]), num(r[4]), num(r[5]),
                        num(r[6].split("~")[0]), num(r[6].split("~")[-1]),
                        r[7], num(r[8]), r[9]))
    cur.executemany(
        "INSERT INTO silver_weapons VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", weapons)

    # ---- 杖(schema不同) ----
    staffs = []
    for r in load_csv("w_staff__0"):
        pow_m = re.search(r"Pow:\s*(\d+)", r[6])
        staffs.append((slug(r[1]) + "_staff", r[1],
                       num(r[2].split("~")[0]), num(r[2].split("~")[-1]),
                       r[3], num(r[4]), num(r[5]),
                       num(pow_m.group(1)) if pow_m else 0, r[6]))
    cur.executemany(
        "INSERT INTO silver_staves VALUES(?,?,?,?,?,?,?,?,?)", staffs)

    # ---- 纹章结合武器(各武器类型__1表, 从notes解析所属纹章) ----
    eweapons = []
    seen_ew = set()
    for wi, wtype in enumerate(WEAPON_TYPES):
        if not (RAW / f"w_{wtype}__1.csv").exists():
            continue
        for r in load_csv(f"w_{wtype}__1"):
            wid = slug(r[1]) + "_ew"
            if wid in seen_ew:
                continue
            seen_ew.add(wid)
            em = re.search(r"Emblem (\w+)", r[9])
            eweapons.append((slug(r[1]) + "_ew", wtype,
                             em.group(1).lower() if em else None, r[1],
                             num(r[2]), num(r[3]), num(r[4]), num(r[5]),
                             num(r[6].split("~")[0]), num(r[6].split("~")[-1]), r[9]))
    cur.executemany(
        "INSERT INTO silver_emblem_weapons VALUES(?,?,?,?,?,?,?,?,?,?,?)", eweapons)

    # ---- 纹章士 ----
    emblems = []
    ob_rows = {r[0]: r for r in load_csv("emb_obtain__0")}
    for eid, meta in cn["emblems"].items():
        en = meta["en"]
        o = ob_rows.get(en, [None] * 4)
        emblems.append((eid, en, meta["cn"],
                        o[1] or meta.get("ring", ""), meta.get("chapter"),
                        json.dumps(meta.get("weapons", [])),
                        bool(meta.get("dlc")), bool(meta.get("weapons_unverified")),
                        bool(meta.get("spoiler"))))
    cur.executemany("INSERT INTO silver_emblems VALUES(?,?,?,?,?,?,?,?,?)", emblems)

    # ---- 牵绊加值(表头动态) ----
    bstats = []
    for eid in cn["emblems"]:
        rows = load_csv(f"emb_{eid}__0")
        if not rows:
            continue
        header = rows[0]
        for r in rows[1:]:
            for i, col in enumerate(header[1:], start=1):
                if i < len(r) and r[i]:
                    bstats.append((eid, num(r[0]), col.lower(),
                                   num(r[i].replace("+", "").replace("-", "-"))))
    cur.executemany(
        "INSERT INTO silver_emblem_bond_stats VALUES(?,?,?,?)", bstats)

    # ---- 纹章士技能 ----
    eskills = []
    for eid in cn["emblems"]:
        for r in load_csv(f"emb_{eid}__1"):
            r = (r + [""] * 5)[:5]
            if not r[1]:
                continue
            eskills.append((eid, num(r[0]), r[1], r[2], r[3], r[4]))
    cur.executemany(
        "INSERT INTO silver_emblem_skills VALUES(?,?,?,?,?,?)", eskills)

    # ---- 绊戒指(13组) ----
    rings = []
    for g in range(13):
        path = RAW / f"bond_rings__{g}.csv"
        if not path.exists():
            continue
        rows = list(csv.reader(open(path, encoding="utf-8-sig")))
        if not rows:
            continue
        header = rows[0]
        for r in rows[1:]:
            r = (r + [""] * 4)[:4]
            if not r[0]:
                continue
            rings.append((g, r[0], r[1], r[2], r[3]))
    cur.executemany("INSERT INTO silver_bond_rings VALUES(?,?,?,?,?)", rings)

    # ---- 技能语义结构化(个人技+兵种技+纹章技) ----
    sems = []
    for c in load_csv("char_personal__0"):
        if len(c) >= 4 and c[3].strip() not in ("Character", "") and "(foe)" not in c[3]:
            sem = extract_skill_semantics(c[1], c[2])
            sems.append(("personal", slug(c[3].replace(" (foe)", "")),
                         c[3].replace(" (foe)", ""), json.dumps(sem, ensure_ascii=False),
                         sem["coverage"]))
    for s in load_csv("class_skills__0"):
        for cls in [x.strip() for x in s[3].split(",")]:
            sem = extract_skill_semantics(s[1], s[2])
            sems.append(("class", slug(cls), cls, json.dumps(sem, ensure_ascii=False),
                         sem["coverage"]))
    for eid in cn["emblems"]:
        for r in load_csv(f"emb_{eid}__1"):
            r = (r + [""] * 5)[:5]
            if not r[1]:
                continue
            sem = extract_skill_semantics(r[1], r[2])
            sems.append(("emblem", eid, r[1], json.dumps(sem, ensure_ascii=False),
                         sem["coverage"]))
    cur.executemany(
        "INSERT INTO silver_skills_semantic VALUES(?,?,?,?,?)", sems)
    partial = sum(1 for s in sems if s[4] == "partial")
    cur.execute("INSERT INTO silver_meta VALUES(?,?)",
                ("skill_semantic_partial", str(partial)))


def main():
    cn = json.load(open(ROOT / "data" / "cn_names.json", encoding="utf-8"))
    chars_meta, classes_meta = cn["characters"], cn["classes"]

    # ---- 角色 ----
    g_rows = {r[0]: r for r in load_csv("char_growth__0")}
    b_rows = {r[0]: r for r in load_csv("char_base__1")}
    m_rows = {r[0]: r for r in load_csv("char_max__0")}
    p_rows = {r[3].replace(" (foe)", ""): r for r in load_csv("char_personal__0")
              if r[3].strip() != "Character"}
    r_rows = {r[0]: r for r in load_csv("char_recruit__0")}
    o_rows = {r[0]: r for r in load_csv("char_other__1")}

    characters = []
    for en, meta in chars_meta.items():
        en_name = meta["en"]
        g, b, m, o = g_rows[en_name], b_rows[en_name], m_rows.get(en_name), o_rows[en_name]
        # char_base: Name,Level,Class,HP..Bld,Mov
        # char_max: Name,Str..Lck (个人上限修正, 空白=0)
        maxmod = {s: num(m[i]) for i, s in enumerate(STATS[1:], start=1)} if m else {}
        characters.append((
            en, meta["cn"], en_name,
            json.dumps(meta.get("aliases", [en_name, meta["cn"]]), ensure_ascii=False),
            int(b[1]), b[2],                      # level_start, class_start
            *[num(b[i]) for i in range(3, 13)],   # hp_base..bld_base, mov (10值)
            *[num(g[i]) for i in range(1, 10)],   # hp..bld growth
            json.dumps(maxmod, ensure_ascii=False),
            p_rows[en_name][1], p_rows[en_name][2],   # personal skill name, desc
            json.dumps(parse_proficiency(o[4]), ensure_ascii=False),
            num(o[5]), o[1], o[2], o[3],          # sp, age, gender, birthday
            *([(int(r[2]) if r[2].isdigit() else None), r[2], r[3]]
              if (r := r_rows.get(en_name)) else [None, "", ""]),
            bool(meta.get("dlc")), meta.get("note", "")
        ))

    # ---- 兵种 ----
    cg_rows = {r[0]: r for r in load_csv("class_growth__0")}
    cb_rows = {r[0]: r for r in load_csv("class_base__1")}
    # 基础值表中 DLC Fell Child 只有单行(妮尔/拉法尔共用), 改名以匹配 other 表的规范名
    if "Fell Child (DLC)" in cb_rows:
        cb_rows["Fell Child (Nel)"] = cb_rows.pop("Fell Child (DLC)")
    cmax_rows = {r[0]: r for r in load_csv("class_max__0")}
    co_rows = {r[0]: r for r in load_csv("class_other__1")}

    classes = []
    unmatched = []
    for en_name, row in co_rows.items():
        cid, meta = lookup_meta(en_name, classes_meta)
        if meta is None:
            unmatched.append(en_name)
            continue
        base, cg, cmax = find_row(cb_rows, en_name), find_row(cg_rows, en_name), find_row(cmax_rows, en_name)
        if not (base and cg and cmax):
            unmatched.append(en_name + " [缺数值表行]")
            continue
        classes.append((
            cid, en_name, meta["cn"],
            json.dumps([meta["en"], meta["cn"]], ensure_ascii=False),
            meta.get("tier", "unknown"),
            row[2],  # movement type
            meta.get("primary_weapon"), json.dumps(meta.get("primary_weapon_alt", []), ensure_ascii=False),
            bool(meta.get("player_usable", True)), bool(meta.get("cn_unverified")),
            *[num(base[i]) for i in range(1, 11)],   # base: hp..bld, mov (10值)
            *[num(cg[i]) for i in range(1, 10)],     # growth: hp..bld (9值)
            *[num(cmax[i]) for i in range(1, 10)],   # max: hp..bld (9值)
            json.dumps(parse_class_weapons(row[3]), ensure_ascii=False),
            row[4], row[5], row[1],                  # lv5 skill, maddening skill, weak
        ))

    # ---- 兵种技能 ----
    skills = []
    for r in load_csv("class_skills__0"):
        for cls in [c.strip() for c in r[3].split(",")]:
            skills.append((slug(cls), cls, r[1], r[2]))

    # ---- 别名表 ----
    aliases = []
    for en, meta in chars_meta.items():
        for a in meta.get("aliases", [meta["en"], meta["cn"]]):
            aliases.append((a.lower(), "character", en))
    for cid, meta in classes_meta.items():
        for a in [meta["en"], meta["cn"]]:
            aliases.append((a.lower(), "class", cid))

    # ---- 写库 ----
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE silver_characters(
      id TEXT PRIMARY KEY, name_cn TEXT, name_en TEXT, aliases TEXT,
      level_start INT, class_start TEXT,
      hp_base INT, str_base INT, mag_base INT, dex_base INT, spd_base INT,
      def_base INT, res_base INT, lck_base INT, bld_base INT, mov_start INT,
      hp_growth INT, str_growth INT, mag_growth INT, dex_growth INT, spd_growth INT,
      def_growth INT, res_growth INT, lck_growth INT, bld_growth INT,
      max_modifiers TEXT,
      personal_skill TEXT, personal_skill_desc TEXT,
      proficiencies TEXT, sp INT, age TEXT, gender TEXT, birthday TEXT,
      join_chapter INT, join_chapter_raw TEXT, join_how TEXT,
      is_dlc INT, note TEXT);
    CREATE TABLE silver_classes(
      id TEXT PRIMARY KEY, name_en TEXT, name_cn TEXT, aliases TEXT,
      tier TEXT, movement_type TEXT,
      primary_weapon TEXT, primary_weapon_alt TEXT,
      player_usable INT, cn_unverified INT,
      hp_base INT, str_base INT, mag_base INT, dex_base INT, spd_base INT,
      def_base INT, res_base INT, lck_base INT, bld_base INT, mov INT,
      hp_growth INT, str_growth INT, mag_growth INT, dex_growth INT, spd_growth INT,
      def_growth INT, res_growth INT, lck_growth INT, bld_growth INT,
      hp_max INT, str_max INT, mag_max INT, dex_max INT, spd_max INT,
      def_max INT, res_max INT, lck_max INT, bld_max INT,
      req_proficiency TEXT, lv5_skill TEXT, maddening_skill TEXT, weak TEXT);
    CREATE TABLE silver_class_skills(class_id TEXT, class_name TEXT, name TEXT, desc TEXT);
    CREATE TABLE silver_aliases(alias TEXT PRIMARY KEY, kind TEXT, ref_id TEXT);
    CREATE TABLE silver_meta(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE silver_weapons(
      id TEXT PRIMARY KEY, type TEXT, category TEXT, name_en TEXT,
      mt INT, hit INT, crit INT, wt INT, rng_min INT, rng_max INT,
      req_rank TEXT, price INT, notes TEXT);
    CREATE TABLE silver_staves(
      id TEXT PRIMARY KEY, name_en TEXT, rng_min INT, rng_max INT,
      req_rank TEXT, uses INT, price INT, pow INT, notes TEXT);
    CREATE TABLE silver_emblem_weapons(
      id TEXT PRIMARY KEY, type TEXT, emblem TEXT, name_en TEXT,
      mt INT, hit INT, crit INT, wt INT, rng_min INT, rng_max INT, notes TEXT);
    CREATE TABLE silver_emblems(
      id TEXT PRIMARY KEY, name_en TEXT, name_cn TEXT, ring TEXT, chapter INT,
      weapons TEXT, is_dlc INT, weapons_unverified INT, spoiler INT);
    CREATE TABLE silver_emblem_bond_stats(
      emblem_id TEXT, level INT, stat TEXT, bonus INT);
    CREATE TABLE silver_emblem_skills(
      emblem_id TEXT, bond_unlock INT, name TEXT, desc TEXT, type TEXT, sp INT);
    CREATE TABLE silver_bond_rings(
      grp INT, name TEXT, rank TEXT, stat_boost TEXT, skill TEXT);
    CREATE TABLE silver_skills_semantic(
      source_kind TEXT, source_id TEXT, name TEXT, semantic TEXT, coverage TEXT);
    """)
    ph_c = ",".join("?" * 38)
    cur.executemany(f"INSERT INTO silver_characters VALUES({ph_c})", characters)
    ph_k = ",".join("?" * 42)
    cur.executemany(f"INSERT INTO silver_classes VALUES({ph_k})", classes)
    cur.executemany("INSERT INTO silver_class_skills VALUES(?,?,?,?)", skills)
    cur.executemany("INSERT OR IGNORE INTO silver_aliases VALUES(?,?,?)", aliases)
    build_p2(cur, cn)
    cur.executemany("INSERT INTO silver_meta VALUES(?,?)", [
        ("built", date.today().isoformat()),
        ("source", "serenesforest.net/engage"),
        ("assumption_reclass", "近似规则:兵种主武器 ∈ 角色天资 → 可转。资质等级/牵绊获取未建模,待校准"),
        ("assumption_rank", "资质等级字母 C<B<A<S; '^'与'*'标记含义未定; 兵种需求表每武器归属未解码"),
        ("unmatched_classes", json.dumps(unmatched, ensure_ascii=False)),
    ])
    con.commit()
    n = lambda t: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"characters={n('silver_characters')} classes={n('silver_classes')} "
          f"skills={n('silver_class_skills')} aliases={n('silver_aliases')}")
    if unmatched:
        print("未匹配兵种:", unmatched)
    con.close()


if __name__ == "__main__":
    sys.exit(main())
