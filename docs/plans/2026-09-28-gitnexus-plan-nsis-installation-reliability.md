# Stella NSIS 安装可靠性工程计划

> 任务：覆盖 NSIS 构建、负载供应、安装、首启、修复、升级、卸载与发布验证，尽可能减少安装失败和失败后的恢复成本。
> 状态：待实施；本次只新增本计划，没有修改生产代码、测试或构建配置。
> 基线提交：3f5a69b087c39052d256dfafe95d6f66642a5f41；仓库 Stella_project；宿主 E:/stella/stella_project，GitNexus 容器挂载 /repo。
> 计划深度：完整。用户要求“详实可行、所有能完善的部分”，按完整计划执行，不另行等待深度选择。
> 索引与分析边界：已用现有 Docker runner 完成 analyze --index-only --pdg，HEAD 与索引匹配（765 文件；GitNexus 1.6.11 / Node 22.23.2）。未改源码；分析器仍报告候选/流程枚举截断及跨语言解析限制，图不能证明全部路径已覆盖。
> 证据：schema 2；全局 dirty digest ddae2d79e44267d6fd40de31c3f37d8d0f10af2a37e7e7e7753d1c4300704ecf；35 个排序后的引用路径；只排除本计划路径。完整记录见 §11。
> 标记说明：[verified] = 当前源码/配置或已完成的隔离实验；[graph] = 图查询；[inferred] = 基于证据的推断；[assumed] = 实施前必须验证。下文“拟新增”、目标值及设计要求均是计划，不表示已经实现。

## 1. 目标与范围

目标是形成“可重复构建、安装前可预判、安装过程可观察、失败可恢复、安装结果可验证”的 Windows 安装链路。安装成功的含义是所选产品的必需组件已可使用，或明确进入“安装已完成、需要重启”的状态；不能仅以 EXE 正常退出、文件存在、pip dry-run 通过作为成功。

本计划覆盖：

- OneClick Python / Rust 的 online / offline 四种 Windows amd64 NSIS 产物。
- Dashboard、嵌入式 Python、Python 依赖、Rust wheel、llama.cpp CPU 后端、默认 embedding、Playwright、NapCat、WebView2。
- 新装、同版本修复、旧版升级、profile 切换、断点续装、并发启动、卸载及数据保留。
- CI 输入锁定、最终 EXE 验收、签名与校验、发布一致性、日志、支持文档和诊断。
- 对共享部署代码涉及的 Standalone/CLI/旧桌面壳做兼容回归，不擅自改变它们的产品语义。

不以“安装完全不可能失败”为承诺；权限策略、硬件、磁盘故障及第三方组件仍需明确失败语义。暂不增加默认聊天模型，不要求安装阶段登录 QQ 或填写用户 API 密钥，不以关闭杀毒软件作为解决办法。

优先级：

- P0：发布阻断项、已确认缺陷、状态可信度与真实安装验收。
- P1：显著降低失败概率或恢复成本的结构改进。
- P2：长期维护、体积/性能优化与支持体验；全部列入工作项，有前置条件，不能借此延后 P0。

## 2. 当前行为与已确认缺口

### 2.1 构建和安装路径

[verified] 主发布入口是 .github/workflows/release.yml:163、248、383。使用 desktop/src-tauri 构建，matrix 为两种 profile × 两种 payload；不是以 stella-installer 目录为主发布入口。

1. Dashboard 构建；Windows 构建 Rust wheel 和固定提交的 llama.cpp CPU 后端。
2. 构建组件 catalog，下载 Python zip、get-pip、依赖 wheels、NapCat MSI、embedding 与 Playwright 浏览器。
3. stage_installer_resources 将白名单程序树与可选 offline 目录复制到 resources/stella。
4. Tauri 生成 NSIS setup EXE，然后上传。
5. 离线版 POSTINSTALL 调用系统 tar 解压 Python，运行 nsis_bootstrap_helper。
6. helper 补 ._pth → get-pip → pip requirements → deps 标记 → deploy bootstrap install。
7. 在线版跳过上述钩子；GUI prepare_runtime 负责首次下载/安装。
8. Release job 汇总并发布，支持同版本资产覆盖。

### 2.2 问题清单

| ID | 事实或风险 | 证据 | 后果 |
| --- | --- | --- | --- |
| F01 | [verified] 构建 EXE 后直接上传，没有最终 EXE 安装 job | release.yml:379–395 | NSIS、用户权限、MSI、DLL、首启错误不能在发布前拦住 |
| F02 | [verified] wheel dry-run 使用 runner 完整 Python | release.yml:229–234 | 不能代表嵌入式 Python 及安装后路径 |
| F03 | [verified] helper 缺少 Rust wheel 装载/自检、profile catalog 标记；GUI 有这些步骤 | nsis_bootstrap_helper.py:75–109；python.rs:99–168、399–507 | 安装成功后 GUI 仍可能安装或失败；不能承诺全部准备完成 |
| F04 | [verified] 组件异常只捕获 BootstrapError；失败/运行中状态不走 complete 分支的复用筛选 | bootstrap.py:416–546 | NapCatError 等可遗留 running；重试重新处理已完成项 |
| F05 | [verified] 上一轮 AST 隔离故障注入复现 NapCatError 后 running，failed 重试重新获取 completed 项 | 上一轮本会话实验，未执行真实 MSI | 已有明确回归用例，应先落测试再修复 |
| F06 | [verified] POSTINSTALL 直接写正式 runtime；只有 Abort，没有对应撤销逻辑 | installer-hooks.nsh:18–49 | [inferred] 文件、pip、注册项及外部组件可能部分落盘 |
| F07 | [verified] $0 同时保存 FindFirst 句柄与 nsExec 退出码，FindClose 得到被覆盖值 | installer-hooks.nsh:24–35 | 句柄管理错误；不将其夸大为已证明的普遍安装失败根因 |
| F08 | [verified] hook/helper 仅判断 MANIFEST 存在；负载清单仅登记 Python zip/get-pip | helper.py:117；build_offline_payload.py:227–290 | Python/get-pip 的安装期校验与 GUI 不一致；wheels/browser 无完整清单 |
| F09 | [verified] 离线组件缺失/损坏可回退在线；已有测试固定这一行为 | bootstrap.py:190–232；test_bootstrap.py:407 | 真离线时耗时后才报网络错误，原始损坏原因易被遮盖 |
| F10 | [verified] MSI 1603 自动重试完整 UI；0/1641/3010 均按成功写 metadata | napcat.py:191–282 | 静默体验不一致；无 1618 专项策略；重启语义丢失 |
| F11 | [verified] requirements 多用范围；CLI ^2；pip/maturin 升级；浏览器用 runner 已安装 playwright | requirements.txt；release.yml:381、408；build_offline_payload.py:201 | [inferred] 重建、在线安装与离线包可能产生版本差异 |
| F12 | [verified] 默认数据目录为 program_root.parent/StellaData | home.py:148；python.rs:1221 | [inferred] OneClick 无已有指针时可落到 INSTDIR/resources/StellaData，仍在安装目录内部 |
| F13 | [verified] GUI offline ensure_pip 没给 --find-links，helper 给了；两份 python.rs 逻辑重复 | python.rs:568–590；helper.py:89 | [inferred] GUI 离线修复路径可能失败并转联网，需真实 get-pip 验证 |
| F14 | [verified] fetch_catalog_packages 对已存在目标直接跳过校验 | build_offline_payload.py:172–174 | 重跑构建复用陈旧/损坏缓存的风险 |
| F15 | [verified] llama 校验以文件、元数据与摘要为主，没有启动推理自检 | verify_llama_package.py:verify | 干净系统缺 DLL/指令集不兼容可能延迟到运行时暴露 |
| F16 | [verified] 已有 transactional_upgrade，但 desktop project_root 当前定位固定资源路径 | upgrade.py:145；python.rs:1221 | 不能把已有 active pointer 写入等同于 NSIS/桌面启动已支持回滚 |
| F17 | [verified] Dashboard 版本标记直接取 GITHUB_REF_NAME，手工发布其它 job 使用 inputs.version | release.yml:build-dashboard、274 | 手工构建版本标记可能不一致 |
| F19 | [verified] UpgradeLock.recover_stale 在 Windows 分支未隔离 os.kill(pid, 0) | upgrade.py:72–90；Python 官方 os.kill 文档 | 调用时可能终止目标；[graph] 未解析到调用者，定向源码搜索仅见定义，属于复用前必须修复的潜在风险，未证明当前 NSIS 可达 |
| F18 | [verified] 已有 NSIS helper/MSI 测试主要模拟子进程；Windows upgrade matrix 使用假程序树 | tests/test_nsis_bootstrap_helper.py；tests/test_napcat_package.py:112；tests/windows/test_upgrade_matrix.py | 它们不能替代最终安装器集成测试 |

需继续验证而不是认定为现有故障：tar 在受支持系统和 NSIS 进程位数下的可用性；VC++/OpenSSL 等传递 DLL；NapCat MSI 自定义动作是否联网；系统/用户安装作用域；Defender/SmartScreen 对签名产物的表现；最终包体与磁盘峰值。此类验证已纳入任务，不要求用户先回答。

## 3. 相关架构与目标边界

### 3.1 保留并扩展的组件

- [verified] build_release_package.py 的白名单、profile 校验、前端必须存在检查仍为发布边界；新增 runtime 路径需要显式允许，不能直接放开 FORBIDDEN_PARTS 中所有 runtime。
- [verified] acquire.py 已有 HTTPS 来源、摘要/大小校验和临时下载文件；扩展重试/恢复而不是绕过校验。
- [verified] bootstrap.py 有原子 JSON 写入、组件 staging 与进度记录；扩展为按组件的事务账本。
- [verified] napcat.py 已有 MSI 日志和原子 metadata；扩展结果语义、机器实际状态检测与最小提权。
- [verified] upgrade.py 已有版本目录、摘要、postflight、active pointer、锁；需补齐启动端读取及 Windows 锁/崩溃语义后复用。
- [verified] WebView2 已采用 offlineInstaller；保留，不能改成 embedBootstrapper 后仍声称完全离线。
- [verified] memory_rust/native/pyproject.toml 将 memory_rust Python 包纳入 wheel；不能仅因 stager 没单独复制 memory_rust 就断言 Rust 源包必然缺失，必须检查真实 wheel 内容。

### 3.2 目标职责划分

| 层 | 目标职责 |
| --- | --- |
| CI | 解析一次发布版本、锁依赖、组装可搬迁 runtime、验证完整负载、构建和签名 EXE、运行安装验收 |
| NSIS | 用户选择、最早可行的预检查、文件释放、安装事务入口、进度/退出码、快捷方式和卸载接入 |
| 安装执行体 | 状态机、哈希验证、就绪检查、组件激活、断点续装、日志与恢复 |
| GUI | 消费同一安装契约和健康状态；明确展示修复操作；常规状态查询不反复触发重型安装 |
| 数据目录 | 用户配置/数据库/QQ 数据、组件状态、安装日志；与可替换程序目录分离 |
| 外部 MSI/WebView2 | 独立生命周期和系统状态；不能伪装成与应用目录同一原子事务 |

拟定长期布局：稳定启动入口 + 版本化程序树（包含已验证 runtime）+ 独立用户数据根。正常启动从已验证的 activation record 选择程序树；所有路径都验证归属，不任意执行指针指定的外部程序。

兼容期先保持现有布局，通过版本化元数据和适配器增加能力。启用版本目录前，必须同时接通资源定位、启动入口、快捷方式、CLI 透传、修复和卸载；只写 active pointer 不算交付。

## 4. GitNexus 发现与影响范围

本次在已有源码扫描证据上追加 impact；没有重新遍历无关代码。命令前缀为 docker exec -w /repo stella-gitnexus gitnexus，repo 均显式指定 Stella_project。

| 主符号 | 查询与原始关键结果 | 全部直接生产消费者（d=1） | 必须覆盖 |
| --- | --- | --- | --- |
| bootstrap_offline | impact upstream depth=3：risk LOW，direct=1，impactedCount=2 | deploy/nsis_bootstrap_helper.py:main | 命令行返回码、NSIS 调用、旧离线安装 |
| stage_installer_resources | impact upstream depth=3：risk LOW，direct=1，impactedCount=2 | scripts/build_release_package.py:main | 四种 OneClick 暂存、资源白名单、CLI 参数兼容 |
| install_profile | impact upstream depth=3：risk LOW，direct=1，impactedCount=1 | deploy/__main__.py:_cmd_bootstrap | deploy JSON 结果、错误码、GUI/helper 子进程 |
| runtime_bootstrap.prepare_runtime | 精确 UID impact upstream depth=3：risk CRITICAL，direct=1，impactedCount=5，processes_affected=7 | desktop/src-tauri/src/python.rs:prepare_runtime 包装函数 | 启动/状态/配置/诊断/人格读取、desktop 启动入口 |
| install_msi | impact upstream depth=3：risk LOW，direct=1，impactedCount=3 | deploy/acquire.py:install_napcat | acquire → bootstrap → deploy 错误与待重启信息传播 |

