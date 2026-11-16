# -*- coding: utf-8 -*-
"""计算结果 → markdown 渲染（分层：简评 / 详细）"""
from . import engine

STAT_CN = engine.STAT_CN


def _v(d, *keys, default="—"):
    for k in keys:
        if d is None:
            return default
        d = d.get(k)
    return default if d is None else d


def render_character(card: dict) -> str:
    g = card["个人成长率"]
    top = sorted(g.items(), key=lambda kv: -kv[1]["个人"])[:3]
    lines = [
        f"## {card['name_cn']}（{card['name_en']}）",
        f"加入: 第{_v(card,'join','章节')}章 · 初始 Lv{_v(card,'初始','等级')} {_v(card,'初始','兵种')}",
        "",
        "**个人成长率Top3**: " + " / ".join(f"{STAT_CN[s]} {v['个人']}({v['排名']})" for s, v in top),
        f"**个人特技**: {_v(card,'个人特技','名称')} — {_v(card,'个人特技','效果')}",
        f"**天资**: " + "、".join(p["武器"] + ("(天生)" if p["天生"] else "") for p in card["天资(自带资质)"]),
    ]
    return "\n".join(lines)


def render_character_detail(card: dict) -> str:
    rows = "\n".join(
        f"| {STAT_CN[s]} | {_v(card,'基础值',s)} | {g['个人']} | {g['排名']} |"
        for s, g in card["个人成长率"].items())
    return render_character(card) + f"""

### 详细数值
| 属性 | 初始值 | 个人成长 | 41人排名 |
|---|---|---|---|
{rows}

上限修正: {card['上限修正']} · 体格初始 {_v(card,'基础值','体格')} · SP {card['SP']}
个人特技原文: {_v(card,'个人特技','效果')}
"""


def render_build(ev: dict, detail: bool = False) -> str:
    c, k = ev["character"], ev["query_class"]
    e = ev["eligibility"]
    icon = "✅" if e["eligible"] else "⚠️"
    tg, proj, rk = ev["total_growth"], ev["projection"], ev["rank_in_class"]
    top = sorted(tg.items(), key=lambda kv: -kv[1]["合计"])[:3]
    brief = [
        f"## {c['cn']} · {k['cn']}路线评估",
        f"**转职资格** {icon} {e['reason']}",
        "",
        "**合计成长率Top3**: " + " / ".join(
            f"{STAT_CN[s]} {v['合计']}(同兵种{rk[s]})" for s, v in top),
        f"**Lv{proj['level']}预测**: " + " / ".join(
            f"{cn} {v['预测']}" for cn, v in proj["values"].items()),
    ]
    if ev.get("growth_notes"):
        brief.append("**注**: " + "；".join(ev["growth_notes"]))
    if not detail:
        brief.append("")
        brief.append("*（回复\"详细\"查看完整成长率对比表与假设说明）*")
        return "\n".join(brief)

    rows = "\n".join(
        f"| {STAT_CN[s]} | {v['个人']} | {v['兵种']} | **{v['合计']}** | {rk[s]} |"
        for s, v in tg.items() if s != "bld")
    combat_md = render_combat(ev["combat"]) if "combat" in ev else ""
    bld = tg["bld"]
    prows = "\n".join(
        f"| {cn} | {v['预测']} | {v['兵种上限']}{' ⚠️触顶' if v['触上限'] else ''} |"
        for cn, v in proj["values"].items())
    return "\n".join(brief) + f"""

### 成长率详情（个人 + 兵种 = 合计）
| 属性 | 个人 | 兵种 | 合计 | 同兵种排名 |
|---|---|---|---|---|
{rows}
| 体格 | {bld['个人']} | {bld['兵种']} | {bld['合计']} | — |

### Lv{proj['level']} 预测值
| 属性 | 预测 | 上限 | |
|---|---|---|---|
{prows}
{combat_md}

### 假设与未建模项
""" + "\n".join(f"- {a}" for a in ev.get("_assumptions", []))


def render_combat(combat: dict) -> str:
    """作战证据表渲染(详细模式)"""
    if "error" in combat:
        return f"\n### 作战证据\n{combat['error']}"
    ENEMY_CN = {"mob": "杂兵", "boss": "BOSS", "mage": "法师"}
    lines = [
        f"\n### 作战证据（{combat['atk_stat']}预测{combat['atk_projected']} / "
        f"速{combat['spd_projected']} / 体格{combat['bld_projected']}）",
        "| 武器 | " + " | ".join(
            f"{ENEMY_CN[b]} 伤害/命中/追击/反击安全" for b in ("mob", "boss", "mage")) + " |",
        "|---|" + "---|" * 3,
    ]
    for w in combat["evidence"]:
        cells = " | ".join(
            f"{w[b]['单击伤害']}/{w[b]['命中%']}%/"
            f"{'✓' if w[b]['追击'] else '✗'}/{'✓' if w[b]['反击安全'] else '✗'}"
            for b in ("mob", "boss", "mage"))
        lines.append(f"| {w['weapon']} | {cells} |")
    if combat.get("patterns_hit"):
        lines.append(f"**模式命中**: {', '.join(combat['patterns_hit'])} "
                     f"(one_shot=单击≥基准HP90%, doubles=可追击)")
    for a in combat.get("_assumptions", []):
        lines.append(f"- ⚠️ {a}")
    return "\n".join(lines)


def render_recommend(rec: dict) -> str:
    lines = [
        f"## {_v(rec,'character','cn')} · 兵种推荐 Top{len(rec['ranking'])}",
        f"依据个人成长Top3: {', '.join(rec['top3个人成长'])}",
        "",
    ]
    for i, r in enumerate(rec["ranking"], 1):
        lines.append(f"{i}. **{r['name_cn']}**（{r['tier']} / {r['移动类型']}）— "
                     f"成长加总 {r['top3成长加总']}" + (f" + 天资加成{r['天资武器加成']}" if r["天资武器加成"] else ""))
    lines += ["", f"*口径: {rec['score_note']}*"]
    return "\n".join(lines)
