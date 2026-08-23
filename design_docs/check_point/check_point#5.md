 兼容层接入 LLM 服务

 Context

 astrbot_compat/ 目前只覆盖非 LLM 插件。AstrBot 生态里相当多插件依赖模型能力——它们调
 context.get_using_provider_async() 拿 provider、provider.text_chat(...) 直接问模型、
 yield event.request_llm(...) 交给管道跑、用 @filter.llm_tool 注册函数工具、用
 conversation_manager 读写多轮历史。这些接口现在全是抛 StellaCompatNotSupported 的占位，
 插件一碰就断。

 本次目标：在兼容层完整复刻 AstrBot 的核心 LLM 接入面，让这类插件能直接跑。

 已确认的四个决策：
 1. 新建完整的 OpenAI 兼容客户端作为底座（现有 LMStudioBackend 与主聊天链路完全不动）。
 2. 插件的 LLM 调用不携带 Stella 的人格与记忆。插件未指定 system_prompt 时，回退到一句话的
    插件专属人格（一个"笨笨的机器人"），既锚定输出又不泄漏 Stella 人设。
 3. conversation_manager 用独立 SQL 表存储，与记忆系统隔离。
 4. 范围＝核心 LLM 接入面。不含 MCP、Agent handoff、TTS/STT、embedding、知识库、WebUI。

 不做的事：Star.text_to_image / html_render 保持 NotSupported（Stella 无渲染服务，且不属于
 LLM 面）；kb_manager / subagent_orchestrator / knowledge_db_manager 继续抛异常。

 插件专属人格

 完全不给 system_prompt 会让本地模型的输出风格漂移（它会按自己的 chat template 默认值走）。
 给一句话既能稳住输出，又和 Stella 的人格彻底隔离：

 ASTRBOT_LLM_SYSTEM_PROMPT = _env(
     "ASTRBOT_LLM_SYSTEM_PROMPT",
     "你是一个简单的机器人助手，请直接、简短地回答，不要扮演角色。",
 )

 生效规则（在 StellaChatProvider 里，只有一处）：
 - 插件传了 system_prompt → 用插件的，一个字不加。插件完全掌控 prompt，这是 AstrBot 语义。
 - 插件没传 → 注入上面这句。
 - 设为空串 → 彻底不发 system 消息（留给想要裸模型的人）。

 成本约 40~50 token，计入下面的预算，可忽略。副作用是插件的回复不会带 Stella 的语气，
 这正是想要的——用户能分辨哪句是插件说的、哪句是 Stella 说的。

 ---

 关于 8192 token 上限

 新客户端本身不增加任何 token，它只是把 messages 数组原样转发。真正会撑爆窗口的是三项，
 其中最大的一项已被决策 2 排除：

 ┌──────────────────────────────┬──────────┬──────────────────────────────────┐
 │             来源             │ 典型开销 │               状态               │
 ├──────────────────────────────┼──────────┼──────────────────────────────────┤
 │ Stella 记忆/RAG 上下文       │ 500~1000 │ 不进来（决策 2）                 │
 ├──────────────────────────────┼──────────┼──────────────────────────────────┤
 │ 插件专属人格（一句话）       │ 40~50    │ 固定，可关                       │
 ├──────────────────────────────┼──────────┼──────────────────────────────────┤
 │ 插件自己的 system_prompt     │ 100~500  │ 插件自负（给了就不再注入上一行） │
 ├──────────────────────────────┼──────────┼──────────────────────────────────┤
 │ 工具 schema（每工具 60~120） │ 0~2500   │ 需要设上限                       │
 ├──────────────────────────────┼──────────┼──────────────────────────────────┤
 │ 插件对话历史 contexts        │ 无上限   │ 必须裁剪                         │
 └──────────────────────────────┴──────────┴──────────────────────────────────┘

 对策（都做在 StellaChatProvider 里，送出前生效）：

 - 复用现成的 memory/prompt_builder.py:126 estimate_tokens(text) -> int 估算，不引新依赖。
 - 超预算时按上游 Provider.pop_record() 的语义，从最早的非 system 消息成对丢弃，
   丢到装得下为止，并 logger.warning 报告丢了几条。
 - 工具数量超 ASTRBOT_LLM_MAX_TOOLS 时截断并告警。
 - 每次调用把估算 token 数打进日志，便于实测调参。

 最坏情况是「插件的老对话被截断」，而不是「请求被拒」或「输出被截断成半句」。

 ---

 实现

 1. 底座：core/llm/openai_client.py（新增）

 唯一的新 HTTP 路径，支持完整 OpenAI chat-completions。lm_studio.py 与 core/pipeline.py
 一行不改。

 async def chat_completion(
     messages: list[dict], *, base_url: str, model: str, api_key: str = "",
     tools: list[dict] | None = None, tool_choice: str = "auto",
     temperature: float = 0.7, max_tokens: int = 1024, timeout: float = 120.0,
 ) -> dict                                   # 原始 OpenAI 响应 dict

 async def chat_completion_stream(...) -> AsyncIterator[dict]

 沿用 lm_studio.py:73-121 的重试形态（3 次退避、4xx 不重试、finish_reason=length 告警、
 trust_env=False）。reasoning_effort=none 的判定也照搬：仅本地（无 api_key）时发送。

 2. astrbot_compat/llm/（新增包）

 ┌────────────┬─────────────────────────────────────────────────────────────────────────────┐
 │    模块    │                                    内容                                     │
 ├────────────┼─────────────────────────────────────────────────────────────────────────────┤
 │ entities.p │ ProviderType ProviderMeta ProviderMetaData ProviderRequest LLMResponse      │
 │ y          │ TokenUsage ToolCallsResult RerankResult                                     │
 ├────────────┼─────────────────────────────────────────────────────────────────────────────┤
 │            │ ContentPart TextPart ThinkPart ImageURLPart AudioURLPart Message ToolCall   │
 │ message.py │ AssistantMessageSegment ToolCallMessageSegment UserMessageSegment           │
 │            │ SystemMessageSegment（pydantic，已是依赖）                                  │
 ├────────────┼─────────────────────────────────────────────────────────────────────────────┤
 │ tool.py    │ ToolSchema FunctionTool ToolSet FunctionToolManager(=FuncCall)              │
 │            │ BaseFunctionToolExecutor                                                    │
 ├────────────┼─────────────────────────────────────────────────────────────────────────────┤
 │ provider.p │ AbstractProvider Provider STTProvider/TTSProvider/EmbeddingProvider/RerankP │
 │ y          │ rovider（后四者只留形状，方法抛 NotSupported）+                             │
 │            │ StellaChatProvider(Provider)                                                │
 ├────────────┼─────────────────────────────────────────────────────────────────────────────┤
 │ manager.py │ ProviderManager——持有单个 StellaChatProvider，实现 inst_map /               │
 │            │ provider_insts / get_provider_by_id                                         │
 ├────────────┼─────────────────────────────────────────────────────────────────────────────┤
 │ agent.py   │ 工具调用循环 + ContextWrapper AstrAgentContext BaseAgentRunHooks            │
 └────────────┴─────────────────────────────────────────────────────────────────────────────┘

 必须照抄的坑（探索已核实）：
 - LLMResponse 是 dataclass 但有自定义 __init__，第二个位置参数是 completion_text；
   completion_text 是 property，有 result_chain 时读写都作用在链上。
 - ProviderMetaData 继承 ProviderMeta，id/model/type 是必填。
 - Conversation.history 是 JSON 字符串不是 list；Personality 是 TypedDict。
 - text_chat 有 extra_user_content_parts，text_chat_stream 没有。
 - text_chat_stream 基类实现用 if False: yield 保证它是异步生成器。

 StellaChatProvider.text_chat 组装顺序：system_prompt → contexts → tool_calls_result
 → 由 prompt/image_urls 组出的 user 消息（复刻 ProviderRequest.assemble_context）。
 组装后过 token 预算裁剪，再经调度器送出：

 async with acquire(RESOURCE_CHAT, tag=f"plugin-llm:{session_id}",
 priority=PRIORITY_INTERACTIVE):
     raw = await chat_completion(messages, tools=..., ...)

 走 core/llm/scheduler.py 的 RESOURCE_CHAT 闸门是硬要求——本地只有一块 GPU，
 主聊天、记忆压缩、插件调用必须 FIFO 串行，否则会互相拖垮。

 3. 持久化

 memory/schema.py：按项目强制约定（docs/development.md:265-286）加两张表——
 SCHEMA_VERSION 8 → 9，DDL 作为模块常量，配套 create_astrbot_conversations_table(conn) /
 create_astrbot_preferences_table(conn)，索引登记进 _INDEXES。

 astrbot_conversations(
   cid TEXT PRIMARY KEY, platform_id TEXT, user_id TEXT,   -- user_id 存 unified_msg_origin
   content TEXT,                                            -- JSON 字符串
   title TEXT, persona_id TEXT, token_usage INTEGER DEFAULT 0,
   created_at INTEGER, updated_at INTEGER)
 astrbot_preferences(scope TEXT, scope_id TEXT, key TEXT, value TEXT,
   updated_at INTEGER, PRIMARY KEY (scope, scope_id, key))

 astrbot_compat/conversation.py（新增）：ConversationManager，异步 API 与上游逐一对齐
 （new_conversation switch_conversation get_curr_conversation_id get_conversation
 get_conversations update_conversation add_message_pair delete_conversation
 get_human_readable_context …）。当前会话 id 存进 astrbot_preferences 的 sel_conv_id，
 与上游一致。

 astrbot_compat/preferences.py（新增）：sp。异步 API（get_async/put_async/remove_async/
 session_get/session_put/global_get/global_put）+ 废弃的同步 API。注意上游同步版是
 get(key, default, scope, scope_id)、异步版是 get_async(scope, scope_id, key, default)
 ——参数顺序不同，必须照抄。

 沿用项目 DB 惯例：模块级 from config import DB_PATH、每次调用自建 sqlite3.connect，
 这样测试才能 monkeypatch.setattr(module, "DB_PATH", tmp)。

 astrbot_compat/persona.py（新增）：PersonaManager，只读，只暴露上面那一个插件专属人格
 （persona_id="plugin_default"，prompt 取 ASTRBOT_LLM_SYSTEM_PROMPT），返回 Personality
 TypedDict。刻意不暴露 Stella 的空间人格——system_prompts/*.md 是 Stella 的身份，泄漏进插件
 就违背了决策 2；那些文件也由安装器 GUI 拥有
 （stella-installer/src-tauri/src/commands.rs:288-369），不能让插件读写。写操作抛 NotSupported。
 好处是这个模块不需要碰 config/spaces.py，零耦合。

 4. 改造现有模块

 - context.py：从 _LLM_PROPS 移除 conversation_manager/persona_manager（注意
   context.py:244 是在类上循环 setattr，必须改这个元组本身）。实装
   get_using_provider(_async) get_provider_by_id get_all_providers get_llm_tool_manager
   add_llm_tools llm_generate(keyword-only) tool_loop_agent(keyword-only)
   get_current_chat_provider_id。
 - events.py：request_llm 返回真的 ProviderRequest，复刻两个行为——
   func_tool_manager 参数被静默丢弃（上游注释掉了）、contexts 非空时清掉 conversation。
 - filters.py：llm_tool 装饰器解析 docstring（Args: name(type): desc）生成 JSON schema
   并注册进全局工具管理器。不引 docstring_parser，写 ~40 行的解析器即可，格式很窄。
 - pipeline.py：handler yield 出 ProviderRequest 时，塞进
   event.set_extra("provider_request", req) 再交给 agent 循环（复刻上游
   process_stage/stage.py:40）。8 个 LLM 钩子按上游的实际参数触发：

 | 钩子                   | 参数（self, event 之后）                                          |
 |------------------------|-------------------------------------------------------------------|
 | on_waiting_llm_request | 无                                                                |
 | on_llm_request         | req: ProviderRequest                                              |
 | on_llm_response        | resp: LLMResponse                                                 |
 | on_agent_begin         | run_context                                                       |
 | on_agent_done          | run_context, resp                                                 |
 | on_using_llm_tool      | tool, tool_args（已过滤）                                         |
 | on_llm_tool_respond    | tool, tool_args, tool_result（未过滤，且触发前先 clear_result()） |
 | on_decorating_result   | 无                                                                |
   钩子必须是 async def（上游有 assert iscoroutinefunction），异常吞掉只记日志，
   event.is_stopped() 为真则中断链路。
 - shim.py：绑定全部新名字，新增假模块 astrbot.core.provider、
   astrbot.core.provider.entities、astrbot.core.provider.entites（上游拼写错误，老插件在用）、
   astrbot.core.agent、astrbot.core.agent.tool、astrbot.core.db、astrbot.core.db.po。
   api.sp 从占位换成真实现。
 - config/settings.py + .env.example：新增 ASTRBOT_LLM_ENABLED、ASTRBOT_LLM_BASE_URL
   /_MODEL/_API_KEY/_TEMPERATURE（默认继承 LM_STUDIO_*，与
   CONSOLIDATION_*/MEMORY_EXTRACT_* 的既有模式一致）、ASTRBOT_LLM_SYSTEM_PROMPT（见上）、
   ASTRBOT_LLM_MAX_TOKENS(1024)、ASTRBOT_LLM_MAX_CONTEXT_TOKENS(8192)、
   ASTRBOT_LLM_MAX_TOOLS(32)、ASTRBOT_LLM_TOOL_TIMEOUT(120)、
   ASTRBOT_LLM_MAX_TOOL_STEPS(10)。

 5. 工具调用循环（astrbot_compat/llm/agent.py）

 上游那套（MCP、handoff、live mode、后台任务、流式）过重，只复刻插件真正依赖的契约：

 1. 带 tools 调模型 → 拿 tool_calls。
 2. 每个调用：ToolSet.get_tool(name) 找工具；按 parameters.properties 过滤多余参数
    （上游行为，多余的丢弃并记日志）。
 3. on_using_llm_tool 钩子 → 执行 → on_llm_tool_respond 钩子。
 4. 调用契约：handler(event, **filtered_args)——即插件写的 async def tool(self, event, loc:
    str)。
    返回 str 回喂模型；返回 None 则把 event.get_result() 直接发给用户，并告诉模型
    「工具无返回值或已直接回复用户」；异常 → f"error: {e}"。
    异步生成器：yield 出的 MessageEventResult 走 event.set_result()。
 5. 把 ToolCallsResult 追加进 messages，回到第 1 步，直到无 tool_calls 或达
    ASTRBOT_LLM_MAX_TOOL_STEPS。
 6. 每步都受 ASTRBOT_LLM_TOOL_TIMEOUT 约束。

 ---

 验证

 新增 tests/astrbot_compat/test_llm_*.py，沿用现有 tests/astrbot_compat/conftest.py 的
 FakeBot/make_event/register_plugin/_clean_registry 夹具：

 1. test_llm_provider.py — monkeypatch core.llm.openai_client.chat_completion 成假响应。
    断言 messages 组装顺序、LLMResponse.completion_text 的 property 行为、
    text_chat_stream 是异步生成器；以及人格三态：插件传了用插件的、没传注入插件人格、
    配置为空串则完全不发 system 消息。
 新增 tests/astrbot_compat/test_llm_*.py，沿用现有 tests/astrbot_compat/conftest.py 的
 FakeBot/make_event/register_plugin/_clean_registry 夹具：

 1. test_llm_provider.py — monkeypatch core.llm.openai_client.chat_completion 成假响应。
    断言 messages 组装顺序、LLMResponse.completion_text 的 property 行为、
    text_chat_stream 是异步生成器；以及人格三态：插件传了用插件的、没传注入插件人格、
    配置为空串则完全不发 system 消息。
    text_chat_stream 是异步生成器；以及人格三态：插件传了用插件的、没传注入插件人格、
    配置为空串则完全不发 system 消息。