[graph] prepare_runtime 的关联入口包括 wait_bot_ready、get_status、run_doctor、start_bot、get_config、get_personas、lib.rs:run。CRITICAL 原样保留，不以 riskSharedAxes=LOW 降级。

[graph] secondary：UpgradeLock.recover_stale 精确 context 仅见类归属；upstream impact risk UNKNOWN、0 callers。按规则补充 deploy/tests/runtime-manager 定向文本核对，仅发现 Python 方法定义；不据此断言永远不可达。deploy.process.is_alive 的 context 与源码确认已有 Windows 专用检测，但其配置导入和失败语义不适合直接当轻量安装锁原语照搬。

[graph] context transactional_upgrade 找到 _cmd_upgrade 以及 test_upgrade.py、tests/windows/test_upgrade_matrix.py；query “upgrade transactional rollback stop processes”定位到现有升级与进程停止测试。

重要边界：

- 表中 d=1 是默认不含测试的生产调用者；上一轮 context 已定位 helper/bootstrap/product-profile/MSI 测试，§8 分别覆盖。
- NSIS → Python、Rust Command → deploy、CI → 脚本是跨进程调用，图可能缺边；已通过配置和命令字面量核对，不能用 LOW 推断安装改动风险低。
- 图资源接口没有作为可读 MCP resource 暴露；用 CLI query/context/impact 的流程和模块结果定位，未假称完整读取 clusters/processes 资源。
- 分析器报告 callable 候选集合截断、跨语言字段无法解析、流程枚举上限；图不是全部调用路径证明。
- 后续修改 secondary symbols、新增调用关系前仍须重新做对应 impact；本计划不替代实施时的门禁。提交前必须完整 detect-changes，partial/truncated 不能作为通过。

## 5. 语句级约束与 PDG

已刷新带 PDG 的索引后，对 install_profile:538、install_msi:255 使用 upstream depth=2、limit=12 有界切片：前者返回 24 个 affectedStatements 且因 depth/limit 截断，后者返回 11 个且因 depth 截断；二者 risk 均为 UNKNOWN。它们用于定位控制/数据相关源码，不是完整影响结论，也不是提交门禁通过证据。

bootstrap_offline 首个锚点 101 是注释；经 AST 校正到 write_deps_marker 可执行调用 99 后仍返回 pdg-no-block-at-line、risk UNKNOWN。已回到源码验证该顺序；没有补造 PDG 边。跨过程 bridge 仅来自 callgraph，不冒充精确语句依赖。具体查询边界保留在 §11。

无论图切片是否覆盖，以下顺序由源码核对，不冒充 PDG 边：

| 位置 | 已验证顺序/条件 | 对实现的约束 |
| --- | --- | --- |
| helper.py:85–109 | patch_pth 先于 pip；deps 标记先于组件安装 | deps-ready 仅代表依赖阶段；不能复用为整个产品 ready |
| bootstrap.py:459–479 | 仅 previous.state=complete 时核验并筛 pending | 新账本必须支持 failed/interrupted/running 后复核，且核验真实文件/MSI 状态 |
| bootstrap.py:492–529、538 | 外部组件执行后才 completed；只处理 BootstrapError | 所有预期下层异常都归一化、保留原始原因，并落最终状态 |
| napcat.py:220–278 | MSI 成功码后写 metadata | reboot-required 与健康可用分开；重启/取消/超时后先查询系统状态，避免重复启动 MSI |
| python.rs:109–112 | deps 标记命中仍调用 Rust/profile | 新兼容适配器必须保留必要健康复核，避免错误早返回，也避免状态轮询触发重新安装 |
| upgrade.py:174–204 | 复制→摘要→postflight→再次复制/摘要→切换指针 | 用户数据不参与程序树复制；指针切换前旧版可用，切换后再延迟清理 |
| hooks.nsh:24–35 | FindFirst 句柄被 Pop 覆盖 | 分离变量并正确释放，错误/超时与数字退出码明确区分 |

就绪指纹不能只取 requirements 文本。目标至少包含 product/profile、运行时版本与架构、依赖锁摘要、Rust wheel 摘要、catalog 摘要、程序清单摘要、安装契约版本和数据根身份。对大型模型避免每次 UI 轮询重复完整哈希：安装/修复做完整验证，平时基于可信账本、存在性、大小和必要健康探测判断。

## 6. 拟实施变更

### WP01｜P0：固定安装契约和回归基线

文件：release.yml、tauri.conf.json、helper.py、bootstrap.py、python.rs、tests/test_nsis_bootstrap_helper.py、tests/test_bootstrap.py、tests/test_product_profiles.py。

- 统一一次解析发布版本，Dashboard、profile、catalog、EXE 元数据、产物名都消费同一个值；修复手工发布前端 marker 来源。
- 生成 release metadata：schema、release_version、build_id、profile、payload_mode、arch、supported_os、runtime 指纹、catalog/lock 摘要。
- payload_mode 不再靠 MANIFEST 是否存在来猜测；声明 offline 却缺清单时必须失败，不能当 online 跳过。
- 安装结果区分 ready、reboot_required、failed、cancelled、interrupted、repair_required；返回码与 JSON/日志有稳定映射。
- 修正“Abort 自动消除半安装”“GUI 首启完全无需装载”等未实现承诺。
- 固定现状重现用例 F03/F04/F07/F09/F13；测试新行为而不是复制旧错误断言。

验收：四产物元数据一致；缺 offline manifest 硬失败；故障注入均有非 running 终态与组件定位。

### WP02｜P0：最终 EXE 安装验收与发布门禁

文件：release.yml；拟新增 scripts/test_nsis_install.ps1、tests/windows/test_nsis_installation.py（名字为提案，当前不存在）。

- 建立 build → artifact metadata/hash check → sign → install-test → publish 的依赖。
- P0 先用独立 Windows job 执行最终 EXE；发布验收进一步使用可重置的干净客户端 VM，不能把预装大量运行库的 hosted runner 当作“干净 Windows”。
- 离线 Python/Rust 必须在断网、无系统 Python/Rust/Node 开发工具环境完成安装、打开 GUI，并进行本地组件自检。
- 在线版必须执行最终 EXE 加 GUI 首启引导；只检查 NSIS 返回 0 不够。
- 记录安装返回码、阶段耗时、peak disk、进程树、WebView2/NapCat 状态和产物 SHA-256；失败时 always 收集日志。
- 测试时不把仓库放进 PYTHONPATH，不使用 runner Python 执行产品自检；从安装目录之外启动随包 python。
- 新增集成测试隔离于全局 conftest 的浏览器禁用/应用 import 夹具，不让单元测试夹具替代真实浏览器。
- 调用 EXE 用明确参数列表、Wait/ExitCode/超时；silent /S、/D 等参数以固定版本生成的 .nsi 为准，处理 /D 必须最后等语法，不套用通用 shell 引号假设。
- 测试安装只在一次性 VM/专用测试账户执行；不可在开发者现用机器默认安装、卸载全局组件。

验收：一个包安装失败即可阻断发布；存档的是测试过的最终字节及摘要。未签名测试包不能替代正式签名包的最终验收。

### WP03｜P0：补齐当前离线 helper，作为兼容桥

文件/符号：nsis_bootstrap_helper.py:bootstrap_offline、patch_pth、_run、write_deps_marker；installer-hooks.nsh；python.rs 对应 ensure_*。

- 按 metadata 精确选取唯一 Python 版本/架构文件，避免通配符匹配多个旧 zip；解压前校验哈希。
- 检查 SetOutPath/目录创建、tar 启动、解压文件结构；分离 FindFirst handle 与 exit code，恢复 hook 使用的寄存器/OUTDIR。
- pip 子进程隔离用户配置：明确本地 find-links、禁用版本检查、禁输入；清除会改变目标目录/约束的 PIP_*，使用受控配置。不能仅依赖 --no-index；--isolated 不等同于忽略所有系统配置。
- offline 模式禁止源码现场构建，只用已校验 wheels；保留必要构建工具/运行依赖的显式定义，不靠开发机碰巧安装。
- Rust profile 必须发现且仅发现匹配 wheel；沿用项目已有原地解包及 _native+selector 导入验证，禁止 pip --target 意外删除 Python 半边。
- helper 与 GUI 使用一致的阶段标记；全部健康检查通过后写产品 ready。写 marker 原子化；失败不留下假的产品完成状态。
- 修复 GUI 离线 get-pip 参数与 helper 的差异；通过真正的嵌入式 Python 测试确认，不仅检查源码包含某字符串。
- 此桥保留用于旧包修复；新 runtime 包启用后 normal install 不再执行 pip，避免长期维持三份不同实现。

验收：安装完成后首次 GUI 不再装 Rust 或重复装组件；legacy 修复在断网下可用；不依赖机器已有 pip 配置。

### WP04｜P0/P1：组件账本、失败归一化与续装

文件/符号：bootstrap.py:install_profile、_installed_record_matches、_write_progress；__main__.py:_cmd_bootstrap；acquire.py 与 napcat.py 错误边界。拟新增安装状态 schema 和共享状态模块。

账本字段至少有：schema、operation_id、product/build/profile、catalog hash、目标目录/数据根、owner PID+进程启动身份、overall state、current step、timestamps、每组件 expected digest/version、attempts、state、artifact/source、error code、native exit code、log path、reboot_required。

- 每组件经历 pending → verified → staged → activated → healthy；失败单独记录。以实际状态复核为准，不能盲信 completed 列表。
- 捕获并转换 AcquireError/NapCatError/PackageError/OSError/子进程异常；未知异常保留诊断并写 failed，不能吞错成功。原始异常链可写日志。
- 启动时发现 owner 已消失的 running 记录转 interrupted；不能仅因时间久或 PID 重用抢锁。
- P0 修复 UpgradeLock.recover_stale 的 Windows os.kill(pid, 0)：该调用不是无副作用探测。采用已核对的 Windows API 检测与进程创建身份；可提取既有 deploy.process 的安全方向，但不能直接复用其“OpenProcess 失败即不存在”语义。权限不足/查询失败为 unknown，绝不据此删锁。原语应轻量，避免 import process 时提前加载全应用配置；Win32 HANDLE/参数类型明确，正常关闭句柄。持有真实 OS 锁或等价机制协调检查与清理，避免旧 owner 删除新 owner 的锁。
- failed/interrupted 重试也跳过验证健康的组件。模型丢失、MSI 被手动卸载、runtime 被隔离后重做对应组件。
- 所有 installer、GUI 修复、CLI bootstrap/upgrade 共享跨进程锁；进程内 PREPARE_LOCK 不够。
- 同时考虑 install root 与共享 data root 两把锁，规定统一获取顺序，避免死锁。
- 取消/超时先写状态并处理所拥有的子进程；外部 MSI 状态重新查询，不能在旧 msiexec 仍运行时重试。
- 兼容旧 JSON/marker；首次升级迁移为“待复核”，不把旧 ready 文本直接提升为健康。

验收：在每一阶段结束前后注入中断，再次安装都能安全继续；不会重复启动已经执行中的 MSI，不出现永久 running/假 ready。

### WP05｜P1：完整负载清单、严格离线与缓存一致性

文件/符号：build_offline_payload.py:write_manifest、fetch_catalog_packages、build_wheels；build_release_package.py:stage_installer_resources；bootstrap.py:_download_record；python.rs:verify_offline_file。

- 清单覆盖 runtime、wheels、Rust wheel、浏览器、组件档案、catalog、profile、必要程序文件；记录相对路径、大小、SHA-256、用途、版本/架构、展开大小或估算依据。
- 清单不包含自身摘要，外层 release metadata/签名负责绑定清单；明确哈希证明完整性，不独自证明可信来源。
- 清单校验拒绝绝对路径、..、重复/大小写冲突、盘符/ADS、越界链接、危险归档项；执行受限解压，限制文件数/展开字节数。
- 缓存命中也校验；损坏先隔离再重取。缓存键包括 OS/arch/Python ABI/锁摘要/catalog，而不只文件名。
- 构建后、上传前、下载 artifact 后、staging 后以及安装使用前分别验证必要边界；不会每次状态轮询重扫数 GB。
- browser revision 与已锁定的 Playwright wheel 对照，保留需要的隐藏文件/标记；对 upload-artifact 的 hidden-files 策略显式声明并验包。
- 严格 offline 缺失/损坏应快速返回 payload_missing/payload_corrupt 与文件信息；不静默联网。提供用户明确发起的“在线修复”入口，采用同一版本摘要。
- 校验 Rust wheel ABI/PE 架构、Python zip 内结构、MSI/模型格式、前端 version marker，而非仅扩展名或非零文件大小。

