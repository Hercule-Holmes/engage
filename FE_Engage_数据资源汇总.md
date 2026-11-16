# 火焰纹章 Engage（FE17）游戏数据搜索汇总

> 搜索日期：2026-11-16 · 覆盖国外（英文圈）与国内（中文圈）数据源

## 一、游戏基本信息

- **游戏名**：Fire Emblem Engage（FE17，中文官方名《火焰纹章 结合》，社区俗称"engage/结合"）
- **发售**：2023-01-20，Nintendo Switch，Intelligent Systems 开发 / Nintendo 发行
- **数据版本**：Ver.2.0.0（含全部 4 弹 DLC「邪龙之章」后数据最全）
- **数据规模**：可操作角色 41 人（本体 36 + DLC 5：Nel、Rafal、Zelestia、Gregory、Madeline）；兵种 40+；纹章士（Emblem）本体 12 + DLC 7

## 二、核心数据结构（抓取/建库时需覆盖的字段）

### 角色数据
- **属性**：HP / 力(Str) / 魔(Mag) / 技(Dex) / 速(Spd) / 守(Def) / 魔守(Res) / 幸(Lck) / 魅(Charm) + 体格(Bld)
- **成长率**：个人成长率 + 兵种成长率 = 实际成长率；Jean（吉恩）个人特技"英才"使兵种成长率×2
- 其他：初始兵种、加入章节、个人特技、武器/魔法资质（熟练度）、默认资质（有限转职）、礼物喜好、绊对话

### 兵种数据
- 兵种基础值 / 兵种成长率 / 兵种上限（三者独立成表）
- 移动类型（步行/重甲/骑兵/飞行/龙）、转职条件（资质 Level）、兵种习得技能（Lv1/10/20）

### 纹章士（Emblem）数据
- 12 本体：玛尔斯、西格尔特、赛莉卡、米卡雅、罗伊、里弗、露琪娜、琳、艾克、贝雷特、神威、艾莉可；13th 为琉尔（剧透）
- 7 DLC：艾黛尔贾特/帝弥托利/库罗德（三兄妹一体）、琪姬、海克托尔、塞涅里欧、卡美拉、库洛武&鲁弗莱、维洛妮卡
- 字段：同步特技（随绊等级解锁）、结合特技、结合武器、可继承技能（SP 价格表）、刻印（Engrave）加成、绊等级 1~20

### 武器道具
- 分类：剑 / 枪 / 斧 / 弓 / 匕首 / 魔法书 / 体术(Arts) / 杖
- 字段：威力(Mt)、命中、必杀、射程、重量、可锻冶（+1~+5）、特效（克制骑兵等）
- 特殊武器、纹章士结合武器、绊戒指（Bond Ring）、素材/料理

## 三、国外数据源（英文）

### 1. Serenes Forest —— 最权威、结构最全的系列数据站（纯文本表格，可直接抓取）

根目录：`https://serenesforest.net/engage/`

| 类别 | 页面（`serenesforest.net/engage/` 后拼接） | 内容 |
|---|---|---|
| 角色 | `characters/base-stats/` | 全角色初始值 |
| | `characters/growth-rates/` | 全角色成长率 ✅已验证，41 人全表 |
| | `characters/maximum-stats/` | 角色个人上限修正 |
| | `characters/personal-skills/` | 个人特技 |
| | `characters/recruitment/` | 加入条件/章节 |
| | `characters/support-list/` `characters/support-bonus/` | 绊系统 |
| | `characters/other-data/` | 资质、喜好等 |
| 兵种 | `classes/base-stats/` `classes/growth-rates/` `classes/maximum-stats/` | 三张核心数值表 |
| | `classes/learnable-skills/` `classes/other-data/` | 兵种技能、资质 |
| 纹章士 | `emblems/how-to-obtain/` | 获取章节 |
| | `emblems/marth|sigurd|celica|micaiah|roy|leif|lucina|lyn|ike|byleth|corrin|eirika|alear/` | 每人详情 |
| | `emblems/edelgard|tiki|hector|veronica|soren|camilla|chrom/` | DLC 纹章士 |
| | `emblems/veronica/summons/` | 维洛妮卡召唤单位 |
| 武器 | `weapons-items/swords|lances|axes|bows|knives|tomes|staves/` | 分武器数值 |
| | `weapons-items/arts/` `weapons-items/special-weapons/` | 体术、特殊武器 |
| | `weapons-items/bond-rings/` | 绊戒指 |
| 其他 | `miscellaneous/skills/` | 全技能索引 |
| | `miscellaneous/paralogues/` | 外传列表 |
| | `script/main-story/` `script/dlc-story/` 等 | 剧情文本（未完全） |

