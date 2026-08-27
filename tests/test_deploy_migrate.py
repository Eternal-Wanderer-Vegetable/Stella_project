# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""``deploy migrate``（从旧版本导入）的端到端测试。

两条铁律各有专门用例：**只读旧目录**、**不覆盖目标已有的用户数据**。
其余覆盖迁移清单的每一类：单文件、整目录、发布包自带可改文件、runtime、
.env 合并、数据库升级。
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from deploy import manifest, migrate
from tests.test_migrations import build_legacy_v5_db

OLD_ENV = """\
ALLOWED_GROUPS=1001,2002
HOST=0.0.0.0
PORT=9000
LM_STUDIO_MODEL=google/gemma-4-26b
PROACTIVE_COOLDOWN=1200
NAPCAT_QQ_ACCOUNT=10001
"""

TEMPLATE = """\
# ---------- 连接 ----------
ALLOWED_GROUPS=
HOST=127.0.0.1
PORT=8080
# ---------- 模型 ----------
LM_STUDIO_MODEL=
# PROACTIVE_COOLDOWN=600
NEW_IN_THIS_VERSION=true
"""

SHIPPED_PERSONA = "# 默认人格\n你是 Stella。\n"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _tree_hash(root: Path) -> dict[str, str]:
    """目录内容指纹，用来断言「旧目录一个字节都没被动过」。"""
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


@pytest.fixture
def install_pair(tmp_path):
    """搭一对目录：``old`` 是用过的旧安装，``new`` 是刚解压的新版本。"""
    old = tmp_path / "Stella-2.2.0"
    new = tmp_path / "Stella-3.1.0"

    # ── 旧安装：有用户数据 ──
    _write(old / "bot.py", "# old entry\n")
    _write(old / "pyproject.toml", 'version = "2.2.0"\n')
    _write(old / ".env", OLD_ENV)
    _write(old / "deploy.answers.toml", "allowed_groups = [1001]\n")
    build_legacy_v5_db(old / "memory" / "agent_memory.db")
    _write(old / "memory" / ".space_assignments.json", '{"1001": "space_1"}')
    _write(old / "memory" / ".last_message_cleanup", "1756000000")
    _write(old / "config" / "spaces" / "casual.toml", "qq_groups = [1001, 2002]\n")
    _write(old / "system_prompts" / "default.md", SHIPPED_PERSONA)  # 未改动
    _write(old / "config" / "capabilities" / "entertainment.toml", "enabled = true\n")
    # 清单反映的是「旧发布包出厂时的内容」，所以要在用户自己加文件之前生成
    manifest.write_manifest(old)
    _write(old / "system_prompts" / "casual.md", "# 我自己写的人格\n")  # 用户新增
    _write(old / "data" / "plugins" / "demo_plugin" / "main.py", "print('hi')\n")
    _write(old / "data" / "plugin_data" / "demo_plugin" / "state.json", "{}")
    _write(old / "runtime" / "python.exe", "binary")
    _write(old / "runtime" / migrate.DEPS_MARKER, "")  # 旧版本写的是空标记
    _write(old / "logs" / "stella.jsonl", "{}\n")  # 永不迁移

    # ── 新版本：只有程序文件 ──
    _write(new / "bot.py", "# new entry\n")
    _write(new / "pyproject.toml", 'version = "3.1.0"\n')
    _write(new / ".env.example", TEMPLATE)
    _write(new / "system_prompts" / "default.md", "# 默认人格 v3\n你是 Stella（新版）。\n")
    _write(new / "config" / "capabilities" / "entertainment.toml", "enabled = false\n")
    return old, new


def test_end_to_end_import(install_pair):
    """一次完整导入：配置、记忆、空间、人格、插件、runtime 全部到位。"""
    old, new = install_pair
    report = migrate.run(new, old)

    assert report.error is None, report.error
    assert report.ok, report.to_markdown()
    assert report.source_version == "2.2.0"
    assert report.target_version == "3.1.0"

    # 单文件
    assert (new / "deploy.answers.toml").is_file()
    assert (new / "memory" / "agent_memory.db").is_file()
    # 账本必须跟着走：丢了它会重新分配 space_N，记忆全挂在旧名下
    assert (new / "memory" / ".space_assignments.json").is_file()
    assert (new / "memory" / ".last_message_cleanup").is_file()
    # 整目录
    assert (new / "config" / "spaces" / "casual.toml").is_file()
    assert (new / "data" / "plugins" / "demo_plugin" / "main.py").is_file()
    assert (new / "data" / "plugin_data" / "demo_plugin" / "state.json").is_file()
    # 永不迁移
    assert not (new / "logs").exists()


