# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动 @ 的任务指令（Memory Verification Loop §5-D2）。

与 prompt_builder 的分工：后者负责把记忆与上下文拼成背景段落，本模块负责
生成「这一次主动发言要做什么」的任务指令。二者在 pipeline 里拼接。

两种模式：
- verify   ：把一条待验证的记忆候选转成一句自然的确认；
- coldstart：从日常话题切入，试探性地了解对方。

共同的硬约束（两条都必须写进指令，否则效果会立刻变差）：
1. **不得复述候选原文**。候选是内部数据，措辞生硬，直接引用会让对话
   听起来像在核对档案；
2. **不得像审问**。一次只问一件事，语气随口，允许对方不回答。
"""
from __future__ import annotations

# 共同的语气与形式约束
_COMMON_RULES = """
要求：
- 只说一句话，不要分行，不要连续追问多件事
- 语气像朋友随口一问，不要像客服或问卷调查
- 不要说「根据我的记录」「我记得数据里」这类暴露系统内部的话
- 不要在话里带上 QQ 号或「用户」这类称呼
- 如果对方不想答也没关系，别用必须回答的句式
"""


VERIFY_PROMPT = """现在群里 {nickname} 正在说话，你想顺便确认一件关于 TA 的事。


你印象里的这件事是：{content}


请把它变成一句自然的、随口的确认或追问。注意：
- **不要照搬上面那句话的措辞**，那是你自己的内部笔记，说出来会很生硬
- 用你自己的话问，比如把「拥有 RTX5080 显卡」问成「你那张 5080 还顺手吗」
- 如果这件事你其实没那么确定，可以问得更松一些，让对方有空间纠正你
{common}
直接输出那句话，不要任何解释或前缀。

（下面可能附有群里最近的对话，那只是帮你把话说得自然、接住当前氛围用的。
**不要去回应下面的任何一句话**，包括你自己刚说过的——你的任务只是说出上面那句话。）"""


COLDSTART_PROMPT = """现在群里 {nickname} 正在说话，你想借机跟 TA 聊两句，顺便了解 TA 一点。


你想切入的话题方向是：{topic}


请把它变成一句自然的搭话。注意：
- 结合当前群里正在聊的内容切入会更自然；如果实在接不上，直接问也可以
- 别问得太正式，也别一次问太多
- 你对 TA 还不太了解，所以是打开话题，不是核对信息
{common}
直接输出那句话，不要任何解释或前缀。

（下面可能附有群里最近的对话，那只是帮你把话说得自然、接住当前氛围用的。
**不要去回应下面的任何一句话**，包括你自己刚说过的——你的任务只是说出上面那句话。）"""


def build_verify_instruction(content: str, nickname: str = "对方") -> str:
    """生成验证式主动 @ 的任务指令。"""
    return VERIFY_PROMPT.format(
        content=(content or "").strip(),
        nickname=nickname or "对方",
        common=_COMMON_RULES,
    )


def build_coldstart_instruction(topic: str, nickname: str = "对方") -> str:
    """生成冷启动式主动 @ 的任务指令。"""
    return COLDSTART_PROMPT.format(
        topic=(topic or "").strip(),
        nickname=nickname or "对方",
        common=_COMMON_RULES,
    )


def build_instruction(target) -> str:
    """按 ProactiveTarget.mode 分派生成指令。

    参数用鸭子类型（不 import ProactiveTarget）避免循环依赖：
    proactive_target 不应依赖 prompt 层。
    """
    if getattr(target, "mode", "") == "verify":
        return build_verify_instruction(
            getattr(target, "candidate_content", ""),
            getattr(target, "nickname", "对方"),
        )
    return build_coldstart_instruction(
        getattr(target, "topic", ""),
        getattr(target, "nickname", "对方"),
    )
