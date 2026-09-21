# MCP Provider 支持实施方案

> 状态：待实施
> 范围：仅引入 MCP Provider，不包含 Skills、知识库、WebUI、沙盒、多平台或 SubAgent。
> 方案依据：design_docs/AstrBot 特性吸收对比报告.md、当前工作树源码、Docker GitNexus 索引及现有测试。
> 当前 HEAD：7a3e05703e3daa285677ef2d78771fa0a583aca0
> GitNexus：Docker 使用 GitNexus 1.6.12 执行 analyze --index-only --pdg，状态 up-to-date；44,466 nodes、105,700 edges、572 clusters、659 flows。
> 证据工作树：存在用户已有未提交改动；本方案没有把这些改动当成 MCP 实现的一部分。

## 1. 目标

让 Stella 能以 MCP Client 身份连接外部 MCP Server，并把选定的 MCP Tools 纳入现有 Capability Router → Comes → Result 摘要链路。

第一版完成后，用户可以：

1. 在 STELLA_HOME/config/mcp.toml 配置 MCP Server；
2. 使用 stdio 或 Streamable HTTP 连接 Server；
3. 启动时完成 initialize 与 tools/list；
4. 将 MCP Tool 映射为 Capability Provider；
5. 通过现有自然语言路由和 Comes 受限 Agent 调用工具；
6. 查看连接、工具发现、失败退避和最近错误；
7. 在 Server 断线或工具列表变化后自动降级、重连和刷新。

第一版只支持 MCP Tools。Resources、Prompts、Sampling、Elicitation、Server 反向请求和 MCP Apps 延后。

## 2. 当前行为

[verified] capability/registry.py:35-40 已声明 KIND_MCP，但 CapabilityProvider 只有通用的 tool_name 字段，没有 Server 标识。

[verified] capability/loader.py:102-137 可以读取 kind，但所有 Provider 都按单一工具名解析；server、远程工具名和权限策略会被丢弃。

[verified] capability/registry.py:351-364 的 _tool_live() 将非 astrbot_tool Provider 判定为不可用；routable() 在 374-392 行依赖这个判据。

[verified] capability/comes/executor.py:92-120 的 resolve_tools() 只从 AstrBot 的 llm_tools 查找工具，MCP 会进入 missing。

[verified] capability/comes/executor.py:284-324 会先要求事件对象，再解析 Provider；因此第一版 MCP 仍沿用聊天 @ 回复链路，不顺便引入无事件执行模型。

[verified] capability/hooks.py:70-131 的 build_tool_tasks() 只从 llm_tools 读取工具 schema。只改 Comes 而不改这里，会导致 MCP 参数提取和缺参判断失效。

[verified] astrbot_compat/llm/tool.py:26-45 的 FunctionTool.call() 已为“没有 handler 的工具（如 MCP）”预留扩展点。

[verified] astrbot_compat/llm/agent.py:136-196 对 handler is None 的工具会完整透传参数，并统一处理超时、异常和结果归一，因此 MCP 可以复用现有工具循环。

[verified] bot.py:95-142 先加载 AstrBot 插件并执行 initialize；bot.py:215-271 随后安装工具探针、运行 capability bootstrap 和 Router 预热。

## 3. 设计边界

### 3.1 Provider 分层

MCP Server 是运行时连接对象，MCP Tool 是具体实现，Capability 仍是语义能力：

    MCP Server
      └── Tool Catalog
            └── Provider(kind=mcp, server_id, remote_tool_name)
                  └── FunctionTool adapter
                        └── Comes

不要把 MCP Tools 全部写入 AstrBot 的全局 llm_tools。MCP Server 有独立的连接、重连、工具刷新和权限生命周期，混入插件注册表会让热重载和存活探针产生错误耦合。

### 3.2 传输

第一版支持：

- stdio：Stella 通过参数数组启动本地子进程；
- Streamable HTTP：Stella 连接远程 MCP endpoint。