验收：任意删一个/改一个关键文件，安装在执行该负载前明确失败；正常离线安装不发出外网连接。

### WP06｜P1：锁定依赖与构建工具链

文件：requirements.txt 保留开发约束；拟新增发布 constraints/lock、构建工具版本文件；release.yml、build_offline_payload.py、build_release_catalog.py、memory_rust/native/pyproject.toml。

- 发布环境统一 Windows amd64、嵌入式 Python 3.12.10 对应 ABI；具体 Python 升级另走兼容评估，不在本计划顺便变更。
- 一次解析得到完整传递依赖版本+哈希，构建/在线 runtime/离线 runtime 使用同一份；setuptools/wheel/pip/build backend 也固定。
- sdist 仅允许在受控 CI 构建；固定构建依赖并保存 wheel 哈希/元数据。用户安装不要求编译器。
- 固定 Tauri CLI 精确版本及实际 NSIS 模板/插件版本，记录 Rust toolchain、maturin、Node/pnpm、CMake/SDK/runner image；正确使用 Cargo.lock 与应用构建 locked 模式，不能把 cargo install --locked 误认为锁住应用构建。
- build-installer 显式 setup-python，不依赖 runner 默认 Python；Windows shell 每条关键 native 命令立即检查 LASTEXITCODE，防止后续成功命令盖掉前面的失败。
- Playwright 用最终锁定环境安装浏览器，再核对 revision；online/offline 不分别解析浮动版本。
- embedding URL 的 main 改为可追溯 revision（实施时查询与当前摘要匹配的真实提交）；不编造 revision。固定来源失效时镜像必须保持同一摘要。
- 依赖更新是独立、可审阅的更新任务，经过相同安装矩阵。所有签名/时间戳造成的字节变化都在锁定/校验链上明确处理。
- 目标是输入和行为可重复，未经测量不承诺 Windows 二进制字节级可重复构建。

验收：同一 lock 的两次构建具有相同依赖清单/browser revision；网络上新发版本不会改变既有 release 的安装内容。

### WP07｜P1：CI 预组装可搬迁 runtime

文件：拟新增 scripts/build_windows_runtime.py、scripts/check_windows_runtime.py；build_offline_payload.py、build_release_package.py；helper.py、python.rs 适配。

- 在干净、短路径 staging 中展开嵌入式 Python，补 ._pth，从锁定 wheelhouse 安装依赖；Rust profile 同步装载完整 memory_rust。
- 用该 runtime 执行 pip check（构建阶段）、关键模块导入、扩展 DLL 加载、ssl/网络栈初始化、Playwright 离线截图、llama 启动/embedding 小请求。
- 生成 runtime manifest 和压缩包；排除构建机路径、用户缓存/凭据、临时日志、编译器、开发数据。Scripts 中有绝对路径的 launcher 必须重建/不用它，启动统一 python -m。
- 将产物搬到完全不同的中文/空格路径，并从外部 cwd 运行；不能用普通 venv 复制代替可搬迁验证。
- offline 直接携带 runtime 成品；online 下载同一 build/profile 的已签名或由可信清单绑定的 runtime。在线小包仍保留离线 WebView2。
- 安装期不执行 get-pip、解析 requirements 或编译 wheels。兼容旧包/显式修复所需 wheelhouse 单独管理，按体积测试决定是否保留，不能误删运行期需要的 Playwright 目录。
- 新 runtime 安装到版本化 staging，健康后激活；运行用户不得需要管理员权限才能启动或修复用户范围数据。
- 先以构建配置开关双轨产出候选包，达到矩阵后切默认；已发布旧包仍走受控兼容路径。

验收：离线正常安装日志中无 pip/编译步骤；搬迁后全部检查通过；Python/Rust 两种产物都独立可用。

### WP08｜P1：NSIS 预检查与最小系统依赖

文件：installer-hooks.nsh、tauri.conf.json；拟新增独立预检查执行体/测试；runtime/metadata 构建步骤。

- 尽早检查系统版本、amd64、当前用户/提权上下文、目录是否可写、路径长度、TEMP、目标卷/数据卷空间。
- 在固定 Tauri .nsi 中核对 hook 的实际顺序；PREINSTALL 可能晚于 WebView2 安装或旧版本处理，不能未经核对宣称“所有操作前预检查”。
- 第一阶段用 hooks 能完成的检查；需要在 .onInit/升级卸载之前介入时采用最小自定义模板或受维护的外层入口，并锁定模板升级差异，不复制大模板后放任漂移。
- 峰值空间模型包含压缩文件、展开树、旧版保留、runtime、模型复制、MSI/Windows Installer 缓存、日志及余量；逐卷计算，按档案清单动态估计，不写死“2 GB 足够”。
- 用安装器内置文件释放或随包受控原生解压能力代替系统 tar；不得在 Python 尚未存在时让 Python 负责解压自己。
- 验证空格/中文/Unicode、长路径、只读目录、网络盘/可移动盘；对不支持的安装目标提前解释。不能默默更改系统长路径策略。
- 当前用户安装作为优先方案；第三方 MSI 确有需要才单独提权，保存原用户 SID/data root，不把用户数据创建到管理员账户。
- 通过干净 VM 的 DLL 依赖扫描+实际启动确定 VC++/OpenSSL 等需求；合法地随包应用本地 DLL 或安装官方 redistributable，并验证其签名/架构/返回码。不能从开发机随机复制未知 DLL。
- 明确验证过的最低 OS/CPU 能力，含 GGML_NATIVE=OFF 仍不代表任意老 CPU 可用；不凭 tar 的版本提示定义整个产品系统支持范围。

验收：已知不满足条件在昂贵步骤前失败；正常安装不依赖机器预装 tar/开发运行库；提权不改变产品用户身份。

### WP09｜P0/P1：NapCat、WebView2 和重启协议

文件/符号：napcat.py:install_msi；acquire.py:install_napcat；bootstrap.py:install_profile；__main__.py；installer-hooks.nsh。

- 用 MSI 产品/版本/安装作用域检测实际状态，区分 Stella 安装、本机预存、被用户卸载和旧 metadata；已装兼容版本按策略复用。
- 固定 MSI 的 ProductCode/UpgradeCode/安装属性在实施时从真实 MSI 提取，不写猜测的代码。
- 返回码策略：0 → 继续健康检查；3010 → 持久记录 reboot_required 并传到最外层；1641 → 记录已启动重启并设计恢复；1618 → 有上限退避等待；1602 → 用户取消；1603 → 保留日志分类诊断，不一律认为需要 UI；其它 → 具名失败。
- 标准模式需交互时给明确提示；silent 模式不得突然弹完整 UI；/norestart 不得被脚本自行覆盖。
- 将 reboot flag 映射到 NSIS 与自动化调用方的稳定退出码；禁止把所有非零都 Abort，也不能误把未知非零当成功。
- MSI 超时不能只终止客户端就宣称安装停止；查询系统安装状态、避免并发 msiexec，不强杀整机 Windows Installer 服务。
- 验证 NapCat MSI 的所有自定义动作/下载依赖；若其本身非离线，必须取得可离线分发且许可证允许的方案，或清楚标注无法满足离线发布条件；不能通过伪造 metadata 放行。
- WebView2 保持 offlineInstaller；覆盖已装、未装、需更新、安装失败和待重启；只有产品确需新 API 才设置经验证的最低版本。
- MSI 和 WebView2 视为独立事务；用户预装组件不能在失败回滚/卸载时被随意删除。QQ 登录态与会话数据始终保留。

验收：各退出码穿过 MSI→Python→NSIS→CI 仍保留语义；无意外重启、无 silent 弹窗、无 metadata 假成功。

### WP10｜P1：事务式安装、升级和崩溃恢复

文件：upgrade.py:transactional_upgrade、UpgradeLock；bootstrap.py；python.rs:project_root/prepare_runtime；installer-hooks.nsh；拟新增安装事务模块/稳定启动入口。

- 程序/runtime staging 放在最终程序卷的受控目录；同卷 rename/replace 做激活。跨卷时复制到目标卷再完整校验，不能假定跨卷原子移动。
- 同一个 operation journal 跟踪 preflight→staged→verified→external_components→healthy→committed；用户配置/数据库不进入程序树备份覆盖。
- 升级旧版先核验占用与可恢复性；仅停止已确认属于本安装的 Stella/Bot/llama 子进程，利用现有停止契约，禁止 taskkill 所有 python/QQ。
- 不在新包通过关键验收前永久卸载旧版。核对 Tauri 默认升级过程是否先调用旧 uninstall；若是，则版本化入口/模板必须重新安排，单加 POSTINSTALL 回滚不足以实现保证。
- 接通启动入口与 active pointer：所选程序、runtime、前端、catalog 必须来自同一版本；把桌面 session secret 等现有行为保留。
- 设置提交点：指针/注册项/快捷方式协调更新；失败时恢复先前可用引用，记录孤立候选树待清理。
- 中断恢复遵循日志与真实文件状态，覆盖复制中、健康检查后、激活前后、注册项更新中、重启中。写入 rename/flush 不宣称对任意断电天然完整，必须故障注入验证。
- 旧程序树保留到新版首启成功并达到明确保留策略；空间不足不能先删唯一可用旧版。回滚不自动降级用户数据库。
- 第三方 MSI 无法整体回滚时记录 partial_external_change/repair_required，保留恢复入口；不谎报“已完全回滚”。

验收：任一失败点旧版仍可启动，或提供准确可恢复的安装状态；旧版、数据、QQ 会话不被误删。

### WP11｜P1：数据目录、profile 切换与卸载契约

文件：config/home.py:resolve/_resolve、部署 init/migrate 调用边界（实施前额外 impact）；build_release_package.py；NSIS uninstall hooks；python.rs。

- OneClick 新装默认用户数据根建议 LOCALAPPDATA/Stella/Data，通过显式安装 metadata/指针接入；保留环境变量、便携目录、旧布局优先规则，不全局改坏 Standalone。
- 不自动移动已有有效数据根。迁移工具必须先证明来源、目标、空闲空间和备份，成功校验后切换指针；源数据延迟保留。
- 安装/修复明确传递原用户 data root，避免管理员账户、当前 cwd 或 stale pointer 改变位置。
- profile 切换沿用当前同一产品身份进行就地切换，先校验新 runtime；Rust→Python 清除本产品旧 Rust 激活状态，避免残留 wheels 被 rust_wheel_present 判成 Rust。不承诺四种 profile 并存。
- online/offline 切换由 metadata 决定，不受旧 offline 目录是否残留影响。
- generated runtime/临时树/缓存不是原始 Tauri resources 清单的一部分；卸载只按受控 ownership manifest 清理，验证路径归属，不递归删除用户目录。
- 默认卸载保留 StellaData、QQ、配置、模型和诊断日志；若提供清除数据选项，单独列出范围且默认不勾选。
- 用户独立安装的 NapCat/WebView2 不随 Stella 卸载；Stella 安装的外部组件也按 ownership/共享策略处理。
- 卸载后重装、安装目录迁移和旧版本升级都验证指针不悬空、数据可发现、旧 ready 标记不误判。

验收：升级/失败/卸载前后用户数据摘要和 QQ session 一致；只有显式迁移/清除操作改变预定范围。

### WP12｜P1：在线获取、缓存与网络恢复

文件：acquire.py:download_verified；bootstrap.py:_download_record；python.rs 网络兼容路径；online runtime 获取入口。

- 下载先复用已验证 cache；写 .part，支持受控 Range/ETag/Last-Modified 验证与断点恢复，服务端不支持时安全重下。
- 将连接/读超时、总期限、有限重试与退避分开。429/5xx/断网可重试；404、永久权限、摘要不匹配给明确处理，不无限换源。
- 镜像来自明确白名单，同一 immutable artifact hash；禁止为提高成功率关闭 TLS 或任意 trusted-host 绕过。
- 尊重合理代理/证书配置；无效代理允许诊断后明确直连重试，不能泄露凭据或无条件清空企业网络策略。
- 输出已下载/总字节和速率；无 Content-Length 时明确未知进度。用户取消能停止本操作并保留可验证续传片段。
- 外网修复是明确模式，不在 strict-offline 中暗中启动。
- 在线版本绑定构建时的 immutable manifest，避免用户安装时重新解析浮动 requirements。

验收：网络中断续装无需重下完整大模型；所有来源都验证相同摘要；离线安装从不走该路径。

### WP13｜P1/P2：可观察性、健康检查与支持入口

文件：helper.py:_run；bootstrap.py:_write_progress；__main__.py；NSIS 详情；GUI 安装状态消费点（实施时 context 定位）；拟新增诊断导出与健康检查脚本。

