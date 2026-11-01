# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""MBENCH-004 P1-1：从候选池构建证据合同人工标注集（locomo-contract-gold-v1）。

标注协议（v1）：
- label: MUST_CAPTURE（稳定事实/明确偏好/具体计划/重要经历，第一手或可靠转述）/
         MAY_CAPTURE（有价值但边缘：瞬时状态、一次性活动、弱意图、依赖上下文）/
         MUST_NOT_CAPTURE（碎片、抽取模板残留、问句、共情应答等非事实）
- category: identity_state / preference_habit / plan_intent / ability_experience / other
- subject: self / children / relationship / other:<名>（事实主体，非说话者）
- fact_time: current / past / future / unspecified
- evidence_binding: exact（逐字引语）/ paraphrase（意译或三人称）/ none
- 文本不入库（CC-BY-NC）：本文件只含标签与 sample_key/content_sha1 锚定，
  文本在运行时从 gitignored 候选池 JSONL 连接。

用法：python memory_eval/annotation/build_gold_v1.py
输出：memory_eval/annotation/locomo-contract-gold.jsonl
"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
POOL = HERE.parent.parent / "memory" / "benchmark" / "_public" / "locomo" / "annotation" / "candidate-pool.jsonl"
OUT = HERE / "locomo-contract-gold.jsonl"

LABEL_VERSION = "locomo-contract-gold-v1"

