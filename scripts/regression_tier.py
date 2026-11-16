# -*- coding: utf-8 -*-
"""41人全量 tier 校准考卷——引擎综合分 vs 社区共识分级

考卷来源: Reddit/游民星空/社区讨论的最大公约数分级(可争议, 改 EXAM_TIERS 即可)。
指标: Spearman相关(综合分 vs 分级) + Top10重合度 + outlier清单。
运行: python scripts/regression_tier.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engage_core import engine  # noqa: E402

# 社区共识三档(3=第一梯队, 2=中坚, 1=偏弱)。DLC角色因加入时点数据缺失暂按中坚处理。
EXAM_TIERS = {
    "T1": ["chloe", "kagetsu", "yunaka", "hortensia", "lapis",
           "louis", "pandreo", "panette", "amber", "alear"],
    "T3": ["vander", "clanne", "framme", "boucheron", "etie", "jade"],
    # 其余 = T2
}


def tier_of(cid, all_ids):
    if cid in EXAM_TIERS["T1"]:
        return 3
    if cid in EXAM_TIERS["T3"]:
        return 1
    return 2


def spearman(xs, ys):
    """带并列秩的 Spearman(平均秩法)"""
    def ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    chars = engine._table("characters")
    # 内部工程公式(P5后引擎不再输出综合分; 此处组合仅供校准回归):
    # 0.25×norm(初始战力) + 0.50×norm(成长Top5和) + 0.15×norm(√技能小计) + 0.10×50
    rows = []
    for c in sorted(chars, key=lambda x: x["id"]):
        cid = c["id"]
        t = engine.tier_assessment(cid)
        bs = t["分项事实"]["初始即时战力"]["值"]
        gr = t["分项事实"]["成长潜力"]["值"]
        pv = t["分项事实"]["个人技价值"]["机械估小计"]
        rows.append({"id": cid, "cn": c["name_cn"], "base": bs, "growth": gr,
                     "psv": max(0.0, pv) ** 0.5, "tier": tier_of(cid, cid),
                     "raw": {"初始战力": bs, "成长Top5和": gr, "技小计": pv}})

    def norm(key, val):
        vals = [r[key] for r in rows]
        lo, hi = min(vals), max(vals)
        return 50.0 if hi == lo else (val - lo) / (hi - lo) * 100

    for r in rows:
        r["score"] = round(norm("base", r["base"]) * 0.25
                           + norm("growth", r["growth"]) * 0.50
                           + norm("psv", r["psv"]) * 0.15 + 5.0, 1)

    tiers = [r["tier"] for r in rows]
    scores = [r["score"] for r in rows]
    rho = spearman(scores, tiers)

    by_score = sorted(rows, key=lambda x: -x["score"])
    top10 = [d["id"] for d in by_score[:10]]
    overlap = len(set(top10) & set(EXAM_TIERS["T1"]))

    print(f"Spearman 相关(内部工程组合分 vs 社区分级): {rho:.3f}")
    print(f"引擎Top10: {[d['cn'] for d in by_score[:10]]}")
    print(f"社区T1   : {EXAM_TIERS['T1']}")
    print(f"Top10重合: {overlap}/10")
    print()
    print("outlier清单(引擎排名与社区档位差距最大, 供口径校准):")
    TIER_LABEL = {3: "T1第一梯队", 2: "T2中坚", 1: "T3垫底"}
    rank_by_id = {d["id"]: i + 1 for i, d in enumerate(by_score)}
    for r in by_score:
        rank = rank_by_id[r["id"]]
        expected_rank_mid = {"T1": 5, "T2": 22, "T3": 38}[TIER_LABEL[r["tier"]][:2]]
        gap = rank - expected_rank_mid
        if abs(gap) >= 12:
            arrow = "引擎低估" if gap > 0 else "引擎高估"
            print(f"  [{arrow}] {r['cn']:8s} 引擎#{rank} 社区{TIER_LABEL[r['tier']]}(≈#{expected_rank_mid}) "
                  f"原始: 初始{r['raw']['初始战力']}/成长{r['raw']['成长Top5和']}/技{r['raw']['技小计']}")


if __name__ == "__main__":
    main()