- 安装第一步即创建原用户可写的 session 日志；不能等 Python/数据根初始化成功后才有日志。
- 结构化 JSONL 事件包括时间、operation_id、build/profile、stage、component、attempt、elapsed、exit code、retryable、reboot、可读摘要。普通 UI 不展示内部实现细节。
- 子进程流式读取，统一可读编码、避免 stdout/stderr 管道死锁；日志保留详细原始输出，UI 显示阶段和最近有意义的进度。
- 设阶段超时、总上限及无进度诊断；NSIS nsExec 的输出超时不等于整个事务总超时。长模型处理有心跳，不能只凭无文本输出杀健康任务。
- 提供“查看日志 / 重试失败步骤 / 选择在线修复 / 导出诊断”操作；重启需要明确提示和恢复方式。
- 健康检查分层：文件与摘要→嵌入式 Python/关键 imports→Rust 扩展→llama-server/本地 embedding 请求→浏览器截图→NapCat 实际安装→桌面配置界面/前端版本。
- 不以远端 LLM API、QQ 登录、用户配置是否完整作为安装失败；明确 installation ready 与 application configured 的边界。
- 日志脱敏环境变量、代理凭据、API 密钥、QQ 数据及用户名路径（导出时可脱敏）；限制单文件/总容量、轮转与保留期限。
- 指标仅从 CI/用户主动提供日志计算；不默认新增遥测。建立阶段失败分类、安装耗时、修复成功率基线，不凭猜测宣称改进百分比。

验收：不靠截图即可定位失败组件/原因；异常和取消均有最终日志；安装器关掉后日志仍可取。

### WP14｜P1：发布一致性、签名与供应链证据

文件：release.yml、build_release_catalog.py；拟新增 release manifest/SHA256SUMS 验证脚本和发布说明。

- 为自有 EXE/安装器签名并时间戳，验证 publisher/chain/文件摘要；第三方签名保留原状，禁止改包后仍沿用旧摘要。
- 密钥在 CI secret/硬件或托管签名服务；日志不输出私钥和令牌。证书方案未就绪是正式发布的外部依赖，不阻碍前置代码测试。
- 最终 release manifest 绑定四 EXE、在线 runtime、catalog、组件、前端版本、lock、SBOM/许可证信息及 build_id。
- 解决在线 catalog 自指尚未发布 asset 的验收问题：将大组件/runtime 作为唯一 build_id 的候选资产先发布到可访问的不可变候选通道，再构建/验证引用这些 URL 的最终安装器；候选通道仅在全部门禁通过后推广。不得在测试时偷偷替换最终包 catalog。
- 若坚持正式 tag URL，必须设计等价的分阶段候选发布/撤回协议，避免“发布前无法下载→不测在线”的循环依赖。
- 默认不覆盖已发布同名二进制；修复发布新版本或显式 build revision。保留应急覆盖时先完成全部新资产校验、明确客户端缓存风险并准备回退，不能声称 GitHub 多资产上传原子化。
- 发布后从真实公开下载地址回读摘要/catalog 依赖，确认无 404、HTML 错误页或旧缓存；支持时间戳签名后的最终大小检查。
- 同一 release 使用 concurrency/互斥，避免两个 workflow 相互 clobber。
- 上传归档、生成 .nsi、工具版本、构建/安装日志、SBOM 和验收报告；诊断文件留存周期显式设置。
- 普通 PR 测试无需签名凭据；正式 release 缺签名或验收结果必须阻断，不使用 continue-on-error 隐藏。

验收：用户下载到的资产就是验收过的字节；catalog 所有依赖在发布可见时存在且摘要一致；候选失败不提升为正式版。

### WP15｜P2：包体、耗时和文档收尾

文件：构建脚本、tauri.conf.json、release_assets 快速开始/Release notes（具体文件已存在，实施时先读再改）。

- 量化 Python/模型/MSI/browser/WebView2 压缩与展开占比，减少源码/桌面工程构建垃圾重复打包；白名单只收运行必需内容。
- 不重复携带预装 runtime 与完整 wheelhouse，除非离线修复有明确需求；模型与浏览器可用内容寻址存储避免无意义复制，不能删掉仍被运行期引用的文件。
- 根据最终 NSIS/签名/发布平台实际限制设置体积守卫；接近上限时明确拆分方案和单文件产品承诺的取舍，不把标准 NSIS 容量上限当作未经验证的固定数。
- 压缩算法/solid compression 以真实安装时间、内存、峰值空间测试决定，不只追求最小 EXE。
- 安装语言、错误文案、进度、帮助链接与支持系统列表统一；补中文/英文 Windows 下编码验证。
- 文档说明 online/offline、已含组件、磁盘/权限、修复、重启、日志位置、卸载数据保留、受支持 OS/架构；解释签名不能保证 SmartScreen 永不提示。
- 清理过期注释和重复初始化逻辑；两份 python.rs 的安装契约必须有一致性测试或共享模块，保留桌面 session secret 等有意差异，不做整个旧壳迁移。

验收：有体积与耗时对比报告，所有用户承诺对应可运行验收用例。

## 7. 实施顺序、依赖与可交付里程碑

工作量 S/M/L 表示相对复杂度，不是工期承诺。每步应形成独立可审阅改动；跨组件切换必须通过兼容开关保持主线可运行。

| 步骤 | 任务 | 依赖 | 工作量 | 退出条件 |
| --- | --- | --- | --- | --- |
| S01 | WP01 契约、版本统一、故障用例 | 无 | M | 现状问题可稳定复现；安装成功定义明确 |
| S02 | WP02 最小最终 EXE smoke 与发布依赖 | S01 | M | 无测试结果不能发布；保留现有失败记录作为基线 |
| S03 | WP03 helper 和 hook 修复 | S01、S02 | M | Rust/profile/离线修复正确，句柄修复 |
| S04 | WP04 状态/异常/锁/续装 | S01、S03 | L | 所有失败注入可恢复，无假 ready |
| S05 | WP09 MSI 重启/取消/忙碌协议 | S04 | M/L | 原生退出码完整传播 |
| S06 | WP05 完整负载清单与 strict offline | S01、S04 | M | 损坏/缺失被准确拦住 |
| S07 | WP06 工具链与依赖锁 | S01 | M | 产物输入稳定，浏览器 revision 一致 |
| S08 | WP07 预装 runtime 构建及搬迁测试 | S06、S07 | L | 两种 profile 的 runtime 可脱离 CI 使用 |
| S09 | WP08 原生预检查/系统依赖 | S02、S06 | M/L | 干净机与路径/权限/空间矩阵通过 |
| S10 | WP11 数据目录兼容、身份与卸载 ownership | S04、S09 | L | 旧数据位置不变、卸载不误删 |
| S11 | WP10 稳定入口+事务激活+旧版本迁移 | S04、S08、S10 | L | 启动实际读取激活记录，旧版失败可恢复 |
| S12 | WP12 在线 runtime/下载恢复 | S06、S07、S08 | M/L | 在线与离线同版本内容一致 |
| S13 | WP13 日志/修复 UI/健康检查完善 | S03–S12 逐步接入 | M | 所有阶段有日志和终态；诊断可导出 |
| S14 | WP14 签名/候选发布/发布后验证 | S02、S06、S07、S12 | M/L | 最终签名字节通过完整门禁 |
| S15 | WP02 完整 VM/故障/升级矩阵、WP15 优化文档 | S09–S14 | L | §13 全部满足，证据归档 |

里程碑 A（先稳定现有实现）：S01–S06，加 S13 的基础日志。它只能称为“当前安装链路加固”，不能提前声称完全事务回滚或安装期零 pip。

里程碑 B（减少安装工作量）：S07–S12。预装 runtime、路径/数据隔离、事务激活和网络恢复形成闭环，才将新模式设默认。

里程碑 C（正式发布质量）：S13–S15。候选→签名→真实安装→发布验证闭环，形成持续可运行的矩阵。

每次提交之前：相关 impact 已做；单元/集成通过；detect-changes --scope all 无 partial/truncated。涉及工具链/产物行为指纹的最终 baseline 在相关步骤收尾一次性更新，不每个中间 commit 重写。

## 8. 测试策略与执行条件

### 8.1 更新已有测试

| 已存在文件 | 要增加/调整的行为断言 |
| --- | --- |
| tests/test_nsis_bootstrap_helper.py | 原始 ._pth、真实 bootstrap 参数、Rust wheel 缺失/多个/损坏、marker 写入时机、子进程错误/取消、manifest 验证 |
| tests/test_bootstrap.py | NapCatError/PackageError/OSError 均写失败；failed/running 重试复用健康组件；损坏组件不跳过；strict offline 替代原自动回退断言；旧 metadata 迁移 |
| tests/test_napcat_package.py | 0/1602/1603/1618/1641/3010；interactive/silent；实际状态检测；超时后不并发重试；原 1603 一律 UI 测试改为策略测试 |
| tests/test_product_profiles.py | 四产物 mode/build/profile 一致；Rust wheel 内容完整；缺 manifest/catalog/front-end 失败；runtime 允许列表边界；输出目录递归剪枝保留 |
| tests/test_upgrade.py | staging/激活前后异常、锁 owner 身份、候选垃圾清理、错误指针、回滚不触及数据；recover_stale 检查后受控存活子进程仍活着，权限不足/PID 重用不抢锁 |
| tests/test_deploy_process.py | 如提取存活原语，保留活进程/死进程/非法 PID/僵尸现有语义；补 Windows 访问拒绝与句柄类型；测试只操作自身创建的子进程 |
| tests/windows/test_upgrade_matrix.py | 将假程序树补充为真实受管进程持有 runtime/DLL 的场景；原测试保留为低成本逻辑回归 |
| tests/test_stella_home.py | OneClick 显式元数据接入；环境变量/便携/旧布局/指针优先顺序不变；提权不换数据根 |
| tests/test_build_llama_package.py | DLL/架构/最小 CPU 约束、metadata、启动检查结果，不把 mock cmake 成功当二进制可执行 |
| desktop/src-tauri/src/python.rs 内测试 | 兼容 marker、新 metadata、状态读取不触发 pip、Rust/profile 检查、共享契约；旧壳覆盖有意差异 |
| tests/conftest.py | 评估新集成测试隔离，避免 autouse 的应用依赖导入和浏览器禁用掩盖产品问题 |

新测试建议路径（拟新增，当前不声称存在）：tests/test_install_state.py、tests/test_offline_payload.py、tests/test_windows_runtime.py、tests/windows/test_nsis_installation.py、tests/windows/test_install_recovery.py；独立 VM harness 和受控 fault injection fixture。故障开关只在测试构建/入口提供，不在正式包暴露可绕过验证的变量。

### 8.2 最终安装矩阵

| 编号 | 输入/环境 → 动作 | 预期 |
| --- | --- | --- |
| T01 | 四种最终 EXE，干净 Windows → 新装/首启 | 组件健康，版本一致；online 包首启也完成 |
| T02 | 两种 offline，断网、无 WebView2/Python/VC runtime → 安装 | 零外网请求、安装成功或明确待重启 |
| T03 | 标准账户、管理员、不同账户提权、silent/interactive | 作用域正确；silent 无意外 UI；用户数据归原用户 |
| T04 | 中文/空格/非 BMP 字符/长路径、非默认盘、目录只读 | 可支持路径成功；不支持的提前解释，命令无拆分 |
| T05 | 安装卷不足、TEMP 不足、data 卷不足、安装中空间耗尽 | 预判或明确失败；无假 ready；可修复 |
| T06 | Python/get-pip/wheel/MSI/model/browser/catalog 任一缺失/损坏 | 在使用前定位文件；offline 不联网；旧版本保持 |
| T07 | 无效代理、TLS/证书错误、429/404/5xx、断网/断点续传 | 分类重试；不关闭校验；取消停止本次操作 |
| T08 | MSI 返回全部目标码、服务忙/禁用、安装被取消 | 状态/退出码/日志/重启信息完整 |
| T09 | 各阶段进程崩溃、强制结束安装器、模拟重启 | 下次复核后续装；无死锁/重复 MSI |
| T10 | installer+installer、installer+GUI、CLI+GUI 修复同时运行；锁 owner 存活/退出/PID 重用/无权查询 | 同一产品/数据根互斥；陈旧锁检测不杀进程，不删除新 owner 锁，unknown 不抢锁 |
| T11 | 上一正式版/关键旧版→候选，同版本重装/失败重试 | 保留配置/数据库/QQ；重复安装幂等 |
| T12 | Python↔Rust、online↔offline | 新 metadata 生效，旧 wheel/marker 不劫持 profile |
| T13 | 旧 Stella/Bot/llama 持有 exe/DLL，另有无关 Python/QQ | 仅处理本产品占用，不杀无关进程 |
| T14 | metadata 说 ready 但文件被删/MSI 被卸载/组件被隔离 | repair_required，按组件修复 |
| T15 | 新 runtime 搬迁后从外部 cwd 运行、无仓库/PYTHONPATH | imports、native、browser、llama 全通过 |
| T16 | 首启配置未填、无 QQ 登录、无 API key | 正常展示配置界面，不误报安装失败 |
| T17 | WebView2 已装/旧版/未装/失败/重启 | 语义正确、离线包无隐式下载 |
| T18 | 卸载默认/明确清数据、卸载后重装 | 默认保留用户和外部共享组件；清理只在授权范围 |
| T19 | 签名后下载、发布 URL/catalog、镜像/缓存 | 签名与摘要正确，所有依赖可获取 |
| T20 | Defender 启用、受支持最低 CPU/OS、不同系统语言 | 实测兼容；不要求关闭保护；记录不支持范围 |
| T21 | 旧/新 schema，损坏/越界 active pointer、数据根迁移 | 安全拒绝或兼容读取，旧数据不被覆盖 |
| T22 | 升级前后字节级数据快照、数据库实际打开检查 | 数据未丢失，回滚不自动降级数据 schema |
| T23 | 最终包体接近限制、超慢磁盘/CPU、无进度长操作 | 大小门禁、合理总期限、可见心跳，无假卡死 |
| T24 | 最终 .nsi 的 hook、WebView2、旧卸载时序 | 预检查和事务承诺与实际顺序一致 |

