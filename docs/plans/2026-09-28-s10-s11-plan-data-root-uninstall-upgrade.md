# S10/S11 实施计划：数据根显式化、卸载/升级契约（含 .nsi 已核实事实）

> 状态：**草案待审**。基于 2026-09-28 用 tauri-cli 2.12.0 真实构建 oneclick-python（online）安装器并读取生成的
> `installer.nsi`（2867 行）后起草；所有模板行为标注 [verified-nsi]，源码行为标注 [verified-src]。
> 前置计划：docs/plans/2026-09-28-gitnexus-plan-nsis-installation-reliability.md（S01–S09、S12、S13、S14 切片已交付）。

## 1. 目标与范围

把安装/升级/卸载中"靠偶然性成立"的安全性质变成显式契约：

1. **S10a 数据根显式接入**：新装默认数据根落到 `$LOCALAPPDATA\Stella\Data`（安装树外），不再依赖
   "卸载器按文件删除所以树内数据侥幸存活"的偶然性；便携/旧布局/环境变量优先级**零改动**。
2. **S10b 卸载契约**：PREUNINSTALL/POSTUNINSTALL 钩子落地——卸载留外置 journal（保留的数据根路径），
   默认不删任何用户数据；运行期残留（runtime/、pip 包）有文档说明。
3. **S11a 升级 journal + profile 切换清理**：升级（含静默 /S）在外置 journal 留 from/to/终态；
   Rust→Python 切换时清除残留 Rust wheel 激活状态（T12 劫持路径）。
4. **S11 Phase 2（版本化程序树 + 稳定启动入口 + 真回滚）单独立项**，本计划只落它的前置决策材料。

明确不做（本计划内）：自动迁移已有数据根；卸载时清理运行期残留；重写 NSIS 模板；动 `config/home.py`；
改 `python.rs` 的 `rust_wheel_present`（防御性加固推迟到 Phase 2，届时随 CRITICAL 影响面一起做 impact）。

## 2. 已核实的模板事实（约束设计的硬边界）

全部 [verified-nsi]，来源 `desktop/src-tauri/target/release/nsis/x64/installer.nsi`（2.12.0 生成）：

