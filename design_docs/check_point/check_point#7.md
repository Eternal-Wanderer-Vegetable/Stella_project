# check_point#7：v3.1.0 pre-release 三项缺陷的修复方案

> 记录日期 2026-08-27。来源：v3.1.0 pre-release 实机验证。
> 前置文档：`design_docs/升级与数据迁移方案 v1.0.md`（下称「v1.0 方案」）。

## 0. 摘要

| # | 现象 | 根因 | 性质 | 建议优先级 |
|---|---|---|---|---|
| 1 | 导入配置后不生效，重启 GUI 才对 | `python.rs:631` 的 `OnceLock` 把数据目录缓存了整个进程生命周期 | 实现缺陷，改动小 | P0，必修 |
| 2 | `StellaData` 落在 `Stella-v3.1.0-win64\` 里，与仓库结构不符 | 发布包多一层 `Stella\` 嵌套，把「安装目录的同级」顶成了「版本文件夹的内部」 | **设计目标被架空**，需决策 | P0，必修 |
| 3 | 「从旧版本导入」是独立菜单项 | 信息架构问题 | 交互改进 | P1 |

问题 2 牵涉一个需要你拍板的分歧：**你提出的「把 StellaData 放进 Stella 文件夹内部」会撤销
v1.0 方案 P1 的核心目标**（升级 1 步、数据不随版本文件夹被删）。§2.4 给了一个同时满足
「结构统一」与「升级安全」的折中，建议采用；若仍选原提案，§2.6 列出必须配套的保护措施。
**本文只是方案，未动代码。**

---

## 1. 缺陷一：导入完成后配置不生效，必须重启

### 1.1 现象

用户在 GUI 里完成「从旧版本导入」，报告显示成功，但配置页仍是空的 / 旧的；关掉 GUI 重新
打开才正确。

### 1.2 根因：Rust 侧把数据目录缓存了整个进程生命周期

`stella-installer/src-tauri/src/python.rs:631-648`：

```rust
pub fn data_root() -> PathBuf {
    static CACHE: OnceLock<PathBuf> = OnceLock::new();
    CACHE.get_or_init(|| { /* 跑一次 deploy paths，取 stella_home */ }).clone()
}
```

`OnceLock` 只初始化一次，此后永不更新。而 GUI 的启动时序恰好保证了**这次初始化必然发生在
导入之前**（`stella-installer/src/index.html:47-52`）：

```text
1. getConfig()              → commands.rs:116 调 data_root() → OnceLock 就地定死
   此刻 StellaData 还不存在、指针文件也还没写，deploy paths 返回的是
   config/home.py 第 4 条的「将来会建在哪」，或回退值 PROJECT_ROOT
2. hasImportableInstall()   → runMigrate({dryRun:true})，create=False，不写指针
3. 用户点确认 → run_migrate → deploy migrate
   __main__.py:222 的 home.resolve(PROJECT_ROOT, create=True) 这时才真正
   mkdir StellaData 并 write_pointer()
4. 之后所有 data_root() 调用仍返回第 1 步的旧值
```

受影响的是全部 6 个调用点：`commands.rs:116`（get_config 读 `.env`）、`151`、`186`
（save_config 写配置）、`288`（人格列表）、`357`（保存人格）、`397`（日志路径）。
所以不只是「配置不显示」——**导入后在 GUI 里保存配置，会写到错误的目录**，这比读不到更糟。

「重启后正常」也解释得通：新进程重跑 `deploy paths`，此时指针文件已存在，
`config/home.py:119-121` 第 2 条命中，返回真正的 `StellaData`。

Python 侧没有这个问题：每次 `run_deploy` 都是新子进程，`config/home.py` 会重新解析。
**缓存只存在于 Rust 一侧**，这一点决定了修复面很小。

### 1.3 修复

主修（Rust）——把「一次性缓存」换成「可失效缓存」：

```rust
static CACHE: RwLock<Option<PathBuf>> = RwLock::new(None);

pub fn data_root() -> PathBuf { /* 命中直接返回，未命中则解析并写入 */ }

