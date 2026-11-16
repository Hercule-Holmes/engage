# -*- coding: utf-8 -*-
"""独立查询 REPL——不依赖任何 LLM/客户端，验证核心引擎可用性。

用法:
  python shells/cli.py                  # 交互模式
  python shells/cli.py 克萝艾 剑士      # 一次性查询
  python shells/cli.py 克萝艾 剑士 --详细
命令: <角色> <兵种> | <角色> | 推荐 <角色> | 兵种 <兵种> | 详细 | 帮助 | 退出
"""
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engage_core import engine, format  # noqa: E402

DETAIL = False

COMMAND_WORDS = ["推荐", "纹章", "强度", "兵种", "武器", "机制", "帮助", "退出"]


def _fmt_cands(text: str, r: dict) -> str:
    """resolve_name 返回多候选时的展示: 交由用户裁决, 不静默取第一个。"""
    lines = [f"「{text}」未唯一匹配, 候选:"]
    for i, c in enumerate(r["candidates"], 1):
        kind = "角色" if c["kind"] == "character" else "兵种"
        lines.append(f"  {i}) {c['name_cn']}（{c['name_en']} · {kind} · {c['matched_by']})")
    lines.append("请用完整名称重试")
    return "\n".join(lines)


def _res(text: str, label: str):
    """resolve_name 的 CLI 封装: 返回实体dict, 或 str(未识别/多候选提示, 直接作为回复)。"""
    r = engine.resolve_name(text)
    if r is None:
        return f"未识别{label}「{text}」"
    if "candidates" in r:
        return _fmt_cands(text, r)
    return r

HELP = """命令:
  <角色> <兵种>     路线评估 (如: 克萝艾 剑士)
  <角色>            角色卡   (如: 尤娜卡)
  推荐 <角色>        兵种推荐 (如: 推荐 花月)
  纹章 <角色> <兵种>  纹章士适配 (如: 纹章 琉尔 剑士)
  武器 [类型] [关键词] 武器查询 (如: 武器 sword 雷神/Levin)
  机制 <关键词>      机制知识检索 (如: 机制 追击)
  强度 <角色>        综合强度参考 (如: 强度 尤娜卡)
  兵种 <兵种名>      兵种卡   (如: 兵种 狮鹫骑士)
  详细              切换详细输出
  退出 / 帮助"""