覆盖策略：每次相关 PR 跑纯逻辑和资源结构；每个候选 release 跑四产物基本矩阵，两种 offline 断网矩阵，以及上一个正式版升级。完整 OS/权限/故障矩阵在发布门禁或周期性专用 VM 运行，阻断正式推广；不要求所有维度做成本不可控的全排列。

### 8.3 命令与前置条件

以下是实施阶段复用的现有入口，不表示本次已运行测试。Windows Python 测试环境必须安装 requirements.txt 和 requirements-dev.txt，因为全局 autouse fixture 会 import 应用；统一设置临时 STELLA_HOME，禁止使用真实用户目录。

- python -m pip install -r requirements.txt -r requirements-dev.txt
- python -m pytest tests/test_nsis_bootstrap_helper.py tests/test_bootstrap.py tests/test_napcat_package.py tests/test_product_profiles.py tests/test_upgrade.py tests/test_deploy_process.py tests/test_stella_home.py tests/test_build_llama_package.py -q
- Windows 专用：python -m pytest tests/windows/test_upgrade_matrix.py -q
- python -m ruff check deploy scripts tests（若有既有无关问题单独记录，不能静默忽略新增问题）
- 在 desktop/src-tauri、完成 dashboard-dist/resources staging 且具备 Windows Rust/MSVC/固定 Tauri CLI 后：cargo test；cargo tauri build --bundles nsis。
- python scripts/build_release_package.py --help；python scripts/build_offline_payload.py --help 用于确认现有 CLI 兼容。
- 提交门禁：node .gitnexus/run.cjs detect-changes --scope all --repo .；本机 runner shim 失败时使用 docker exec -w /repo stella-gitnexus gitnexus detect-changes --scope all --repo Stella_project。
- 新增测试 harness 的命令在实现后填入 CI，当前不伪称已有可运行的一键完整矩阵命令。

### 8.4 数值验收与基线

硬指标：required 用例全过；offline 外网连接次数为 0；必需组件漏包数为 0；出现假 ready/永久 running 为 0；数据保留用例摘要变化为 0；每个失败有唯一 operation_id/组件/错误码/日志；发布文件与被测文件摘要一致。

安装时间、峰值内存/磁盘、修复耗时先记录基线，再设置按机型分层的回归预算。建议首次使用“相对基线超过 20% 需解释”的候选告警阈值，它是待校准的设计值，不是已测结果；不能把低端机器统一硬超时为高配 runner 的耗时。

## 9. 风险、兼容与回滚边界

| 风险 | 级别/来源 | 控制措施 |
| --- | --- | --- |
| prepare_runtime 广泛调用 | CRITICAL，[graph] | 先契约后适配，保持包装函数签名与错误格式；覆盖所有 §4 入口 |
| NSIS 默认升级先移除旧版 | 高，[assumed] 待固定模板验证 | S11 前核对真实 .nsi；版本树/稳定入口设计未完成不声称完整回滚 |
| 跨进程事务/外部 MSI 不可原子撤销 | 高，设计边界 | 独立 journal，明确 partial state，保留共享组件，不做假回滚 |
| 数据根规则变化 | 高，[verified] 共享 config.home | OneClick 显式元数据接入，不全局替换旧 fallback；迁移独立可恢复 |
| root/current user/提权身份不同 | 高，Windows 真实环境 | 明确 SID、ACL、作用域；不执行任意用户可改脚本为 SYSTEM |
| 不可信 pointer/归档路径 | 高，安装边界 | containment、摘要、schema、reparse/链接检查；所有清理仅限 ownership |
| runtime 搬迁和动态 DLL | 高，[inferred] | 目标系统实际 import/启动；不复制普通 venv |
| 数据库 schema 与程序回滚不兼容 | 高，未做全局 schema 审计 | 禁止安装阶段不可逆数据迁移；后续迁移另备份/版本检查 |
| Windows 锁探测误终止进程 | 高，源码+官方语义；当前调用可达性未证明 | S04 先修复再复用；存活/退出/权限未知三态，不盲目复用 PID |
| graph 低风险漏掉 shell/动态调用 | 中，分析器限制 | 保留源码/产物/跨进程矩阵证据，不以 0 caller 放行 |
| 下载与缓存版本漂移 | 中，[verified] 范围依赖/覆盖发布 | lock + immutable assets + 完整摘要 |
| 真实 VM、签名证书不可用 | 外部依赖 | 提前建 S02 基础设施；无证据就保留候选，不伪装验收通过 |
| 预装 runtime 增加包体/磁盘 | 中，待测 | 体积门禁、分 profile、去重、保留策略，不先删旧版省空间 |
| 状态格式新旧混用 | 中 | schema version、旧 marker 复核迁移、新 CLI 可选字段、同一 contract |

§4 的所有 d=1 消费者均保持兼容或同批更新：helper main、release script main、_cmd_bootstrap、prepare_runtime 包装函数、acquire.install_napcat。对新增 secondary edits（home、upgrade、process、GUI 命令、下载等）逐符号做 impact，再决定对应回归，不能沿用上述五个结果当作整库通行证。

回滚策略按层执行：构建开关回旧稳定 runtime/安装流程；候选不推广；正式修复发新 build/version；安装事务恢复旧程序引用；用户数据与第三方组件不做无条件逆操作。发现数据风险立即停止推广并保留日志和旧版，不能通过手工删目录“修好”。

## 10. 预计改动文件

以下路径是预期实施范围；“拟新增”尚不存在。仅写此计划不触发任何实现修改。

| 文件/范围 | 当前符号/入口 | 改动职责 |
| --- | --- | --- |
| .github/workflows/release.yml | build-dashboard/build-offline-payload/build-installer/build | 版本、锁定、runtime、签名、验收、发布顺序 |
| .github/workflows/ci.yml | test/现有 Windows 相关入口 | 快速回归与专用安装测试分层 |
| desktop/src-tauri/tauri.conf.json | bundle.windows/nsis | 安装模式、WebView2、模板/签名接入 |
| desktop/src-tauri/installer-hooks.nsh | NSIS_HOOK_POSTINSTALL；拟新增必要 pre/uninstall hooks | 预检查、执行体、退出码、日志、受控卸载 |
| deploy/nsis_bootstrap_helper.py | bootstrap_offline/_run/patch_pth/write_deps_marker/main | 兼容桥、验证、Rust/profile 完整性 |
| deploy/bootstrap.py | install_profile/_installed_record_matches/_download_record/_write_progress | 状态、续装、离线策略 |
| deploy/__main__.py | _cmd_bootstrap/_cmd_upgrade | JSON/退出码/修复接口兼容 |
| deploy/napcat.py | install_msi | MSI 检测、退出码、日志、重启 |
| deploy/acquire.py | download_verified/install_napcat/verify_local_artifact | 下载、缓存、状态传递 |
| deploy/upgrade.py | transactional_upgrade/UpgradeLock/read_active | 程序版本树、Windows 安全锁探测、激活/恢复 |
| deploy/process.py（仅必要时提取共享原语） | is_alive/_windows_is_alive | 轻量且无终止副作用的进程检测；先做额外 impact，不顺便重构进程管理 |
| config/home.py | resolve/_resolve | OneClick 身份与数据根显式接入 |
| desktop/src-tauri/src/python.rs | runtime_bootstrap.prepare_runtime、ensure_*、project_root | 新 runtime 消费、健康判据、兼容 |
| stella-installer/src-tauri/src/python.rs | 对应兼容路径 | 共享契约或一致性测试；不覆盖有意差异 |
| scripts/build_offline_payload.py | parse_runtime_constants/build_wheels/fetch_catalog_packages/install_browsers/write_manifest | 锁定、成品 runtime、完整负载 |
| scripts/build_release_package.py | stage_installer_resources/build_oneclick | 产物结构校验与 metadata |
| scripts/build_release_catalog.py | build_catalog | immutable 来源/build identity |
| scripts/build_llama_package.py、scripts/verify_llama_package.py | build/verify | native 依赖与运行验证 |
| memory_rust/native/pyproject.toml | maturin 配置 | 锁定构建/确认 wheel 内容；仅必要时改 |
| requirements.txt、拟新增发布 lock/工具版本文件 | 发布依赖定义 | 不漂移且可升级 |
| 拟新增 deploy/install_state.py、安装 schema、runtime 构建/自检脚本、Windows harness | 新接口 | 状态契约、预组装与验收 |
| 拟新增/更新稳定启动入口及其 build 配置 | 选定设计后落点 | 真实接通 active pointer，不预先假称已存在 |
| §8 所列测试 | 现有与新场景 | 行为回归、真实 Windows 安装 |
| release_assets 快速开始/RELEASE_NOTES_TEMPLATE.md | 用户文档 | 兼容范围、修复、数据/重启承诺 |

实施者先从 S01 开始；禁止把整张文件表作为“一次性重写所有文件”的要求。

## 11. 可复用实施上下文

下方 JSON 是交接契约；evidence_provenance 由技能提供的原始 helper 生成，未自行计算或改写字段。初次执行按其 snapshot 检查源代码是否漂移；如果变了只重读变更的引用范围，不重新扫描整个仓库。

