# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""``deploy migrate``：把旧安装目录里的用户数据搬到当前目录，并升级数据库。

为什么需要它：用户数据与程序在同一个目录，而发布包是整目录 zip
（``config/settings.py`` 的路径全锚在 ``PROJECT_ROOT``，``release.yml`` 打包时把用户
数据排除）。于是「解压到新目录」这个动作本身就把用户和他的数据分开了。

两条铁律：

1. **只读旧目录**。全程不写、不删、不移动旧目录的任何文件。任何一步失败，用户的
   旧安装都还在原地能跑，可以原地重跑本命令。
2. **不覆盖目标已有的用户数据**。目标已经有 ``agent_memory.db`` 说明用户已经用过
   新版本，覆盖等于毁掉他这段时间的记忆——那种情况只报告、不动手。
   ``.env`` 是唯一例外：它走合并（新模板骨架 + 旧值），不是覆盖。

用户视角就两步：解压新版 → 双击启动后点「从旧版本导入」（GUI 调的就是本命令）。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from config import space_map, state

from . import env_merge, manifest

if TYPE_CHECKING:  # 只为类型标注：运行时不 import memory.*（那会连带拉起整个记忆层）
    from memory.migrations import MigrationReport

# ── 用户数据清单：全项目「什么是用户数据」的唯一定义 ──────────
#
# 迁移、CI 的清单闭环校验、将来 P1 的数据目录布局都从这里派生。之前这份清单
# 只存在于 README-快速开始.txt 里，而且只写了 2 项（.env 与 agent_memory.db），
# 漏掉的每一项都造成静默故障——最危险的是 .space_assignments.json：账本丢了会
# 重新分配 space_N，记忆全挂在旧空间名下，表现为「一切正常但什么都不记」。
USER_DATA: tuple[str, ...] = (
    ".env",
    "deploy.answers.toml",
    "memory/agent_memory.db",
    "memory/stella_memory_backup.db",
    "memory/.space_assignments.json",
    "memory/.last_message_cleanup",
    "config/spaces/",
    "system_prompts/",
    "config/capabilities/",
    "data/plugins/",
    "data/config/",
    "data/plugin_data/",
)

# 发布包自带、用户可能改过的文件：走「改过才保留」判定（见 deploy/manifest.py）
SHIPPED_EDITABLE: tuple[str, ...] = ("system_prompts/", "config/capabilities/")

# 永不迁移：日志、缓存、临时产物。带过去只会让新安装继承一堆无意义的历史。
NEVER_MIGRATE: tuple[str, ...] = (
    "logs/",
    "data/render_cache/",
    "__pycache__/",
    ".stella-stop-request",
)

# 嵌入式 Python 运行时：默认复用（100MB+，重下很痛），可用 --fresh-runtime 强制重建
RUNTIME_DIR = "runtime"
DEPS_MARKER = ".stella-deps-ready"


@dataclass
class ItemResult:
    """单个迁移项的结果。``action`` 是给人看的短语，报告里直接用。"""

    path: str
    action: str
    detail: str = ""


@dataclass
class MigrateReport:
    """整次导入的结果。GUI 直接渲染 :meth:`to_markdown`。"""

    source: Path | None = None
    target: Path | None = None
    program_root: Path | None = None
    source_version: str | None = None
    target_version: str | None = None
    dry_run: bool = False
    items: list[ItemResult] = field(default_factory=list)
    env_report: env_merge.EnvMergeReport | None = None
    db_report: MigrationReport | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        if self.error:
            return False
        db = self.db_report
        return not (db is not None and not getattr(db, "ok", True))

    def add(self, path: str, action: str, detail: str = "") -> None:
        self.items.append(ItemResult(path=path, action=action, detail=detail))

    def to_markdown(self) -> str:
        title = "# 从旧版本导入" + ("（预演，未落盘）" if self.dry_run else "")
        lines = [title, ""]
        lines.append(f"- 来源目录：`{self.source}`" if self.source else "- 来源目录：未找到")
        if self.source_version:
            lines.append(f"- 来源版本：{self.source_version}")
        if self.program_root:
            lines.append(f"- 程序目录：`{self.program_root}`")
        if self.target and self.target != self.program_root:
            lines.append(f"- 用户数据目录：`{self.target}`（升级时不会被覆盖）")
        elif self.target:
            lines.append(f"- 目标目录：`{self.target}`")
        if self.target_version:
            lines.append(f"- 目标版本：{self.target_version}")
        if self.error:
            lines += ["", f"**导入失败**：{self.error}", "", "旧目录未被改动，可原地重跑。"]
            return "\n".join(lines)
        lines += ["", "## 文件", "", "| 项目 | 结果 | 说明 |", "|---|---|---|"]
        for item in self.items:
            lines.append(f"| `{item.path}` | {item.action} | {item.detail or '—'} |")
        if self.env_report:
            lines += ["", self.env_report.to_markdown()]
        if self.db_report is not None:
            lines += ["", self.db_report.to_markdown()]
        if self.warnings:
            lines += ["", "## 需要你注意", ""] + [f"- {w}" for w in self.warnings]
        return "\n".join(lines)


