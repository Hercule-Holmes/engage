# -*- coding: utf-8 -*-
"""数据一致性校验——两级验证:
  A. 在线真对拍: 重抓 Serenes Forest 成长率页全表, 逐行与 DB 比对(41角色×9属性)
  B. 离线锚点: 内嵌人工核实值(5角色成长率 + 4武器)
运行: python scripts/verify_data.py [--offline]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup  # noqa: E402

from engage_core import db, engine  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 FE-Engage-Agent/0.1 verify"}
GROWTH_URL = "https://serenesforest.net/engage/characters/growth-rates/"

ANCHOR_GROWTH = {
    "Alear": (60, 35, 20, 45, 50, 40, 25, 25, 5),
    "Chloé": (75, 25, 35, 40, 55, 30, 25, 25, 5),
    "Jean": (50, 20, 20, 35, 40, 25, 20, 25, 5),
    "Kagetsu": (60, 30, 15, 50, 50, 40, 25, 40, 10),
    "Hortensia": (40, 20, 20, 35, 50, 25, 55, 50, 0),
}
ANCHOR_WEAPON = {
    "Iron Sword": (5, 90, 0, 5),
    "Silver Sword": (12, 90, 0, 11),
    "Killing Edge": (9, 75, 30, 10),
    "Levin Sword": (13, 85, 0, 11),
}
STAT_COLS = ["hp_growth", "str_growth", "mag_growth", "dex_growth",
             "spd_growth", "def_growth", "res_growth", "lck_growth", "bld_growth"]


def check_offline() -> list[str]:
    errs = []
    con = db.connect()
    chars = {r["name_en"]: r for r in db.query(con, "SELECT * FROM silver_characters")}
    con.close()
    for name, vals in ANCHOR_GROWTH.items():
        c = chars.get(name)
        if not c:
            errs.append(f"[offline] 角色 {name} 不在库中")
            continue
        got = tuple(c[k] for k in STAT_COLS)
        if got != vals:
            errs.append(f"[offline] {name} 成长率 {got} != 锚点 {vals}")
    weapons = {w["name_en"]: w for w in engine.query_weapons()}
    for name, (mt, hit, crit, wt) in ANCHOR_WEAPON.items():
        w = weapons.get(name)
        if not w:
            errs.append(f"[offline] 武器 {name} 不在库中")
            continue
        if (w["mt"], w["hit"], w["crit"], w["wt"]) != (mt, hit, crit, wt):
            errs.append(f"[offline] {name} 数值不符")
    return errs


def check_online() -> list[str]:
    """重抓成长率页全表(41行×9列), 与 DB 逐行比对——真对拍"""
    import requests
    errs = []
    try:
        r = requests.get(GROWTH_URL, headers=UA, timeout=30)
        r.raise_for_status()
    except Exception as e:
        return [f"[online] 抓取失败(网络原因, 离线锚点仍有效): {e}"]
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table")
    con = db.connect()
    chars = {c["name_en"]: c for c in db.query(con, "SELECT * FROM silver_characters")}
    con.close()
    compared = 0
    for tr in table.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) < 10 or cells[0] in ("Name", ""):
            continue
        name = cells[0]
        c = chars.get(name)
        if not c:
            errs.append(f"[online] 页面角色 {name} 不在 DB")
            continue
        page_vals = tuple(int(x) if x.isdigit() else 0 for x in cells[1:10])
        db_vals = tuple(c[k] for k in STAT_COLS)
        if page_vals != db_vals:
            errs.append(f"[online] {name}: 页面{page_vals} != DB{db_vals}")
        compared += 1
    print(f"  在线对拍完成: {compared} 角色 × 9 属性")
    if compared < 40:
        errs.append(f"[online] 对拍行数异常({compared}<40), 解析可能不完整")
    return errs


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    offline_mode = "--offline" in sys.argv
    errs = check_offline()
    if not offline_mode:
        print("在线对拍中...")
        errs += check_online()
    if errs:
        print(f"❌ 校验失败 {len(errs)} 项:")
        for e in errs:
            print(" ", e)
        sys.exit(1)
    print("✅ 数据校验全部通过(离线锚点5+4" + ("" if offline_mode else " + 在线全表对拍") + ")")


if __name__ == "__main__":
    main()