```json
{
  "implementation_context": {
    "task_summary": "提高 Stella 四种 Windows amd64 OneClick NSIS 安装器的构建/安装/首启/修复/升级/卸载可靠性。仅计划；按正文 S01–S15 实施，不一次性重写。",
    "acceptance_criteria": [
      "四种最终签名 EXE 通过真实安装门禁；offline 两种断网完成本地健康检查",
      "正常新安装消费 CI 预装 runtime，不在用户机器解析 pip/编译 wheels",
      "异常/取消/待重启语义完整；失败复核续装；跨进程锁与 Windows 存活检测无误杀",
      "启动端实际消费版本激活记录；升级失败保留旧版/明确恢复入口；不误删用户数据",
      "完整 manifest/依赖锁/immutable 发布资产；发布字节与验收字节一致",
      "兼容既有 CLI、Standalone、旧桌面壳；完成正文 §13 DoD"
    ],
    "evidence_provenance": {
      "schema_version": 2,
      "head_commit": "3f5a69b087c39052d256dfafe95d6f66642a5f41",
      "generated_plan_path": "docs/plans/2026-09-28-gitnexus-plan-nsis-installation-reliability.md",
      "global_dirty_digest": {
        "algorithm": "sha256",
        "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
        "value": "ddae2d79e44267d6fd40de31c3f37d8d0f10af2a37e7e7e7753d1c4300704ecf"
      },
      "cited_path_manifest": [
        {
          "path": ".github/workflows/ci.yml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:bd4bc7fccb641a01d37fecc43014a27a0e01fbee36f8b892b39721e207af1419",
          "index_digest": "sha256:bd4bc7fccb641a01d37fecc43014a27a0e01fbee36f8b892b39721e207af1419",
          "worktree_digest": "sha256:34d982e2622d379623fa8dcb96e87e6b2b352afadb1ae1be27de86e1ef7ec957",
          "untracked_digest": "absent"
        },
        {
          "path": ".github/workflows/release.yml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b5ebda1fd5bba1f2361dcd245d9049e5a81edc6b627e26f48241c7fad12a3930",
          "index_digest": "sha256:b5ebda1fd5bba1f2361dcd245d9049e5a81edc6b627e26f48241c7fad12a3930",
          "worktree_digest": "sha256:efb44f0d2a5d2db8d503d0b1c2de00d410625c5645e0a369af342e2520ea9c43",
          "untracked_digest": "absent"
        },
        {
          "path": "AGENTS.md",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:d2a89022b9fa5087cad8d80549aade7104a50ee4768db4979c243ab6b16f4db2",
          "index_digest": "sha256:d2a89022b9fa5087cad8d80549aade7104a50ee4768db4979c243ab6b16f4db2",
          "worktree_digest": "sha256:d2a89022b9fa5087cad8d80549aade7104a50ee4768db4979c243ab6b16f4db2",
          "untracked_digest": "absent"
        },
        {
          "path": "config/home.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:1ee5d75e8df01f9e3abfd5bbf59e5e2a79ef3dc7e805e8d4652fb7140042f175",
          "index_digest": "sha256:1ee5d75e8df01f9e3abfd5bbf59e5e2a79ef3dc7e805e8d4652fb7140042f175",
          "worktree_digest": "sha256:1ee5d75e8df01f9e3abfd5bbf59e5e2a79ef3dc7e805e8d4652fb7140042f175",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/__main__.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:9211b4a33201c880785b354162e8ae2b7fccafb6fefd0e55d1802c38bef342a2",
          "index_digest": "sha256:9211b4a33201c880785b354162e8ae2b7fccafb6fefd0e55d1802c38bef342a2",
          "worktree_digest": "sha256:217409ed43004f98a559daa0af2de8be69f74859cb8183c618a9ac4e661aed4e",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/acquire.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:9fc2620eceb1c0368c0279fb01524dff00f182ebdc325365b177caa8b8252826",
          "index_digest": "sha256:9fc2620eceb1c0368c0279fb01524dff00f182ebdc325365b177caa8b8252826",
          "worktree_digest": "sha256:9fc2620eceb1c0368c0279fb01524dff00f182ebdc325365b177caa8b8252826",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/bootstrap.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:7909f4cc09eb014d174f546b41d96a81830af7a784630d0866375fc8b0dd0f45",
          "index_digest": "sha256:7909f4cc09eb014d174f546b41d96a81830af7a784630d0866375fc8b0dd0f45",
          "worktree_digest": "sha256:7909f4cc09eb014d174f546b41d96a81830af7a784630d0866375fc8b0dd0f45",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/napcat.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:1096b49d22c79f584dc7615dd818c4989a67fd86b7c40910766d3f96215f83e4",
          "index_digest": "sha256:1096b49d22c79f584dc7615dd818c4989a67fd86b7c40910766d3f96215f83e4",
          "worktree_digest": "sha256:1096b49d22c79f584dc7615dd818c4989a67fd86b7c40910766d3f96215f83e4",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/nsis_bootstrap_helper.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a088b86d56a7d0caa50fd0c3bd31ecfb8af12f5967a31ecff8422ddc189dcfc9",
          "index_digest": "sha256:a088b86d56a7d0caa50fd0c3bd31ecfb8af12f5967a31ecff8422ddc189dcfc9",
          "worktree_digest": "sha256:5e1ed616d4d9ddf40b3692449b50eeec362285f0f2c30a9ba9b9d39b453e5376",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/process.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:f0a63831ec54323d1fc992dc6057ec8cf02caa0dacf1b6e002b0aa0ba903389d",
          "index_digest": "sha256:f0a63831ec54323d1fc992dc6057ec8cf02caa0dacf1b6e002b0aa0ba903389d",
          "worktree_digest": "sha256:5c450fd0450449dd5a579e5ccf0f062271ae614daf8b2998574b77ca5236c220",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/profiles.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c196a3919e80bdb6f61a5694d40c595a9afa964e3850a9de73d7789de73650da",
          "index_digest": "sha256:c196a3919e80bdb6f61a5694d40c595a9afa964e3850a9de73d7789de73650da",
          "worktree_digest": "sha256:c196a3919e80bdb6f61a5694d40c595a9afa964e3850a9de73d7789de73650da",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/upgrade.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:0d9d931ce1e8841bb46fbab03992ab9aa81cb66602ffc175560af0fba3c63381",
          "index_digest": "sha256:0d9d931ce1e8841bb46fbab03992ab9aa81cb66602ffc175560af0fba3c63381",
          "worktree_digest": "sha256:0d9d931ce1e8841bb46fbab03992ab9aa81cb66602ffc175560af0fba3c63381",
          "untracked_digest": "absent"
        },
        {
          "path": "desktop/src-tauri/installer-hooks.nsh",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:0bec3db85b542079fbefebb83ebfe9b9177cff62114a4beb733fc52ab080d2c6",
          "index_digest": "sha256:0bec3db85b542079fbefebb83ebfe9b9177cff62114a4beb733fc52ab080d2c6",
          "worktree_digest": "sha256:0bec3db85b542079fbefebb83ebfe9b9177cff62114a4beb733fc52ab080d2c6",
          "untracked_digest": "absent"
        },
        {
          "path": "desktop/src-tauri/src/python.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:0a5fe3c72acdd8fdf6c8be2d7acbb47b52f867e62b0b5febc6fcdcc3d8960fd5",
          "index_digest": "sha256:0a5fe3c72acdd8fdf6c8be2d7acbb47b52f867e62b0b5febc6fcdcc3d8960fd5",
          "worktree_digest": "sha256:82775283cf2b7921051b5419675ed0bf7657c450839ed932fd5cf25eb7783846",
          "untracked_digest": "absent"
        },
        {
          "path": "desktop/src-tauri/tauri.conf.json",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:dc0d2b37e393b0b496c8845d4eef20cbe49b18c9e84ea3528dc5362639297be3",
          "index_digest": "sha256:dc0d2b37e393b0b496c8845d4eef20cbe49b18c9e84ea3528dc5362639297be3",
          "worktree_digest": "sha256:47ee6bf06ffc81cb2ca603f0e3ed0440323c783420d4837ff78e8ba83f18471a",
          "untracked_digest": "absent"
        },
        {
          "path": "memory_rust/native/pyproject.toml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a7bd8449c7c6c97472bb6cbf871299ae8d5743e69a8fbd2563a141d9bf4df9c6",
          "index_digest": "sha256:a7bd8449c7c6c97472bb6cbf871299ae8d5743e69a8fbd2563a141d9bf4df9c6",
          "worktree_digest": "sha256:a7bd8449c7c6c97472bb6cbf871299ae8d5743e69a8fbd2563a141d9bf4df9c6",
          "untracked_digest": "absent"
        },
        {
          "path": "pyproject.toml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:ff81c6a9b85768d6a729701562eb38bf12a8cae24d355c4a7ee86f9b84887655",
          "index_digest": "sha256:ff81c6a9b85768d6a729701562eb38bf12a8cae24d355c4a7ee86f9b84887655",
          "worktree_digest": "sha256:352e4951a876897d481af7b84c5cc244dea0f03673dbabab0bfb88e1e2cf500f",
          "untracked_digest": "absent"
        },
        {
          "path": "requirements-dev.txt",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:9e84af5f5e54f236fea657ab951f6e8dd513881a138f636936026c105878b298",
          "index_digest": "sha256:9e84af5f5e54f236fea657ab951f6e8dd513881a138f636936026c105878b298",
          "worktree_digest": "sha256:10f621cf66c00bfef5978463dd9648e54b72d2cbe8eeabe701cd2e77899e74cb",
          "untracked_digest": "absent"
        },
        {
          "path": "requirements.txt",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:cc6049bd2dea944fa9697fa4a70d35b8b0994696d124584ad266530502b216ed",
          "index_digest": "sha256:cc6049bd2dea944fa9697fa4a70d35b8b0994696d124584ad266530502b216ed",
          "worktree_digest": "sha256:702da877e41c8a8d5d681c4e46a22bddae0d5d13984a55a61ece1711ebe55363",
          "untracked_digest": "absent"
        },
        {
          "path": "scripts/build_llama_package.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:18de2ad98f0b3ece9a4a261f73cc5c45fb07717148a088874c11777abd384988",
          "index_digest": "sha256:18de2ad98f0b3ece9a4a261f73cc5c45fb07717148a088874c11777abd384988",
          "worktree_digest": "sha256:18de2ad98f0b3ece9a4a261f73cc5c45fb07717148a088874c11777abd384988",
          "untracked_digest": "absent"
        },
        {
          "path": "scripts/build_offline_payload.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e82be87f37027c29b72b773ce62337d87c6f7d35ca5c409700b321d4c9a29eb4",
          "index_digest": "sha256:e82be87f37027c29b72b773ce62337d87c6f7d35ca5c409700b321d4c9a29eb4",
          "worktree_digest": "sha256:6b80ba164964e931f9db621f948af35c69ad12aebfd53da51c2982a753bef324",
          "untracked_digest": "absent"
        },
        {
          "path": "scripts/build_release_catalog.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:8d16d070c75d38f0baa19c0995d5aa65c37f8d3319dc0eb8063c10519575270f",
          "index_digest": "sha256:8d16d070c75d38f0baa19c0995d5aa65c37f8d3319dc0eb8063c10519575270f",
          "worktree_digest": "sha256:8d16d070c75d38f0baa19c0995d5aa65c37f8d3319dc0eb8063c10519575270f",
          "untracked_digest": "absent"
        },
        {
          "path": "scripts/build_release_package.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b4f43c1c96a00c00ddbe0222c647cc1ea29a0a31410114ceca9c24006acedf6c",
          "index_digest": "sha256:b4f43c1c96a00c00ddbe0222c647cc1ea29a0a31410114ceca9c24006acedf6c",
          "worktree_digest": "sha256:5a79e281f389c69a3060de32009a3a5651bb4cdea09e57c199607aa0934f3c2f",
          "untracked_digest": "absent"
        },
        {
          "path": "scripts/verify_llama_package.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4ae8290c4150548d3f3633679332bdbd452c0fd2ac332171ef6d3f2b11b1e5db",
          "index_digest": "sha256:4ae8290c4150548d3f3633679332bdbd452c0fd2ac332171ef6d3f2b11b1e5db",
          "worktree_digest": "sha256:4ae8290c4150548d3f3633679332bdbd452c0fd2ac332171ef6d3f2b11b1e5db",
          "untracked_digest": "absent"
        },
        {
          "path": "stella-installer/src-tauri/src/python.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:90e12f682cfef20fcb1ec1be2b3091aa484440aa6bae207390cdc16490a85d4b",
          "index_digest": "sha256:90e12f682cfef20fcb1ec1be2b3091aa484440aa6bae207390cdc16490a85d4b",
          "worktree_digest": "sha256:90e12f682cfef20fcb1ec1be2b3091aa484440aa6bae207390cdc16490a85d4b",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/conftest.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a750590c032930cc8cb709f14ae52d2d387ef834a3af6d6be77b307bd8bdd32d",
          "index_digest": "sha256:a750590c032930cc8cb709f14ae52d2d387ef834a3af6d6be77b307bd8bdd32d",
          "worktree_digest": "sha256:a750590c032930cc8cb709f14ae52d2d387ef834a3af6d6be77b307bd8bdd32d",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_bootstrap.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b2e1dffa5c8f00b60abb9e61e816638e63f9c7c486fd9ee7de3f95d59a837a9e",
          "index_digest": "sha256:b2e1dffa5c8f00b60abb9e61e816638e63f9c7c486fd9ee7de3f95d59a837a9e",
          "worktree_digest": "sha256:b2e1dffa5c8f00b60abb9e61e816638e63f9c7c486fd9ee7de3f95d59a837a9e",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_build_llama_package.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4d3319fce55de377fcc7e5bb36c26d5b50386278f7d79647a8c9d16cbfd31fa6",
          "index_digest": "sha256:4d3319fce55de377fcc7e5bb36c26d5b50386278f7d79647a8c9d16cbfd31fa6",
          "worktree_digest": "sha256:4d3319fce55de377fcc7e5bb36c26d5b50386278f7d79647a8c9d16cbfd31fa6",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_deploy_process.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:214e18bfaac967f64ce8b54a2c3e0ba749130e626cd66f863e39754004866eeb",
          "index_digest": "sha256:214e18bfaac967f64ce8b54a2c3e0ba749130e626cd66f863e39754004866eeb",
          "worktree_digest": "sha256:985e222f9504e2ecfcce8ee96a180302134414b4eb7589e2546df286aad53c61",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_napcat_package.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:32650043051544222befd459261b775a21e93e3b4b1ec060f5ffc2570ab45ab1",
          "index_digest": "sha256:32650043051544222befd459261b775a21e93e3b4b1ec060f5ffc2570ab45ab1",
          "worktree_digest": "sha256:32650043051544222befd459261b775a21e93e3b4b1ec060f5ffc2570ab45ab1",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_nsis_bootstrap_helper.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:d6e0e4f52fd757d00360c77af786d886aca0fc2891d48e7b7225bdd84f5e0e1a",
          "index_digest": "sha256:d6e0e4f52fd757d00360c77af786d886aca0fc2891d48e7b7225bdd84f5e0e1a",
          "worktree_digest": "sha256:d6e0e4f52fd757d00360c77af786d886aca0fc2891d48e7b7225bdd84f5e0e1a",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_product_profiles.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:1c735131de6b5c196f5055c09fccddab0f50cdd168311dbb1092c774daf3ed4c",
          "index_digest": "sha256:1c735131de6b5c196f5055c09fccddab0f50cdd168311dbb1092c774daf3ed4c",
          "worktree_digest": "sha256:1eb8a1851dee3e306dddf2780961c86f9c5bb94eeb352794f2ccf6e2bd848d36",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_stella_home.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:d51fb0478b9eaa4cd89edd06b11e6a78b101bd3f033f74c9b9707fdca9de5b3b",
          "index_digest": "sha256:d51fb0478b9eaa4cd89edd06b11e6a78b101bd3f033f74c9b9707fdca9de5b3b",
          "worktree_digest": "sha256:2af36db8458cc573b581d8d121dec26eec1e692131a9a7a55763508fb6d9eb03",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_upgrade.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:eb2b6e8a0c9d8787ee7df1a01cf963596ca81c642f73bac1becdf3f7ab971799",
          "index_digest": "sha256:eb2b6e8a0c9d8787ee7df1a01cf963596ca81c642f73bac1becdf3f7ab971799",
          "worktree_digest": "sha256:eb2b6e8a0c9d8787ee7df1a01cf963596ca81c642f73bac1becdf3f7ab971799",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/windows/test_upgrade_matrix.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:2e7c5c90cd81e19bd1f547f4d130faed95a2b3f73b723e58c15acd6fc36764ba",
          "index_digest": "sha256:2e7c5c90cd81e19bd1f547f4d130faed95a2b3f73b723e58c15acd6fc36764ba",
          "worktree_digest": "sha256:2e7c5c90cd81e19bd1f547f4d130faed95a2b3f73b723e58c15acd6fc36764ba",
          "untracked_digest": "absent"
        }
      ]
    },
    "index_provenance": {
      "repository": "Stella_project",
      "head": "3f5a69b087c39052d256dfafe95d6f66642a5f41",
      "refresh": "analyze --index-only --pdg",
      "runner": "Docker stella-gitnexus; GitNexus 1.6.11; Node 22.23.2; /usr/local/bin/node",
      "analyzer_artifact_sha256": "c7d271007a9858c4a966a249474aa193a055ec35a7126dc91eea5c806f414f19",
      "analyzer_build_digest": "9faaea7491d7a9f1955c300305fb7a21a14f44196981c249bf1c9a905083c4bc",
      "freshness": "HEAD matched after refresh; 765 indexed files",
      "limitations": [
        "callable candidate cap",
        "cross-language unresolved fields/calls",
        "flow entry/depth/callee/walk enumeration caps",
        "NSIS/Python/Rust subprocess edges source-verified, not exhaustive graph"
      ]
    },
    "primary_symbols": [
      {
        "name": "bootstrap_offline",
        "file": "deploy/nsis_bootstrap_helper.py",
        "role": "离线兼容桥",
        "risk": "LOW",
        "direct_dependents": [
          "deploy/nsis_bootstrap_helper.py:main"
        ],
        "source_verified": true
      },
      {
        "name": "stage_installer_resources",
        "file": "scripts/build_release_package.py",
        "role": "安装资源白名单和结构",
        "risk": "LOW",
        "direct_dependents": [
          "scripts/build_release_package.py:main"
        ],
        "source_verified": true
      },
      {
        "name": "install_profile",
        "file": "deploy/bootstrap.py",
        "role": "组件安装状态与异常",
        "risk": "LOW",
        "direct_dependents": [
          "deploy/__main__.py:_cmd_bootstrap"
        ],
        "source_verified": true
      },
      {
        "name": "runtime_bootstrap.prepare_runtime",
        "file": "desktop/src-tauri/src/python.rs",
        "role": "GUI 运行时准备",
        "risk": "CRITICAL",
        "direct_dependents": [
          "desktop/src-tauri/src/python.rs:prepare_runtime"
        ],
        "related_entrypoints": [
          "wait_bot_ready",
          "get_status",
          "run_doctor",
          "start_bot",
          "get_config",
          "get_personas",
          "lib.rs:run"
        ],
        "source_verified": true
      },
      {
        "name": "install_msi",
        "file": "deploy/napcat.py",
        "role": "NapCat 安装/重启语义",
        "risk": "LOW",
        "direct_dependents": [
          "deploy/acquire.py:install_napcat"
        ],
        "source_verified": true
      }
    ],
    "related_symbols": [
      {
        "name": "transactional_upgrade",
        "file": "deploy/upgrade.py",
        "note": "已有 staged/check/postflight/active record；尚不等于桌面 NSIS 事务"
      },
      {
        "name": "UpgradeLock.recover_stale",
        "file": "deploy/upgrade.py",
        "line": 72,
        "note": "UNKNOWN impact，文本仅定位定义；Windows os.kill(pid,0) 潜在终止目标，复用前必须修"
      },
      {
        "name": "is_alive",
        "file": "deploy/process.py",
        "line": 113,
        "note": "已有 Windows 分流；轻量原语提取先做额外 impact；未知状态不能视为退出"
      },
      {
        "name": "_windows_is_alive",
        "file": "deploy/process.py",
        "line": 155,
        "note": "OpenProcess/GetExitCodeProcess；当前失败返回 False，不能直接用于抢陈旧锁"
      },
      {
        "name": "_installed_record_matches",
        "file": "deploy/bootstrap.py",
        "note": "复核组件实际状态"
      },
      {
        "name": "_download_record",
        "file": "deploy/bootstrap.py",
        "note": "旧离线自动回退需显式 strict offline"
      },
      {
        "name": "_write_progress",
        "file": "deploy/bootstrap.py",
        "note": "原子状态写入扩展"
      },
      {
        "name": "download_verified",
        "file": "deploy/acquire.py",
        "note": "复用摘要校验和临时文件模式"
      },
      {
        "name": "install_napcat",
        "file": "deploy/acquire.py",
        "note": "传播 MSI 结果"
      },
      {
        "name": "_cmd_bootstrap",
        "file": "deploy/__main__.py",
        "note": "CLI JSON/退出码兼容"
      },
      {
        "name": "write_manifest",
        "file": "scripts/build_offline_payload.py",
        "note": "完整内容清单"
      },
      {
        "name": "fetch_catalog_packages",
        "file": "scripts/build_offline_payload.py",
        "note": "已存在缓存仍应校验"
      },
      {
        "name": "build_wheels",
        "file": "scripts/build_offline_payload.py",
        "note": "锁定 wheelhouse"
      },
      {
        "name": "install_browsers",
        "file": "scripts/build_offline_payload.py",
        "note": "与最终 Playwright revision 一致"
      },
      {
        "name": "write_deps_marker",
        "file": "deploy/nsis_bootstrap_helper.py",
        "note": "依赖阶段 ready 不等于整体 ready"
      },
      {
        "name": "patch_pth",
        "file": "deploy/nsis_bootstrap_helper.py",
        "note": "先于 pip/module 加载"
      },
      {
        "name": "project_root",
        "file": "desktop/src-tauri/src/python.rs",
        "note": "当前固定 resources 定位，须接激活记录"
      },
      {
        "name": "resolve/_resolve",
        "file": "config/home.py",
        "note": "保留旧 fallback/便携优先规则"
      },
      {
        "name": "build_catalog",
        "file": "scripts/build_release_catalog.py",
        "note": "绑定 immutable assets"
      },
      {
        "name": "verify",
        "file": "scripts/verify_llama_package.py",
        "note": "现静态校验不能替代干净机启动"
      }
    ],
    "execution_path": [
      "release.yml: Dashboard/native/catalog/offline payload",
      "build_release_package.stage_installer_resources → Tauri NSIS EXE",
      "offline: POSTINSTALL → Python 解压 → nsis_bootstrap_helper.main → bootstrap_offline",
      "helper: patch_pth → get-pip → requirements → deps marker → deploy bootstrap install",
      "online/GUI: prepare_runtime 包装 → runtime_bootstrap.prepare_runtime → ensure_* / deploy",
      "deploy.__main__._cmd_bootstrap → install_profile → acquire.install_napcat → napcat.install_msi",
      "release job uploads published assets without current final EXE install gate",
      "目标: CI runtime → verified staging → external components → health → activation → shared GUI/CLI readiness"
    ],
    "pdg_constraints": [
      {
        "target": "install_profile",
        "anchor_line": 538,
        "query": "impact --mode pdg --direction upstream --depth 2 --limit 12",
        "epistemic": "pdg-intra-procedural",
        "risk": "UNKNOWN",
        "truncated": true,
        "reason": "depth and limit",
        "source_constraint": "previous complete 分支才筛 pending；组件成功后 completed；except 仅 BootstrapError；PDG 为有界辅助切片"
      },
      {
        "target": "install_msi",
        "anchor_line": 255,
        "query": "impact --mode pdg --direction upstream --depth 2 --limit 12",
        "epistemic": "pdg-intra-procedural",
        "risk": "UNKNOWN",
        "truncated": true,
        "reason": "depth",
        "source_constraint": "0/1641/3010 都进入 metadata；1603 再次启动 UI；返回语义以源码为准"
      },
      {
        "target": "bootstrap_offline",
        "anchor_line": 99,
        "epistemic": "pdg-no-block-at-line",
        "risk": "UNKNOWN",
        "truncated": false,
        "reason": "101 为注释锚点，改到 AST 可执行 marker 调用99仍无 block",
        "source_constraint": "没有图边不表示无影响；通过源码确认 patch→pip→marker→profile/bootstrap 顺序"
      },
      {
        "note": "interprocedural bridge 是 callgraph 投影，不是精确语句依赖；以上不作为 clean change gate；实施前仍重新 impact，提交 detect-changes 必须完整"
      }
    ],
    "architectural_patterns": [
      {
        "pattern": "资源白名单",
        "example_location": "scripts/build_release_package.py:stage_installer_resources",
        "usage_guidance": "新增 runtime 显式放行，保留敏感/开发目录排除"
      },
      {
        "pattern": "校验下载与临时文件",
        "example_location": "deploy/acquire.py:download_verified",
        "usage_guidance": "在原边界扩展恢复/缓存，不绕过摘要/TLS"
      },
      {
        "pattern": "原子 JSON 与组件 staging",
        "example_location": "deploy/bootstrap.py",
        "usage_guidance": "扩展有版本账本/终态/复核"
      },
      {
        "pattern": "版本树与 activation record",
        "example_location": "deploy/upgrade.py:transactional_upgrade",
        "usage_guidance": "接通 desktop 真正消费后才承诺回滚；外部 MSI 独立"
      },
      {
        "pattern": "Windows 专用进程检测",
        "example_location": "deploy/process.py:is_alive",
        "usage_guidance": "复用设计而非照搬权限失败=死亡；独立轻量三态与 PID 创建身份"
      },
      {
        "pattern": "数据根兼容解析",
        "example_location": "config/home.py",
        "usage_guidance": "OneClick 显式传递身份，不全局替换旧规则"
      }
    ],
    "files_to_modify": [
      {
        "file": ".github/workflows/release.yml",
        "changes": "四产物版本统一、锁定、runtime、签名/安装 gate、候选发布"
      },
      {
        "file": ".github/workflows/ci.yml",
        "changes": "快速测试和 VM 验收分层"
      },
      {
        "file": "desktop/src-tauri/installer-hooks.nsh",
        "changes": "预检查、正确句柄/退出码/日志、受控卸载"
      },
      {
        "file": "desktop/src-tauri/tauri.conf.json",
        "changes": "固定模板/WebView2/模式/签名"
      },
      {
        "file": "deploy/nsis_bootstrap_helper.py",
        "changes": "桥接 Rust/profile、manifest、阶段标记"
      },
      {
        "file": "deploy/bootstrap.py",
        "changes": "状态/异常/复核/strict offline"
      },
      {
        "file": "deploy/napcat.py",
        "changes": "MSI 检测、return codes、reboot"
      },
      {
        "file": "deploy/acquire.py",
        "changes": "下载恢复/缓存/结果传递"
      },
      {
        "file": "deploy/upgrade.py",
        "changes": "锁安全、事务激活、恢复"
      },
      {
        "file": "deploy/process.py",
        "changes": "仅必要时提取安全轻量原语，先额外 impact"
      },
      {
        "file": "deploy/__main__.py",
        "changes": "安装结果 CLI JSON/退出码"
      },
      {
        "file": "config/home.py",
        "changes": "OneClick metadata/原用户身份"
      },
      {
        "file": "desktop/src-tauri/src/python.rs",
        "changes": "runtime 消费与激活、健康读取、兼容旧包"
      },
      {
        "file": "stella-installer/src-tauri/src/python.rs",
        "changes": "共享契约或一致性测试，保留差异"
      },
      {
        "file": "scripts/build_offline_payload.py",
        "changes": "完整清单、锁定、缓存、runtime"
      },
      {
        "file": "scripts/build_release_package.py",
        "changes": "staging 结构/metadata"
      },
      {
        "file": "scripts/build_release_catalog.py",
        "changes": "immutable assets"
      },
      {
        "file": "scripts/build_llama_package.py",
        "changes": "native 依赖和运行验收"
      },
      {
        "file": "scripts/verify_llama_package.py",
        "changes": "实际执行检查"
      },
      {
        "file": "memory_rust/native/pyproject.toml",
        "changes": "必要时固定构建输入/完整 wheel"
      },
      {
        "file": "requirements.txt",
        "changes": "保留开发约束；拟新增发布 lock 和 tools 版本文件"
      },
      {
        "file": "deploy/install_state.py",
        "status": "proposed new",
        "changes": "共享安装账本/契约"
      },
      {
        "file": "scripts/build_windows_runtime.py",
        "status": "proposed new",
        "changes": "预组装"
      },
      {
        "file": "scripts/check_windows_runtime.py",
        "status": "proposed new",
        "changes": "搬迁和健康"
      },
      {
        "file": "scripts/test_nsis_install.ps1",
        "status": "proposed new",
        "changes": "最终 EXE harness"
      },
      {
        "file": "stable launcher/schema/docs",
        "status": "design location to decide",
        "changes": "§7 S11 和 WP15；不假称现有实现"
      }
    ],
    "tests": [
      {
        "file": "tests/test_nsis_bootstrap_helper.py",
        "scenarios": [
          "manifest",
          "Rust/profile",
          "marker timing",
          "errors"
        ]
      },
      {
        "file": "tests/test_bootstrap.py",
        "scenarios": [
          "all exception families",
          "resume",
          "offline corruption",
          "schema migration"
        ]
      },
      {
        "file": "tests/test_napcat_package.py",
        "scenarios": [
          "0/1602/1603/1618/1641/3010",
          "silent",
          "busy/timeout"
        ]
      },
      {
        "file": "tests/test_product_profiles.py",
        "scenarios": [
          "four artifacts identity",
          "wheel contents",
          "allowlist"
        ]
      },
      {
        "file": "tests/test_upgrade.py",
        "scenarios": [
          "activation/crash",
          "owner identity",
          "no process killed by stale recovery"
        ]
      },
      {
        "file": "tests/test_deploy_process.py",
        "scenarios": [
          "liveness",
          "permission unknown",
          "HANDLE typing",
          "preserve existing behavior"
        ]
      },
      {
        "file": "tests/windows/test_upgrade_matrix.py",
        "scenarios": [
          "real owned process file locks",
          "data preservation"
        ]
      },
      {
        "file": "tests/test_stella_home.py",
        "scenarios": [
          "legacy/portable priority",
          "UAC identity",
          "migration"
        ]
      },
      {
        "file": "tests/test_build_llama_package.py",
        "scenarios": [
          "native runtime",
          "metadata"
        ]
      },
      {
        "file": "tests/windows/test_nsis_installation.py",
        "status": "proposed new",
        "scenarios": [
          "T01–T24 in §8"
        ]
      },
      {
        "file": "tests/windows/test_install_recovery.py",
        "status": "proposed new",
        "scenarios": [
          "interruption/reboot/parallel locks"
        ]
      }
    ],
    "verification_commands": [
      {
        "command": "python -m pip install -r requirements.txt -r requirements-dev.txt",
        "prerequisite": "isolated Windows test env; temporary STELLA_HOME; current conftest imports application"
      },
      {
        "command": "python -m pytest tests/test_nsis_bootstrap_helper.py tests/test_bootstrap.py tests/test_napcat_package.py tests/test_product_profiles.py tests/test_upgrade.py tests/test_deploy_process.py tests/test_stella_home.py tests/test_build_llama_package.py -q"
      },
      {
        "command": "python -m pytest tests/windows/test_upgrade_matrix.py -q",
        "prerequisite": "Windows"
      },
      {
        "command": "python -m ruff check deploy scripts tests"
      },
      {
        "command": "cargo test; cargo tauri build --bundles nsis",
        "prerequisite": "separate commands in desktop/src-tauri; Windows MSVC; dashboard/resources staged; pinned Tauri CLI"
      },
      {
        "command": "node .gitnexus/run.cjs detect-changes --scope all --repo .",
        "prerequisite": "before commits; full result"
      },
      {
        "command": "docker exec -w /repo stella-gitnexus gitnexus detect-changes --scope all --repo Stella_project",
        "prerequisite": "existing Docker CLI fallback if host runner shim fails"
      }
    ],
    "risks": [
      "CRITICAL prepare_runtime impact; must retain callers",
      "UNKNOWN recover_stale callers not proof unused; Windows os.kill is destructive",
      "NSIS template may uninstall old version before hooks; inspect fixed .nsi",
      "external MSI transactions cannot be fully atomically rolled back",
      "runtime relocation/native DLLs require real clean Windows",
      "user data root and UAC identity require compatibility",
      "GitNexus PDG/flow coverage bounded",
      "signing/VM/NapCat offline capability external validation dependencies"
    ],
    "assumptions": [
      "same install identity for profile/mode switching unless product decision changes",
      "Windows amd64 and existing Python 3.12.10 baseline; OS/CPU minimum to validate",
      "existing upgrade patterns reusable after actual launcher integration",
      "data migration never automatic on valid old data root"
    ],
    "open_questions": [
      "supported OS/CPU matrix",
      "stable launcher/minimal NSIS template implementation choice",
      "signing credentials/service",
      "clean VM resources and licenses",
      "candidate asset channel retention",
      "offline repair wheelhouse cost",
      "NapCat ownership/offline behavior"
    ],
    "avoid": [
      "implementation edits during planning",
      "unsafe Windows os.kill(pid,0) liveness",
      "fake ready marker",
      "silent offline network fallback",
      "swallow MSI reboot/cancel",
      "whole-machine taskkill or unrequested external uninstall",
      "automatic data deletion/migration",
      "copying ordinary venv as portable runtime",
      "claiming current static/mocked tests validate EXE",
      "release untested bytes or overwrite immutable artifacts",
      "treating graph UNKNOWN/partial as clean"
    ]
  }
}
```