| # | 事实 | 对设计的影响 |
| --- | --- | --- |
| F1 | 交互式升级在重装页 `PageLeaveReinstall → reinst_uninstall` 执行 `ExecWait '旧uninstall.exe _?=$INSTDIR'`，**先删旧树再装新** | "升级失败旧版可用"无法只靠新构建的钩子实现——删除发生在我们的任何钩子之前；真回滚必须 Phase 2（版本树） |
| F2 | 静默 /S 升级**跳过页面** → 旧卸载器不运行 → 原地覆盖（旧文件孤儿残留）；`/UPDATE` 模式显式跳过卸载 | 升级安全的另一条路是 /UPDATE 语义；journal 必须覆盖静默路径 |
| F3 | 卸载 = 923 条按文件 `Delete` + 非递归 `RMDir`；hook 生成的 `runtime/`、pip 包、`.stella` 缓存、树内数据根**均不在清单** | 用户数据"卸载后存活"是偶然性；S10b 把它变成显式语义并留痕 |
| F4 | `INSTALLMODE="currentUser"`：`RequestExecutionLevel user`、默认 `$LOCALAPPDATA\Stella`、`SetShellVarContext current` | 安装/钩子全程原用户身份；写 `%LOCALAPPDATA%\Stella\` 指针无需提权 |
| F5 | Section 顺序：EarlyChecks → WebView2 →（交互）旧版卸载 → Section Install（SetOutPath → **PREINSTALL** → CheckIfAppIsRunning → 文件释放 → 注册表/快捷方式 → **POSTINSTALL**） | PREINSTALL 在 WebView2 之后、释放之前；数据根决策放 POSTINSTALL（helper 内，python 可用）而非 PREINSTALL（python 尚未就位） |
| F6 | 卸载段有 PREUNINSTALL/POSTUNINSTALL 钩子位（模板已接线）；"Delete app data" 勾选框只清 `$APPDATA/$LOCALAPPDATA\com.stella.desktop`（WebView2 数据） | 卸载契约可以直接进钩子；不需要动模板 |
| F7 | CheckIfAppIsRunning 用 Restart Manager 只针对 Stella.exe（静默强杀/交互可取消） | 进程占用处理已够用，不重复建设 |

[src 侧事实]：`config/home.py` 解析顺序为 环境变量 > 便携 `StellaData` > 旧布局痕迹 > 机器指针
`%LOCALAPPDATA%\Stella\home.txt` > 新建默认 `install_root.parent\StellaData`（= `$INSTDIR\resources\StellaData`，
树内——F12 的根源）。指针机制已存在，**本计划不需要改 home.py**。

## 3. 拟实施变更

### Step 1｜S10a：新装数据根外置（helper 内，home.py 零改动）

文件：`deploy/nsis_bootstrap_helper.py`、`tests/test_nsis_bootstrap_helper.py`、`tests/test_install_contract.py`。

helper 在组件装载（`deploy bootstrap install`）**之前**做数据根决策，逻辑镜像 home.py 的优先级
（纯 stdlib 文件/环境检查，不 import config）：

1. `STELLA_HOME` 环境变量已设 → 沿用，不动（也不写指针）；
2. 安装树内有便携目录（`<install_root>\StellaData`）→ 沿用（便携用户升级零影响）；
3. 安装树内有旧布局痕迹（`.env` / `memory\agent_memory.db` / `deploy.answers.toml`）→ 沿用树内旧布局；
4. 机器指针已存在且指向有效目录 → 沿用；
5. 都没有（全新安装）→ 数据根 = `%LOCALAPPDATA%\Stella\Data`：
   - 写机器指针 `home.txt`（幂等；写失败不阻断，退化为现状默认）；
   - 为 `deploy bootstrap install` 子进程注入 `STELLA_HOME`，组件、模型、账本、事件流全部落树外。

约束与兼容：
- **不迁移、不移动**任何已有数据根（含升级安装里树内 StellaData——按规则 2 沿用便携语义，数据原地）；
- GUI/CLI 后续解析经指针自动命中树外数据根（现有机制），`deploy init/migrate` 的 `create=True` 路径不再触发树内默认；
- 会话日志（S13）记录所选数据根与来源（env/portable/legacy/pointer/new-default）。

### Step 2｜S10b：卸载契约钩子

文件：`desktop/src-tauri/installer-hooks.nsh`、`tests/windows/test_nsis_hook_compiles.py`、
`tests/test_install_contract.py`。

- **PREUNINSTALL**：若 `%LOCALAPPDATA%\Stella\home.txt` 存在，向 `%LOCALAPPDATA%\Stella\uninstall-journal.txt`
  追加一行（时间 + 卸载动作 + 保留的数据根路径）；**不删除任何文件**。数据根在树内的旧安装（无指针）
   journal 写"数据根未外置，树内数据随安装目录存留"——如实记录而非假装保留。
- **POSTUNINSTALL**：空实现占位 + 注释（ownership 清单清理属于 Phase 2）。
- 文档性输出：卸载完成后 DetailPrint 说明"用户数据（记忆/配置/QQ 登录态）已保留于 <路径>"。
- 已知限制（如实标注）：钩子只随**新构建**分发；从旧版本升级来的安装在卸载时没有这些钩子。

### Step 3｜S11a：升级 journal + profile 切换清理

文件：`deploy/nsis_bootstrap_helper.py`、`desktop/src-tauri/installer-hooks.nsh`、两个测试文件。

- **PREINSTALL**（新构建）：检测 `$INSTDIR\Stella.exe` 已存在 → 向
  `%LOCALAPPDATA%\Stella\upgrade-journal.txt` 追加"升级开始"（时间 + 旧版
  `.stella-release-metadata.json` 的 release_version，读不到记 unknown）。Journal 在 INSTDIR 之外，
  旧卸载器删不到。
- **POSTINSTALL（helper 末尾）**：按装载结果追加"升级完成"终态（ready / reboot_required / failed
  + 失败步骤名）——复用 S13 会话日志已具备的信息。
- **profile 切换清理（T12）**：helper 装载开始时，若本包声明 `oneclick-python` 而树内存在
  `wheels/stella_memory_rust-*.whl` 或 `runtime\.stella-rust-ready` → 删除（残留 wheel 会让 GUI 的
  `rust_wheel_present` 把后端劫持成 Rust）。反向（python→rust）无需清理（新 wheel 覆盖 + marker 刷新）。
- journal 为**只写诊断流**：GUI/doctor 的消费属于后续（不在本计划承诺内）。

### Step 4｜S11 Phase 2 立项材料（不在本计划实施）

版本化程序树 + 稳定启动入口 + 激活记录 + 真回滚。前置决策（需维护者拍板）：
1. 稳定入口形态：新建轻量 launcher exe（新 crate，读指针启动版本树）vs 自定义 NSIS 模板（维护成本，计划已警告漂移）；
2. `python.rs project_root()` 读激活记录（CRITICAL prepare_runtime 影响面，逐符号 impact）；
3. 快捷方式/CLI 透传/修复/卸载与版本树的接线清单。

## 4. 测试与验收

- helper 数据根决策矩阵单测：env/portable/legacy/pointer/fresh 五路 + 指针写入幂等 + 写失败退化
  （测试内以临时 `LOCALAPPDATA` 隔离，绝不碰真实用户目录）；
- T12：python 包 + 残留 rust wheel/marker → 清理后装载；rust 包 + wheel → 不误删；
- hook 源码断言 + 真实 makensis 编译门禁扩展到四个钩子宏；
- 回归：现有 202 项测试全绿；`ruff check deploy scripts tests` 干净；
- 每步提交过 `detect-changes --scope all`（docker 兜底）。

## 5. 风险与兼容

| 风险 | 缓解 |
| --- | --- |
| 指针为机器级，同机多份 OneClick 共享数据根 | 与现状指针机制一致（"同一安装身份"假设，计划 §12.2 已接受）；便携/开发仓库不受影响（便携优先） |
| 全新安装的 `deploy bootstrap install` 在指针生效后落新数据根，与旧版升级路径不同 | 升级安装命中规则 2/3（树内已有数据），行为不变；fresh 才走新默认 |
| helper 写指针失败（权限/只读盘） | 静默退化到现状树内默认 + 会话日志记录；不阻断安装 |
| journal/journal 写失败 | 与 S13 事件流同策略：诊断流绝不阻断 |
| PREUNINSTALL 只在新构建生效 | 如实写入发布说明；不做假承诺 |
| `LOCALAPPDATA` 重定向/网络盘等非常规环境 | 指针写失败即退化；不新增系统级修改 |

## 6. 决策点（审阅时请拍板）

1. Step 1 的新默认数据根 `$LOCALAPPDATA\Stella\Data` 是否接受？（备选：维持树内默认，仅加 journal——不改任何行为，但 F12 隐患保留）
2. Step 3 的 T12 清理放 helper（本计划，安装期清理）是否足够？python.rs 侧 `rust_wheel_present` 加固推迟到 Phase 2 是否接受？
3. S11 Phase 2 的启动入口形态（launcher exe vs 自定义模板）建议单独立项后再定——是否同意暂缓？
