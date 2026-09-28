# 干净 VM 验收矩阵 runbook（S15）

执行环境：自托管 runner（labels `[self-hosted, stella-vm-windows]`），
作业前由宿主还原基线检查点（干净 Windows amd64，无 VC++/Python/Node
开发工具）。自动化入口：`.github/workflows/release-vm-validation.yml`
（workflow_dispatch，填 Release 工作流 run id + 上一正式版 tag）。

## 分级映射（T01–T24）

| 场景 | 级别 | 位置/说明 |
| --- | --- | --- |
| T01 四产物新装/首启 | VM 自动 | 矩阵作业逐产物跑 test_nsis_install.ps1 |
| T02 断网离线安装零外联 | VM 自动（宿主禁 vSwitch 步骤） | 离线两个矩阵项；宿主在安装步骤前切网络 |
| T03 账户/提权/silent 交互 | VM 自动（silent）+ 手册（提权矩阵） | harness /S；提权场景按本表手册节执行 |
| T04 中文/空格/长路径/只读 | 手册 | 改安装目录参数（/D=）逐项跑 harness |
| T05 磁盘不足（安装卷/TEMP/数据卷） | 手册 | 缩小 VM 磁盘后跑 harness，核对预检查 Abort |
| T06 组件缺失/损坏 | VM 自动 | 破坏 app 内一个负载文件 → 期待 payload_corrupt（S06 语义） |
| T07 网络故障注入（代理/TLS/429/404） | 手册 | 在线变体 + 代理工具注入；核对 acquire 分类重试 |
| T08 MSI 全退出码 | 手册 | 造假 MSI/退出码环境；核对 msi_* 具名失败与日志 |
| T09 各阶段崩溃/强杀安装器 | VM 手册 | 任务管理器杀 installer/helper → 重跑核对续装 |
| T10 installer+GUI/CLI 并发 | VM 自动（两作业并行）| 矩阵作业与手动 GUI 同时跑；核对 install_in_progress |
| T11 上一正式版升级 + 回滚 | VM 自动 | 矩阵作业 T11 步骤（旧版安装→新版→激活记录/回滚） |
| T12 Python↔Rust / online↔offline 切换 | VM 自动（跨矩阵两次安装） | 核对 T12 清理事件与后端选择 |
| T13 旧进程占用（Stella/QQ/python） | 手册 | 起 QQ + 无关 python 再升级；只许动 Stella.exe |
| T14 metadata ready 但组件被删 | VM 自动 | 删 napcat.json → 重装核对 repair_required |
| T15 runtime 搬迁后外部 cwd 运行 | VM 自动（check_windows_runtime.py） | 附加步骤：搬迁中文目录 + 外部 cwd 自检 |
| T16 首启未配置（无 QQ/API key） | VM 手册 | 打开 GUI 核对配置向导出现、无安装失败误报 |
| T17 WebView2 已装/旧版/未装 | VM 手册 | 三台检查点快照分别验证 offlineInstaller 行为 |
| T18 卸载默认/清数据/重装 | VM 自动（卸载+数据根核对） | 矩阵作业 T18 步骤 |
| T19 签名后下载/发布 URL/catalog | CI 自动 | build 作业回读校验 + check_release_hashes |
| T20 Defender/最低 CPU/系统语言 | 手册 | 需要专门快照；记录支持范围 |
| T21 旧/新 schema 与损坏指针 | CI 自动（pytest） | tests/test_upgrade.py 激活记录用例 |
| T22 升级前后数据快照 | VM 手册 | 字节级对照数据根；回滚不降级 schema |
| T23 体积接近上限/慢盘/长操作 | CI 体积门禁 + VM 手册 | check_installer_size + 人为慢盘观察心跳 |
| T24 .nsi 钩子/WebView2/旧卸载时序 | CI 自动（构建期） | installer.nsi 断言 + makensis 门禁 |

## 证据归档

每次矩阵运行上传 `vm-matrix-<profile>-<payload>` artifact（验收报告
JSON 含 hash/签名状态/逐项检查/耗时）；正式发布的证据随 release 归档。
手册项执行后在 release 记录勾选并附截图/日志路径。

## 基础设施清单

- Hyper-V 宿主 + 干净 Windows amd64 基线检查点（无开发工具）
- VM 内 runner 注册（labels: self-hosted, stella-vm-windows）+ gh CLI
- 宿主还原脚本挂钩（vars.STELLA_VM_RESTORE_COMMAND）
- T02 断网：宿主在离线矩阵项前禁用 VM vSwitch，安装完成步骤后恢复