## 12. 假设、开放问题与明确延后

### 12.1 可按默认方案推进，但必须在对应步骤验证

| 项目 | 计划默认 | 验证方式与影响 |
| --- | --- | --- |
| [assumed] 产品兼容范围 | Windows amd64；当前已用 Python 3.12.10 | S01/S09 用最新依赖与干净最低系统确定 OS/CPU 下限，不把 1803 提示当已验证承诺 |
| [assumed] 四种产品关系 | 同一安装身份，就地切 profile/mode | 核对 NSIS 注册项/identifier；若要共存须另设计独立身份与共享数据策略 |
| [assumed] NapCat 可离线安装 | 固定 MSI 为待验证输入 | 从干净断网 VM 运行所有动作；若需要下载，候选离线发布被阻断 |
| [assumed] 原用户安装优先 | per-user 程序+独立用户数据，必要组件单独提权 | 真实 MSI 属性、UAC、用户 SID/ACL 验证；不盲改 perMachine |
| [assumed] 事务升级可复用现有模块 | 复用 staging/check/postflight/active record 模式 | 接通 desktop 实际读取、检查跨卷与残留；已有测试不证明 shell 升级事务已完备 |
| [assumed] runtime 可搬迁 | 使用嵌入式发行版及随包 wheel | 中文路径搬迁、自检、Scripts/绝对路径审计 |
| [assumed] 有资源运行 VM 和签名 | 作为正式发布依赖 | S02/S14 先验证基础设施和证书；缺失不阻止逻辑开发，但不得放行正式包 |