### 2. Wiki 百科（含页面内嵌数值表）
- **fireemblemwiki.org**（独立维基）：https://fireemblemwiki.org/wiki/List_of_classes_in_Fire_Emblem_Engage —— 兵种总表带初始值/成长（已验证：Dragon Child 神竜ノ子 Lv24、8/1/4/8/6/5/3/7/5）
- **Fandom 维基**：https://fireemblem.fandom.com/wiki/List_of_classes_in_Fire_Emblem_Engage

### 3. 社区整理表格（Google Sheets / Excel）
- GameFAQs 综合表（角色/兵种 初始值、成长率、平均值）：见 GameFAQs Engage 板块置顶帖
- Serenes 论坛可变兵种成长计算表：https://forums.serenesforest.net/topic/98030-...
- Reddit 成长率热力图：https://www.reddit.com/r/fireemblem/comments/10hjvtq/
- FE Engage Toolkit（成长模拟器/评级工具）

### 4. GitHub（机器可读数据/解析工具）
- **Raytwo/Cobalt** —— Engage 模组核心依赖，含 gamedata 解析（JSON）
- **Nifyr/A-Little-Secret-Ingredient** —— 随机化器（读取全量角色/兵种数据）
- **LordMewtwo73 的 Engage Randomizer** —— 随机化初始兵种/成长/上限
- **ViolaBuddy/Fire-Emblem-Data** —— 系列 HTML 数据收集 + Python 生成 MySQL（含 Engage，WIP）

## 四、国内数据源（中文）

### 1. 游民星空 gamersky（攻略最全，注意：多数数据表为图片，文字不可直接抓）
- 全角色攻略汇总（初始数据、专属兵种）：https://www.gamersky.com/handbook/202301/1559320.shtml
- 兵种成长率汇总（表格为图片）：https://www.gamersky.com/handbook/202301/1559571.shtml
- 纹章士刻印特技数据及搭配：https://www.gamersky.com/handbook/202302/1562074.shtml
- 全纹章士强度评级：https://www.gamersky.com/handbook/202302/1562634.shtml
- 武器数据系列（剑/枪/斧/弓/魔法书/匕首/体术/杖 分篇）

### 2. 腾讯文档在线 Excel（国内玩家整理的全数据表）
- 《火焰纹章ENGAGE》全攻略汇总表：https://docs.qq.com/sheet/DUXN5ZUlMVFNIdVZM?tab=iicbgv
  （关卡攻略 + 人物数据，巴哈姆特社区推荐的备份源，注意随时可能失效）

### 3. Bilibili 专栏 / 视频
- wiki 式详细攻略（战斗/经验/等级/SP 机制全解析）：https://www.bilibili.com/read/cv21850595
- 全纹章士继承能力信息表 Ver2.0（专栏系列）
- 「角色真实成长率」分析视频系列；B站搜索"火焰纹章engage 成长率"

### 4. 百度百科 / 知乎
- 百度百科逐角色词条（含成长率等数据，如"艾比"=Ivy：速40/魔30/技25）
- 知乎/贴吧：全角色培养与纹章士搭配推荐、兵种克制分析

## 五、附录：全 41 名角色个人成长率（Serenes Forest，已验证）

列：HP / 力 / 魔 / 技 / 速 / 守 / 魔守 / 幸 / 体格(%)，另有魅力未列于该表