# ── 旧安装目录的探测 ────────────────────────────────────


def read_version(root: Path) -> str | None:
    """从 ``pyproject.toml`` 读版本号（发布包里就是靠这一行标版本的）。

    判据只有 ``config/state.py`` 一份：同一个「版本号从哪来」的问题在两处各解析一遍，
    迟早会一边认 ``version = "3.0.0"``、另一边认别的写法。
    """
    return state.program_version(root)


def looks_like_install(path: Path) -> bool:
    """像不像一个装过 Stella 的目录：有记忆库或有 .env，且有 bot.py。

    只认「有用户数据」的目录——一个刚解压、还没配置过的目录没有任何可导入的东西。

    **任何 OSError 一律判为「不是」**：探测会走到用户机器上的任意目录，其中必然有读不了的
    （Linux 的 ``/boot/lost+found`` 是 root 0700、Windows 有系统保留目录、还有断链的网络盘）。
    在一个「像不像」的判断里让异常逃出去，等于让一个无关目录的权限问题炸掉整个导入流程。
    """
    try:
        if not path.is_dir() or not (path / "bot.py").is_file():
            return False
        return (path / "memory" / "agent_memory.db").is_file() or (path / ".env").is_file()
    except OSError:
        return False


def _data_mtime(path: Path) -> float:
    """用记忆库（其次 .env）的修改时间代表「这份安装有多新」。"""
    for candidate in (path / "memory" / "agent_memory.db", path / ".env"):
        try:
            if candidate.is_file():
                return candidate.stat().st_mtime
        except OSError:
            continue
    return 0.0


def _scan_roots(target: Path) -> list[Path]:
    """要扫的几处起点。

    盘根（``target.anchor``）是为 Windows 准备的：``D:\\Stella-3.0.0`` 是常见解压位置。
    但在 POSIX 上 anchor 恒为 ``/``，扫它意味着走遍 ``/boot`` ``/proc`` ``/sys`` ``/dev``
    ——既慢又全是读不了的路径，而没有人会把 Stella 解压到文件系统根目录下。
    """
    home = Path.home()
    roots = [target.parent, target.parent.parent, home / "Desktop", home / "Downloads"]
    anchor = target.anchor
    if anchor and anchor != "/":
        roots.append(Path(anchor))
    return roots


def detect_sources(target: Path, *, limit: int = 400) -> list[Path]:
    """扫常见位置找旧安装目录，按数据新旧排序（最新在前）。

    只扫「兄弟目录、伯父目录、桌面/下载、盘根」这几处的两层深度：用户解压时几乎
    总落在这些地方（``Downloads/Stella-v3.0.0/Stella/`` 这种嵌套所以要两层）。
    刻意不做全盘扫描——那会慢到让人以为程序卡死，而且会翻出备份副本造成误导。

    **本函数不抛异常**：探测失败最多是「没找到」，由用户手工指定 ``--from``；
    绝不该因为路上某个目录读不了就让导入无法进行。
    """
    target = _resolve(target)
    seen: set[Path] = set()
    found: list[Path] = []
    scanned = 0
    for root in _scan_roots(target):
        try:
            if not root.is_dir():
                continue
        except OSError:
            continue
        for child in _iter_dirs(root):
            if scanned >= limit:
                break
            scanned += 1
            for candidate in (child, *_iter_dirs(child)):
                resolved = _resolve(candidate)
                if resolved == target or resolved in seen:
                    continue
                seen.add(resolved)
                if looks_like_install(resolved):
                    found.append(resolved)
    return sorted(found, key=_data_mtime, reverse=True)


def _resolve(path: Path) -> Path:
    """``resolve()`` 的不抛版本：解析不了就用原路径（比让探测崩掉强）。"""
    try:
        return path.resolve()
    except OSError:
        return path


def _iter_dirs(root: Path):
    """安全列子目录：权限不足/路径过长直接跳过，不能让探测炸掉整个流程。

    ``is_dir()`` 也要逐个兜住：能列出目录项，不代表能 stat 每一项（断链的符号链接、
    权限受限的挂载点都会在这一步抛）。
    """
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_dir() and not entry.name.startswith("."):
                yield entry
        except OSError:
            continue