# (pool_idx, label, category, subject, fact_time, binding, note)
A = [  # en-conv-26
 (0, "MAY_CAPTURE", "other", "self", "current", "exact", "瞬时状态（忙），非稳定事实"),
 (1, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "昨日参加互助小组"),
 (3, "MUST_CAPTURE", "plan_intent", "self", "future", "paraphrase", "打算继续学业"),
 (4, "MUST_CAPTURE", "plan_intent", "self", "future", "paraphrase", "职业意向：心理咨询/心理健康"),
 (6, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "去年画湖边日出"),
 (7, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "画画是表达方式"),
 (8, "MAY_CAPTURE", "preference_habit", "self", "current", "exact", "指代不明的观点句"),
 (10, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "抽取模板残留（X 占位符），非对话内容"),
 (11, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "单亲家长"),
 (12, "MUST_CAPTURE", "plan_intent", "self", "current", "exact", "正在调研领养机构"),
 (15, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "喜欢画画"),
 (16, "MUST_CAPTURE", "ability_experience", "self", "current", "exact", "会拉小提琴"),
 (17, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "习惯性跑步"),
 (18, "MAY_CAPTURE", "preference_habit", "self", "current", "exact", "过泛（I read）"),
 (20, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "去年画作（与6同事实二次强化）"),
 (21, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "上周六慈善跑"),
 (22, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "下月露营计划（subject=we）"),
 (23, "MAY_CAPTURE", "other", "self", "current", "exact", "领悟表述，非事实"),
 (27, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "LGBTQ+ 身份"),
 (28, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "单亲家长（与11同事实二次强化）"),
 (29, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "三年前开始过渡"),
 (30, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "从祖国搬来"),
 (31, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "认识朋友4年"),
 (33, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "碎片（5 years already!）"),
 (35, "MAY_CAPTURE", "preference_habit", "self", "current", "exact", "价值观格言（Family is everything）"),
 (36, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "来自瑞典"),
 (38, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "艰难分手经历"),
 (40, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "跨性别者"),
 (41, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "想从事跨性别者相关工作"),
 (42, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "上周五参加工作坊"),
 (43, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "奶奶送的项链（财物）"),
 (46, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "有两个较小的孩子"),
 (49, "MUST_CAPTURE", "plan_intent", "self", "current", "exact", "正在探索心理咨询职业"),
 (51, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "碎片（people like me）"),
 (53, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "本月参加跨性别者大会"),
 (54, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "昨天报名陶艺课"),
 (55, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "陶艺爱好者"),
 (57, "MUST_CAPTURE", "preference_habit", "children", "current", "paraphrase", "subject=孩子们（第三人主体的家庭事实）"),
 (62, "MUST_CAPTURE", "plan_intent", "self", "current", "exact", "为孩子建图书馆（进行中）"),
 (68, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "热爱当妈妈"),
 (69, "MUST_CAPTURE", "preference_habit", "self", "past", "exact", "童年喜欢的书（过去偏好）"),
 (71, "MUST_CAPTURE", "identity_state", "self", "current", "paraphrase", "三人称意译自身身份（主体=说话者）"),
 (72, "MUST_CAPTURE", "ability_experience", "self", "past", "paraphrase", "曾经历心理健康挣扎"),
 (73, "MUST_CAPTURE", "plan_intent", "self", "current", "paraphrase", "正在追求心理咨询职业"),
 (75, "MUST_CAPTURE", "preference_habit", "self", "current", "paraphrase", "最喜欢的书 Becoming Nicole"),
 (78, "MUST_CAPTURE", "identity_state", "self", "current", "paraphrase", "三人称意译自身（Melanie 是母亲）"),
 (79, "MUST_CAPTURE", "identity_state", "self", "current", "paraphrase", "宠物 Luna 与 Oliver"),
 (80, "MUST_CAPTURE", "preference_habit", "self", "current", "paraphrase", "跑步减压"),
 (83, "MUST_CAPTURE", "plan_intent", "self", "current", "paraphrase", "中文意译：考虑心理咨询职业"),
 (101, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "正在办 LGBTQ 艺术展"),
 (104, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "一年只去一两次海滩（频率习惯）"),
 (106, "MUST_CAPTURE", "ability_experience", "children", "past", "exact", "小女儿迈出第一步（家庭里程碑）"),
 (110, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "我是艺术家"),
 (114, "MAY_CAPTURE", "preference_habit", "self", "current", "exact", "对书的感受，指代依赖上下文"),
 (120, "MUST_CAPTURE", "ability_experience", "self", "past", "paraphrase", "徒步时被言语攻击（负面经历）"),
 (122, "MUST_CAPTURE", "identity_state", "relationship", "current", "paraphrase", "Caroline 与 Melanie 的支持性友谊"),
 (124, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "猫叫 Bailey"),
 (128, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "小时候常骑马（过去习惯——past/current 测试点）"),
 (129, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "一直喜欢马"),
 (131, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "已申请领养机构"),
 (135, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "我是女性"),
 (137, "MUST_NOT_CAPTURE", "other", "other", "unspecified", "exact", "共情应答句（对他人情绪的回应），非事实"),
 (141, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "最爱画风景与静物"),
 (146, "MAY_CAPTURE", "other", "other:Caroline", "current", "exact", "夸赞他人（I'm in awe of your courage）——易被误当说话者偏好"),
 (148, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "最爱画花"),
 (149, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "下月办 LGBTQ 艺术展"),
 (150, "MUST_CAPTURE", "ability_experience", "self", "current", "paraphrase", "弹木吉他约5年"),
 (153, "MUST_CAPTURE", "preference_habit", "self", "current", "paraphrase", "歌曲 Brave 对其有特殊意义"),
 (157, "MUST_CAPTURE", "preference_habit", "self", "current", "paraphrase", "喜欢古典+现代音乐"),
 (158, "MUST_CAPTURE", "identity_state", "self", "current", "paraphrase", "跨性别女性（与40/27同事实重复强化）"),
 (159, "MUST_CAPTURE", "ability_experience", "self", "past", "paraphrase", "17岁起创作艺术"),
 (164, "MUST_CAPTURE", "identity_state", "self", "current", "paraphrase", "三人称意译自身（是家长）"),
 (167, "MUST_CAPTURE", "plan_intent", "self", "future", "paraphrase", "中文意译：下月办艺术展"),
 (170, "MUST_CAPTURE", "identity_state", "self", "current", "paraphrase", "中文意译：跨性别女性"),
 (173, "MUST_CAPTURE", "ability_experience", "self", "past", "paraphrase", "上个月受伤暂停陶艺"),
 (174, "MUST_CAPTURE", "ability_experience", "children", "past", "paraphrase", "儿子近期车祸（第三人/敏感家庭事件）"),
 (182, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "上周五通过领养面试"),
 (183, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "希望建立自己的家庭"),
 (185, "MAY_CAPTURE", "ability_experience", "self", "past", "exact", "自我接纳是长过程（模糊）"),
 (187, "MAY_CAPTURE", "other", "self", "current", "exact", "格言式表达"),
]
B = [  # zh-conv-26
 (188, "MAY_CAPTURE", "other", "self", "current", "exact", "瞬时状态（忙）"),
 (189, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "昨天参加互助小组"),
 (190, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "打算继续学业"),
 (191, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "对心理咨询感兴趣"),
 (192, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "去年画湖边日出"),
 (193, "MAY_CAPTURE", "ability_experience", "self", "current", "exact", "一次性活动（带孩子游泳）"),
 (194, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "碎片（跨性别者，无谓语）"),
 (197, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "单亲家长"),
 (198, "MUST_CAPTURE", "plan_intent", "self", "future", "paraphrase", "梦想组建家庭+正在调研领养"),
 (200, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "有孩子"),
 (201, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "喜欢画画"),
 (203, "MUST_CAPTURE", "ability_experience", "self", "current", "exact", "会拉小提琴"),
 (206, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "考虑下月露营"),
 (207, "MUST_CAPTURE", "plan_intent", "self", "future", "paraphrase", "梦想组建家庭"),
 (208, "MAY_CAPTURE", "other", "self", "unspecified", "paraphrase", "假设语气（作为单亲家长会很不容易）"),
 (211, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "认识朋友4年+从祖国搬来"),
 (212, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "碎片（尤其是那次分手之后）"),
 (214, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "碎片（已经5年了）"),
 (215, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "来自瑞典"),
 (217, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "经历过分手"),
 (218, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "奶奶送的项链"),
 (221, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "我是跨性别者"),
 (222, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "想从事跨性别者心理咨询"),
 (223, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "参加过心理咨询工作坊"),
 (226, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "有两个较小的孩子"),
 (229, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "手绘碗（朋友十年前做）"),
 (230, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "上周带家人露营"),
 (232, "MAY_CAPTURE", "other", "self", "current", "paraphrase", "长句意译（经历+意愿混合）"),
 (233, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "参加了骄傲游行"),
 (234, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "昨天报名陶艺课"),
 (237, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "本月参加跨性别者大会"),
 (242, "MUST_CAPTURE", "plan_intent", "self", "current", "exact", "正在为将来建儿童图书馆"),
 (249, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "话题碎片（我为什么喜欢当妈妈）"),
 (251, "MAY_CAPTURE", "preference_habit", "self", "current", "exact", "指代依赖（我们很喜欢它）"),
 (254, "MUST_CAPTURE", "plan_intent", "self", "current", "paraphrase", "正在建儿童图书馆（与242同事实意译）"),
 (257, "MUST_CAPTURE", "identity_state", "children", "current", "paraphrase", "孩子喜欢恐龙博物馆（subject=children）"),
 (258, "MUST_CAPTURE", "identity_state", "self", "current", "paraphrase", "宠物 Luna 与 Oliver"),
 (261, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "蓝色是最喜欢的颜色"),
 (262, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "更坚定要领养"),
 (264, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "碎片（Luna和Oliver，无谓语）"),
 (267, "MAY_CAPTURE", "other", "self", "current", "exact", "瞬时状态（我这边特别忙）"),
 (270, "MAY_CAPTURE", "other", "self", "current", "exact", "婚礼布置指代句，依赖上下文"),
 (276, "MAY_CAPTURE", "other", "self", "past", "exact", "领悟表述（意识到可以做你自己）"),
 (278, "MUST_CAPTURE", "ability_experience", "self", "current", "exact", "参加 LGBTQ 青年导师项目"),
 (284, "MAY_CAPTURE", "ability_experience", "self", "current", "exact", "遇到支持的年轻人（模糊）"),
 (285, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "碎片（展出我的画）"),
 (287, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "组织名 Connected LGBTQ Activists"),
 (288, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "一年只去一两次（频率）"),
 (290, "MUST_CAPTURE", "ability_experience", "children", "past", "exact", "小女儿迈出第一步"),
 (296, "MUST_CAPTURE", "identity_state", "self", "current", "paraphrase", "三人称意译自身（跨性别者+带教青少年）"),
 (299, "MUST_CAPTURE", "ability_experience", "self", "past", "paraphrase", "徒步时遭言语攻击"),
 (300, "MUST_CAPTURE", "preference_habit", "self", "current", "paraphrase", "Melanie 喜欢陶艺（三人称自述）"),
 (304, "MUST_CAPTURE", "ability_experience", "self", "past", "paraphrase", "已向领养机构提交申请"),
 (313, "MUST_CAPTURE", "plan_intent", "self", "future", "paraphrase", "计划今年夏天出游"),
 (317, "MAY_CAPTURE", "identity_state", "self", "current", "paraphrase", "宠物 Oliver（候选自带“推测”不确定标记）"),
 (322, "MAY_CAPTURE", "ability_experience", "self", "current", "exact", "一次性见闻（彩虹人行道）"),
 (328, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "歌曲 Brave 意义重大"),
 (331, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "碎片（我有多爱现场音乐）"),
 (338, "MAY_CAPTURE", "other", "self", "current", "exact", "意义表述（看到工作带来改变）"),
 (344, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "碎片（已经七年了[接触艺术]，带方括号伪迹）"),
]
C = [  # zh-conv-30
 (377, "MUST_CAPTURE", "identity_state", "self", "current", "paraphrase", "失业+计划开舞蹈工作室（Jon）"),
 (378, "MUST_CAPTURE", "preference_habit", "self", "current", "paraphrase", "热爱跳舞，偏好当代舞"),
 (379, "MUST_CAPTURE", "identity_state", "self", "current", "paraphrase", "Gina 本月失业（此前 Door Dash）"),
 (380, "MUST_CAPTURE", "preference_habit", "self", "current", "paraphrase", "Gina 热爱跳舞"),
 (381, "MUST_CAPTURE", "ability_experience", "self", "past", "paraphrase", "15岁随舞蹈队获地区第一"),
 (382, "MUST_CAPTURE", "ability_experience", "self", "past", "paraphrase", "去年舞蹈队本地第一"),
 (383, "MUST_CAPTURE", "plan_intent", "self", "future", "paraphrase", "下个月节日表演，正在编舞"),
 (384, "MUST_CAPTURE", "plan_intent", "self", "future", "paraphrase", "约了下周五舞蹈练习"),
 (385, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "去年比赛第一时拍的（照片）"),
 (386, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "下班后与舞者排练（习惯）"),
 (387, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "碎片（我和学生跳舞时安全）"),
 (388, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "昨天去了巴黎"),
 (390, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "以前参加过舞蹈比赛和演出"),
 (392, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "碎片（自己开店）"),
 (393, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "只去过罗马一次"),
 (394, "MUST_CAPTURE", "plan_intent", "self", "current", "exact", "还在找舞蹈工作室场地"),
 (399, "MAY_CAPTURE", "plan_intent", "self", "future", "exact", "可以扩大服装店（弱意图）"),
 (405, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "正在准备下月舞蹈比赛"),
 (406, "MAY_CAPTURE", "other", "self", "current", "exact", "决心表述长句（决心+低估困难混合）"),
 (413, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "离开了银行工作"),
 (418, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "上周开始去健身房"),
 (419, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "失业"),
 (421, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "纹身提醒自己"),
 (423, "MUST_CAPTURE", "identity_state", "self", "past", "exact", "自从 Door Dash 失业后"),
 (425, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "对时尚潮流有热情"),
 (430, "MAY_CAPTURE", "other", "self", "current", "exact", "瞬时状态（失业挺难）"),
 (431, "MUST_NOT_CAPTURE", "other", "other:Jon", "unspecified", "exact", "问句被抽成候选（靠什么保持动力？）"),
 (432, "MAY_CAPTURE", "other", "self", "current", "exact", "动机表述（学生成功激励我）"),
 (435, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "不得不关掉银行账户"),
 (437, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "碎片（我的学生）"),
 (438, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "下月打算办舞蹈比赛"),
 (439, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "碎片（我的店）"),
 (444, "MAY_CAPTURE", "ability_experience", "self", "current", "exact", "店里新促销（商业动态，时效短）"),
 (446, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "想与时尚博主合作"),
 (452, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "以前怕别人看法→明白快乐最重要（past state + 转变）"),
 (457, "MAY_CAPTURE", "other", "self", "past", "exact", "过去状态（以前特别怕别人怎么想）"),
 (460, "MUST_NOT_CAPTURE", "other", "self", "unspecified", "none", "碎片（失业之后）"),
 (464, "MUST_CAPTURE", "preference_habit", "self", "current", "exact", "跳舞从小是减压神器"),
 (468, "MUST_CAPTURE", "plan_intent", "self", "future", "exact", "想打造让大家跳舞的地方"),
 (474, "MAY_CAPTURE", "identity_state", "self", "current", "exact", "身份表述（舞蹈就是我）"),
 (475, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "昨天去设计实习面试"),
 (480, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "刚拿到时尚实习 offer"),
 (482, "MUST_CAPTURE", "ability_experience", "self", "current", "exact", "在读《精益创业》"),
 (484, "MAY_CAPTURE", "other", "self", "current", "exact", "困难表述（找投资人挺难）"),
 (487, "MUST_NOT_CAPTURE", "other", "other:Gina", "unspecified", "exact", "问句被抽成候选（会不会带来灵感？）"),
 (488, "MAY_CAPTURE", "other", "self", "current", "exact", "白板点子（依赖上下文）"),
 (494, "MAY_CAPTURE", "preference_habit", "self", "current", "paraphrase", "生产力习惯（白板管理）——边际价值"),
 (497, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "昨天被商业前辈指点"),
 (500, "MAY_CAPTURE", "other", "self", "current", "exact", "回忆触发表述"),
 (502, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "已是创业者（因失业）"),
 (504, "MAY_CAPTURE", "other", "self", "past", "exact", "旧照片指代句"),
 (510, "MUST_CAPTURE", "ability_experience", "self", "past", "exact", "上周罗马小旅行"),
 (513, "MAY_CAPTURE", "preference_habit", "self", "current", "exact", "把目标写纸上保持动力（生产力习惯）"),
 (516, "MAY_CAPTURE", "preference_habit", "self", "current", "exact", "喜欢和朋友们在一起（泛）"),
 (518, "MUST_CAPTURE", "ability_experience", "self", "current", "exact", "把所有计划写下来了"),
 (521, "MAY_CAPTURE", "other", "self", "current", "exact", "瞬时状态（失业挺糟）"),
 (522, "MAY_CAPTURE", "plan_intent", "self", "future", "paraphrase", "期待引导舞者（弱意图）"),
 (525, "MAY_CAPTURE", "ability_experience", "self", "past", "exact", "生意上的艰难时刻（泛）"),
 (527, "MAY_CAPTURE", "ability_experience", "self", "current", "exact", "拓展人脉是救命稻草（比喻）"),
 (529, "MUST_CAPTURE", "identity_state", "self", "current", "exact", "舞蹈工作室现在有点悬（经营状态）"),
 (530, "MUST_CAPTURE", "ability_experience", "self", "current", "exact", "找了份临时工作补贴开销"),
 (537, "MAY_CAPTURE", "other", "self", "current", "exact", "决心表述（我不会放弃）"),
]


def main() -> int:
    rows = [json.loads(ln) for ln in POOL.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out = []
    for pool, ann in (("en-conv-26", A), ("zh-conv-26", B), ("zh-conv-30", C)):
        for idx, label, cat, subject, ftime, binding, note in ann:
            r = rows[idx]
            assert r["pool"] == pool, (idx, r["pool"])
            content = r["content"] or ""
            out.append({
                "sample_key": r["sample_key"],
                "pool": pool,
                "pool_idx": idx,
                "cand_id": r["cand_id"],
                "speaker_user_id": r["speaker_user_id"],
                "content_sha1": hashlib.sha1(content.encode("utf-8")).hexdigest(),
                "label": label,
                "category": cat,
                "subject": subject,
                "audience": "CURRENT_SPACE",
                "fact_time": ftime,
                "evidence_binding": binding,
                "note": note,
                "label_version": LABEL_VERSION,
            })
    counts: dict[str, int] = {}
    cats: dict[str, int] = {}
    for o in out:
        counts[o["label"]] = counts.get(o["label"], 0) + 1
        cats[o["category"]] = cats.get(o["category"], 0) + 1
    OUT.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in out), encoding="utf-8")
    print(f"annotated: {len(out)} | labels: {counts} | categories: {cats}")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
