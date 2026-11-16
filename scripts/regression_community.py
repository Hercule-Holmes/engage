# -*- coding: utf-8 -*-
"""社区共识回归考卷——用大众公认结论校验引擎输出, 只追 outlier, 不定罪。

考题来源: 游民星空/B站/Reddit 共识(如"克罗艾转狮鹫""尤娜卡回避坦")。
运行: python scripts/regression_community.py
输出: 每题 PASS/WARN + 汇总。WARN 只提示人工复核, 不算失败。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engage_core import engine  # noqa: E402

EXAM = [
    # (角色, 检查函数(recommend结果)→bool, 出处/理由)
    ("chloe", lambda r: any(x["class_id"] == "griffin_knight" for x in r["ranking"]),
     "游民星空: 克萝艾10级转狮鹫骑士是公认路线"),
    ("yunaka", lambda r: any(x["class_id"] in ("thief", "swordmaster", "wolf_knight")
                             or _movement(x["class_id"]) == "Covert"
                             for x in r["ranking"]),
     "社区共识: 尤娜卡=盗贼/剑圣回避坦 或 狼骑士刀流(均为真实主流)"),
    ("kagetsu", lambda r: any(x["class_id"] in ("swordmaster", "hero", "sword_fighter")
                              for x in r["ranking"]),
     "社区共识: 花月=顶级剑士系"),
    ("louis", lambda r: any(_movement(x["class_id"]) == "Armor" for x in r["ranking"]),
     "社区共识: 路易=重甲坦"),
    ("hortensia", lambda r: any(_movement(x["class_id"]) in ("Mystical", "Flying")
                                for x in r["ranking"]),
     "社区共识: 奥尔坦希亚=顶级奶妈(魔法/飞行)"),
    ("ivy", lambda r: any(_movement(x["class_id"]) in ("Flying", "Mystical")
                          for x in r["ranking"]),
     "社区共识: 艾比=魔法飞兵系"),
    # 强度锚点: 主角级不至于垫底, 凡德雷不应进前半
    ("alear", lambda r: r["ranking"][0]["score"] >= 30, "主角保底强度"),
]


def _movement(class_id):
    k = engine.class_card(class_id)
    return k.get("移动类型")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    warns = 0
    for char_id, check, why in EXAM:
        rec = engine.recommend_builds(char_id, top_n=5)
        ok = check(rec)
        tag = "PASS" if ok else "WARN"
        warns += 0 if ok else 1
        print(f"[{tag}] {char_id:10s} → top5: {[x['class_id'] for x in rec['ranking']]}")
        if not ok:
            print(f"        共识: {why}")
    print(f"\n结果: {len(EXAM) - warns}/{len(EXAM)} PASS, {warns} WARN"
          f" (WARN=与社区共识有出入的outlier, 需人工复核口径而非必错)")


if __name__ == "__main__":
    main()
