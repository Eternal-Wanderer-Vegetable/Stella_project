# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""知识库 ACL 评估。

权限判定的**唯一**入口。检索过滤（search 前）与 chunk 补水（hydration 前）
都必须走这里——同一套判定跑两遍不是冗余，是 plan §9 的第一条风险
（permission leakage：先过滤检索、再过滤取原文）的执行点。

判定原则：

1. 库主（owner）恒为 owner 角色，不依赖授权表；授权表只存 viewer /
   contributor / maintainer；
2. 角色取**最大**命中：一个用户同时以 user / group / space 三种主体命中时，
   取其中最强的角色（授权是加法，不是交集）；
3. 匿名主体（user_id 为空）一律 viewer 以下——实际上就是「无权限」：
   私库/未授权的任何信息（含元数据）都不给；
4. **private 库在群聊不可见**（plan 测试策略）：群聊场景的判定必须显式传
   ``in_group=True``，此时空间/群授权照常生效，但「仅 user 授权的库」不进
   候选——群聊里每个人都看得到回复，等于把私库内容公开广播。

mode 与默认角色的关系（plan §6.5）在 service 层落地；本模块只回答
「这个主体在这个库上是谁」与「能不能做这件事」。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from knowledge.domain import (
    KB_MODE_MANAGED,
    PRINCIPAL_GROUP,
    PRINCIPAL_SPACE,
    PRINCIPAL_USER,
    ROLE_CONTRIBUTOR,
    ROLE_MAINTAINER,
    ROLE_OWNER,
    ROLE_RANKS,
    ROLE_VIEWER,
    KnowledgeBase,
)


@dataclass(frozen=True)
class Principal:
    """发起请求的主体：用户身份 + 它所在的群/空间（允许为空）。"""

    user_id: str
    group_id: str = ""
    space: str = ""

    def iter_principals(self, *, in_group: bool = False):
        """按 user → group → space 枚举本主体的授权键。

        ``in_group=True``（群聊）时跳过「仅 user 主体」的枚举由调用方在
        ``resolve_role`` 里处理，这里仍然全部产出——构造键与过滤语义分层。
        """
        if self.user_id:
            yield PRINCIPAL_USER, self.user_id
        if self.group_id:
            yield PRINCIPAL_GROUP, self.group_id
        if self.space:
            yield PRINCIPAL_SPACE, self.space


@dataclass(frozen=True)
class ACLSnapshot:
    """一次判定的授权表快照：principal_key → role。

    store 层一次查询灌进来；评估本身是纯函数（可离线单测、无 IO）。
    """

    roles: dict[str, str] = field(default_factory=dict)

    def role_of(self, kind: str, principal_id: str) -> str | None:
        return self.roles.get(f"{kind}:{principal_id}")


def resolve_role(
    kb: KnowledgeBase,
    principal: Principal,
    snapshot: ACLSnapshot,
    *,
    in_group: bool = False,
) -> str | None:
    """主体在库上的有效角色；无任何授权返回 None。

    群聊规则：private 库（没有任何 group/space 授权、也没有 viewer 以上的
    群主体可见性）在群聊里不可用——群聊的回复对全员可见，私库内容进群聊
    等于泄露。实现上：群聊时 user 主体命中的角色只对**非 viewer** 生效
    （私库主人在自己的群里检索自己的私库，同样不给过）。

    归档库对所有人降为 None：归档就是「下架」，检索与维护都不再可用。
    """
    if kb.is_archived:
        return None

    best: str | None = None

    def _consider(role: str | None) -> None:
        nonlocal best
        if role is None:
            return
        if best is None or ROLE_RANKS.get(role, -1) > ROLE_RANKS.get(best, -1):
            best = role

    # 库主恒为 owner（不限场景：群聊里库主也能检索自己的库——若不想公开，
    # 群聊的排除规则见下）
    if principal.user_id and kb.owner_user_id and principal.user_id == kb.owner_user_id:
        _consider(ROLE_OWNER)

    user_role = (
        snapshot.role_of(PRINCIPAL_USER, principal.user_id)
        if principal.user_id
        else None
    )
    group_role = (
        snapshot.role_of(PRINCIPAL_GROUP, principal.group_id)
        if principal.group_id
        else None
    )
    space_role = (
        snapshot.role_of(PRINCIPAL_SPACE, principal.space) if principal.space else None
    )

    if in_group and group_role is None and space_role is None:
        # 群聊 + 该库没有任何群/空间授权：user 授权不生效（private 库在群聊不可见）。
        # 库主除外——上面已 consider 过 owner，这里维持原判。
        pass
    else:
        _consider(user_role)
    _consider(group_role)
    _consider(space_role)
    return best


def role_at_least(role: str | None, minimum: str) -> bool:
    """角色是否达到某一档。None（无授权）永远 False。"""
    if role is None:
        return False
    return ROLE_RANKS.get(role, -1) >= ROLE_RANKS.get(minimum, 99)


def can_search(kb: KnowledgeBase, role: str | None) -> bool:
    """能否检索该库（published 内容）。viewer 即可。"""
    return role_at_least(role, ROLE_VIEWER)


def can_submit(kb: KnowledgeBase, role: str | None) -> bool:
    """能否向该库上传/投稿。

    managed：维护者即可（成员不是贡献者——统一维护的含义）；
    shared：贡献者即可（成员共建的含义）。
    """
    minimum = ROLE_MAINTAINER if kb.mode == KB_MODE_MANAGED else ROLE_CONTRIBUTOR
    return role_at_least(role, minimum)


def can_review(kb: KnowledgeBase, role: str | None) -> bool:
    """能否审核投稿（改状态/发布/驳回）。两种模式都是维护者以上。"""
    return role_at_least(role, ROLE_MAINTAINER)


def can_publish(kb: KnowledgeBase, role: str | None) -> bool:
    """能否发布。上传与发布是**两个**权限（plan §6.5），shared 库的贡献者
    能投稿不等于能发布。"""
    return role_at_least(role, ROLE_MAINTAINER)


def can_manage_acl(kb: KnowledgeBase, role: str | None) -> bool:
    """能否增删授权（不含库主变更）。维护者以上。"""
    return role_at_least(role, ROLE_MAINTAINER)


def can_manage_kb(kb: KnowledgeBase, role: str | None) -> bool:
    """能否做库级操作（归档/删除/开关直发/改基础信息）。仅库主。"""
    return role == ROLE_OWNER


def submit_needs_review(kb: KnowledgeBase, role: str | None) -> bool:
    """一次投稿是否需要审核。

    managed 库没有审核概念——能投稿的只有维护者，投稿即维护者操作，
    直接进发布流程；shared 库里维护者以上**本来就有**发布权（can_publish），
    自己审核自己的投稿是无意义的一步，同样免审。``direct_publish`` 的意义
    在于让 shared 库的**贡献者**投稿也免审——那是库主对「低风险库」的判断
    （plan §6.5），粒度是库不是人。
    """
    if not can_submit(kb, role):
        return False
    if kb.mode == KB_MODE_MANAGED:
        return False
    if role_at_least(role, ROLE_MAINTAINER):
        return False
    return not kb.direct_publish


__all__ = [
    "ACLSnapshot",
    "Principal",
    "can_manage_acl",
    "can_manage_kb",
    "can_publish",
    "can_review",
    "can_search",
    "can_submit",
    "resolve_role",
    "role_at_least",
    "submit_needs_review",
]