HTTP+SSE 只作为后续兼容适配，不作为第一版主实现。配置和客户端实现应以当前 MCP 规范的传输模型为准。

### 3.3 路由策略

发现到的 MCP Tools 默认不自动参与 Router。

只有用户或插件声明了 Capability 的 MCP Provider 才进入路由；未声明工具可以显示在管理员清单中，但 route_enabled=false。因为 Comes 当前没有通用的用户确认环节，未知 MCP Tool 可能产生外部副作用。

第一版建议只开放显式声明的只读工具。修改、发送、删除、执行命令等工具保留发现和显式调用能力，但默认不参与自然语言路由。

### 3.4 上下文隔离

MCP Tool schema 只进入本次 Comes 的受限 ToolSet，不进入 Stella 人格 Prompt。

MCP 原始返回只进入 Result.data；进入 Stella Prompt 的仍然只有压缩后的 Result.summary。必须设置单次结果字符上限，防止远程 Server 返回超大内容。

## 4. GitNexus 影响分析

本次索引刷新后，关键结果如下：

- [graph] CapabilityRegistry upstream impact：CRITICAL，40 个受影响符号，其中 33 个直接依赖。它被 Router、Comes、loader、inventory、部署工具和多个测试共同使用，不能直接塞入 MCP 业务逻辑。
- [graph] capability.comes.executor.execute upstream impact：HIGH，至少 29 个受影响符号，其中 25 个直接依赖；GitNexus 标记 3 个调用点因 receiver typing 未解析，结果是 lower-bound。
- [graph] build_tool_tasks upstream impact：MEDIUM，5 个直接依赖，主要是 _run_comes 和任务构造测试。
- [graph] capability.adapters.astrbot.bootstrap upstream impact：HIGH，8 个直接调用者，包括 bot.py 启动、AstrBot 热重载和 Router benchmark。
- [graph] CapabilityRegistry 的直接调用者包含 capability/hooks.py、capability/comes/executor.py、capability/inventory.py、capability/loader.py、Router 和 AstrBot loader。
- [verified] 当前 execute() 的失败保证、工具健康度、direct call 和摘要不变量都已有测试覆盖，MCP 应接入这些不变量，而不是另造一条执行链。

PDG 索引已刷新，但当前 GitNexus CLI 对 impact --mode pdg --line ... 返回旧用法错误，无法取得可审计的语句级 slice。本方案不把不存在的 PDG 边当作证据；执行阶段应在实现前重新探测。

## 5. 建议的模块结构

新增：

    capability/providers/
      __init__.py              # ProviderBackend / ProviderRuntime 协议
      registry.py              # Backend 注册与统一 resolve/schema/status
      mcp/
        __init__.py
        model.py               # ServerConfig、ServerState、ToolDescriptor
        client.py              # stdio / Streamable HTTP MCP 会话
        manager.py             # 多 Server 生命周期、重连、刷新、调用
        tool.py                # MCP Tool → FunctionTool 适配器
    capability/adapters/mcp.py # MCP 工具目录 → Capability Provider 同步

如果实现时发现目录过重，可以将 providers/registry.py 合并到 capability/providers.py，但不要把 MCP 客户端放进 capability/registry.py。

## 6. 数据模型

### 6.1 Provider

扩展 CapabilityProvider：

- kind：保持 mcp；
- tool_name：Stella 内部唯一、给模型看到的命名空间名称，例如 mcp_brave_search；
- server_id：配置中的 Server ID；
- remote_tool_name：MCP tools/list 返回的原始工具名；
- provider_id：稳定 ID，例如 mcp:brave:search；
- 保留现有 priority、enabled、failures、disabled_until。

Provider 的唯一键必须同时包含 Server 和远程工具名，不能只按 search 认领，否则两个 Server 的同名工具会互相覆盖。

### 6.2 Server 配置

配置文件：STELLA_HOME/config/mcp.toml。

