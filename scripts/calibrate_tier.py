# -*- coding: utf-8 -*-
"""P4 校准网格实验——系统化测各口径假设组合的 Spearman 相关度

假设维度:
  成长潜力: sum(9项合计) / top5 / top4     (专精 vs 均衡)
  技能价值: raw / cap10 / sqrt             (噪声控制)
  初始战力: raw / 章节衰减 / 后期折半       (可用性折扣)
  权重组合: (0.35,0.40,0.15,0.10) / (0.25,0.50,0.15,0.10) / (0.30,0.45,0.15,0.10)
运行: python scripts/calibrate_tier.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engage_core import engine  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from regression_tier import EXAM_TIERS, spearman, tier_of  # noqa: E402


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    chars = engine._table("characters")
    data = []
    for c in chars:
        cid = c["id"]
        bs = engine.base_strength(cid)
        ch = (c["join_chapter"] or 12)
        raw_base = bs.get("即时战力分") or 0
        g = sorted((c[s + "_growth"] for s in engine.STAT_KEYS), reverse=True)
        psv = engine.personal_skill_value(cid).get("机械估小计") or 0
        data.append({"id": cid, "raw_base": raw_base, "ch": ch,
                     "sum": sum(g), "top5": sum(g[:5]), "top4": sum(g[:4]),
                     "psv": psv})

    def norm(key, val, rows):
        vals = [r[key] for r in rows]
        lo, hi = min(vals), max(vals)
        return 50.0 if hi == lo else (val - lo) / (hi - lo) * 100

    tiers = [tier_of(r["id"], r["id"]) for r in data]
    results = []
    for gmode in ("sum", "top5", "top4"):
        for pmode, pfn in (("raw", lambda x: x), ("cap10", lambda x: min(x, 10)),
                           ("sqrt", lambda x: max(0.0, x) ** 0.5)):
            for bmode, bfn in (("raw", lambda x, ch: x),
                               ("衰减", lambda x, ch: x * max(0.2, (27 - ch) / 26)),
                               ("后期折半", lambda x, ch: x * (1.0 if ch <= 12 else 0.6))):
                for w in ((0.35, 0.40, 0.15, 0.10),
                          (0.25, 0.50, 0.15, 0.10),
                          (0.30, 0.45, 0.15, 0.10)):
                    rows = []
                    for r in data:
                        rows.append({"id": r["id"],
                                     "base": bfn(r["raw_base"], r["ch"]),
                                     "growth": r[gmode],
                                     "psv": pfn(r["psv"])})
                    comps = []
                    for r in rows:
                        s = (norm("base", r["base"], rows) * w[0]
                             + norm("growth", r["growth"], rows) * w[1]
                             + norm("psv", r["psv"], rows) * w[2] + 50 * w[3])
                        comps.append((r["id"], s))
                    rho = spearman([s for _, s in comps], tiers)
                    by = sorted(comps, key=lambda x: -x[1])
                    top10 = {x[0] for x in by[:10]}
                    ov = len(top10 & set(EXAM_TIERS["T1"]))
                    results.append((rho, ov, gmode, pmode, bmode, w,
                                    [x[0] for x in by[:5]]))
    results.sort(key=lambda x: -x[0])
    print(f"{'Spearman':>8s} {'Top10':>5s}  成长   技能   初始   权重                Top5样例")
    for rho, ov, gm, pm, bm, w, top5 in results[:10]:
        print(f"{rho:8.3f} {ov:5d}  {gm:5s} {pm:6s} {bm:6s} {w}  {[t[:4] for t in top5]}")
    worst = results[-1]
    print(f"最差组合: {worst[0]:.3f} ({worst[2]}/{worst[3]}/{worst[4]}/{worst[5]})")


if __name__ == "__main__":
    main()