def handle(parts: list[str]) -> str:
    if parts[0] in ("退出", "q", "quit", "exit"):
        sys.exit(0)
    if parts[0] in ("帮助", "help", "h"):
        return HELP
    if parts[0] == "详细":
        global DETAIL
        DETAIL = not DETAIL
        return f"详细模式: {'开' if DETAIL else '关'}"

    if parts[0] == "兵种":
        if len(parts) < 2:
            return "用法: 兵种 <兵种名>"
        r2 = _res(parts[1], "兵种")
        if isinstance(r2, str):
            return r2
        if r2["kind"] != "class":
            return f"「{parts[1]}」不是兵种（解析为{r2['name_cn']}）"
        return _class_brief(r2["id"])

    if parts[0] == "武器":
        wtype = parts[1] if len(parts) > 1 else None
        kw = parts[2] if len(parts) > 2 else None
        ws = engine.query_weapons(wtype, kw)
        if not ws:
            return "无匹配武器（类型: sword/lance/axe/bow/knife/tome/staff/arts）"
        lines = [f"共{len(ws)}件:"]
        for w in ws[:15]:
            mt = w.get("mt", w.get("pow", "—"))
            lines.append(f"- {w['name_en']} 威力{mt} 命中{w.get('hit','—')} "
                         f"必杀{w.get('crit','—')} 重量{w.get('wt','—')} "
                         f"射程{w['rng_min']}~{w['rng_max']} 所需{w.get('req_rank','')}")
        return "\n".join(lines)

    if parts[0] == "纹章":
        if len(parts) < 3:
            return "用法: 纹章 <角色> <兵种>"
        r1, r2 = _res(parts[1], "角色"), _res(parts[2], "兵种")
        if isinstance(r1, str):
            return r1
        if isinstance(r2, str):
            return r2
        if r1["kind"] != "character":
            return f"「{parts[1]}」不是角色（解析为{r1['name_cn']}）"
        if r2["kind"] != "class":
            return f"「{parts[2]}」不是兵种（解析为{r2['name_cn']}）"
        fit = engine.emblem_fit(r1["id"], r2["id"])
        lines = [f"## {fit['character']['cn']} · {fit['query_class']['cn']}"
                 f" 纹章士适配({len(fit['ranking'])}个候选, band并列分组)",
                 f"可用武器集: {', '.join(fit['可用武器集'])}",
                 f"路线偏好: {', '.join(fit['路线偏好']['效果'])} ({fit['路线偏好']['口径']})", ""]
        for r in fit["ranking"]:
            syn = "、".join(f"{h['技能']}({h['类型']})" for h in r["同步技协同"]["命中"])
            eg = "、".join(r["engage技"]) or "无"
            lines.append(
                f"- **{r['cn']}**(band{r['band']}, {r['入手']}) 主武器:{r['主武器']} | "
                f"精准匹配:{r['精准匹配']['分']}分({r['精准匹配']['依据']}) | "
                f"额外重合:{'/'.join(r['额外重合']['武器']) or '无'}({r['额外重合']['分']}分) | "
                f"同步技协同:{syn or '无'}({r['同步技协同']['分']}分) | "
                f"engage技:{eg}")
        lines += ["", f"*{fit['band说明']}*",
                  f"*未建模维度: {', '.join(fit['未建模维度'])}*"]
        return "\n".join(lines)

    if parts[0] == "强度":
        if len(parts) < 2:
            return "用法: 强度 <角色>"
        r2 = _res(parts[1], "角色")
        if isinstance(r2, str):
            return r2
        if r2["kind"] != "character":
            return f"「{parts[1]}」不是角色（解析为{r2['name_cn']}）"
        t = engine.tier_assessment(r2["id"])
        f = t["分项事实"]
        return (f"## {t['character']['cn']} · 分项事实\n"
                f"初始即时战力: {f['初始即时战力']['值']}（全游戏{f['初始即时战力']['全游戏排名']}）\n"
                f"成长潜力(Top5和): {f['成长潜力']['值']}（全游戏{f['成长潜力']['全游戏排名']}）\n"
                f"个人技机械估小计: {f['个人技价值']['机械估小计']}（全游戏{f['个人技价值']['全游戏排名']}）"
                f"——仅参考, 真实价值请综合判断\n"
                f"*引擎不提供综合结论; 综合强度请结合三维度自行权衡*\n"
                f"明细: {json.dumps(f['个人技价值']['明细'], ensure_ascii=False)}")

    if parts[0] == "机制":
        if len(parts) < 2:
            return "用法: 机制 <关键词> (如: 追击/锻造/资质/SP)"
        r = engine.get_knowledge(parts[1])
        if not r["files"]:
            return f"知识库无「{parts[1]}」相关内容"
        out = [f"匹配文件: {', '.join(r['files'])}"]
        for h in r["excerpts"]:
            out.append(f"--- {h['file']} ---")
            out.append(h["excerpt"][:600])
        return "\n".join(out)

    if parts[0] == "推荐":
        if len(parts) < 2:
            return "用法: 推荐 <角色>"
        r2 = _res(parts[1], "角色")
        if isinstance(r2, str):
            return r2
        if r2["kind"] != "character":
            return f"「{parts[1]}」不是角色（解析为{r2['name_cn']}）"
        return format.render_recommend(engine.recommend_builds(r2["id"]))

    r = engine.resolve_name(parts[0])
    if r is None:
        # 名称未识别 → 命令词模糊兜底(语音/错别字: "纹张 剑士" → "纹章 剑士")
        close = difflib.get_close_matches(parts[0], COMMAND_WORDS, n=1, cutoff=0.5)
        if close:
            return handle([close[0]] + parts[1:])
        return f"未识别名称「{parts[0]}」，试试: 克萝艾 / 花月 / 剑士 / 狮鹫骑士"
    if "candidates" in r:
        return _fmt_cands(parts[0], r)

    if r["kind"] == "class":
        return _class_brief(r["id"])

    if r["kind"] == "character":
        if len(parts) >= 2:
            r2 = _res(parts[1], "兵种")
            if isinstance(r2, str):
                return r2
            if r2["kind"] != "class":
                return f"「{parts[1]}」不是兵种（解析为{r2['name_cn']}）"
            ev = engine.compute_build(r["id"], r2["id"])
            out = format.render_build(ev, detail=DETAIL)
        else:
            card = engine.character_card(r["id"])
            out = format.render_character_detail(card) if DETAIL else format.render_character(card)
        return out
    return HELP


def _class_brief(class_id: str) -> str:
    k = engine.class_card(class_id)
    return (f"## {k['name_cn']}（{k['name_en']}）\n"
            f"{k['tier']} / {k['移动类型']} / 主武器:{k['主武器']}\n"
            f"兵种成长: " + " ".join(f"{engine.STAT_CN[s]}{g}" for s, g in k['兵种成长率'].items() if g))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    global DETAIL
    args = [a for a in sys.argv[1:] if a != "--详细"]
    if "--详细" in sys.argv:
        DETAIL = True
    if args:
        print(handle(args))
        return
    print("火焰纹章Engage 培养咨询 (P1) — 输入'帮助'看命令，'退出'结束")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        try:
            print(handle(line.split()))
        except Exception as e:
            print(f"[错误] {e}")


if __name__ == "__main__":
    main()