/// 任何可能改变数据目录位置的操作之后必须调用。
pub fn invalidate_data_root() { *CACHE.write().unwrap() = None; }
```

调用点：`run_migrate` 成功且 `dry_run == false` 之后、`save_config` 成功之后
（`deploy init --force` 也会 `create=True` 建目录写指针）。

不直接改成「每次都跑一次 `deploy paths`」的原因：那是一次 Python 子进程启动
（约 100~300ms），而 `data_root()` 在日志轮询等路径上会被高频调用。缓存 + 显式失效
在成本和正确性之间是合适的。

配套（前端）：`migrate.html` 在导入成功后重新拉一次配置再跳转，让「刚导入的值」立刻
可见，而不是依赖用户手动切页。

### 1.4 防复发

`data_root()` 的文档注释里写明**不变量**：「任何写指针文件或建数据目录的命令之后，必须
`invalidate_data_root()`」。这类「缓存 + 会变的底层状态」的组合，将来新增命令时最容易忘，
注释要写在缓存本身上而不是调用点上。

---

## 2. 缺陷二：数据目录落在版本文件夹内部

### 2.1 实测现状

发布流程（`.github/workflows/release.yml:104-105, 191`）：产物先组装进 `dist/Stella/`，
再 `zip -r "Stella-<ref>-win64.zip" Stella` —— **zip 内部带一层 `Stella/` 目录**。

用户侧：Windows 资源管理器解压默认建一个与 zip 同名的文件夹，于是：

```text
D:\Stella_working_space\
  Stella-v3.1.0-win64\        ← 解压产生（zip 名）
    Stella\                   ← zip 内部自带的那一层  = 程序目录 PROJECT_ROOT
    StellaData\               ← config/home.py:126 的 install_root.parent/StellaData
```

`config/home.py:126` 写的是 `install_root.parent / DEFAULT_DIR_NAME`，语义是
「安装目录的**同级**」。多出来的这一层 `Stella\` 让「同级」正好落进了版本文件夹**内部**。

### 2.2 为什么这是缺陷，而不只是不好看

v1.0 方案 §6 把数据挪出安装目录，要解决的就是「解压新版 = 人和数据分家」。现在的位置让它
只兑现了一半：

- **数据仍绑在版本文件夹上**。用户升级后按常识清理 `Stella-v3.1.0-win64\`，
  连带删掉的是自己的全部记忆、配置和人格。指针文件此时指向一个已被删除的目录，
  `read_pointer()` 的 `is_dir()` 判空返回 None，程序静默退回「新建数据目录」——
  用户看到的是「一切正常但什么都不记得了」，与 v1.0 方案 §4.3 描述的最坏体验同构。
- **目录名有误导性**。`Stella-v3.1.0-win64\StellaData` 读起来就是「v3.1.0 的数据」，
  强化了「删旧版本 = 删旧版本的东西」这个错误直觉。

也就是说：这一项不修，v1.0 方案 P1 等于没做。

### 2.3 三个候选方案

| | 方案 A（你的提案） | 方案 B | 方案 C（推荐，见 §2.4） |
|---|---|---|---|
| 位置 | `…\Stella-v3.1.0-win64\Stella\StellaData` | `D:\Stella_working_space\StellaData` | 默认同 B，但显式放内部时也认 |
| 与仓库结构一致 | 一致 | 不一致 | 一致（仓库走「显式放内部」这条） |
| 删旧版本文件夹 | **数据全丢** | 安全 | 安全 |
| 每次升级操作数 | 解压 → 必须再跑一次导入 | 解压 → 双击（指针自动接上） | 解压 → 双击 |
| 是否兑现 P1 目标 | 否 | 是 | 是 |

关于方案 A 需要说清楚的一点：把数据放进程序目录，**升级时数据不会自动接上**。指针文件确实
会让新版本找到旧版本文件夹里的 StellaData，但那意味着「运行 v3.2.0 的程序、数据却躺在名为
v3.1.0 的文件夹里」——用户一旦清理就是不可逆的数据丢失。这正是 v1.0 方案 §0 把
「此后每次升级 = 解压 → 双击，1 步」列为目标时要消除的东西。

### 2.4 推荐方案 C：默认在外，显式在内也认

两处改动，互相独立：

**(1) 去掉发布包的嵌套层**，让「安装目录的同级」回到它本来的含义。

`release.yml` 的打包步骤改为从 `dist/Stella/` 内部打包（zip 根直接是程序文件）：

```bash
cd dist/Stella && zip -q -r "../Stella-${RELEASE_REF}-win64.zip" .
```

解压后：

```text
D:\Stella_working_space\
  Stella-v3.1.0-win64\      ← 程序目录（升级整体替换 / 可安全删除）
  StellaData\               ← 用户数据（版本中立，升级不动）
