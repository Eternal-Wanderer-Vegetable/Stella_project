# Corona / Nucleus CN01 实施记录

日期：2026-10-23（Asia/Shanghai）。状态：**CN01 完成，CN02 待开始；CORONA-IMPL 仍 NOT READY。**

## 范围与图影响

分支 `codex/corona-nucleus-implementation`，CN01 基于 `f9d6920`（CN00 完成提交）。实施前 GitNexus 索引绑定到该 HEAD，GitNexus 1.6.12 / PDG；分析保留上游报告的文件大小、入口候选、分支预算和跨语言边限制，UNKNOWN/缺失流程不作为“无调用”证据。

| 目标 | 编辑前 upstream impact | 直接影响 |
| --- | --- | --- |
| `config/__init__.py` | CRITICAL，205 个受影响 / 69 个直接 | bot、capability、core 等运行入口 |
| `config/home.py` | CRITICAL，236 / 5 | cometa/config、settings、deploy 与 release-layout 检查 |
| `config/instance.py` | CRITICAL，218 / 2 | settings 与 deploy process |
| `config/settings.py` | CRITICAL，278 / 76 | AstrBot 兼容、bot、capability、core、WebUI 等；编辑前已在评论中提示高风险 |
| adapter/env 解析、schema 与 envfile | LOW：分别 4/2、11/3、15/3、10/4 | adapter 装配、deploy 配置合并/schema、多个 WebUI 配置流程 |
| `scripts/build_release_package.py` | UNKNOWN / 0 图调用者 | 源码补查 `.github/workflows/release.yml`、评估脚本、测试；新包需加入公共发行目录 |
| 新测试文件与新增包 | 新文件无既有图节点；既有 fixture 文件 UNKNOWN / 0 | 由 import fence、发行布局和专项回归补证 |

既有图查询 `resolve` 的调用集合有大量接收者类型未知导致的丢边；adapter/配置动态流程也有入口截断。相关生产入口以源码与测试补证，不把低风险当作遗漏调用的豁免。新增发行包目录 `stella_bootstrap`、`stella_contracts` 已同步加入 standalone/installer 的公共发行清单与对应测试夹具。

## 实施内容

- 新增 `stella_bootstrap/`：集中 home、identity、adapter-name、dotenv/raw-env 解析、schema AST 读取和 config revision 生成/读回；旧 `config.home`、`config.instance`、`deploy.env_schema` 与 adapter parser 保持兼容出口。
- 新增 `stella_contracts.ConfigRevision`：不可变 revision 合同、严格字段/来源校验、映射只读、脱敏公开元数据；未知插件键保留。revision 使用不透明 ID、逐来源摘要及一次写入文件。
- 配置构建在纯函数式输入上明确 defaults < base `.env` < captured external env < 当前 profile overlay 的优先级；`ENVIRONMENT` 由 base/外部环境选择，不被 overlay 改选。控制身份键、操作系统变量和 revision marker 不写入业务配置。解析复用 python-dotenv 的语法与变量展开器，并把合成输入传入，不读取用户 home。
- POSIX revision 文件及五级目录使用 0600/0700，并拒绝宽权限、符号链接和不匹配的存储路径；写入使用临时文件、文件 fsync、原子替换和目录 fsync。Windows 通过当前用户 SID 配置 `icacls` 私有 ACL，但本机未执行 Windows 验收。
- `STELLA_CONFIG_REVISION_FILE` 为显式 opt-in。managed `config.settings` 只读该 revision，验证项目根匹配、跳过两层 dotenv 加载，并不以宿主进程的旧业务环境值覆盖快照；未设置 marker 时沿用 legacy dotenv 路径。保留 `PROJECT_ROOT` 为项目 cwd，不调用 `chdir`。
- WebUI `envfile` 对 settings 改为函数内延迟导入，避免仅导入叶子服务时触发整套业务配置加载。
- 发布包 `COMMON_DIRS` 和 standalone/OneClick 夹具均包含两新包，避免源码测试通过但实际产品缺少运行时模块。

