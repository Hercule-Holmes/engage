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
    "(6)emblem_fit/recommend_builds 返回并列分组(band)的组件事实,无综合分;"
    "band不构成推荐,组内顺序无含义;权衡由你基于组件完成,"
    "并说明'未建模维度'字段所列维度(engage武器/专属特技/入手门槛等)对结论的影响;"
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
def compute_build(char_id: str, class_id: str, level: int = 20) -> str:
    """路线评估证据卡: 转职资格+合计成长率(个人+兵种,含同兵种41人排名)+Lv预测值+假设声明。"""
    return _j(engine.compute_build(char_id, class_id, level))


@mcp.tool()
def compare_builds(char_id: str, class_ids: list, level: int = 20) -> str:
    """多兵种并排对比: 对同一角色返回多个 compute_build 证据卡列表。"""
    return _j(engine.compare_builds(char_id, class_ids, level))


@mcp.tool()
def recommend_builds(char_id: str, top_n: int = 5) -> str:
    """按角色个人成长Top3属性推荐适配兵种Top-N(透明排序启发式,非强度结论)。"""
    return _j(engine.recommend_builds(char_id, top_n))


@mcp.tool()
def emblem_fit(char_id: str, class_id: str, top_n: int | None = None) -> str:
    """纹章士适配: 返回全量候选的组件事实卡(精准匹配/额外重合/同步技协同), 按band并列分组。
    band是组件合计相同的并列组, 不是推荐排序, 组内顺序无含义; 默认全量返回,
    传入top_n时按band整组截断保证并列完整。
    综合与权衡由调用方基于组件完成, 应结合'未建模维度'字段说明本工具未覆盖维度的影响。"""
    return _j(engine.emblem_fit(char_id, class_id, top_n))


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
def get_knowledge(query: str) -> str:
    """机制公式/攻略知识检索(如'追击'/'伤害公式'/'锻造')。"""
    return _j(engine.get_knowledge(query))


if __name__ == "__main__":
    mcp.run()