### 12.2 实施内需要形成决定记录的事项

1. 最低 Windows/CPU 支持矩阵，第三方组件给出的更高下限优先；需取实际版本文档与 VM 结果。
2. 稳定启动入口与 NSIS 自定义模板的最小改动方案；维护成本与真正回滚保证一起评估。
3. signed release 使用哪种证书/签名服务，凭据由维护者在部署阶段配置。
4. CI 干净 VM 的来源、Windows 许可、网络隔离、重启恢复能力及预算。
5. 默认新数据目录 LOCALAPPDATA/Stella/Data 是否满足便携产品预期；旧路径默认保留。
6. offline runtime 是否保留全部 wheels 用于修复；以包体/磁盘/修复场景结果决定。
7. 在线候选资产通道、保留策略与旧 catalog 生命周期；不得删仍有已发布安装器引用的资产。
8. NapCat MSI 安装 ownership/共享/升级策略；不随意卸载用户已安装版本。
9. 签名与 SmartScreen、AV 报告需要真实产物验证，不能只通过配置推断。
10. 图枚举与 PDG 仅辅助定位，源码/最终产物/运行结果优先。语句覆盖不足处见 §5。

这些事项均有默认与验证任务，无需在计划阶段逐个向用户追问；涉及证书/外部资源采购或产品支持范围变更时，实施到具体可审阅决策再由维护者确认。

### 12.3 明确延后的相邻工作

- ARM64/32-bit/macOS/Linux 安装支持、替换 Tauri/NSIS、全量重写旧桌面壳。
- 自动升级服务/后台遥测、迁移所有历史用户数据、重构整个配置系统。
- 默认模型产品策略变更或删除 NapCat 来“降低失败率”。
- 把所有开发依赖强行锁死；本计划锁定发布依赖，开发升级策略独立。

### 12.4 官方依据（本会话已核对）

- [Tauri Windows installer：hook 时序与 WebView2 offlineInstaller](https://v2.tauri.app/distribute/windows-installer/)
- [NSIS Abort：停止执行，不提供本项目所需的事务撤销](https://nsis.sourceforge.io/Reference/Abort)
- [NSIS FindClose：关闭 FindFirst 返回的搜索句柄](https://nsis.sourceforge.io/Reference/FindClose)
- [Python 3.12 嵌入式发行版：依赖随应用分发及 pip 边界](https://docs.python.org/3.12/using/windows.html#the-embeddable-package)
- [pip 可重复安装与 wheelhouse](https://pip.pypa.io/en/latest/topics/repeatable-installs/)
- [Python os.kill 的 Windows 语义：除控制事件外会调用 TerminateProcess](https://docs.python.org/3.12/library/os.html#os.kill)
- [Microsoft MSI 返回码](https://learn.microsoft.com/en-us/windows/win32/msi/error-codes)

官方文档说明工具语义，不代替本项目固定工具版本生成的 .nsi 和实际 EXE 验证。

## 13. 完成定义

以下全部勾选才称为本计划完成；只完成里程碑 A 时必须如实标记其余项未交付。

- [ ] 四种安装器有一致的 release metadata、依赖锁、完整负载清单与最终摘要。
- [ ] 最终签名 EXE 的安装/首启/升级/卸载验证成为发布硬门禁。
- [ ] 两种 offline 在干净断网 Windows 完成安装与本地健康检查，外网请求为零。
- [ ] 常规新安装不在用户机器上运行 get-pip、解析依赖或编译 wheels。
- [ ] Rust wheel、profile、catalog、browser、native DLL 和模型均通过真实运行检查，GUI 首启不补做正常安装步骤。
- [ ] 所有预期异常/取消/超时有准确终态；重启信息从组件传到 NSIS/CI。
- [ ] failed/interrupted 续装只修复未健康项；跨进程互斥、崩溃恢复、所有者身份验证通过。
- [ ] 新旧 marker/schema 兼容，metadata 与真实组件状态不一致时进入修复。
- [ ] 程序版本激活、桌面/CLI 资源定位和回滚真实接通，非仅写指针。
- [ ] 升级中断保留可用旧版本或明确修复路径；不宣称可自动撤销第三方全部副作用。
- [ ] 数据根、提权身份、profile 切换、卸载后重装矩阵通过；用户数据/QQ 会话无非预期变化。
- [ ] 不依赖系统 tar、开发机 Python 或偶然预装 DLL；支持 OS/CPU 范围有实测证据。
- [ ] 在线下载有限重试、断点续传、缓存校验、取消与代理/TLS 诊断通过；不绕过校验。
- [ ] 每次安装都有持久日志与诊断导出，脱敏/保留策略有效。
- [ ] 发布候选到正式推广有一致性协议，正式 URL 依赖完整，被测/发布字节一致。
- [ ] 体积、耗时、内存/磁盘峰值有基线和门禁；文档与实际行为一致。
- [ ] 共享 CLI/Standalone/旧桌面壳回归通过；CRITICAL prepare_runtime 所有关联入口有覆盖。
- [ ] 相关测试、lint、Windows 实测、提交前 GitNexus 完整变更分析完成，所有剩余限制写入发布说明。