建议字段：

    [servers.brave]
    enabled = true
    transport = "streamable_http"
    url = "https://example.com/mcp"
    auth_env = "STELLA_MCP_BRAVE_TOKEN"
    connect_timeout = 10
    call_timeout = 30
    allowed_tools = ["search"]

    [servers.filesystem]
    enabled = false
    transport = "stdio"
    command = "npx"
    args = ["-y", "@modelcontextprotocol/server-filesystem", "D:/data"]
    env = {}
    allowed_tools = ["read_file", "list_directory"]

约束：

- stdio 使用 command + args，禁止 shell 字符串和 shell=True；
- 密钥只通过环境变量引用，日志必须脱敏；
- allowed_tools 为空时按“全部发现但全部不可路由”处理，避免默认放开；
- HTTP endpoint 应支持 URL 白名单、认证、连接/调用超时；
- 默认 MCP_ENABLED=false，首次启用必须由部署者显式配置。

### 6.3 Server 状态

至少记录：

    disabled / starting / ready / degraded / reconnecting / stopped
    last_error
    last_success_at
    last_tools_refresh_at
    tool_count
    call_count
    failure_count

Server 状态与 Provider 的单工具退避分开维护。Server 不可用时，其下所有 Provider 的 is_live 为 false，但不删除 Capability 声明。

## 7. 具体改动

### 7.1 新增 Provider Runtime

文件：capability/providers/registry.py

提供统一接口：

- register_backend(kind, backend)
- resolve(provider) -> ProviderTool
- schema(provider) -> dict
- is_live(provider) -> bool
- status(provider) -> dict

AstrBot 后端包装现有 llm_tools；MCP 后端包装 McpServerManager。Registry 不 import AstrBot 或 MCP SDK，只依赖接口。

### 7.2 改造 CapabilityRegistry

文件：capability/registry.py

改动：

1. 将当前单一 _tool_probe 抽象为 Provider Runtime 的存活查询；
2. 保留 set_tool_probe 兼容 AstrBot 测试和离线 benchmark；
3. _tool_live() 对 astrbot_tool 和 mcp 分别委托对应 backend；
4. 将 Provider 认领键改为 backend-aware key；
5. 增加按 Provider ID 移除/替换的方法，供 tools/list_changed 差量刷新；
6. 每次 MCP schema 或可用性变化都递增 registry.version，让 Router 原型缓存失效。

不要修改 routable() 的业务判据：仍然必须同时满足 route_enabled、存在 live provider 和 prototype text。

### 7.3 改造声明加载

文件：capability/loader.py

扩展 provider 表格式：

    [[capability]]
    id = "web.search"
    description = "联网搜索"
    examples = ["搜索这个问题"]
    providers = [
      {
        id = "mcp:brave:search",
        kind = "mcp",
        server = "brave",
        tool = "search",
        priority = 10
      }
    ]

解析时：

- kind="astrbot_tool" 保持现有行为；
- kind="mcp" 必须要求 server 和 tool；
- tool_name 生成稳定的内部命名空间名；
- 未知 kind 继续记录 warning 并跳过；
- 离线声明检查不能把 MCP Server 当前是否在线当作解析错误。

### 7.4 实现 MCP Client 和 Manager

文件：capability/providers/mcp/client.py、manager.py、model.py

职责：

1. 启动 stdio 或建立 Streamable HTTP 会话；
2. 完成 MCP initialize；
3. 调用 tools/list，规范化为 ToolDescriptor；
4. 对工具列表做名称、schema 大小和描述长度校验；
5. 处理 tools/call；
6. 统一把 text、JSON 和其他 content block 转成受限文本；
7. 对每个 Server 使用连接锁或 semaphore，避免未验证 Server 的并发问题；
8. 断线后按指数退避重连；
9. 收到工具列表变化通知后刷新 catalog；
10. 关闭时取消后台任务并终止 stdio 子进程。