## 验收证据

| 检查 | 结果 |
| --- | --- |
| CN01 配置 revision、dotenv、home/identity/schema/merge、adapter、WebUI、发行布局及 CN00 合同专项 | **148 passed / 3.12s**；隔离 `STELLA_HOME=/tmp/stella-cn01-isolated-home-20261023` |
| Ruff（所有本包改动模块与测试） | 通过 |
| 全仓 Python Ruff（`ruff check .`） | 通过 |
| `compileall`（新增 bootstrap/contracts 及相关改动模块） | 通过 |
| revision 数据和权限 | 连续 revision 子进程隔离、外部环境优先级、空值/继承/删除路径语义、未知键保留、已知类型拒绝、只读值、脱敏 metadata、文件与父目录权限拒绝均有合成回归 |
| import fence / cwd | 新子进程 import 不装载受围栏的 legacy 业务模块；合成 cwd 保持不变，revision 外目录 dotenv 不污染配置 |
| legacy 配置基线 | 旧 home、instance、env merge/schema、adapter 与 WebUI 设置回归纳入上述定向集合；managed 未设置时保留 legacy 分支 |
| 文档状态 | `python3 scripts/check_docs.py`：119 files / 1269 local links / 577 anchors / 0 errors；`git diff --check` 通过 |
| 用户数据边界 | 使用临时 STELLA_HOME 与合成 dotenv；未读取宿主 `.env`、真实聊天、生产库或凭据，未启动 Bot、模型或平台 |

全量 Python suite 两次均未全绿：首次 **4027 passed / 29 skipped / 2 failed / 238.99s**；第二次 **4028 passed / 29 skipped / 1 failed / 243.96s**。首次失败的 Cometa worker-policy ACK、WebUI trace detail 与第二次失败的 Cometa unknown-session 测试各自单独重跑都通过。失败集合不同，未确认共同根因或与 CN01 的因果关系；不能把单项重跑说成全量通过。此处保留为回归稳定性缺口。

## GitNexus 提交门禁

最终强制重建索引在 1.6.12 / PDG 下成功：106,344 nodes / 265,516 edges / 1,115 clusters / 823 inferred flows；`status` 显示 1,926 个 covered files 内容匹配并 up-to-date。分析仍跳过 34 个大文件，报告 2,910/3,110 个入口候选未排名、807 个 callee 分支、42 次 walk 预算截断、25 次 trace 深度上限及 317 个跨语言字段位点；属性流还对 33 候选触发 cap=32。流程图是有界近似，不能证明遗漏路径不存在。

提交前串行运行：

| 命令 | 结果 |
| --- | --- |
| `node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project --limit 1000` | 28 files / 154 symbols / 57 affected processes / **CRITICAL** |
| `node .gitnexus/run.cjs detect-changes --scope compare --base-ref main --repo Stella_project --limit 1000` | 135 files / 287 symbols / 57 affected processes / **CRITICAL**，含 main 继承的计划/CN00 工作 |

两条输出均未报告 partial/truncated；all 与 compare 串行执行。CRITICAL 是 settings/config 广泛既有调用图的 cumulative impact，不抵消专项回归结果，也不替代全量与外部验收。

当前本机验证没有运行 Windows ACL 分支、完整 Python suite、真实 NoneBot managed Nucleus 进程、QQ/WebChat、Docker 或 clean VM；这些不是 CN01 的本地专项结果。Windows ACL 的实际行为仍待 Windows 环境验证。产品仍 **NOT READY**。

## 下一步

进入 CN02：在本阶段 snapshot Driver spike 与受控配置来源之上，实现 Nucleus framework adapter、启动顺序和有界生命周期。managed framework 的私有桥接必须集中于 `nucleus/framework.py`；生产子进程 ready/drain/退出、源配置变更隔离、双核心与超时失败语义必须有独立退出证据。