def test_env_is_merged_not_copied(install_pair):
    """.env 走合并：新模板骨架 + 旧值，废弃键清掉，新键留默认。"""
    from deploy import env_merge

    old, new = install_pair
    migrate.run(new, old)
    values = env_merge.parse_env((new / ".env").read_text(encoding="utf-8"))

    assert values["HOST"] == "0.0.0.0"  # 旧值沿用
    assert values["PORT"] == "9000"
    assert values["PROACTIVE_COOLDOWN"] == "1200"  # 模板里是注释掉的默认值
    assert values["NEW_IN_THIS_VERSION"] == "true"  # 新版新增，走默认
    assert "NAPCAT_QQ_ACCOUNT" not in values  # 废弃键已移除
    assert "# ---------- 连接 ----------" in (new / ".env").read_text(encoding="utf-8")


def test_database_upgraded_to_space_semantics(install_pair):
    """数据库跟着一起升级：列改名 + 值重写为空间名，且与 spaces 配置一致。"""
    old, new = install_pair
    report = migrate.run(new, old)

    db = new / "memory" / "agent_memory.db"
    conn = sqlite3.connect(db)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)")]
        assert "group_shared_space" in cols and "group_id" not in cols
        # casual.toml 把 1001/2002 都划进 casual → 两个群的记忆都归 casual
        spaces = {
            row[0]
            for row in conn.execute("SELECT DISTINCT group_shared_space FROM memories")
        }
        assert "casual" in spaces
        # 溯源列留住真实群号，合并后还能拆回来
        origins = dict(conn.execute("SELECT id, origin_group_id FROM memories"))
        assert origins["m1"] == "1001"
        assert origins["m3"] == "2002"
    finally:
        conn.close()
    assert report.db_report is not None
    assert report.db_report.problems == []


def test_modified_shipped_file_kept_and_new_saved_aside(install_pair):
    """用户改过的自带文件保留他的版本，新版另存 *.new；没改过的用新版。"""
    old, new = install_pair
    # entertainment.toml 在旧包清单里是 enabled=true，用户把它改了
    (old / "config" / "capabilities" / "entertainment.toml").write_text(
        "enabled = true\nextra = 1\n", encoding="utf-8"
    )
    report = migrate.run(new, old)

    # 改过 → 保留旧内容，新版进 .new
    kept = (new / "config" / "capabilities" / "entertainment.toml").read_text(encoding="utf-8")
    assert "extra = 1" in kept
    assert (new / "config" / "capabilities" / "entertainment.toml.new").is_file()
    assert any("entertainment.toml" in w for w in report.warnings)
    # default.md 未改动（命中旧包哈希）→ 保留新版本的内容
    assert "新版" in (new / "system_prompts" / "default.md").read_text(encoding="utf-8")
    # 用户自己新增的人格文件照常带过来
    assert (new / "system_prompts" / "casual.md").is_file()


def test_runtime_reused_and_marker_cleared(install_pair):
    """复用 runtime 省 100MB，但必须清掉依赖就绪标记，否则新依赖永远装不上。"""
    old, new = install_pair
    migrate.run(new, old)

    assert (new / "runtime" / "python.exe").is_file()
    assert not (new / "runtime" / migrate.DEPS_MARKER).exists()


def test_fresh_runtime_skips_copy(install_pair):
    """--fresh-runtime：不复用，交给 start.bat 重新下载。"""
    old, new = install_pair
    migrate.run(new, old, reuse_runtime=False)
    assert not (new / "runtime").exists()


def test_source_directory_is_never_touched(install_pair):
    """铁律一：旧目录只读。任何一步失败，用户的旧安装都还能跑。"""
    old, new = install_pair
    before = _tree_hash(old)

    migrate.run(new, old)

    assert _tree_hash(old) == before