```

这同时消掉了 `Stella-v3.1.0-win64\Stella\` 这个重复命名。
需同步调整：`release.yml` 的 zip 内容校验步骤（`unzip -l` 的几处 grep 路径前缀）、
`scripts/check_release_layout.py` 的入参、`release_assets/README-快速开始.txt` 的目录示意。

**(2) `config/home.py` 增加一条解析规则**：`<安装目录>/StellaData` 已存在 → 就用它。

插在现有第 3 条（旧布局判据）与第 4 条（新建默认目录）之间：

```text
1. 环境变量 STELLA_HOME
2. 机器级指针文件
3. 安装目录本身像用过的旧布局（.env / memory/agent_memory.db）→ 就地使用
3.5 <安装目录>/StellaData 存在 → 用它（便携模式 / 开发仓库走这条）   ← 新增
4. 都没有 → <安装目录>/../StellaData，并写指针文件
```

这条规则让「自带数据的便携目录」成为一个受支持的布局：谁想把整个 Stella 连数据拷进 U 盘，
建一个 `StellaData` 子目录即可；而**默认**仍然是安全的外置位置。开发仓库正好走这条
（见 §2.5），于是仓库、发布包、运行期三者的**相对布局**统一为「数据在 `StellaData/` 里」，
差别只在这个目录挂在哪一层——这也正是你想要的「统一」。

### 2.5 仓库结构统一（与 §2.4 的选择正交）

把开发机的用户数据也收进 `StellaData/`：

```text
stella_project/
  StellaData/          ← 新增，整体 gitignore
    .env  deploy.answers.toml
    memory/  config/spaces/  system_prompts/  data/  logs/
  bot.py  config/  deploy/  memory/  …   ← 程序代码，不动