| 角色 | HP | 力 | 魔 | 技 | 速 | 守 | 魔守 | 幸 | 体格 |
|---|---|---|---|---|---|---|---|---|---|
| Alear（琉尔） | 60 | 35 | 20 | 45 | 50 | 40 | 25 | 25 | 5 |
| Vander（凡德雷） | 60 | 25 | 10 | 25 | 35 | 35 | 20 | 10 | 5 |
| Clanne（柯岚） | 40 | 35 | 10 | 40 | 50 | 30 | 25 | 20 | 5 |
| Framme（芙岚） | 55 | 30 | 25 | 35 | 55 | 25 | 30 | 25 | 0 |
| Alfred（阿尔弗雷德） | 65 | 40 | 5 | 35 | 40 | 40 | 20 | 40 | 10 |
| Etie（艾堤耶） | 45 | 40 | 0 | 25 | 35 | 25 | 30 | 25 | 5 |
| Boucheron（布修隆） | 85 | 20 | 0 | 50 | 45 | 35 | 20 | 15 | 20 |
| Céline（锡莉奴） | 50 | 35 | 25 | 30 | 45 | 30 | 40 | 50 | 5 |
| Chloé（克萝艾） | 75 | 25 | 35 | 40 | 55 | 30 | 25 | 25 | 5 |
| Louis（路易） | 75 | 40 | 0 | 25 | 25 | 50 | 20 | 25 | 15 |
| Yunaka（尤娜卡） | 50 | 35 | 25 | 40 | 45 | 15 | 45 | 25 | 5 |
| Alcryst（史塔卢克） | 65 | 30 | 10 | 40 | 45 | 30 | 20 | 15 | 10 |
| Citrinne（希特丽妮卡） | 45 | 10 | 40 | 25 | 30 | 20 | 40 | 25 | 5 |
| Lapis（菈琵思） | 55 | 25 | 20 | 35 | 55 | 35 | 30 | 25 | 5 |
| Diamant（帝亚曼德） | 75 | 30 | 15 | 20 | 40 | 40 | 25 | 20 | 15 |
| Amber（安巴） | 65 | 45 | 0 | 25 | 30 | 35 | 5 | 35 | 15 |
| Jade（洁德） | 55 | 35 | 25 | 35 | 30 | 40 | 30 | 20 | 10 |
| Ivy（艾比/艾薇） | 55 | 25 | 30 | 25 | 40 | 30 | 35 | 15 | 10 |
| Kagetsu（花月） | 60 | 30 | 15 | 50 | 50 | 40 | 25 | 40 | 10 |
| Zelkov（杰尔科巴） | 65 | 35 | 15 | 40 | 35 | 35 | 15 | 25 | 10 |
| Fogado（佛贾特） | 60 | 30 | 25 | 30 | 55 | 30 | 35 | 25 | 10 |
| Pandreo（庞德罗） | 60 | 5 | 30 | 45 | 45 | 15 | 55 | 30 | 15 |
| Bunet（波聂） | 65 | 30 | 10 | 40 | 35 | 45 | 25 | 40 | 10 |
| Timerra（蜜丝提拉/蒂米拉） | 55 | 25 | 25 | 45 | 45 | 30 | 30 | 30 | 10 |
| Panette（帕涅托涅） | 75 | 45 | 10 | 40 | 25 | 30 | 15 | 20 | 15 |
| Merrin（玫琳） | 55 | 25 | 25 | 40 | 50 | 30 | 30 | 25 | 10 |
| Hortensia（奥尔坦希亚） | 40 | 20 | 20 | 35 | 50 | 25 | 55 | 50 | 0 |
| Seadall（赛安达斯） | 55 | 25 | 15 | 25 | 50 | 25 | 25 | 35 | 10 |
| Rosado（罗萨德） | 75 | 45 | 25 | 40 | 45 | 30 | 30 | 20 | 5 |
| Goldmary（戈尔德玛莉） | 65 | 30 | 5 | 25 | 25 | 55 | 25 | 25 | 5 |
| Lindon（孤栗） | 65 | 25 | 25 | 25 | 40 | 25 | 40 | 15 | 10 |
| Saphir（赛皮雅） | 80 | 35 | 0 | 25 | 30 | 30 | 5 | 20 | 10 |
| Veyle（薇尔/贝珥） | 40 | 25 | 45 | 35 | 30 | 25 | 35 | 20 | 0 |
| Mauvier（莫布/莫维叶） | 70 | 35 | 40 | 40 | 35 | 50 | 45 | 15 | 15 |
| Anna（安娜） | 55 | 15 | 50 | 50 | 50 | 20 | 35 | 45 | 5 |
| Jean（吉恩） | 50 | 20 | 20 | 35 | 40 | 25 | 20 | 25 | 5 |
| Nel（尼尔，DLC） | 55 | 30 | 25 | 40 | 45 | 30 | 35 | 30 | 10 |
| Rafal（拉法尔，DLC） | 70 | 40 | 10 | 40 | 35 | 45 | 20 | 10 | 10 |
| Zelestia（泽莱斯提亚，DLC） | 60 | 35 | 35 | 35 | 50 | 30 | 35 | 20 | 5 |
| Gregory（格雷戈里，DLC） | 55 | 30 | 50 | 20 | 25 | 35 | 50 | 25 | 5 |
| Madeline（玛德琳，DLC） | 75 | 50 | 20 | 15 | 15 | 55 | 25 | 25 | 10 |

**亮点值**：HP 最高 Boucheron 85；力最高 Madeline 50；魔并列 Anna/Gregory/Veyle 50；速最高 Framme/Chloé/Lapis/Fogado 55；守最高 Goldmary 55；魔守最高 Hortensia/Pandreo/Gregory 55；幸最高 Céline/Hortensia 50。

> 注：中文译名以社区常用（游民星空/百度百科）为准，个别角色官方译名与社区译名存在差异（如 Ivy：官方"艾薇"，社区"艾比"）。

## 六、建议的下一步（数据工程视角）

1. **主数据抓取**：Serenes Forest 纯文本表格最规整，可写爬虫一次性抓全部页面 → 生成 CSV/JSON（角色、兵种、武器、纹章士 4 张核心表）
2. **中文译名对照**：以 gamersky/B站官方译名帖建立 EN↔CN 映射表
3. **机制公式**：伤害=力+武器威力-守；命中=技×2+幸/2+武器命中-敌方回避(速×2+幸/2)；追击需速度-体格>敌方等（cv21850595 有完整公式）
4. **兜底校验**：与 fireemblemwiki.org / GameFAQs 表格交叉验证数值