MCP SDK 应作为可选依赖加入 pyproject.toml，默认安装不因 MCP 缺失而失败。SDK 版本必须固定到经过 Python 3.10、Windows 和 Docker 验证的版本。

### 7.5 MCP Tool Adapter

文件：capability/providers/mcp/tool.py

每个 live MCP Tool 生成一个 FunctionTool：

- name 使用内部命名空间名；
- description 来自 MCP，但限制长度并作为不可信文本处理；
- parameters 使用 MCP inputSchema，缺省时规范化为空 object schema；
- call() 调用 McpServerManager.call_tool(server_id, remote_tool_name, args)；
- 使用调用级 timeout；
- 返回文本或受限 JSON 字符串；
- MCP 错误统一转换成 error: ...，不得把认证头、命令行和完整异常栈送回 Stella。

### 7.6 改造 Comes

文件：capability/comes/executor.py、capability/comes/__init__.py

改动：

- resolve_tools() 从 Provider Runtime 解析，不再只查 llm_tools；
- 保留现有 ToolSet、direct call、agent loop、超时、ResultStatus 和 summarizer；
- MCP 工具使用同一条 execute_tool() 路径；
- _record_health() 使用稳定的内部工具名或 Provider ID，避免同名工具健康度串线；
- Server 级失败只影响对应 MCP Provider，不得让整个 Comes 或主 Pipeline 抛异常；
- 第一版保留 event is None 的快速失败契约，不引入无事件 MCP 执行。

### 7.7 改造任务输入解析

文件：capability/hooks.py

build_tool_tasks() 不再直接从 llm_tools 读取 schema，而是通过 Provider Runtime 获取能力下第一个 live Provider 的 schema。

这样 MCP 的 required 字段才能参与：

- parse_input()；
- deterministic route；
- 缺参澄清；
- 无模型 direct call。

activate_capabilities() 的并行结构和失败隔离保持不变。

### 7.8 启动、关闭和热刷新

文件：bot.py、astrbot_compat/loader.py

启动顺序：

1. 加载 AstrBot 插件；
2. 执行插件 initialize；
3. 启动 MCP Server Manager 并完成初始发现；
4. 安装 Provider Runtime；
5. 运行现有 capability bootstrap；
6. 后台 Router warmup。

关闭顺序：

1. 停止接受新的 MCP 调用；
2. 等待或取消在途 MCP 调用；
3. 关闭 HTTP 会话；
4. 终止 stdio 子进程；
5. 继续现有 AstrBot、embedding 和 renderer 关闭流程。

AstrBot 热重载仍调用现有 bootstrap()。MCP Manager 不随插件热重载重启；如果混合 Capability 被重建，声明重新解析后由 MCP Runtime 重新判断 live 状态。

### 7.9 状态与诊断

文件：capability/inventory.py，必要时增加 deploy CLI 命令。

MCP Provider 快照增加：

- server_id
- remote_tool
- tool_state
- server_state
- last_error
- call_count
- failures
- backoff_seconds

提供最小诊断命令：

    python -m deploy mcp list
    python -m deploy mcp test <server_id>

test 只做连接、initialize 和 tools/list，不调用真实业务工具；输出必须脱敏。

## 8. 实施顺序

1. 锁定协议和依赖：确定 MCP Python SDK 版本，在 Docker、Windows、Python 3.10 上验证 stdio 和 Streamable HTTP，增加 MCP_ENABLED 等配置项。
2. 实现 Provider Runtime：新增 backend 协议和 Runtime Registry，将 AstrBot 工具包装为现有行为，不改变现有 llm_tools 注入方式。
3. 实现 MCP Manager 和两个传输：先 fake transport，再 stdio，最后 Streamable HTTP；加入连接状态、超时、重连和工具目录缓存。
4. 扩展 Provider 与声明：修改 Provider 数据模型和 TOML 解析，增加 Server/Tool 命名空间和差量替换 Provider API。
5. 接入 Registry 和 Router：统一 is_live/schema/status；MCP Tool 默认不自动路由；工具列表变化递增 Registry version。
6. 接入 Comes：resolve_tools() 使用 Runtime；MCP Tool 通过 FunctionTool.call() 进入现有 Agent；保留 direct call、摘要、失败和退避契约。
7. 接入任务输入、启动和状态：build_tool_tasks() 使用通用 schema；bot 启动/关闭接入 Manager；inventory 和 mcp test 接入同一状态源。
8. 回归和验收：运行定向测试、全量测试和 lint；Docker 中刷新索引并执行 detect-changes --scope all；仅在结果通过后再考虑 WebUI 配置页。

