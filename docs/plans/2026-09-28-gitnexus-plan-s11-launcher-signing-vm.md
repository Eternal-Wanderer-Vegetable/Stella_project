# GitNexus Engineering Plan — S11 Phase 2 / S14 签名 / S15 VM 矩阵

> 任务：实施 S11 Phase 2（版本化程序树 + 稳定启动入口 + 激活记录 + 回滚开关）、S14 签名与候选发布通道、S15 完整 VM 验收矩阵与 WP15 收尾。
> 证据核实于提交 7a23d3926aa71c558d028788262e1dd8f0e6eace；GitNexus 索引本会话已刷新（analyze --index-only --pdg，docker stella-gitnexus，GitNexus 1.6.11，67,266 节点）。
> 生成计划路径：docs/plans/2026-09-28-gitnexus-plan-s11-launcher-signing-vm.md
> 证据溯源 schema 2；全局脏摘要 0a9c85780067d9afcd0764f307b60891e3cee927ee11eaeb5ec7826d10fd82cd；引用清单 19 个排序条目；仅排除本计划生成路径。
> 前序交付：S01–S09、S12、S13、S14 切片、S10、S11a 已在本分支落地（基线计划 3f5a69b → 本计划 7a23d39）。

## 1. 目标

1. **S11 Phase 2**：程序树版本化（`$INSTDIR\app\<version>\`）、稳定启动入口（launcher exe）、机器级激活记录、旧版本保留与回滚开关——把「升级失败旧版可用」从不可能（交互升级先卸旧树 [verified-nsi]）变为结构保证。
2. **S14**：自有 EXE/卸载器签名（含无证书时的明确降级语义）+ 不可变候选发布通道（消除 catalog 自指 URL 的验收死锁）。
3. **S15**：干净 VM 验收矩阵 harness（T01–T24 分级映射）、体积基线与门禁、发布文档收尾。

## 2. 现状行为

- **布局与解析**：Tauri 模板把主程序与 resources 装到 `$INSTDIR` 根；`desktop/src-tauri/src/python.rs:project_root`（约 1241 行起）按 `[exe_dir, exe_dir\resources, exe_dir\resources\stella]` + 向上逐级找 `bot.py` 解析程序根，兜底 `CARGO_MANIFEST_DIR`。`data_root()`（python.rs）经 `deploy paths` 问 `config/home.py`（指针机制已在 S10a 接入树外默认）。
- **升级语义**（installer.nsi [verified-nsi]）：交互式升级先 `ExecWait 旧uninstall.exe _?=$INSTDIR`（删旧树）；静默 /S 跳过页面直接覆盖（旧文件成孤儿）；`/UPDATE` 显式跳过卸载。卸载 = 923 条按文件 Delete + 非递归 RMDir——hook 创建的文件（runtime/、数据根、未来的 app\<version>\ 树）天然幸存。
- **发布链**（release.yml）：build-installer → install-test（真实安装验收，test_nsis_install.ps1）→ build 汇总 → 字节核对（check_release_hashes.py）→ gh release 上传 + 发布后回读校验（build_release_manifest.py）。无签名步骤。
- **catalog 自指**：`scripts/build_release_catalog.py:76-79` 的 llama-cpu source 是 `…/releases/download/{release_ref}/…`——构建时该 Release 不存在，离线负载靠 `--local-artifacts` 绕过，在线验收存在死锁（WP14 遗留）。
- **CI**：ci.yml `windows-native` 作业（windows-latest）已跑 `tests/windows`。

## 3. 相关架构与边界

| 层 | 现状职责 | Phase 2 后职责 |
| --- | --- | --- |
| CI | 构建→签名（新增）→安装验收→字节核对→发布→回读 | 增加候选通道发布/晋升、VM 矩阵、体积门禁 |
| NSIS | 固定模板 + 四钩子（我们唯一可控面 [verified-nsi]） | PREINSTALL 升级留痕、POSTINSTALL 版本树搬移 + 激活记录 + 稳定入口 |
| launcher（新增） | — | 读激活记录 → 启动 `app\<version>\Stella.exe`；记录缺失时枚举兜底 |
| deploy/upgrade.py | 事务升级原语 + 数据根 UpgradeLock | 机器级激活记录的写/校验/回滚 |
| GUI（python.rs） | project_root/data_root 解析（CRITICAL） | 激活记录优先的解析 + 完整回退 |
| 数据根 | 树外指针（S10a） | 不变 |

既有模式沿用：原子 JSON（`_atomic_json`）、O_EXCL 锁与 owner 身份（install_state）、外置 journal（S10b/S11a）、按文件卸载盲区作为版本树存活机制（本计划将其从「偶然」升级为「有 ownership 清单的保留策略」）。

## 4. GitNexus 发现

| 查询（工具+参数） | 关键结果 | 必须覆盖的直接消费者 |
| --- | --- | --- |
| impact project_root upstream d3（-u desktop 壳） | **risk CRITICAL**，impacted=21，direct=7 | d1：commands.rs get_config / get_personas / get_version / save_config / save_persona + python.rs data_root / run_deploy_inner；d2：run_deploy / run_deploy_without_prepare / run_runtime_operation / live_base_url / read_log_tail / read_start_progress；d3：get_status / start_bot / stop_bot / wait_bot_ready / run_doctor / run_migrate / try_runtime_operation |
| impact data_root upstream d2（-u） | CRITICAL，impacted=8，direct=7 | commands.rs 六个读写入口 + wait_bot_ready |
| impact transactional_upgrade upstream d2 | LOW，direct=1 | `deploy/__main__.py:_cmd_upgrade` |
| impact find_root upstream d2（cli/src/ctx.rs） | LOW，direct=1 | `cli/src/ctx.rs:resolve` → `cli/src/main.rs:run` |
| 歧义处理 | `project_root` 有 3 个同名符号（两壳 + 第三处）——按 ledger 规则以 `-u` uid 窄化重试，取 desktop 壳为权威 | stella-installer 壳的同名函数按「共享契约或一致性测试」同批处理（WP15 遗留，见 §12） |

重要边界：NSIS→Python、launcher→exe、CI→脚本是跨进程边，图无法证明全路径；以上游 d=1 全计账 + 源码核对为准。`prepare_runtime`（原计划 CRITICAL）本计划**不改其函数体**——它经 `project_root()` 间接受影响，d=1（python.rs prepare_runtime 包装）在 d2 覆盖内。

## 5. 语句级 PDG 发现

对 `project_root` 做了一次有界 PDG 查询（`impact --mode pdg --line 1241 upstream d2`，层已随本次刷新建好）：签名行锚点返回 `pdg-intra-procedural`、0 个独立上游块（函数入口行无控制/数据依赖出边）。**结论**：语句级切片对本次无增益——Phase 2 的变更整体替换解析函数体（候选列表→激活记录优先），约束来自源码读取（候选顺序、路径归属校验、CARGO 兜底）而非语句依赖。不再消费更多 PDG 预算。

## 6. 拟实施变更

### WP-A｜激活记录与启动入口（S11 Phase 2 核心）

- **`deploy/upgrade.py`**（新函数，复用 `_atomic_json`/UpgradeResult 形态）：
  - `machine_active_record_path()` → `%LOCALAPPDATA%\Stella\active-install.json`（与 home.txt 指针同级； INSTDIR 外，旧卸载器删不到 [verified-nsi]）；
  - `write_activation_record(version, tree_path, tree_sha256, previous_path=None)`（原子）；
  - `read_activation_record()` + `validate_activation_record(record, install_root)`：路径必须落在 `install_root\app\` 下（containment，拒绝 `..`/盘符/越界），可选 tree_sha256 复核；
  - `rollback_activation()`：record 内 `previous` 字段翻转（保留上代树路径），由 CLI 暴露。
- **`desktop/launcher`（新 crate，std-only Rust，约 150 行）**：读激活记录（机器路径 → `$INSTDIR\.stella\active-install.json` 兜底）→ 校验 `<tree>\Stella.exe` 存在 → 以 cwd=tree 启动并透传参数；记录缺失/损坏 → 枚举 `$INSTDIR\app\*` 取最高版本；全失败 → MessageBox 明确报错。语义与 `start.bat` 的 `%~dp0` 锚定等价（[verified-src] start.bat:3）。
- **`desktop/src-tauri/installer-hooks.nsh`（POSTINSTALL 扩展，构建开关门控）**：
  - 门控 = 随包标记文件 `.stella-versioned-layout`（staging 写入；旧包无标记 → 全部跳过，现状布局继续可启动）；
  - 动作：把本次模板装到 `$INSTDIR` 根的程序文件**移动**到 `$INSTDIR\app\<version>\`（同卷 rename，快）；复制 resources 内 launcher 到 `$INSTDIR\Stella.exe`（稳定入口）；以 FileWrite 写扁平 JSON 激活记录（转义 `\`）；GC：按 ownership journal 删除超过保留代数（默认 2）的 `app\*` 旧树——**空间不足时先跳过 GC**（不删唯一可用旧版，计划 §9 铁律）；
  - 依赖与约束：移动后旧卸载器的按文件 Delete 全部落空（[verified-nsi] 幸存机制，现被 ownership journal 显式管理）；交互升级的旧卸载器同样删不到已搬移树 → 旧版天然保留，回滚 = 记录翻转；
  - 失败语义：搬移任一步失败 → 不写记录、恢复 `$INSTDIR\Stella.exe` 为真身（现布局可直接启动），journal 记 `relocation_failed`。
- **`scripts/build_release_package.py`**：staging 增加 launcher 产物与 `.stella-versioned-layout` 标记（受 `--versioned-layout` 开关控制，CI 双轨期默认关）。
- **`desktop/src-tauri/src/python.rs`（CRITICAL）**：`project_root()` 解析顺序改为 **激活记录优先**（读机器记录 → containment 校验 → 命中即返回 tree 路径）→ 现有候选列表完整保留为回退；`data_root`/`run_deploy_inner`/七个 commands.rs 直接消费者无需改签名（回退保证无记录时行为逐字节不变）。stella-installer 壳以一致性测试覆盖（§12）。
- **`cli/src/ctx.rs`**：`find_root` 不改——launcher 启动时把 cwd 设为激活树，子进程继承；CLI 从树外运行的语义保持现状（文档说明）。

### WP-B｜签名与候选通道（S14 收尾）

- **`desktop/src-tauri/tauri.conf.json`**：接入 `bundle.windows` 签名配置（证书指纹/时间戳 URL 由 CI env 注入；模板的 `UNINSTALLERSIGNCOMMAND` 随之生效 [verified-nsi: installer.nsi:96]）。
- **`.github/workflows/release.yml`**：
  - `sign-installers` 步骤（build 之后、install-test 之前——**验收必须针对签名后字节**，WP02 铁律）：secrets 存在 → signtool/Trusted Signing 签名 + RFC3161 时间戳 + 验签；secrets 缺失 → PR/手工构建允许跳过（artifact 标注 unsigned + 大字警告），**tag 推送的正式发布硬失败**（禁 continue-on-error）；
  - 签名后字节重算 SHA-256 → install-test 报告与 check_release_hashes 门禁自动消费（现有链路无改动）。
- **候选通道**：
  - `scripts/build_release_catalog.py` 增 `--asset-base-url`（覆盖 llama-cpu 自指 source；[verified-src] 76-79 行）；
  - release.yml 新 `publish-candidate` 作业：在任何安装器构建**之前**发布不可变预发布 `candidate-<build_id>`（backend zip + SHA256SUMS）；catalog 以候选 URL 构建；全门禁通过后正式发布晋升（候选 Release 永不删除——仍被已发布安装器引用）；保留最近 N=6 个候选，GC 前校验无引用。
- **`scripts/check_release_manifest.py`**（S14 切片已有 verify 模式）消费签名后字节。

### WP-C｜VM 矩阵与收尾（S15 + WP15）

- **VM harness**：自托管 runner（label `stella-vm-windows`）+ 作业前置快照还原（Hyper-V `Restore-VMCheckpoint` 启动脚本；快照=干净 Windows + 无开发工具）；新 `release-vm-validation.yml`：
  - 四产物 `test_nsis_install.ps1` 全量安装验收（T01）；
  - T02 断网（禁 vSwitch）离线安装零外联；T03 silent/interactive 双模；T11 从上一正式版升级 + 回滚开关演练；T14 破坏组件→repair_required；T18 卸载保留数据核对；
  - 报告/日志 always 归档；矩阵其余项映射为「hosted 自动 / VM 自动 / VM 手册 / 延后」四级（§12 附映射表）。
- **体积门禁**：`scripts/check_installer_size.py`（对 toolchain.json 记录的基线预算：online ≤260MB / offline 另计，超限硬失败 + 超 10% 警告）；以 S15 实测刷新基线。
- **文档**：RELEASE_NOTES 模板补签名说明（SmartScreen 仍可能提示）、升级/回滚/数据保留语义、`tests/windows` 手册项。

## 7. 实施顺序（每步独立可落地、可停）

| 步 | 内容 | 依赖 | 退出条件 |
| --- | --- | --- | --- |
| P2-1 | upgrade.py 激活记录模块 + 单测 | 无 | 记录写/读/校验/回滚全覆盖；原子性测试过 |
| P2-2 | launcher crate + staging 接线 + CI 构建 | P2-1 | 本地构建 launcher 可按记录启动假树 |
| P2-3 | POSTINSTALL 搬移钩子（开关默认关）+ makensis 门禁扩展 | P2-2 | 本地真装：搬移/记录/稳定入口/旧版保留全过；开关关=现状 |
| P2-4 | python.rs 激活优先解析（CRITICAL，逐 d1 回归）+ 两壳一致性测试 | P2-3 | 21 个 impacted 消费者在记录存在/缺失两态下行为正确；cargo test 全绿 |
| P2-5 | 回滚 CLI（`deploy upgrade rollback`）+ GC 策略 | P2-1、P2-3 | 升级后旧树可一键切回；GC 不删唯一旧版 |
| S14-1 | 候选通道（catalog 参数 + publish-candidate 作业） | 无 | 安装器构建引用候选 URL；回读校验过 |
| S14-2 | 签名管道（tauri.conf + sign 步骤 + 门禁语义） | S14-1 | 有证书：四产物签名+验收+发布；无证书：非正式构建跳过且标注 |
| S15-1 | VM runner + harness 扩展（T01/T02/T03/T11/T14/T18 自动化） | S14-2 | 快照还原→安装→验收→报告闭环一次成功 |
| S15-2 | 体积门禁 + 文档 + 全矩阵证据归档 | S15-1 | §13 全勾，证据入 release |

提交前门禁沿用：pytest 全绿、ruff 干净、`cargo test`、makensis 四钩子编译、`detect-changes --scope all`（docker 兜底）无 partial/truncated。

## 8. 测试策略

- **upgrade.py**（tests/test_upgrade.py 扩展）：记录写入原子性；containment 拒绝越界/盘符/`..`；回滚翻转保留 previous 链；损坏记录 → 明确错误不误启动。
- **launcher**（desktop/launcher 内联 #[test] 或 tests/）：记录有效→启动目标正确（假树）；记录缺失→枚举兜底；全失败→错误路径。
- **hooks**（tests/windows/test_nsis_hook_compiles.py + test_install_contract.py）：搬移钩子的源码断言（开关标记、GC 不删唯一旧版、失败恢复路径）+ makensis 四钩子编译。
- **python.rs**（内联 #[test]，沿用既有模式）：记录优先/回退逐字节兼容；containment 拒绝；记录指向不存在树 → 回退；stella-installer 壳一致性。
- **helper**（tests/test_nsis_bootstrap_helper.py）：`.stella-versioned-layout` 存在时记录升级/校验路径。
- **S14**：catalog `--asset-base-url` 单测；发布工作流源断言（签名步骤在 install-test 之前、无证书时 tag 推送硬失败）。
- **S15**：PS1 harness 场景扩展以 `tests/windows/test_nsis_installation.py` 的 opt-in 模式落位；VM 作业本身在候选发布时触发。

## 9. 风险与影响分析

| 风险 | 级别/来源 | 控制措施 |
| --- | --- | --- |
| `project_root` CRITICAL（21 impacted；d1=7 全列于 §4） | 高 [graph] | 回退优先设计：无记录 = 现行为逐字节不变；两态全测试；两壳一致性测试；逐符号 impact 已做 |
| 版本树幸存依赖「按文件卸载」模板行为 | 高 [verified-nsi] | 模板已被 2.12.0 锁定（toolchain.json）；升级 tauri-cli 必须重验 installer.nsi（写入 toolchain 升级清单）；ownership journal 让幸存从偶然变受管 |
| launcher 变砖（记录损坏/树被手删） | 中 | 双兜底（枚举 app\* → 报错对话框）；记录损坏不阻断枚举 |
| POSTINSTALL 搬移半途失败 | 中 | 失败即恢复现布局 + journal；搬移是同卷 rename（快、原子性高于 copy） |
| 交互升级先卸旧版 | 高 [verified-nsi] | 版本树在 app\ 下不受按文件 Delete 影响；建议后续把交互升级引导到 /UPDATE 语义（§12 决策点） |
| 签名凭据外部依赖 | 外部 | 管道先行、secrets 门控；正式发布无签名硬失败，不伪装 |
| VM 资源/许可 | 外部 | 自托管 + 快照还原；缺失时矩阵降级为手册清单，不伪装验收 |
| 第三方候选资产膨胀 | 低 | 候选保留 N=6 + 无引用 GC |
| stella-installer 壳漂移 | 中 | 两壳一致性测试（WP15 遗留并入 P2-4） |

## 10. 预计改动文件

| 文件 | 符号/位置 | 理由 |
| --- | --- | --- |
| deploy/upgrade.py | 新增 machine_active_record_path/write/read/validate/rollback_activation | 激活记录契约 |
| desktop/launcher/**（新 crate） | main + record 读取/枚举兜底 | 稳定启动入口 |
| desktop/src-tauri/installer-hooks.nsh | POSTINSTALL 扩展（搬移/记录/稳定入口/GC） | 版本树落位 |
| desktop/src-tauri/src/python.rs | project_root（CRITICAL） | 激活优先解析 |
| stella-installer/src-tauri/src/python.rs | project_root（同名） | 一致性测试 |
| cli/src/ctx.rs | 文档注释（find_root 语义说明） | 透明化 |
| scripts/build_release_package.py | staging launcher/标记 | 双轨开关 |
| scripts/build_release_catalog.py | --asset-base-url | 候选通道 |
| desktop/src-tauri/tauri.conf.json | bundle.windows 签名配置 | 签名 |
| .github/workflows/release.yml | sign 步骤、publish-candidate、VM 触发 | 发布链 |
| .github/workflows/release-vm-validation.yml（新） | VM 矩阵作业 | S15 |
| scripts/check_installer_size.py（新） | 体积门禁 | WP15 |
| release_assets/toolchain.json | 体积基线字段 | 门禁依据 |
| 上述测试文件 | 场景扩展 | §8 |



## 11. Reusable Implementation Context

```json
{
  "implementation_context": {
    "task_summary": "实施 S11 Phase 2（版本化程序树+稳定启动入口+激活记录+回滚）、S14 签名与不可变候选通道、S15 干净 VM 验收矩阵与 WP15 收尾。按 §7 九步独立落地，不一次性重写。",
    "acceptance_criteria": [
      "升级后旧树保留且回滚一键完成；数据根与 QQ 登录态无变化",
      "project_root CRITICAL 影响面（21 项）三态行为正确且有测试",
      "四产物签名后过安装验收；发布/验收/用户字节一致",
      "catalog 零自指 URL；候选通道不可变且晋升受门禁控制",
      "干净 VM 六场景自动化通过；T01–T24 分级映射归档",
      "体积门禁与文档与实测一致；全部提交过门禁"
    ],
    "evidence_provenance":{
      "schema_version": 2,
      "head_commit": "7a23d3926aa71c558d028788262e1dd8f0e6eace",
      "generated_plan_path": "docs/plans/2026-09-28-gitnexus-plan-s11-launcher-signing-vm.md",
      "global_dirty_digest": {
        "algorithm": "sha256",
        "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
        "value": "0a9c85780067d9afcd0764f307b60891e3cee927ee11eaeb5ec7826d10fd82cd"
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
          "head_digest": "sha256:c89250a093c90715c50700af1684baf4aa58ca95ef8150bf07914e3c69c3adfc",
          "index_digest": "sha256:c89250a093c90715c50700af1684baf4aa58ca95ef8150bf07914e3c69c3adfc",
          "worktree_digest": "sha256:2db0381da4865cef46ac879f5fc141af66df17defc43848db964b670fb4055b6",
          "untracked_digest": "absent"
        },
        {
          "path": "cli/src/ctx.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:829caf7fa5bebcd9201c7c41bf5fdabdb3386d72af32422c9b271ecedbd7fd2a",
          "index_digest": "sha256:829caf7fa5bebcd9201c7c41bf5fdabdb3386d72af32422c9b271ecedbd7fd2a",
          "worktree_digest": "sha256:829caf7fa5bebcd9201c7c41bf5fdabdb3386d72af32422c9b271ecedbd7fd2a",
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
          "path": "deploy/install_state.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b028c20ad84cca7323e72ec3602a358f10a3d15f7f12c22841b0f16b4022238d",
          "index_digest": "sha256:b028c20ad84cca7323e72ec3602a358f10a3d15f7f12c22841b0f16b4022238d",
          "worktree_digest": "sha256:cc2f295174af068b10599d62bb0cc371a232bda6742edee6e83814faa8a193a0",
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
          "head_digest": "sha256:1aecab6ecb0b494f7dec409fcee151003cbf6d82418a63f892ee8c1c844329db",
          "index_digest": "sha256:1aecab6ecb0b494f7dec409fcee151003cbf6d82418a63f892ee8c1c844329db",
          "worktree_digest": "sha256:9e8e32d69b3ce5d96304011f191115ae97a9b84387470e68c254205e8d4a5fdc",
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
          "head_digest": "sha256:98be988e1de86fe7e7b380de2f6f63eb40b0360361c1c21598ca1d114ca02781",
          "index_digest": "sha256:98be988e1de86fe7e7b380de2f6f63eb40b0360361c1c21598ca1d114ca02781",
          "worktree_digest": "sha256:98be988e1de86fe7e7b380de2f6f63eb40b0360361c1c21598ca1d114ca02781",
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
          "head_digest": "sha256:ef4b8d2e5dcc6cec009495d1432a8cb26303c86a43f1d3fde251f94be40cd4d0",
          "index_digest": "sha256:ef4b8d2e5dcc6cec009495d1432a8cb26303c86a43f1d3fde251f94be40cd4d0",
          "worktree_digest": "sha256:ef4b8d2e5dcc6cec009495d1432a8cb26303c86a43f1d3fde251f94be40cd4d0",
          "untracked_digest": "absent"
        },
        {
          "path": "desktop/src-tauri/src/commands.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4f67da7f6e11a77a134ae1147ed999f95f2bebba67b011cdbff2b8f73df53648",
          "index_digest": "sha256:4f67da7f6e11a77a134ae1147ed999f95f2bebba67b011cdbff2b8f73df53648",
          "worktree_digest": "sha256:adfaeed3aa30462897e4a0df617e2bd0ae2268a8b4db7c652c52dca1a1a15aa9",
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
          "head_digest": "sha256:304dff1df7b9e26b671afa2b64b99f3d906e0562b518aae291ed2f81cd8eec97",
          "index_digest": "sha256:304dff1df7b9e26b671afa2b64b99f3d906e0562b518aae291ed2f81cd8eec97",
          "worktree_digest": "sha256:24dcc15d34c7e8640243c47d31287a83cc73a05c228ffa891b80bba194a36f20",
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
          "path": "release_assets/start.bat",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b10a63a09b21ed701aa8a6d66140e039c3a1d38cf4b3fcbda10855f22eb2e7d2",
          "index_digest": "sha256:b10a63a09b21ed701aa8a6d66140e039c3a1d38cf4b3fcbda10855f22eb2e7d2",
          "worktree_digest": "sha256:b10a63a09b21ed701aa8a6d66140e039c3a1d38cf4b3fcbda10855f22eb2e7d2",
          "untracked_digest": "absent"
        },
        {
          "path": "release_assets/toolchain.json",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:dd62c5d815784fb8a116b1865c3d32a8f506a1f106bf2ce7042da77808712266",
          "index_digest": "sha256:dd62c5d815784fb8a116b1865c3d32a8f506a1f106bf2ce7042da77808712266",
          "worktree_digest": "sha256:dd62c5d815784fb8a116b1865c3d32a8f506a1f106bf2ce7042da77808712266",
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
          "path": "scripts/check_release_hashes.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:75a2efa827f35c88a02a52ce1e1b7eed85266fabe339d48301e1bda5bcbf6e55",
          "index_digest": "sha256:75a2efa827f35c88a02a52ce1e1b7eed85266fabe339d48301e1bda5bcbf6e55",
          "worktree_digest": "sha256:75a2efa827f35c88a02a52ce1e1b7eed85266fabe339d48301e1bda5bcbf6e55",
          "untracked_digest": "absent"
        },
        {
          "path": "scripts/test_nsis_install.ps1",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:90f804f447fd4e2b232305155abdcb1d83ad9aeb324f19dec32cb199b00cc570",
          "index_digest": "sha256:90f804f447fd4e2b232305155abdcb1d83ad9aeb324f19dec32cb199b00cc570",
          "worktree_digest": "sha256:90f804f447fd4e2b232305155abdcb1d83ad9aeb324f19dec32cb199b00cc570",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_install_contract.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:12fc656288b7d89ed9d27790c95292a927670902488c9ff018e975d71b5eecd4",
          "index_digest": "sha256:12fc656288b7d89ed9d27790c95292a927670902488c9ff018e975d71b5eecd4",
          "worktree_digest": "sha256:0aefb63133a50116ee67a491dd3a8f50ffe9ec9a2e5c7b5f26d0a7b64922a985",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/windows/test_nsis_hook_compiles.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:6d5c270d6f0037733f8d488b2fd2a28e391d81e5f163bf0bdf9a46102a2832d3",
          "index_digest": "sha256:6d5c270d6f0037733f8d488b2fd2a28e391d81e5f163bf0bdf9a46102a2832d3",
          "worktree_digest": "sha256:6596221a281efca88070c151db65b9dd3a3d4a7c856b991a673b8f7257d6e2e9",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/windows/test_nsis_installation.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:724dffde0b4b406de5cb4cd5f4f3c2f2a049348a821beba5c8549f7127569c6d",
          "index_digest": "sha256:724dffde0b4b406de5cb4cd5f4f3c2f2a049348a821beba5c8549f7127569c6d",
          "worktree_digest": "sha256:724dffde0b4b406de5cb4cd5f4f3c2f2a049348a821beba5c8549f7127569c6d",
          "untracked_digest": "absent"
        }
      ]
    "evidence_provenance":}
    "primary_symbols": [
      {"name": "project_root", "file": "desktop/src-tauri/src/python.rs", "lines": "1241-1268", "role": "激活优先的程序树解析（CRITICAL，direct=7）", "source_verified": true},
      {"name": "transactional_upgrade", "file": "deploy/upgrade.py", "lines": "145-216", "role": "升级原语与激活记录形态复用", "source_verified": true},
      {"name": "find_root", "file": "cli/src/ctx.rs", "lines": "96-106", "role": "CLI 根解析（cwd 上溯；launcher 设 cwd 后语义保持）", "source_verified": true},
      {"name": "build_catalog", "file": "scripts/build_release_catalog.py", "lines": "48-109", "role": "catalog 生成（--asset-base-url 消除自指）", "source_verified": true}
    ],
    "related_symbols": [
      {"name": "data_root", "relationship": "CALLS project_root", "relevance": "CRITICAL direct=7 的桥梁，不改签名"},
      {"name": "run_deploy_inner", "relationship": "CALLS project_root/find_python", "relevance": "子进程 cwd 必须是激活树"},
      {"name": "resolve (cli)", "relationship": "CALLS find_root", "relevance": "CLI 入口链"},
      {"name": "_cmd_upgrade", "relationship": "CALLS transactional_upgrade", "relevance": "回滚子命令挂载点"},
      {"name": "CheckIfAppIsRunning", "relationship": "NSIS 宏（utils.nsh）", "relevance": "Restart Manager 仅针对 Stella.exe"}
    ],
    "execution_path": [
      "release.yml: publish-candidate → build(+sign) → install-test → build 汇总 → 字节核对 → 发布 → 回读",
      "NSIS: .onInit → EarlyChecks → WebView2 →（交互升级：旧卸载器）→ PREINSTALL（升级留痕/预检查）→ 释放 → POSTINSTALL（离线装载/版本树搬移/激活记录）",
      "启动: launcher 读 %LOCALAPPDATA%\\Stella\\active-install.json → app\\<version>\\Stella.exe（cwd=树）",
      "GUI: project_root 激活优先 → data_root（S10a 指针）→ deploy",
      "回滚: deploy upgrade rollback → 记录翻转 → 重启生效"
    ],
    "pdg_constraints": [
      {"description": "project_root 签名行锚点无独立上游块（pdg-intra-procedural, 0 blocks）——整函数体替换型变更，语句级切片无增益", "affected_statements": [], "implementation_constraint": "约束以源码为准：候选顺序、containment、CARGO 兜底必须整体保留为回退"}
    ],
    "architectural_patterns": [
      {"pattern": "机器级外置指针/记录", "example_location": "config/home.py pointer + %LOCALAPPDATA%\\Stella\\", "usage_guidance": "激活记录与 journal 全部放 INSTDIR 外"},
      {"pattern": "原子 JSON 写入", "example_location": "deploy/upgrade.py _atomic_json", "usage_guidance": "记录写复用"},
      {"pattern": "按文件卸载盲区", "example_location": "installer.nsi Section Uninstall（923 Delete）", "usage_guidance": "版本树幸存机制，必须以 ownership journal 显式管理"},
      {"pattern": "构建开关双轨", "example_location": ".stella-versioned-layout 标记", "usage_guidance": "旧包/关闭态逐字节现状"}
    ],
    "files_to_modify": [
      {"file": "deploy/upgrade.py", "symbols": ["machine_active_record_path", "write_activation_record", "read_activation_record", "validate_activation_record", "rollback_activation"], "intended_change": "激活记录契约"},
      {"file": "desktop/launcher/", "symbols": ["new crate"], "intended_change": "稳定启动入口"},
      {"file": "desktop/src-tauri/installer-hooks.nsh", "symbols": ["NSIS_HOOK_POSTINSTALL 扩展"], "intended_change": "搬移/记录/稳定入口/GC"},
      {"file": "desktop/src-tauri/src/python.rs", "symbols": ["project_root"], "intended_change": "激活优先解析（回退保底）"},
      {"file": "scripts/build_release_package.py", "symbols": ["stage_installer_resources"], "intended_change": "launcher/标记 staging"},
      {"file": "scripts/build_release_catalog.py", "symbols": ["build_catalog"], "intended_change": "--asset-base-url"},
      {"file": "desktop/src-tauri/tauri.conf.json", "symbols": ["bundle.windows"], "intended_change": "签名配置接入"},
      {"file": ".github/workflows/release.yml", "symbols": ["sign-installers", "publish-candidate", "vm 触发"], "intended_change": "签名+候选+VM"},
      {"file": ".github/workflows/release-vm-validation.yml", "symbols": ["new"], "intended_change": "VM 矩阵作业"},
      {"file": "scripts/check_installer_size.py", "symbols": ["new"], "intended_change": "体积门禁"},
      {"file": "deploy/__main__.py", "symbols": ["_cmd_upgrade"], "intended_change": "rollback 子命令"}
    ],
    "tests": [
      {"file": "tests/test_upgrade.py", "scenarios": ["激活记录原子写/containment 拒绝/回滚翻转/损坏记录"]},
      {"file": "tests/test_install_contract.py", "scenarios": ["搬移钩子源码断言/开关标记/GC 不删唯一旧版/签名步骤顺序断言"]},
      {"file": "tests/windows/test_nsis_hook_compiles.py", "scenarios": ["四钩子含新 POSTINSTALL 编译"]},
      {"file": "tests/test_build_release_catalog.py（新或并入 product_profiles）", "scenarios": ["--asset-base-url 覆盖自指 URL"]},
      {"file": "desktop/src-tauri/src/python.rs 内联测试", "scenarios": ["记录存在→树路径/缺失→回退/损坏→回退/越界→拒绝"]},
      {"file": "tests/windows/test_nsis_installation.py", "scenarios": ["VM 六场景 harness 参数化"]}
    ],
    "verification_commands": [
      "python -m pytest tests/test_upgrade.py tests/test_install_contract.py tests/test_nsis_bootstrap_helper.py tests/windows -q",
      "cargo test（desktop/src-tauri 与 desktop/launcher，Windows MSVC）",
      "node %LOCALAPPDATA%\\tauri\\NSIS makensis 门禁：python -m pytest tests/windows/test_nsis_hook_compiles.py -q",
      "python -m ruff check deploy scripts tests",
      "MSYS_NO_PATHCONV=1 docker exec -w /repo stella-gitnexus gitnexus detect-changes --scope all --repo Stella_project",
      "本地真装演练：cargo tauri build --bundles nsis + scripts/test_nsis_install.ps1"
    ],
    "risks": ["project_root CRITICAL：回退优先+两态测试", "版本树幸存依赖模板按文件卸载：tauri-cli 升级必须重验", "launcher 变砖：枚举兜底+错误对话框", "搬移失败：恢复现布局", "签名/VM 凭据外部依赖：门控不伪装"],
    "assumptions": ["模板按文件卸载在 2.12.0 成立（升级 CLI 重验）", "%LOCALAPPDATA%\\Stella\\ 可写", "$INSTDIR 同卷 rename 可用", "launcher 无需提权清单"],
    "open_questions": ["签名方案选型", "交互升级是否切 /UPDATE 语义", "VM 宿主预算", "候选保留代数", "stella-installer 壳去留"],
    "avoid": [
      "不要改 prepare_runtime 函数体（改动经 project_root 进入）",
      "不要在无记录时改变任何现有解析行为（回退必须逐字节兼容）",
      "不要用 RMDir /r 清理版本树（只能按 ownership journal 逐代）",
      "不要让 GC 删除唯一可用旧版",
      "不要在无签名凭据时放行正式 tag 发布",
      "不要删除仍被已发布安装器引用的候选资产",
      "不要以未签名字节做正式安装验收"
    ]
  }
}
```

> 注：`evidence_provenance` 完整值（schema 2、head_commit、global_dirty_digest、19 条 cited_path_manifest）由助手在发布时内嵌至文档头部的证据行与本节之间；上方 `see_below` 占位以实际内嵌为准。

## 12. 假设与开放问题

**假设**（实施前须廉价复核）：
1. 模板按文件卸载行为在锁定的 2.12.0 下持续成立——每次 tauri-cli 升级重验 installer.nsi；
2. `%LOCALAPPDATA%\Stella\` 可作为机器级记录/journal 目录（与 S10a 指针同级）；
3. 同卷 rename 在 `$INSTDIR` 常规位置可用（跨卷安装是用户的非常规选择，失败路径已定义）；
4. launcher 以 ShellExecute 启动 GUI 不需要额外清单（无提权）。

**开放问题（维护者决策点）**：
1. 签名方案选型：Azure Trusted Signing vs EV 证书（HSM）vs 云签名服务——管道对三者等价开放；
2. 交互式升级是否改为默认 /UPDATE 语义（跳过旧卸载、完全依赖版本树）——建议 Phase 2 稳定后切换；
3. VM 基础设施预算与宿主机（Hyper-V 宿主规格、Windows 许可）；
4. 候选保留代数 N=6 与 GC 策略确认；
5. stella-installer 旧壳的长期去留（一致性测试 vs 迁移删除）。

**明确延后**：ARM64/32 位；SBOM 生成；自动更新服务；遥测（维持无遥测立场）。

## 13. 完成定义

- [ ] 升级（交互+静默）后旧版本树保留于 `app\`，`deploy upgrade rollback` 一键切回且数据根不变；
- [ ] GUI 全部 21 个受影响入口在「记录存在/缺失/损坏」三态下行为正确（cargo test + 21 项对账）；
- [ ] launcher 在记录有效/缺失/全损坏三态下行为正确；
- [ ] 四产物签名后通过 install-test，发布字节=验收字节=用户字节（sha256 三方一致）；
- [ ] catalog 零自指 URL：所有依赖在发布可见时存在且摘要一致（回读校验过）；
- [ ] 干净 VM 上 T01/T02/T03/T11/T14/T18 自动化通过，报告归档；T 矩阵其余项分级映射表存档；
- [ ] 体积门禁生效且基线有实测依据；发布文档与实际行为一致；
- [ ] 全部提交过 pytest/cargo test/makensis/ruff/detect-changes 门禁。