# ── 文件搬迁 ────────────────────────────────────────────


def _is_never_migrate(relative: str) -> bool:
    return any(relative.startswith(pattern.rstrip("/")) for pattern in NEVER_MIGRATE)


def _copy_file(src: Path, dst: Path, written: list[Path]) -> None:
    """复制单个文件并记账（失败回滚要用）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    existed = dst.exists()
    shutil.copy2(src, dst)
    if not existed:
        written.append(dst)


def _merge_tree(
    src_dir: Path,
    dst_dir: Path,
    report: MigrateReport,
    written: list[Path],
    *,
    label: str,
    dry_run: bool,
) -> None:
    """整目录搬迁：**只补不覆盖**。目标已有同名文件时保留目标的并报告。

    第三方插件（``data/plugins/<name>/``）按 ``__file__`` 定位自身资源，所以整目录
    搬过去是安全的；它们写数据用的是兼容层给的目录，只要那几个常量指对就行。
    """
    copied = 0
    skipped = 0
    for src in sorted(src_dir.rglob("*")):
        if not src.is_file():
            continue
        relative = src.relative_to(src_dir).as_posix()
        if _is_never_migrate(relative) or "__pycache__" in relative:
            continue
        dst = dst_dir / relative
        if dst.exists():
            skipped += 1
            continue
        copied += 1
        if not dry_run:
            _copy_file(src, dst, written)
    detail = f"复制 {copied} 个文件" + (f"，跳过 {skipped} 个已存在" if skipped else "")
    report.add(label, "已导入" if copied else "无需导入", detail)


def _migrate_shipped_tree(
    src_root: Path,
    dst_root: Path,
    program_root: Path,
    relative_dir: str,
    report: MigrateReport,
    written: list[Path],
    *,
    dry_run: bool,
) -> None:
    """发布包自带、用户可能改过的目录（人格、能力配置）走「改过才保留」判定。

    命中旧包原始哈希 = 用户没改 → 什么都不做（新版本自带的那份会被用上）；
    不命中 = 用户改过 → 把他的文件搬进用户数据目录，并把新版本那份另存为 ``*.new``
    放在旁边便于对照。没有清单的旧版本（≤3.0.0）一律按「改过」处理——把用户写了
    几小时的人格覆盖掉是不可逆的，多留一个 ``*.new`` 只是有点吵。
    """
    src_dir = src_root / relative_dir.rstrip("/")
    if not src_dir.is_dir():
        return
    entries = manifest.load_manifest(src_root)
    kept, pristine, conflicts = 0, 0, []
    for src in sorted(src_dir.rglob("*")):
        if not src.is_file() or "__pycache__" in src.as_posix():
            continue
        relative = src.relative_to(src_root).as_posix()
        shipped = program_root / relative
        dst = dst_root / relative
        # 新版本没有这个文件 → 一定是用户自己加的（如他写的 casual.md），必须带走。
        # 「未改动」只说明「与旧发布包一致」，不代表新包里也有它。
        if shipped.is_file() and manifest.is_pristine(src_root, relative, entries):
            pristine += 1
            continue
        kept += 1
        if shipped.is_file() and manifest.file_sha256(shipped) != manifest.file_sha256(src):
            conflicts.append(relative)
            if not dry_run:
                _copy_file(shipped, dst.with_suffix(dst.suffix + ".new"), written)
        if not dry_run:
            _copy_file(src, dst, written)
    detail_parts = []
    if kept:
        detail_parts.append(f"保留你改过的 {kept} 个")
    if pristine:
        detail_parts.append(f"{pristine} 个未改动、用新版")
    if conflicts:
        detail_parts.append(f"新版另存为 *.new：{'、'.join(conflicts)}")
    if not entries:
        detail_parts.append("旧版本无发布清单，按「一律保留旧文件」处理")
    report.add(relative_dir, "已导入" if kept else "无需导入", "；".join(detail_parts))
    for relative in conflicts:
        report.warnings.append(
            f"`{relative}` 你改过，已保留你的版本；新版默认值在 `{relative}.new`，可自行对照"
        )


def _allowed_groups(env_text: str) -> tuple[int, ...]:
    """从 ``.env`` 文本里取 ALLOWED_GROUPS。

    刻意不 import ``config.settings``：它在 import 时就 load_dotenv 并冻结常量，
    迁移时目标 ``.env`` 可能刚写好，读到的会是空值（``deploy/__main__.py`` 记过这个坑）。
    """
    raw = env_merge.parse_env(env_text).get("ALLOWED_GROUPS", "")
    groups = []
    for part in raw.replace("，", ",").strip("\"'").split(","):
        part = part.strip()
        if part.isdigit():
            groups.append(int(part))
    return tuple(groups)


def _migrate_env(
    source: Path,
    target: Path,
    program_root: Path,
    report: MigrateReport,
    written: list[Path],
    *,
    dry_run: bool,
) -> str:
    """合并 ``.env``（新模板骨架 + 旧值），返回合并后的文本。

    模板与 schema 来自**程序目录**（新版本自带），结果写进**用户数据目录**。
    """
    old_env = source / ".env"
    destination = target / ".env"
    if not old_env.is_file():
        report.add(".env", "跳过", "旧目录没有 .env")
        return destination.read_text(encoding="utf-8") if destination.is_file() else ""
    template = program_root / ".env.example"
    if not template.is_file():
        report.add(".env", "失败", "当前目录缺少 .env.example，无法合并")
        return old_env.read_text(encoding="utf-8")
    rendered, env_report = env_merge.merge_env_files(
        old_env,
        template,
        schema_keys=env_merge.settings_keys(program_root / "config" / "settings.py"),
    )
    report.env_report = env_report
    report.add(
        ".env", "已合并", f"沿用 {len(env_report.kept)} 项，移除废弃 {len(env_report.removed)} 项"
    )
    if not dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            shutil.copy2(destination, target / ".env.bak")
            report.warnings.append("目标已有 .env，合并前已备份为 `.env.bak`")
        else:
            written.append(destination)
        destination.write_text(rendered, encoding="utf-8")
    return rendered


def _migrate_runtime(
    source: Path, target: Path, report: MigrateReport, *, dry_run: bool, reuse: bool
) -> None:
    """复用旧目录的嵌入式 Python 运行时（100MB+，重下很痛）。

    关键：**不能连 ``.stella-deps-ready`` 一起带过来**当成「依赖已就绪」。那个标记
    改成了存 ``requirements.txt`` 的 sha256（见 start.bat / python.rs），新版本的
    requirements 变了就会自动重装；但旧版本写的是空文件，所以这里直接删掉标记，
    让新版本自己判断。
    """
    src = source / RUNTIME_DIR
    dst = target / RUNTIME_DIR
    if not reuse:
        report.add(RUNTIME_DIR, "跳过", "已指定 --fresh-runtime，将重新下载")
        return
    if not src.is_dir():
        report.add(RUNTIME_DIR, "跳过", "旧目录没有 runtime，首次启动会自动下载")
        return
    if dst.exists():
        report.add(RUNTIME_DIR, "跳过", "当前目录已有 runtime")
        return
    if dry_run:
        report.add(RUNTIME_DIR, "将复用", "省下一次约 100MB 的下载")
        return
    shutil.copytree(src, dst)
    marker = dst / DEPS_MARKER
    if marker.exists():
        marker.unlink()
    report.add(RUNTIME_DIR, "已复用", "已清除依赖就绪标记，新版本会按 requirements.txt 自行校验")


def _migrate_database(
    source: Path,
    target: Path,
    env_text: str,
    report: MigrateReport,
    *,
    dry_run: bool,
) -> None:
    """升级数据库：列改名 + 值重写为空间名 + 画像重建 + FTS 重建 + 校验。

    空间名解析用的是**目标目录**的 spaces 配置与账本（迁移已经把它们搬过来了），
    这样迁移写进去的名字与运行时 ``resolve_space()`` 返回的名字必然一致——不一致会
    让检索静默查不到（「一切正常但什么都不记」）。
    """
    from memory import migrations, schema

    root = source if dry_run else target
    db_path = root / "memory" / "agent_memory.db"
    if not db_path.is_file():
        report.add("数据库", "跳过", "没有找到 agent_memory.db")
        return
    ctx = migrations.context_from_paths(
        root / "config" / "spaces",
        db_path.parent / space_map.LEDGER_FILENAME,
        _allowed_groups(env_text),
        persist=not dry_run,
    )
    db_report = schema.migrate_to_latest(db_path, ctx, dry_run=dry_run)
    report.db_report = db_report
    if db_report.error:
        report.add("数据库", "失败", db_report.error)
    elif db_report.problems:
        report.add("数据库", "校验未通过", f"{len(db_report.problems)} 项，详见下方")
    else:
        report.add(
            "数据库",
            "已升级" if not dry_run else "预演通过",
            f"v{db_report.from_version} → v{db_report.to_version}，改动 {db_report.changed_rows} 行",
        )
    report.warnings.extend(
        warning for step in db_report.steps for warning in step.warnings
    )


# ── 入口 ────────────────────────────────────────────────


def _rollback(written: list[Path]) -> None:
    """删掉本次写进目标目录的文件（**只删我们自己新建的**）。

    旧目录全程只读，所以回滚后回到「还没导入」的状态，可以原地重跑。
    已存在的目标文件不在 ``written`` 里，绝不会被这里删掉。
    """
    for path in reversed(written):
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            continue


def run(
    program_root: Path,
    source: Path | None = None,
    *,
    data_root: Path | None = None,
    dry_run: bool = False,
    reuse_runtime: bool = True,
) -> MigrateReport:
    """把 ``source`` 里的用户数据导入本安装，并把数据库升到最新。

    两个目标根目录分开传：``program_root`` 是程序目录（新版本的 ``.env.example``、
    ``settings.py``、自带默认人格、``runtime/`` 都在这儿），``data_root`` 是用户数据
    目录（``STELLA_HOME``，收所有搬过来的东西）。旧布局下两者相同。
    """
    program_root = program_root.resolve()
    target = (data_root or program_root).resolve()
    report = MigrateReport(
        target=target,
        program_root=program_root,
        dry_run=dry_run,
        target_version=read_version(program_root),
    )

    if source is None:
        candidates = detect_sources(program_root)
        if not candidates:
            report.error = (
                "没有找到旧版本的安装目录。请用 --from <旧目录> 指定"
                "（旧目录应当含有 bot.py 与 memory/agent_memory.db）。"
            )
            return report
        source = candidates[0]
        if len(candidates) > 1:
            others = "、".join(f"`{p}`" for p in candidates[1:4])
            report.warnings.append(
                f"还发现 {len(candidates) - 1} 个候选旧目录（{others}）；"
                f"本次选的是数据最新的 `{source}`。若选错了请用 --from 指定后重跑。"
            )
    source = Path(source).resolve()
    report.source = source
    report.source_version = read_version(source)

    if source in (target, program_root):
        report.error = "来源目录与当前安装相同，无需导入。"
        return report
    if not looks_like_install(source):
        report.error = f"`{source}` 看起来不是一份用过的 Stella 安装（缺少 bot.py 或用户数据）。"
        return report

    written: list[Path] = []
    try:
        for relative in USER_DATA:
            if relative == ".env":
                continue  # .env 走合并，见下
            if relative.endswith("/"):
                if relative in SHIPPED_EDITABLE:
                    _migrate_shipped_tree(
                        source,
                        target,
                        program_root,
                        relative,
                        report,
                        written,
                        dry_run=dry_run,
                    )
                else:
                    src_dir = source / relative.rstrip("/")
                    if src_dir.is_dir():
                        _merge_tree(
                            src_dir,
                            target / relative.rstrip("/"),
                            report,
                            written,
                            label=relative,
                            dry_run=dry_run,
                        )
                    else:
                        report.add(relative, "跳过", "旧目录里没有")
                continue
            src = source / relative
            dst = target / relative
            if not src.is_file():
                report.add(relative, "跳过", "旧目录里没有")
            elif dst.exists():
                report.add(relative, "跳过", "当前目录已存在，未覆盖")
            elif dry_run:
                report.add(relative, "将导入", f"{src.stat().st_size / 1024:.0f} KB")
            else:
                _copy_file(src, dst, written)
                report.add(relative, "已导入", f"{src.stat().st_size / 1024:.0f} KB")

        env_text = _migrate_env(
            source, target, program_root, report, written, dry_run=dry_run
        )
        _migrate_runtime(
            source, program_root, report, dry_run=dry_run, reuse=reuse_runtime
        )
        _migrate_database(source, target, env_text, report, dry_run=dry_run)
        if not dry_run and report.ok:
            # 版本标记必须在导入成功之后才写：写早了，一次失败的导入会让下次启动
            # 以为「已经是新版跑过的数据」，从而不再提示可以重跑导入。
            error = state.record_migration(
                target,
                program_root,
                report.source_version,
                schema_version=getattr(report.db_report, "to_version", None),
            )
            if error:
                report.warnings.append(f"版本标记未能写入（不影响数据）：{error}")
    except Exception as e:
        if not dry_run:
            _rollback(written)
        report.error = f"{type(e).__name__}: {e}（旧目录未被改动，可原地重跑）"
    return report


def write_report(target: Path, report: MigrateReport) -> Path:
    """把报告写成 ``migration_report.md``（GUI 直接渲染这份文件）。"""
    path = target / "migration_report.md"
    path.write_text(report.to_markdown() + "\n", encoding="utf-8")
    return path