## 9. 测试策略

新增：

- tests/capability/providers/test_mcp_client.py：initialize、tools/list、tools/call、超时、JSON-RPC 错误、断线重连、工具列表变化、密钥不进日志。
- tests/capability/providers/test_mcp_manager.py：多 Server 隔离、故障隔离、状态转移、shutdown、stdio 不经过 shell。
- tests/capability/test_provider_runtime.py：AstrBot/MCP backend 的 resolve、schema、live、status 契约。
- tests/capability/test_mcp_adapter.py：命名空间、同名工具、allowlist、只读/副作用策略。

更新：

- tests/capability/test_registry.py：MCP live probe、Server 不可用时不可路由、差量替换、registry.version。
- tests/capability/test_capability_loader.py：MCP TOML、缺字段、未知 kind、Provider ID。
- tests/capability/test_comes_executor.py：MCP ToolSet、direct call、agent call、超时、失败、部分成功和摘要。
- tests/capability/test_capability_hooks.py：MCP schema 输入解析、缺参、tool summary。
- tests/test_status_api.py：MCP 状态不含 token、命令行密钥和聊天内容。

验证命令：

    python -m pytest tests/capability -q
    python -m pytest tests/test_status_api.py -q
    ruff check .
    python -m pytest tests -q
    docker exec stella-gitnexus bash -lc "cd /repo && npx --yes gitnexus@1.6.12 status --json"
    docker exec stella-gitnexus bash -lc "cd /repo && npx --yes gitnexus@1.6.12 detect-changes --scope all --repo /repo"

## 10. 风险与影响

- [graph] CapabilityRegistry 为 CRITICAL：只扩展 Provider Runtime 和刷新 API，不把 MCP 连接管理写进 Registry。
- [graph] execute() 为 HIGH 且调用图 lower-bound：至少 3 个调用点未被类型解析，执行阶段必须用文本搜索和全量测试补足。
- [graph] bootstrap() 为 HIGH：不要把 MCP 生命周期强行绑定到 AstrBot 插件热重载。
- [verified] build_tool_tasks() 直接读取 llm_tools：这是 MCP 最容易遗漏的参数解析入口。
- [inferred] MCP Server 可能返回超大或提示注入型 description/result，必须做长度限制、allowlist 和摘要隔离。
- [inferred] stdio 子进程和 Streamable HTTP 都是外部边界；命令、环境变量、URL、认证、超时和输出大小必须在配置层明确。
- [inferred] 多个 Server 的同名工具会造成模型调用和健康度串线，必须使用稳定命名空间。
- [assumed] 选定的 Python MCP SDK 能在 Python 3.10、Windows 和当前 Docker 基础镜像中稳定运行；实施第 1 步必须验证。
- [assumed] Streamable HTTP Server 的认证方式可通过环境变量或现有 HTTP client 注入；若 SDK 不支持所需 header，需要在 client 层封装。

