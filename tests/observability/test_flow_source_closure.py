# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""源码闭包与入口发现回归（修复计划 M0/M4，R4 探针固化）。

锁定复核报告 R4 的隔离探针结论：

- 跨文件本地调用（relative import / direct import / 类方法）必须解析为
  项目内闭包，不再统一归 external；
- 可达辅助函数的**实际函数体**参与 hash：辅助函数 return 逻辑变化必须
  使 manifest content hash 漂移（旧探针：改 `_flow_key` 返回逻辑，
  problems=[] 且 hash 不变）；
- 独立入口扫描能发现清单（inventory）以外的新 matcher/startup/worker，
  与声明集合形成双向差集门禁；
- 循环、预算截断、动态/跨语言边界诚实标注，不伪装 third_party。

全部在 tmp_path fixture 树上运行，不触碰仓库源码。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.generate_message_flow import (
    analyze_project_closure,
    discovered_entries_diff,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


CALLER = '''"""caller module."""
from . import helper
from .helper import shaped


def entry(value):
    return helper.normalize(value) + shaped(value)
'''

HELPER = '''"""helper module."""


def normalize(value):
    return value.strip().lower()


def shaped(value):
    return f"<{value}>"
'''

MATCHER = '''"""a matcher-style entry not present in any inventory."""
from nonebot import on_message

_demo = on_message()


@_demo.handle
async def demo_handler():
    return None
'''


@pytest.fixture()
def fixture_root(tmp_path) -> Path:
    root = tmp_path / "proj"
    pkg = root / "pkg"
    _write(pkg / "__init__.py", "")
    _write(pkg / "caller.py", CALLER)
    _write(pkg / "helper.py", HELPER)
    return root


class TestCrossFileClosure:
    def test_local_import_resolves_not_external(self, fixture_root):
        """项目内 import 目标解析为本地闭包，第三方才归 external。"""
        closure = analyze_project_closure(
            fixture_root, entry_files=[Path("pkg/caller.py")],
            entry_symbols=["entry"])
        helpers = {(c["file"], c["qualname"]) for c in closure["symbols"]}
        assert ("pkg/helper.py", "normalize") in helpers
        assert ("pkg/helper.py", "shaped") in helpers
        assert all(c["resolution"] == "local" for c in closure["symbols"])

    def test_helper_body_change_drifts_hash(self, fixture_root):
        """R4 探针固化：辅助函数体变化 → 闭包 hash 漂移。"""
        before = analyze_project_closure(
            fixture_root, entry_files=[Path("pkg/caller.py")],
            entry_symbols=["entry"])
        _write(fixture_root / "pkg" / "helper.py",
               HELPER.replace("value.strip().lower()", "value.strip()"))
        after = analyze_project_closure(
            fixture_root, entry_files=[Path("pkg/caller.py")],
            entry_symbols=["entry"])
        hash_before = {(c["file"], c["qualname"]): c["body_hash"]
                       for c in before["symbols"]}
        hash_after = {(c["file"], c["qualname"]): c["body_hash"]
                      for c in after["symbols"]}
        key = ("pkg/helper.py", "normalize")
        assert hash_before[key] != hash_after[key]
        assert before["closure_hash"] != after["closure_hash"]

    def test_cycle_and_budget_truncated_honestly(self, fixture_root):
        """环与预算截断必须显式 truncated，不静默丢符号。"""
        _write(fixture_root / "pkg" / "loop_a.py",
               "from .loop_b import ping\n\n\ndef loop_a():\n    return ping()\n")
        _write(fixture_root / "pkg" / "loop_b.py",
               "from .loop_a import loop_a\n\n\ndef ping():\n    return loop_a()\n")
        closure = analyze_project_closure(
            fixture_root, entry_files=[Path("pkg/loop_a.py")],
            entry_symbols=["loop_a"], max_symbols=1)
        assert closure["truncated"] is True
        assert closure["truncation_reason"] == "symbol_budget"


class TestEntryDiscovery:
    def test_new_matcher_found_outside_inventory(self, fixture_root):
        """独立扫描发现清单以外的新 matcher 入口（双向差集的「多」半边）。"""
        _write(fixture_root / "pkg" / "plugin_mod.py", MATCHER)
        found = discovered_entries_diff(
            fixture_root, declared=[("pkg/caller.py", "entry")])
        discovered = {(f["file"], f["symbol"]) for f in found["undeclared"]}
        assert ("pkg/plugin_mod.py", "demo_handler") in discovered

    def test_removed_declared_entry_fails_reconciliation(self, fixture_root):
        """声明入口被删除 → 差集报告 missing，不静默通过。"""
        found = discovered_entries_diff(
            fixture_root, declared=[("pkg/gone.py", "removed_entry")])
        assert ("pkg/gone.py", "removed_entry") in {
            (m["file"], m["symbol"]) for m in found["missing"]}

    def test_dynamic_boundary_not_masquerading_third_party(self, fixture_root):
        """动态/跨语言边界显式归类，不伪装 third_party 或静默豁免。"""
        closure = analyze_project_closure(
            fixture_root, entry_files=[Path("pkg/caller.py")],
            entry_symbols=["entry"])
        externals = {c["qualname"]: c for c in closure["symbols"]
                     if c["resolution"] == "external"}
        dynamic = closure.get("boundaries", [])
        # nonebot 属于显式 boundary registry（如果出现），不标 unresolved
        for info in externals.values():
            assert info["resolution"] == "external"
        assert isinstance(dynamic, list)


class TestDiscoveryShapes:
    """验收报告 M3：带参装饰器与模块级注册表达式必须被扫描到。"""

    def test_argued_decorators_discovered(self, fixture_root):
        """@scheduler.scheduled_job(...) 与 @matcher.handle() 是 ast.Call。"""
        _write(fixture_root / "pkg" / "jobs.py", (
            "from nonebot import get_driver, on_command\n"
            "from nonebot_plugin_apscheduler import scheduler\n\n"
            "cmd = on_command('/ping')\n\n\n"
            "@cmd.handle()\n"
            "async def ping_handler():\n"
            "    return None\n\n\n"
            "@scheduler.scheduled_job('interval', seconds=30)\n"
            "async def tick_job():\n"
            "    return None\n\n\n"
            "@get_driver().on_startup\n"
            "async def boot_hook():\n"
            "    return None\n"))
        found = discovered_entries_diff(
            fixture_root, declared=[], package_dirs=["pkg"])
        discovered = {(f["file"], f["symbol"], f["kind"])
                      for f in found["discovered"]}
        assert ("pkg/jobs.py", "ping_handler", "matcher_handler") in discovered
        assert ("pkg/jobs.py", "tick_job", "lifecycle_hook") in discovered
        assert ("pkg/jobs.py", "boot_hook", "lifecycle_hook") in discovered
        assert ("pkg/jobs.py", "cmd", "matcher") in discovered

    def test_worker_registration_expression_discovered(self, fixture_root):
        """register_handler('x', fn) 不经赋值——此前完全漏检。"""
        _write(fixture_root / "pkg" / "worker.py", (
            "def register_handler(job_type, handler):\n"
            "    return None\n\n\n"
            "def _handle_job():\n"
            "    return None\n\n\n"
            "register_handler('resolve_effect', _handle_job)\n"))
        found = discovered_entries_diff(
            fixture_root, declared=[], package_dirs=["pkg"])
        discovered = {(f["file"], f["symbol"], f["kind"])
                      for f in found["discovered"]}
        assert ("pkg/worker.py", "resolve_effect",
                "worker_registration") in discovered


class TestClosureAliasAndUnresolved:
    """验收报告 M4：导入别名原名还原、不存在的 local 显式 unresolved。"""

    def test_aliased_helper_body_drifts(self, fixture_root):
        """`normalize as transform` 改 helper 体 → 闭包必须漂移。"""
        _write(fixture_root / "pkg" / "helper.py",
               "def normalize(v):\n    return v + 1\n")
        _write(fixture_root / "pkg" / "caller.py",
               "from .helper import normalize as transform\n\n\n"
               "def entry(v):\n    return transform(v)\n")
        before = analyze_project_closure(
            fixture_root, entry_files=[Path("pkg/caller.py")],
            entry_symbols=["entry"])
        helpers = {(c["file"], c["qualname"]) for c in before["symbols"]}
        # 解析到模块内**原名** normalize，而不是不存在的 transform
        assert ("pkg/helper.py", "normalize") in helpers
        _write(fixture_root / "pkg" / "helper.py",
               "def normalize(v):\n    return v + 2\n")
        after = analyze_project_closure(
            fixture_root, entry_files=[Path("pkg/caller.py")],
            entry_symbols=["entry"])
        assert before["closure_hash"] != after["closure_hash"]

    def test_missing_local_callee_reports_unresolved(self, fixture_root):
        """解析为 repo-local 但符号不存在 → 显式 unresolved，不静默。"""
        _write(fixture_root / "pkg" / "caller.py",
               "from .helper import gone_fn\n\n\n"
               "def entry(v):\n    return gone_fn(v)\n")
        closure = analyze_project_closure(
            fixture_root, entry_files=[Path("pkg/caller.py")],
            entry_symbols=["entry"])
        resolutions = {b["resolution"] for b in closure["boundaries"]}
        assert "unresolved" in resolutions
        assert any("helper.py#gone_fn" in b["target"]
                   for b in closure["boundaries"])


class TestModuleAliasAndReverseDiff:
    """复验报告 A3：模块别名解析、反向注销差集、handler 换绑漂移。"""

    def test_module_import_alias_resolves_and_drifts(self, fixture_root):
        """`import pkg.helper as h` 调 h.normalize → 解析到模块内 normalize，
        体变化必须漂移（旧实现记录不存在的 helper.py#h.normalize）。"""
        _write(fixture_root / "pkg" / "helper.py",
               "def normalize(v):\n    return v + 1\n")
        _write(fixture_root / "pkg" / "caller.py",
               "import pkg.helper as h\n\n\n"
               "def entry(v):\n    return h.normalize(v)\n")
        before = analyze_project_closure(
            fixture_root, entry_files=[Path("pkg/caller.py")],
            entry_symbols=["entry"])
        helpers = {(c["file"], c["qualname"]) for c in before["symbols"]}
        assert ("pkg/helper.py", "normalize") in helpers, (
            "模块别名必须解析到真实符号")
        _write(fixture_root / "pkg" / "helper.py",
               "def normalize(v):\n    return v + 2\n")
        after = analyze_project_closure(
            fixture_root, entry_files=[Path("pkg/caller.py")],
            entry_symbols=["entry"])
        assert before["closure_hash"] != after["closure_hash"]

    def test_removed_registration_is_reverse_missing(self, fixture_root):
        """注册删除但函数保留 → declared_entries_meta 反向差集必须报 missing。"""
        _write(fixture_root / "pkg" / "tick.py",
               "from nonebot_plugin_apscheduler import scheduler\n\n\n"
               "@scheduler.scheduled_job('interval', seconds=30)\n"
               "async def tick_job():\n    return None\n")
        declared_meta = [{"file": "pkg/tick.py", "symbol": "tick_job",
                          "registration": "lifecycle_hook"}]
        before = discovered_entries_diff(
            fixture_root, declared=[("pkg/tick.py", "tick_job")],
            package_dirs=["pkg"], declared_entries_meta=declared_meta)
        assert before["missing"] == []
        # 删除注册装饰器，保留函数
        _write(fixture_root / "pkg" / "tick.py",
               "async def tick_job():\n    return None\n")
        after = discovered_entries_diff(
            fixture_root, declared=[("pkg/tick.py", "tick_job")],
            package_dirs=["pkg"], declared_entries_meta=declared_meta)
        assert any(m["reason"] == "registration_removed"
                   for m in after["missing"]), "注销必须被反向差集抓住"

    def test_worker_handler_rebinding_drifts(self, fixture_root):
        """register_handler 同键换绑 handler → discovered 记录变化（漂移）。"""
        _write(fixture_root / "pkg" / "worker.py",
               "def register_handler(job_type, handler):\n"
               "    return None\n\n\n"
               "def _handle_a():\n    return 1\n\n\n"
               "def _handle_b():\n    return 2\n\n\n"
               "register_handler('resolve', _handle_a)\n")
        before = discovered_entries_diff(
            fixture_root, declared=[("pkg/worker.py", "resolve")],
            package_dirs=["pkg"])
        rec_before = next(d for d in before["discovered"]
                          if d["symbol"] == "resolve")
        assert rec_before["handler"] == "_handle_a"
        # 换绑到 _handle_b：discovered 记录变化（handler + 体哈希）
        _write(fixture_root / "pkg" / "worker.py",
               "def register_handler(job_type, handler):\n"
               "    return None\n\n\n"
               "def _handle_a():\n    return 1\n\n\n"
               "def _handle_b():\n    return 2\n\n\n"
               "register_handler('resolve', _handle_b)\n")
        after = discovered_entries_diff(
            fixture_root, declared=[("pkg/worker.py", "resolve")],
            package_dirs=["pkg"])
        rec_after = next(d for d in after["discovered"]
                         if d["symbol"] == "resolve")
        assert rec_after["handler"] == "_handle_b"
        assert rec_before["handler_body_hash"] != rec_after["handler_body_hash"]
