# -*- coding: utf-8 -*-
"""MCP Server——把 engage_core 引擎注册为 MCP 工具（薄封装）。

接入 Claude Code:  claude mcp add engage -- python F:/nstool/engage/shells/mcp_server.py
工具返回 JSON 字符串（证据卡契约）。数字全部来自引擎，禁止 LLM 自行补数。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from engage_core import engine  # noqa: E402

mcp = FastMCP("engage", instructions=(
    "火焰纹章Engage培养咨询工具。使用规范:"
    "(1)先 resolve_name 解析用户口中的角色/兵种名;"
    "语音/手打输入常含错字: 拼音层会兜住同音字(如'花悦'→花月), 编辑距离层兜住手误;"
    "若返回 candidates 多候选, 结合对话上下文选最可能一项, 无法确定就用候选清单向用户确认,"
    "禁止直接取第一个;"
    "(2)数字与排名只准引用工具返回值,禁止凭记忆补充数值;"
    "(3)回答默认分层简评(结论+关键数字),用户追问'详细'才展开完整表格;"
    "(4)转职资格为近似规则(仅判天资),不满足时如实说明牵绊可补;"
    "(5)反锚定铁律: 工具只提供分项事实,没有官方综合分。"
    "综合强度判断(如'她是不是第一梯队')必须由你基于分项事实自行论证,"
    "并明确说明你的权衡逻辑(如'成长平庸但技能定义玩法,我更看重后者')。"
    "个人技价值的'机械估小计'只是换算参考,不代表技能真实价值;"
    "(5b)个人技为条件触发效果: compute_build/combat证据里的技活数值是'条件成立时'的影响,"
    "条件是否成立/多常成立/值多少权重由你结合玩法语境判断(get_knowledge('触发条件')有经验参考);"
    "(6)emblem_fit 返回纯组件事实,不排序不分组不推荐;"
    "先用定位引出(role_check的12定位词表: 开荒期→max_chapter过滤/长期成型/特定玩法),"
    "再从组件论证2~3个候选并说明排除逻辑;"
    "recommend_builds 的score是成长匹配启发式,非强度结论;"
    "权衡由你基于组件完成,并说明'未建模维度'字段所列维度(engage武器/专属特技/入手门槛等)对结论的影响;"
    "(6b)'她适合什么定位/玩法' → role_check 输出指标实际值与定位词表,归属判断由你论证;"
    "(7)强度判断依据 compute_build 的证据卡(combat字段:对基准敌的伤害/命中/追击/反击安全)"
    "与 patterns_hit 模式标签(如one_shot_ranged=可远程秒杀),综合解读而非照抄;"
    "(8)推荐类结论给出前自检: 候选集是否完整(band是否全组呈现)?"
    "并列段内做过权衡还是只取切片?论断是否全部来自工具返回值?"
    "凡非工具来源的信息必须显式标注'待验证',不得作为事实断言。"
))


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


@mcp.tool()
def resolve_name(text: str) -> str:
    """解析中/英文角色名、兵种名、别名(如'花月'→Kagetsu)。
    分层容错: 规范化→精确→包含→拼音(语音同音字, 如'花悦')→模糊音→编辑距离。
    唯一命中返回 kind+id+中英名; 多候选返回 {query, candidates}; 无命中返回 null。"""
    return _j(engine.resolve_name(text))


@mcp.tool()
def character_card(char_id: str) -> str:
    """角色完整卡片: 初始值、个人成长率(含41人排名)、个人特技、天资资质、加入信息。"""
    return _j(engine.character_card(char_id))


@mcp.tool()
def class_card(class_id: str) -> str:
    """兵种完整卡片: 基础值、兵种成长率、上限、资质要求、兵种技能、移动类型。"""
    return _j(engine.class_card(class_id))


@mcp.tool()
def can_reclass(char_id: str, class_id: str) -> str:
    """判断角色能否转该兵种(近似规则:仅判天资,牵绊资质未建模,结论偏保守)。"""
    return _j(engine.can_reclass(char_id, class_id))


@mcp.tool()
def compute_build(char_id: str, class_id: str, level: int = 20,
                  promote_at: int | None = None) -> str:
    """路线评估证据卡: 转职资格+合计成长率(个人+兵种,含同兵种41人排名)+分段等级预测
    (段1旧兵种→转职点→段2兵种基础差→段3新兵种)+作战证据表+假设声明。
    promote_at=计划转职的当前兵种显示等级; null=最早可行时点(晋升按Lv10下限)。"""
    return _j(engine.compute_build(char_id, class_id, level, promote_at))


@mcp.tool()
def compare_builds(char_id: str, class_ids: list, level: int = 20,
                   promote_at: int | None = None) -> str:
    """多兵种并排对比: 对同一角色返回多个 compute_build 证据卡列表。"""
    return _j(engine.compare_builds(char_id, class_ids, level, promote_at))


@mcp.tool()
def recommend_builds(char_id: str, top_n: int = 5) -> str:
    """按角色个人成长Top3属性推荐适配兵种Top-N(透明排序启发式,非强度结论)。"""
    return _j(engine.recommend_builds(char_id, top_n))


@mcp.tool()
def emblem_fit(char_id: str, class_id: str, max_chapter: int | None = None,
               sort_by: str | None = None) -> str:
    """纹章士适配(纯组件事实, 不排序不分组不推荐): 每个纹章士返回
    精准匹配/额外重合/同步技协同/入手章节/engage技要点。
    max_chapter=效用过滤(只看该章前可得, 解决开荒期推荐后期纹章的荒谬);
    sort_by='chapter'|'precise' 为客观单一维度排序, 默认不排序。
    哪个纹章士更适合须结合效用(开荒/长期/玩法)与未建模维度由 LLM 自行论证。"""
    return _j(engine.emblem_fit(char_id, class_id, max_chapter, sort_by))


@mcp.tool()
def engage_detail(emblem_id: str) -> str:
    """Engage技/奥义完整事实卡(按需详情): 技能名/解锁牵绊/完整描述 + Engage武器全参数(含效果注记)。
    emblem_fit 只列engage技要点(名+解锁牵绊+武器数值摘要), 完整描述用本工具按需取。"""
    return _j(engine.emblem_engage_detail(emblem_id))


@mcp.tool()
def query_weapons(weapon_type: str = "", keyword: str = "") -> str:
    """武器查询: 按类型(sword/lance/axe/bow/knife/tome/staff/arts/special)与关键词过滤。"""
    return _j(engine.query_weapons(weapon_type or None, keyword or None))


@mcp.tool()
def tier_assessment(char_id: str) -> str:
    """分项事实卡: 初始即时战力/成长潜力(Top5和)/个人技价值明细, 各带全游戏独立排名。
    无综合分——综合强度判断由 LLM 基于分项自行论证。"""
    return _j(engine.tier_assessment(char_id))


@mcp.tool()
def role_check(char_id: str, class_id: str, level: int = 20,
               promote_at: int | None = None) -> str:
    """定位核查: 该路线在12个定位词表(回避坦/追击手/斩杀手/承伤坦/治疗位/泛用型...)下的
    关键指标实际值+同兵种排名。引擎不判定定位归属——'算不算合格的X'由 LLM 按词表定义与
    数据分布论证; 命中零定位属合法结果(泛用型/过渡型)。"""
    return _j(engine.role_check(char_id, class_id, level, promote_at))


@mcp.tool()
def get_knowledge(query: str) -> str:
    """机制公式/攻略知识检索(如'追击'/'伤害公式'/'锻造'/'触发条件')。"""
    return _j(engine.get_knowledge(query))


if __name__ == "__main__":
    mcp.run()