def test_existing_target_data_is_not_overwritten(install_pair):
    """铁律二：目标已有的用户数据不覆盖——那说明用户已经用过新版了。"""
    old, new = install_pair
    (new / "memory").mkdir(parents=True, exist_ok=True)
    marker = new / "memory" / "agent_memory.db"
    marker.write_bytes(b"already-in-use")

    report = migrate.run(new, old)

    assert marker.read_bytes() == b"already-in-use"
    assert any(
        item.path == "memory/agent_memory.db" and "已存在" in item.detail
        for item in report.items
    )


def test_dry_run_writes_nothing(install_pair):
    """--dry-run 只出报告：目标目录一个新文件都不该多。"""
    old, new = install_pair
    before = _tree_hash(new)

    report = migrate.run(new, old, dry_run=True)

    assert report.dry_run is True
    assert report.error is None
    assert _tree_hash(new) == before
    # 预演也要给出真实的数据库结论（在副本上真跑了一遍）
    assert report.db_report is not None
    assert report.db_report.changed_rows > 0
    assert "预演" in report.to_markdown()


def test_report_is_written_and_readable(install_pair):
    """报告落盘给 GUI 渲染，关键结论必须在里面。"""
    old, new = install_pair
    report = migrate.run(new, old)
    path = migrate.write_report(new, report)

    text = path.read_text(encoding="utf-8")
    assert "# 从旧版本导入" in text
    assert "memory/agent_memory.db" in text
    assert "配置文件（.env）" in text
    assert "数据库迁移" in text


def test_autodetect_picks_the_used_install(install_pair):
    """自动探测：兄弟目录里那份「用过的」安装会被找到。"""
    old, new = install_pair
    # 一个刚解压、没用过的目录不该被当成候选
    fresh = old.parent / "Stella-3.1.0-fresh"
    _write(fresh / "bot.py", "# fresh\n")

    found = migrate.detect_sources(new)

    assert old.resolve() in found
    assert fresh.resolve() not in found


def test_refuses_when_source_is_not_an_install(tmp_path):
    """指了个不是安装目录的路径 → 明确报错，不做任何事。"""
    new = tmp_path / "new"
    _write(new / "bot.py", "# new\n")
    junk = tmp_path / "junk"
    junk.mkdir()

    report = migrate.run(new, junk)

    assert report.error is not None
    assert "不是一份用过的 Stella 安装" in report.error


def test_data_root_separate_from_program_dir(install_pair, tmp_path):
    """P1 布局：用户数据全部落进 STELLA_HOME，程序目录只收 runtime。

    这才是「此后每次升级 1 步」的形态——换掉程序目录，数据目录不动。
    """
    old, new = install_pair
    data = tmp_path / "StellaData"

    report = migrate.run(new, old, data_root=data)

    assert report.error is None, report.error
    # 用户数据 → 数据目录
    assert (data / ".env").is_file()
    assert (data / "memory" / "agent_memory.db").is_file()
    assert (data / "memory" / ".space_assignments.json").is_file()
    assert (data / "config" / "spaces" / "casual.toml").is_file()
    assert (data / "data" / "plugins" / "demo_plugin" / "main.py").is_file()
    assert not (new / ".env").exists()
    assert not (new / "memory" / "agent_memory.db").exists()
    # runtime 是解释器，属于程序目录
    assert (new / "runtime" / "python.exe").is_file()
    assert not (data / "runtime").exists()
    # 数据库也在数据目录里升级完成
    conn = sqlite3.connect(data / "memory" / "agent_memory.db")
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)")]
    finally:
        conn.close()
    assert "group_shared_space" in cols
    assert "用户数据目录" in report.to_markdown()


def test_shipped_file_untouched_when_user_never_edited_it(install_pair, tmp_path):
    """数据目录模式下，用户没改过的自带文件**不复制**——新版本自带的那份直接生效。"""
    old, new = install_pair
    data = tmp_path / "StellaData"

    migrate.run(new, old, data_root=data)

    # default.md 命中旧包哈希（未改动）→ 数据目录里不该出现它
    assert not (data / "system_prompts" / "default.md").exists()
    # 用户自己写的那份必须搬过来
    assert (data / "system_prompts" / "casual.md").is_file()
    # 程序目录里的新版默认人格保持原样
    assert "新版" in (new / "system_prompts" / "default.md").read_text(encoding="utf-8")



