# P09 后台投递、策略与配额

日期：2026-10-25（Asia/Shanghai）
范围：Participation、Scheduling、Cometa 的后台路线与投递边界；仅 fixture/本地验证。

## 实施

- `transport_delivery.resolve_background_bot` 与 `send_background_message` 现在先按完整 `BotRef` 查询 `TransportRegistry`。注册路由通过 `OutboundService` 的 generation 校验；只有完全匹配 `legacy-qq:{self_id}` 的 OneBot QQ 目标可以回退旧 `get_bots()` 精确键。其他未绑定身份直接失败，不尝试另一个在线 Bot。
- 注册的新连接在后台发送前必须具备主动发送能力，并通过已启用连接、完整场景（kind、scene、parent path、thread）与合并策略校验。缺省 `proactive_enabled=false`；quiet hours 在配置时区内按起点包含、终点不包含判断，跨午夜有效，时区/配置不合法时拒绝发送。新连接没有可验证场景绑定时拒绝发送。
- 有效策略中的 `requests_per_window` / `rate_window_seconds` 转为 scene-scoped `request` bucket，交给既有出站 FIFO 调度器；它与 adapter API quota 保持独立。配额对不完整配置 fail closed。
- Participation 保留原来的群锁、静音/冷却和 direct reply 独立性；它已经用完整 `DeliveryTarget` 走 `OutboundService`。Scheduling 与 Cometa 保留持久化 target、精确作用域配额和 `sending → delivery_unknown` 终态；未知回执不自动重投。历史 legacy QQ 任务没有被升级为新连接路由。

## GitNexus 与源码核对

- 编辑前索引：GitNexus 1.6.12，仓库 `/home/vegetable/repos/Stella`，工作区与索引提交 `d69e367` 一致、2045 个覆盖文件。
- `impact transport_delivery.py --direction upstream`：LOW，13 个上游节点、4 个直接引用、5 个模块；直接文件引用含 `ai_gateway.py`、`cometa_bridge.py`，间接模块含 Scheduling 与 Cometa。独立符号 `resolve_background_bot` / `send_background_message` 均未解析，记作 UNKNOWN，不按零调用处理。概念 query 没有给出可用的后台流程，因此用源码核对了调度发送、Participation、睡眠播报、Cometa 文本与长结果调用点。
- 当前图存在已知提取下界：39 个大文件跳过、3318/3518 个入口候选未排序、931 个 callees 跳过、46 个 walk 截断、23 个 trace 达深度上限，以及 364 处跨语言属性调用未连边。图结果不替代调用源码复核。

## 验证

验证目录为 `STELLA_HOME=/tmp/stella-p09-check-20261025`，`STELLA_TRANSPORT_SETTINGS_JSON` 显式置空；未读取或修改生产库、本机配置、凭据，也未启动 Bot、模型或平台。

- 定向回归：Scheduling 投递/store/runtime/gate，Cometa 投递/桥接/恢复，Participation/主动 @、Transport outbound/scheduler/pipeline 与新增后台策略/路由用例：**234 passed**，1 条既有 NoneBot “No adapters found” RuntimeWarning。
- Ruff、变更 Python `py_compile`、`git diff --check`：通过。
- `python scripts/check_docs.py`：121 files / 1322 local links / 577 migration anchors / 0 errors。
- `python scripts/generate_message_flow.py --check`：退出 1；28 个归档清单均未匹配，首个同拓扑候选仅有正文锚点差异，`nodes_added/removed=[]`、`edges_added/removed=[]`、`topology_changed=false`。按计划留给 P10 最后一次 immutable flow 刷新，本包不更新该工件。

## 边界与状态

本包只证明 fixture 与隔离环境行为，不证明新平台 live、真实账号/线程权限、生产配额阈值或发布包行为。官方 32 项矩阵仍 0/32 certified；P04 native wheel/API parity 与恢复演练、完整 Python/CI、真实模型/平台、VM/发布门禁仍未通过或未运行，整体 **NOT READY**。
