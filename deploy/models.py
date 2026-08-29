# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""doctor 的数据模型：单项检查结论与整机环境快照。

两个 dataclass 都不做 IO、不 import 业务模块，供 probe / checks / report
与测试共用。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CheckResult:
    """单项检查的结论。

    id 是稳定标识（GUI 用它做图标与本地化映射），改名等于破坏前端兼容。
    level != "ok" 时 fix_hint 必须非空——只报告问题不给解法对用户没有价值，
    这条由测试断言强制。
    """

    id: str
    level: str  # "ok" / "warn" / "error"
    title: str
    detail: str = ""
    fix_hint: str = ""


@dataclass
class Snapshot:
    """环境快照：只装「采集到的事实」，不含任何判断。

    两个约定：
    1. 采集失败用 None 表示「无法确定」，检查层必须把 None 与 False 区别处理——
       「探测不到」应是 warn，「确定有问题」才是 error；
    2. 所有字段都有默认值（健康态），测试构造时只需覆盖关心的那一项。
    """

    # ── Python 与依赖 ──
    python_version: tuple[int, int, int] = (3, 12, 0)
    missing_packages: list[str] = field(default_factory=list)

    # ── 配置文件 ──
    env_exists: bool = True
    deprecated_env_keys: list[str] = field(default_factory=list)
    allowed_groups: list[int] = field(default_factory=lambda: [123456789])
    db_cleanup_on_start: bool = False

    # ── OneBot 连接 ──
    onebot_mode: str = "reverse"  # "forward" / "reverse" / "unknown"
    onebot_host: str = "0.0.0.0"
    onebot_port: int = 8080
    onebot_port_in_use: bool | None = False
    onebot_forward_reachable: bool | None = None
    # 状态接口是否可达。它同时是「端口被自己占用」的可靠证据——
    # 接口挂在同一个 HTTP 服务器上，能连上说明监听者就是 Stella。
    status_api_reachable: bool = False

    # ── LM Studio ──
    lm_reachable: bool | None = True
    lm_error: str = ""
    lm_base_url: str = "http://127.0.0.1:1234"
    lm_models: list[str] = field(default_factory=lambda: ["model-a", "model-b"])
    lm_model_chat: str = "model-a"
    lm_model_consolidation: str = "model-a"
    lm_model_extract: str = "model-a"
    lm_model_embedding: str = "model-a"
    embedding_enabled: bool = False
    # embedding 的地址单独记：R2「embedding 恒定本地」是硬要求，而这条只能靠
    # 「它指到哪」来验证——指向在线端点时必须报出来。
    embedding_base_url: str = "http://127.0.0.1:1234"

    # ── LLM 端点与角色（core/llm/registry 的解析结果） ──
    # 结构就是 ``registry.describe()`` 的输出，doctor **不自己再解析一遍配置**：
    # 那必然与运行时漂移，而 doctor 的全部价值就在于「看到的和运行时一样」。
    # 默认空 dict = 拿不到解析结果，相关检查一律跳过（测试构造健康快照时同理）。
    llm_endpoints: dict[str, dict] = field(default_factory=dict)
    llm_roles: dict[str, dict] = field(default_factory=dict)
    # registry.validate() 的原样输出：[{"level": "error"/"warn", "message": ...}]
    llm_issues: list[dict] = field(default_factory=list)
    llm_embedding_gate: str = "none"
    # 槽名 → 该端点 /v1/models 的探测结果。None = 没探（槽未配置或探测异常）。
    # 分槽存而不是只留一份：切到在线后「哪个地址不通」才是有用的信息。
    llm_endpoint_reachable: dict[str, bool | None] = field(default_factory=dict)
    llm_endpoint_error: dict[str, str] = field(default_factory=dict)
    llm_endpoint_models: dict[str, list[str]] = field(default_factory=dict)
    # .env 里仍留着的、已被新键取代的键（env_keys.SUPERSEDED）
    superseded_env_keys: list[str] = field(default_factory=list)

    # ── 数据库 ──
    db_exists: bool = True
    db_path: str = "memory/agent_memory.db"
    db_writable: bool | None = True
    schema_version: int | None = 8
    code_schema_version: int = 8
    legacy_group_id_tables: list[str] = field(default_factory=list)
    source_kind_counts: dict[str, int] = field(
        default_factory=lambda: {"AT_MENTION": 1, "PASSIVE": 1, "BOT_SELF": 1}
    )

    # ── 群组空间 ──
    space_conflicts: list[dict] = field(default_factory=list)
    space_assignment_mismatch: list[dict] = field(default_factory=list)

    # ── HTML → 图片渲染（插件卡片） ──
    render_enabled: bool = True
    playwright_installed: bool = True
    # Chromium 内核是否已下载。None = 探测不到（按目录启发式判断，见 probe）
    chromium_installed: bool | None = True

    # ── 用户数据目录（STELLA_HOME） ──
    # 数据目录与程序目录分开后，「我的数据在哪」必须能一眼看到——否则用户找不到
    # 自己的记忆库，也无法判断升级后有没有接上老数据。
    stella_home: str = ""
    stella_home_source: str = ""
    program_root: str = ""
    home_pointer_exists: bool = True

    # ── 版本标记（STELLA_HOME/.stella-state.json） ──
    # 「上次跑这份数据的是哪个版本」是升级判定的唯一依据：只看当前版本号看不出
    # 用户刚换了包（见 config/state.py）。
    program_version: str = ""
    last_run_version: str = ""
    version_transition: str = ""
    state_file_error: str = ""

    # ── 其它 ──
    persona_exists: bool = True
    persona_size: int = 1024
    disk_free_mb: float | None = 1024.0
