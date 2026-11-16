# -*- coding: utf-8 -*-
"""抓取 Serenes Forest 的 FE Engage 数据页 → data/raw/*.html + *.csv

用法: python scripts/scrape_serenes.py [--phase P1|P2|P3|all]
输出: data/raw/<key>.html  原始页面
      data/raw/<key>__<n>.csv  第 n 个表格（n=0,1,2...）
"""
import sys
import time
import csv
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

BASE = "https://serenesforest.net/engage/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FE-Engage-Agent/0.1"}

# key -> (相对路径, 阶段)
PAGES = {
    # ---- P1 培养数据 ----
    "char_base":     ("characters/base-stats/", "P1"),
    "char_growth":   ("characters/growth-rates/", "P1"),
    "char_max":      ("characters/maximum-stats/", "P1"),
    "char_personal": ("characters/personal-skills/", "P1"),
    "char_recruit":  ("characters/recruitment/", "P1"),
    "char_other":    ("characters/other-data/", "P1"),
    "class_base":    ("classes/base-stats/", "P1"),
    "class_growth":  ("classes/growth-rates/", "P1"),
    "class_max":     ("classes/maximum-stats/", "P1"),
    "class_skills":  ("classes/learnable-skills/", "P1"),
    "class_other":   ("classes/other-data/", "P1"),
    # ---- P2 武器/纹章士 ----
    "w_sword":   ("weapons-items/swords/", "P2"),
    "w_lance":   ("weapons-items/lances/", "P2"),
    "w_axe":     ("weapons-items/axes/", "P2"),
    "w_bow":     ("weapons-items/bows/", "P2"),
    "w_knife":   ("weapons-items/knives/", "P2"),
    "w_tome":    ("weapons-items/tomes/", "P2"),
    "w_staff":   ("weapons-items/staves/", "P2"),
    "w_arts":    ("weapons-items/arts/", "P2"),
    "w_special": ("weapons-items/special-weapons/", "P2"),
    "w_items":   ("weapons-items/items/", "P2"),
    "bond_rings": ("weapons-items/bond-rings/", "P2"),
    "emb_obtain": ("emblems/how-to-obtain/", "P2"),
    "emb_veronica_summons": ("emblems/veronica/summons/", "P2"),
    # 19 个纹章士详情页
    **{f"emb_{n}": (f"emblems/{n}/", "P2") for n in (
        "marth", "sigurd", "celica", "micaiah", "roy", "leif", "lucina",
        "lyn", "ike", "byleth", "corrin", "eirika", "alear",
        "edelgard", "tiki", "hector", "veronica", "soren", "camilla", "chrom")},
    # ---- P3 知识层 ----
    "misc_skills":  ("miscellaneous/skills/", "P3"),
    "paralogues":   ("miscellaneous/paralogues/", "P3"),
    "script_main":  ("script/main-story/", "P3"),
    "script_dlc":   ("script/dlc-story/", "P3"),
    "script_support": ("script/support-conversations/", "P3"),
    "script_bond":  ("script/bond-conversations/", "P3"),
}

# 这些页面是长文本（非表格），只存 HTML 不解析 CSV
TEXT_ONLY = {"script_main", "script_dlc", "script_support", "script_bond"}


def parse_tables(html: str):
    """把页面里所有 <table> 解析成 [[cell,...],...] 列表"""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tb in soup.find_all("table"):
        rows = []
        for tr in tb.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append(cells)
        if rows:
            out.append(rows)
    return out


def fetch(key: str, path: str, save_html: bool) -> int:
    url = BASE + path
    try:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[FAIL] {key}: {e}")
        return 0
    if save_html:
        (RAW / f"{key}.html").write_text(r.text, encoding="utf-8")
    if key in TEXT_ONLY:
        print(f"[OK]   {key}: text page saved ({len(r.text)} bytes)")
        return 1
    tables = parse_tables(r.text)
    if not tables:
        print(f"[WARN] {key}: 200 but no tables found")
        return 0
    for i, rows in enumerate(tables):
        with open(RAW / f"{key}__{i}.csv", "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows(rows)
    print(f"[OK]   {key}: {len(tables)} tables, rows={[len(t) for t in tables]}")
    return len(tables)


def main():
    phase = "all"
    if len(sys.argv) > 2 and sys.argv[1] == "--phase":
        phase = sys.argv[2]
    ok = fail = 0
    for key, (path, ph) in PAGES.items():
        if phase != "all" and ph != phase:
            continue
        ok += fetch(key, path, save_html=True)
        fail += 0 if ok else 1
        time.sleep(1.0)  # 礼貌抓取
    print(f"\nDone: {ok} pages OK, target phase={phase}")


if __name__ == "__main__":
    main()
