# WP10 控制面与交付实施记录

日期：2026-10-21（Asia/Shanghai）

实现提交：`a20c3a1 feat(webui): configure cross-platform adapters (WP10)`

打包修复：`b0cb052 fix(release): include editable manifest in packages (WP10)`

状态：WP10 本地实现与定向门禁完成；跨平台 live、全量 Python、QQ 灰度、clean VM 与真实 Release 验收仍 NOT READY。

## 交付

- 平台页现可配置 `STELLA_ADAPTER_MODULES` 模块路径列表，分别显示保存配置、生效模块和进程环境覆盖；保存写入 `STELLA_HOME/.env`，要求重启。模块路径只在 Bot 启动时装载，WebUI 不会 import 或自动安装第三方适配器。
- 保留 OneBot V11 连接 profile，支持多个正向 WS 地址；读取接口只返回 `has_token`，不会返回 token 明文。对适配器模块和 OneBot 配置的写操作继续受管理鉴权、审计和 `restart_required` 契约保护。
- Doctor 根据进程环境优先级及 `.env` 判断 OneBot V11 是否启用；未启用时不探测 NapCat 端口/URL，并跳过模式、端点、反向端口、正向连接、token 五项检查。默认值仍是 OneBot V11，因此旧 QQ 配置和检查继续工作。安装器状态卡和诊断复制分别呈现 OneBot 不适用、链路监控关闭与确实未连接。
- API router 顺序未变；已有 `tests/webui/test_webui_mount.py` 覆盖 OneBot WS、status、`/api/v1/*` 在 SPA fallback 之前注册。
- 发布测试发现 allowlist 打包器不携带隐藏 `.stella-manifest.json`。follow-up 在 standalone 和 OneClick installer resource 的最终 staging 树中调用同一 `deploy.manifest.write_manifest()`，因此哈希来自实际随包默认文件，而不依赖 source checkout 是否预先运行过 manifest 命令。加入 standalone archive 与 installer resource staging 断言。

## GitNexus

初始影响索引绑定 WP09 提交 `c59c2ff`：

- `deploy.probe._probe_onebot`：HIGH，10 个受影响节点、2 个直接调用者、3 条流程，涉及 Deploy、Link monitor 与 Bot status；编辑范围限定在适配器关闭时不做 OneBot 网络探测及将适用性传给 checks。
- `deploy.checks.check_onebot_mode`：UNKNOWN/0。源码核对 `_ALL_CHECKS` 确认模式、端点、端口、正向 URL 和 token 检查均在 Doctor 主执行列表。
- `webui.services.platformcfg.onebot`：LOW；`update`：LOW、图中调用下界 1。源码核对由 `webui/routers/config.py` 的 OneBot 路由调用。
- `stella-installer/src/run.html` 文件级影响 UNKNOWN/0。内嵌脚本调用通过状态刷新进入 `renderStatus`，诊断按钮调用 `copyDiag`；引用搜索确认显示逻辑均在该文件内。没有改动 Rust CLI status renderer；它已有 disabled-monitor 分支。
- 第一实现批次提交前 `scope=all` 为 16 files / 47 symbols / 8 processes / HIGH。against-main 第一次 query PARTIAL 后串行重跑，得到 331 files / 1,110 symbols / 115 processes / CRITICAL（WP00–WP10 累计；图列表有上限）。

为检查打包问题，索引在 `a20c3a1` 后刷新：99,307 nodes、246,672 edges、1,039 clusters、847 flows。刷新图后，`build_standalone` 为 LOW（5 impacted / 2 direct），`stage_installer_resources` 为 MEDIUM（15 / 12 direct），`write_manifest` 为 LOW（2）。包修复批次 `scope=all` 为 2 files / 4 symbols / 0 processes / LOW；against-main 为 333 files / 1,122 symbols / 106 processes / CRITICAL，完整返回且标明符号列表 capped。此后索引已再次刷新并绑定 `b0cb052`；WP11 开始前会核对状态提交后的索引新鲜度。

索引仍跳过 20 个大文件；分析器记录 callable candidate cap、跨语言属性解析缺边、2,946 个入口候选中 2,746 个未入选，以及 trace budget、深度和 branching 截断。流程缺失不能用作无调用者证明。

## 验证

命令使用临时 `STELLA_HOME=/tmp/stella-wp10-20261021`，包输出写到新建的 `/tmp/stella-wp10-*` 目录；未启动 Bot 或连接生产服务。

- Deploy、runtime、status、link monitor、WebUI platform/config/read-only/mount 定向组合：**253 passed**。新平台配置文件加入 OneBot 多 URL/token 脱敏用例后，该文件单独 **4 passed**；产品包测试 **18 passed**。测试组有重叠，不相加。
- `.venv/bin/ruff check .` 与 `git diff --check`：通过。
- `python scripts/check_docs.py`：119 个文件、1,225 个本地链接、577 个迁移锚点、0 errors。`python scripts/generate_message_flow.py --check`：`message-flow.9b80952673b2.json` 匹配当前源码。
- Dashboard `vue-tsc --noEmit`：通过；Vitest：**100 passed**；Vite production build：通过。构建报告已有 dynamic import 同步/异步混用和大于 500 KB chunk 警告。
- `stella-installer/src/run.html` 内嵌模块脚本经 Node `--check`：通过。
- `scripts/build_release_package.py` 生成 `Stella-Standalone-Python-v6.2.0-windows-amd64.zip`；`check_release_archive.py` 返回成功。Standalone staging 与 OneClick Python installer resource staging 均通过 `check_release_layout.py`，manifest、`core/transport/adapter_loader.py`、`webui/dist/index.html` 与 `desktop/dashboard-dist/index.html` 均在包树中。
- 静态检查 `pyproject.toml` 确认 NoneBot adapter 列表仍为空；`requirements.txt` 保留 OneBot V11 默认依赖，额外适配器未被自动安装。

pnpm 11 wrapper 首次执行因 `package.json` 的旧 `onlyBuiltDependencies` 配置被识别为 ignored build scripts 而未能自动准备命令；未批准额外脚本。使用已安装依赖和 Codex bundled Node 直接运行 typecheck、Vitest 与 Vite 后全部通过。pnpm 生成的审批提示文件已还原，未进入提交。

## 未验收

- 本地未安装或启动新的第三方 adapter；其 Python 版本、driver、权限/发送能力与真实凭据组合没有 live 证据。
- 没有启动 QQ Bot、真实模型、QQ 灰度、跨平台多账号恢复或 clean VM；没有运行全量 Python、完整 Windows Release CI 或用户机器升级验收。WP07 记录的 Cometa worker 挂起仍是集成测试缺口。
- 因此 WP10 的本地控制面、部署检查与 package-layout 门禁通过，不代表 32 项注册平台认证完成；整体 XPLAT-IMPL 保持 NOT READY，下一阶段 WP11。