## 11. 实现上下文包

    task_summary: "为 Stella 增加受控 MCP Client，将 MCP Tools 映射为 Capability Provider 并复用 Comes 执行链路"
    head_commit: "7a3e05703e3daa285677ef2d78771fa0a583aca0"
    gitnexus_index: "Docker GitNexus 1.6.12, refreshed --index-only --pdg, up-to-date"
    index_stats: "44466 nodes, 105700 edges, 572 clusters, 659 flows"
    global_dirty_digest: "e9c28eed55c5f631f0b1c28105c8ed8a9fadcffc2ccedac4a8fda436428d7669"
    primary_symbols:
      - "CapabilityRegistry (capability/registry.py:196-415)"
      - "resolve_tools (capability/comes/executor.py:92-120)"
      - "execute (capability/comes/executor.py:284-443)"
      - "build_tool_tasks (capability/hooks.py:70-131)"
      - "activate_capabilities (capability/hooks.py:219-268)"
      - "bootstrap (capability/adapters/astrbot.py:217-243)"
      - "_bootstrap_capabilities (bot.py:215-271)"
    related_symbols:
      - "FunctionTool.call (astrbot_compat/llm/tool.py:26-45)"
      - "execute_tool (astrbot_compat/llm/agent.py:172-196)"
      - "CapabilityRegistry.routable (capability/registry.py:374-392)"
      - "CapabilityProvider.mark_failure (capability/registry.py:94-112)"
      - "_parse_provider (capability/loader.py:102-137)"
    execution_path:
      - "bot startup loads plugins and initialize"
      - "MCP Manager starts and discovers tools"
      - "capability bootstrap loads explicit MCP declarations"
      - "Router selects only routable live capabilities"
      - "build_tool_tasks obtains MCP schema through Provider Runtime"
      - "Comes resolves namespaced MCP FunctionTools"
      - "existing run_tool_loop calls FunctionTool.call"
      - "MCP result is bounded, summarized, and only summary enters Stella"
    avoid:
      - "Do not inject all MCP schemas into the main Stella prompt"
      - "Do not put MCP tools into AstrBot llm_tools global registry"
      - "Do not auto-route undisclosed MCP tools"
      - "Do not use shell=True for stdio"
      - "Do not expose MCP secrets or raw errors"
      - "Do not make MCP lifecycle depend on AstrBot plugin reload"

## 12. 假设、开放问题和明确延期

假设：

1. MCP SDK 在目标 Python/Windows/Docker 矩阵中可用；第 1 步验证。
2. 当前 Comes 的事件对象可以覆盖第一版用户聊天调用；主动 Agent 和无事件调用延期。
3. MCP Server 的 tool schema 可以转换为现有 OpenAI-style FunctionTool schema。

开放问题：

1. 是否允许显式 Capability 调用有副作用的 MCP Tool，还是第一版完全只读？本方案默认后者。
2. MCP 配置错误是否保持“Bot 启动、MCP degraded”的降级策略？本方案默认后者。
3. MCP SDK 是否作为默认依赖？本方案默认可选 extras。
4. 是否需要兼容旧 HTTP+SSE Server？本方案暂不纳入 MVP。

明确延期：

- MCP Resources/Prompts；
- Server sampling、elicitation 和 roots；
- WebUI 管理 MCP；
- 用户确认流程；
- 沙盒化 stdio Server；
- MCP Tool 自动生成中文 examples；
- 将 MCP 用于独立知识库。

## 13. 完成定义

- [ ] stdio 和 Streamable HTTP Server 均可连接、初始化、列出工具和调用工具。
- [ ] MCP Tool 通过 Capability Provider 显式声明后可被 Router 命中。
- [ ] MCP schema 参与输入解析、缺参澄清和 direct call。
- [ ] Comes Agent 只收到当前任务的 MCP ToolSet。
- [ ] MCP 结果遵守 data/summary 隔离和输出大小限制。
- [ ] Server 断线不会阻塞 Stella，重连后工具可恢复。
- [ ] tools/list 变化能刷新 schema、Registry version 和 Router cache。
- [ ] 同名工具、认证信息、错误信息和 stdio 命令均有隔离或脱敏。
- [ ] 现有 AstrBot、Router、Comes、状态 API 和全量测试通过。
- [ ] Docker GitNexus 在最终实现提交上重新刷新，status up-to-date，detect-changes 结果已审阅。