```

改造面：

| 项目 | 动作 |
|---|---|
| `config/home.py` | 加 §2.4(2) 的第 3.5 条 |
| `.gitignore` | 加 `StellaData/`；移除已被它覆盖的逐条规则（`logs/`、`memory/*.db`、`memory/.space_assignments.json` 等） |
| `.github/workflows/release.yml` | rsync 排除清单加 `StellaData/` |
| `scripts/check_release_layout.py` | 清单闭环校验按新前缀比对 |
| `deploy/migrate.py` 的 `USER_DATA` | **相对路径不变**——它描述的是 STELLA_HOME 内部的相对布局，而这个布局本来就没变。这正是 `config/home.py` 开头那段「内部布局与旧安装完全一致」的设计红利 |
| 开发者迁移 | 一次性：把现有 `.env`、`memory/`、`config/spaces/`、`system_prompts/`、`data/` 移进 `StellaData/`。写进 `docs/development.md`，并在 `deploy doctor` 里给一条提示 |
| 测试 | `tests/test_stella_home.py` 增「第 3.5 条命中」用例；`tests/conftest.py` 检查是否有隐式依赖仓库根即数据根的夹具 |

`config/settings.py` 的路径常量**一行都不用改**：它们已经全部挂在 `STELLA_HOME` 上，
移动的是这个变量的取值，不是它的用法。

### 2.6 若仍决定采用方案 A

那么以下三条必须同时做，否则「删掉旧版本文件夹」这个动作迟早会吃掉某个用户的全部数据：

1. **启动时检测「指针指向的 StellaData 不在当前程序目录内」**，弹一条显式警告并提供
   「把数据搬到当前目录」的一键操作；
2. 在版本文件夹里放一个 `请勿删除此文件夹—您的数据在里面.txt` 之类的标记文件；
3. `release_assets/README-快速开始.txt` 与升级说明里，把「升级后不要删除旧文件夹，
   先完成导入」写成显著警告。

这三条加起来的复杂度高于方案 C，收益却更低——这是我建议方案 C 的实质理由。

---

## 3. 缺陷三：「从旧版本导入」的菜单位置与命名

### 3.1 现状

`config.html:18`、`doctor.html:18`、`persona.html:18`、`run.html:20`、`migrate.html:18`
各有一份相同的顶栏，「从旧版本导入」与「运行状态 / 配置 / 人格设定 / 环境自检」并列。

问题在于权重不对：其余四项是**长期都要用**的功能，导入是**一次性**的。把一次性动作放在
常驻导航里，既占位置，也让老用户每次都要看见一个自己再也用不到的入口。

### 3.2 改动

1. **改名**：全部「从旧版本导入」→「配置导入」（`migrate.html:11` 的 `<h1>` 一并改）。
2. **移出顶栏**：5 个文件的 `nav.top-nav` 删掉该链接，顶栏回到 4 项。
3. **并入配置页**：`config.html` 里加一个小节——

   ```text
   ┌ 从旧版本导入配置 ───────────────────────┐
   │ 有 3.0.0 或更早的安装？可以把配置、记忆、  │
   │ 人格和插件数据一次性搬过来。              │
   │                        [ 打开配置导入 ]   │
   └──────────────────────────────────────┘
   ```

   放在配置表单**下方**：新用户的主线是填配置，导入是支线，不该抢在主线前面。
4. **保留 `migrate.html` 作为独立页面**：`index.html:50-52` 的自动路由
   （未配置且探测到旧安装 → 直接进导入页）是存量用户的正确起点，逻辑不变。
   页面本身仍可直达，只是不再挂在顶栏。
5. 返回路径：`migrate.html` 的「返回」指向 `config.html`，与新的从属关系一致。

### 3.3 可选增强

`config.html` 的那个小节可以按 `migrate --dry-run` 的结论决定措辞：探测到旧安装时显示
「检测到 D:\… 的旧安装」，没探测到就显示「手动选择旧版本目录」。判据 `index.html:28-36`
已经有了，直接复用即可；但要注意 `--dry-run` 会真的预演一遍数据库，别放在页面加载的
同步路径上阻塞渲染。

---

## 4. 交付顺序

| # | 内容 | 涉及文件 | 依赖 |
|---|---|---|---|
| 1 | `data_root` 可失效缓存 + 调用点失效 | `python.rs`、`commands.rs` | 无 |
| 2 | 导入成功后前端重新拉配置 | `migrate.html`、`api.js` | 1 |
| 3 | `config/home.py` 第 3.5 条 + 测试 | `config/home.py`、`tests/test_stella_home.py` | 无 |
| 4 | 发布包去掉 `Stella/` 嵌套层 | `release.yml`、`check_release_layout.py`、`README-快速开始.txt` | 无 |
| 5 | 仓库数据收进 `StellaData/` | `.gitignore`、`release.yml`、`docs/development.md` | 3 |
| 6 | UI 改名 + 并入配置页 | `stella-installer/src/*.html` | 无 |

1~2 是纯缺陷修复，可以先单独发一个 pre-release 验证。3~5 建议同批，因为它们共同定义
「数据目录在哪」，分批发布会出现两个版本对同一台机器给出不同答案的窗口期。

## 5. 验证

- **缺陷一**：全新目录启动 GUI → 走完导入 → **不重启**，直接进配置页确认值已加载；
  再改一个值保存，确认写进的是 `StellaData/.env` 而不是程序目录。
- **缺陷二**：解压 v3.1.0 → 配置并运行 → 解压 v3.2.0 到同级 → 双击启动，
  确认数据自动接上；**再删掉 v3.1.0 的文件夹**，确认数据仍在、程序仍正常。
  这一条是本次修复的核心断言。
- **便携模式**：手工建 `<安装目录>/StellaData` → 确认第 3.5 条命中，`doctor` 显示来源正确。
- **缺陷三**：4 个页面顶栏无该项、配置页可进入导入页、`index.html` 自动路由不受影响。
- 全部走 `deploy doctor`：`stella_home` 与 `version_marks` 两条结论都要与实际布局相符。

> 按 v1.0 方案 §9 的既定规矩，涉及数据目录的改动**必须用真实发布包验证，不能用开发机这份
> 目录**——开发机的副本被手工改过，`data/plugins/` 又是 gitignore 的，缺口正是这样漏到
> release 的。本次缺陷二本身就是一个佐证：它只在「按 zip 解压」的真实布局下才出现。
