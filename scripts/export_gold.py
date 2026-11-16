# -*- coding: utf-8 -*-
"""导出 gold 审阅快照 → data/gold/*.csv（供人工核对口径）

  gold_growth_ranking.csv    41角色 × 8属性 个人成长率+全游戏排名
  gold_class_fit_top5.csv    每角色推荐兵种Top5(当前启发式口径)
  gold_reclass_matrix.csv    角色×兵种 转职资格矩阵(近似规则)
运行: python scripts/export_gold.py
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engage_core import engine  # noqa: E402

OUT = ROOT / "data" / "gold"

STATS = ["hp", "str", "mag", "dex", "spd", "def", "res", "lck"]
STAT_CN = engine.STAT_CN


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. 成长率排名表
    with open(OUT / "gold_growth_ranking.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["角色", "id"] + [f"{STAT_CN[s]}成长" for s in STATS] + [f"{STAT_CN[s]}排名" for s in STATS])
        chars = engine._table("characters")
        for c in sorted(chars, key=lambda x: x["id"]):
            card = engine.character_card(c["id"])
            row = [card["name_cn"], c["id"]]
            row += [card["个人成长率"][s]["个人"] for s in STATS]
            row += [card["个人成长率"][s]["排名"] for s in STATS]
            w.writerow(row)

    # 2. 兵种适配Top5
    with open(OUT / "gold_class_fit_top5.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["角色", "id", "推荐1", "推荐2", "推荐3", "推荐4", "推荐5",
                    "分数1~5", "口径说明"])
        for c in sorted(chars, key=lambda x: x["id"]):
            rec = engine.recommend_builds(c["id"], top_n=5)
            names = [x["name_cn"] for x in rec["ranking"]]
            names += [""] * (5 - len(names))
            scores = [x["score"] for x in rec["ranking"]]
            scores += [""] * (5 - len(scores))
            w.writerow([rec["character"]["cn"], c["id"], *names, *scores,
                        rec["score_note"]])

    # 3. 转职资格矩阵
    classes = [k for k in engine._table("classes") if k["player_usable"]]
    with open(OUT / "gold_reclass_matrix.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["角色\\兵种"] + [k["name_cn"] for k in classes])
        for c in sorted(chars, key=lambda x: x["id"]):
            row = [engine.character_card(c["id"])["name_cn"]]
            for k in classes:
                r = engine.can_reclass(c["id"], k["id"])
                row.append("✓" if r["eligible"] else "✗(需牵绊)")
            w.writerow(row)

    print(f"已导出 3 个审阅快照 → {OUT}")


if __name__ == "__main__":
    main()
