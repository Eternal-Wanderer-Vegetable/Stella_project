# 架构说明

此路径保留以兼容旧链接。当前正文请读[架构说明](architecture/README.md).

下方保留原章节锚点并指向新位置；维护时修改目标正文。

<a id="610-当前架构增补"></a>

- [6.1.0 当前架构增补](architecture/overview.md#610-当前架构增补)

<a id="分层概览"></a>

- [分层概览](architecture/overview.md#分层概览)

<a id="目录结构"></a>

- [目录结构](architecture/code-map.md#目录结构)

<a id="一次消息的处理流程"></a>

- [一次消息的处理流程](architecture/message-lifecycle.md#一次消息的处理流程)

<a id="1-接入与落库"></a>

- [1. 接入与落库](architecture/message-lifecycle.md#1-接入与落库)

<a id="2-触发路径"></a>

- [2. 触发路径](architecture/message-lifecycle.md#2-触发路径)

<a id="3-上下文构建pre-hooks"></a>

- [3. 上下文构建（pre hooks）](architecture/message-lifecycle.md#3-上下文构建pre-hooks)

<a id="4-llm-调用"></a>

- [4. LLM 调用](architecture/message-lifecycle.md#4-llm-调用)

<a id="5-输出处理post-hooks"></a>

- [5. 输出处理（post hooks）](architecture/message-lifecycle.md#5-输出处理post-hooks)

<a id="6-记忆写入与晋升"></a>

- [6. 记忆写入与晋升](architecture/message-lifecycle.md#6-记忆写入与晋升)

<a id="7-定时任务"></a>

- [7. 定时任务](architecture/message-lifecycle.md#7-定时任务)

<a id="关键数据结构"></a>

- [关键数据结构](architecture/data-boundaries.md#关键数据结构)

<a id="chatcontext"></a>

- [ChatContext](architecture/data-boundaries.md#chatcontext)

<a id="主要数据表"></a>

- [主要数据表](architecture/data-boundaries.md#主要数据表)

<a id="llm-成本控制"></a>

- [LLM 成本控制](architecture/llm-budget.md#llm-成本控制)

<a id="记账链路"></a>

- [记账链路](architecture/llm-budget.md#记账链路)

<a id="预算在哪里生效"></a>

- [预算在哪里生效](architecture/llm-budget.md#预算在哪里生效)

<a id="前置过滤跳过是攒批不是丢弃"></a>

- [前置过滤：跳过是攒批，不是丢弃](architecture/llm-budget.md#前置过滤跳过是攒批不是丢弃)

<a id="400-不降级"></a>

- [400 不降级](architecture/llm-budget.md#400-不降级)

<a id="astrbot-插件兼容层"></a>

- [AstrBot 插件兼容层](architecture/integrations.md#astrbot-插件兼容层)

<a id="加载时机与目录名"></a>

- [加载时机与目录名](architecture/integrations.md#加载时机与目录名)

<a id="html--图片渲染"></a>

- [HTML → 图片渲染](architecture/integrations.md#html--图片渲染)

<a id="本地状态接口"></a>

- [本地状态接口](architecture/integrations.md#本地状态接口)

<a id="扩展机制"></a>

- [扩展机制](architecture/integrations.md#扩展机制)

<a id="v2-控制面webui-与桌面壳"></a>

- [v2 控制面（WebUI 与桌面壳）](architecture/integrations.md#v2-控制面webui-与桌面壳)

<a id="时间处理约定"></a>

- [时间处理约定](architecture/data-boundaries.md#时间处理约定)

<a id="两层归属的分界线"></a>

- [两层归属的分界线](architecture/data-boundaries.md#两层归属的分界线)
