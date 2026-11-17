# -*- coding: utf-8 -*-
"""工具层: 12 个工具的显式 JSON schema + dispatch → engage_core。
schema 是引擎证据卡契约给 LLM 的入口; dispatch 负责参数校验与错误归一。
"""
import json

from engage_core import engine

# ---------- 显式 schema ----------

_TOOL_DEFS = [
    ("resolve_name", "解析用户口中的角色/兵种/纹章士名称(支持中文、英文、别名、拼音同音、模糊音)。调用其他工具前必须先用本工具把名字转成 id。",
     {"type": "object", "properties": {"text": {"type": "string", "description": "名称原文, 如'克萝艾'/'花月'/'剑士'"}},
      "required": ["text"]}),
    ("character_card", "角色完整卡片: 初始值/个人成长率(含41人排名)/个人特技/天资资质/加入信息。",
     {"type": "object", "properties": {"char_id": {"type": "string"}}, "required": ["char_id"]}),
    ("class_card", "兵种完整卡片: 基础值/兵种成长率/上限/资质要求/兵种技能/移动类型。",
     {"type": "object", "properties": {"class_id": {"type": "string"}}, "required": ["class_id"]}),
    ("can_reclass", "判断角色能否转该兵种(近似规则:仅判天资, 牵绊资质未建模, 结论偏保守)。",
     {"type": "object", "properties": {"char_id": {"type": "string"}, "class_id": {"type": "string"}},
      "required": ["char_id", "class_id"]}),
    ("compute_build", "路线评估证据卡(P6事件式): 转职资格+合计成长率(含排名)+分段等级预测(当前兵种→转职点→阶级基础差→新兵种成长; 晋升重置等级为1/平转保持)+作战证据表。promote_at=计划转职点, 可对比不同转职时点。",
     {"type": "object",
      "properties": {"char_id": {"type": "string"}, "class_id": {"type": "string"},
                     "level": {"type": "integer", "default": 20},
                     "promote_at": {"type": ["integer", "null"], "default": None,
                                    "description": "计划转职的当前兵种显示等级; null=最早可行时点(晋升按Lv10下限, 平转=加入等级); 可对比不同转职时点"}},
      "required": ["char_id", "class_id"]}),
    ("compare_builds", "多兵种并排对比: 对同一角色返回多个路线证据卡列表。",
     {"type": "object",
      "properties": {"char_id": {"type": "string"}, "class_ids": {"type": "array", "items": {"type": "string"}},
                     "level": {"type": "integer", "default": 20}},
      "required": ["char_id", "class_ids"]}),
    ("recommend_builds", "按角色个人成长Top3属性推荐适配兵种(透明排序启发式,非强度结论;分数=成长加总+天资加成5)。",
     {"type": "object",
      "properties": {"char_id": {"type": "string"}, "top_n": {"type": "integer", "default": 5}},
      "required": ["char_id"]}),
    ("emblem_fit", "纹章士适配(纯组件事实, 不排序不推荐): 每个纹章士返回精准匹配/额外重合/同步技协同/入手章节/engage技要点。max_chapter=效用过滤(只看该章前可得); sort_by='chapter'|'precise'客观排序。哪个纹章士更适合须结合效用由你自行论证并说明排除逻辑。",
     {"type": "object",
      "properties": {"char_id": {"type": "string"}, "class_id": {"type": "string"},
                     "max_chapter": {"type": ["integer", "null"],
                                     "description": "只看该章节前可得的非DLC纹章士"},
                     "sort_by": {"type": ["string", "null"],
                                 "enum": ["chapter", "precise", None],
                                 "description": "客观单一维度排序"}},
      "required": ["char_id", "class_id"]}),
    ("engage_detail", "纹章士Engage技/奥义完整事实卡(按需详情): 技能名/解锁牵绊/完整描述+Engage武器全参数。emblem_fit 只列要点, 完整描述用本工具。",
     {"type": "object", "properties": {"emblem_id": {"type": "string"}}, "required": ["emblem_id"]}),
    ("query_weapons", "武器查询: 按类型(sword/lance/axe/bow/knife/tome/staff/arts/special)与名称关键词过滤。",
     {"type": "object",
      "properties": {"weapon_type": {"type": "string", "default": ""},
                     "keyword": {"type": "string", "default": ""}}}),
    ("tier_assessment", "强度分项事实卡: 初始即时战力/成长潜力(Top5和)/个人技价值明细, 各带全游戏独立排名。注意: 没有官方综合分——综合强度判断由你基于分项自行论证并说明权衡逻辑。",
     {"type": "object", "properties": {"char_id": {"type": "string"}}, "required": ["char_id"]}),
    ("role_check", "定位核查: 该路线在12定位词表(回避坦/追击手/斩杀手/承伤坦/治疗位/再动位/泛用型/过渡型等)下的关键指标实际值+同兵种排名。引擎不判定归属——定位判断由你按词表定义与分布论证; 零命中属合法结果。",
     {"type": "object",
      "properties": {"char_id": {"type": "string"}, "class_id": {"type": "string"},
                     "level": {"type": "integer", "default": 20}},
      "required": ["char_id", "class_id"]}),
    ("get_knowledge", "机制公式/攻略知识检索(如'追击'/'伤害公式'/'锻造'/'资质'/'SP')。",
     {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
]

TOOL_SCHEMAS = [
    {"type": "function",
     "function": {"name": name, "description": desc, "parameters": params}}
    for name, desc, params in _TOOL_DEFS
]

TOOL_NAMES = {name for name, _, _ in _TOOL_DEFS}

# ---------- dispatch ----------

_HANDLERS = {
    "resolve_name": lambda a: engine.resolve_name(a["text"]),
    "character_card": lambda a: engine.character_card(a["char_id"]),
    "class_card": lambda a: engine.class_card(a["class_id"]),
    "can_reclass": lambda a: engine.can_reclass(a["char_id"], a["class_id"]),
    "compute_build": lambda a: engine.compute_build(a["char_id"], a["class_id"],
                                                    a.get("level", 20), a.get("promote_at")),
    "compare_builds": lambda a: engine.compare_builds(a["char_id"], a["class_ids"],
                                                      a.get("level", 20), a.get("promote_at")),
    "recommend_builds": lambda a: engine.recommend_builds(a["char_id"], a.get("top_n", 5)),
    "emblem_fit": lambda a: engine.emblem_fit(a["char_id"], a["class_id"],
                                              a.get("max_chapter"), a.get("sort_by")),
    "engage_detail": lambda a: engine.emblem_engage_detail(a["emblem_id"]),
    "query_weapons": lambda a: engine.query_weapons(a.get("weapon_type") or None, a.get("keyword") or None),
    "tier_assessment": lambda a: engine.tier_assessment(a["char_id"]),
    "role_check": lambda a: engine.role_check(a["char_id"], a["class_id"],
                                              a.get("level", 20), a.get("promote_at")),
    "get_knowledge": lambda a: engine.get_knowledge(a["query"]),
}


def dispatch(name: str, arguments_json: str) -> str:
    """执行工具调用, 返回证据卡JSON字符串。错误归一为可执行的提示(附最近候选)。"""
    if name not in TOOL_NAMES:
        return json.dumps({"error": f"未知工具 {name}",
                           "hint": f"可用工具: {sorted(TOOL_NAMES)}"}, ensure_ascii=False)
    try:
        args = json.loads(arguments_json or "{}")
        if not isinstance(args, dict):
            raise ValueError("参数必须是JSON对象")
        result = _HANDLERS[name](args)
        return json.dumps(result, ensure_ascii=False, default=str)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"参数不是合法JSON: {e}",
                           "hint": "请修正arguments后重试"}, ensure_ascii=False)
    except KeyError as e:
        return json.dumps({"error": f"缺少必需参数: {e}",
                           "hint": "查看工具schema的required字段"}, ensure_ascii=False)
    except Exception as e:  # 引擎内部错误也结构化回喂, 不中断循环
        return json.dumps({"error": f"{type(e).__name__}: {e}",
                           "hint": "可尝试修正参数; 若持续失败请告知用户换一个问题角度"}, ensure_ascii=False)
