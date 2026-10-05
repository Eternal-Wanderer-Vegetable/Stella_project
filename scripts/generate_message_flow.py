#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""内部流程 manifest 生成器（计划 §6.2）：目录语义 × 源码闭包 → 版本化图。

- 输入：``core/observability/flow_catalog.py``（语义身份、边、边界）与
  各节点 ``source`` 指向的源码符号（AST 解析），以及
  ``core/observability/internal_flow_catalog.py``（运行入口 inventory、
  流程族、显式边界、三层覆盖分母）。
- 输出：``core/observability/flows/message-flow.<content-hash>.json``
  （不可变归档，随包发布；生产无 Docker/Git 也可读）+ coverage 报告。
- **源码闭包**（计划 §6.2 第 3 点）：每个已解析符号自动列出调用点
  （带解析目标）、分支条件、循环、try/except/finally、return/raise、
  await、task spawn、with；同文件可达符号传递展开（递归/环去重、
  有界截断并诚实标注 ``truncated``）。行号只作导航，不参与身份。
- **边界对账**（第 4 点）：标准库/第三方调用解析为 external；本地解析
  失败的调用进 ``unresolved_calls`` 计数（不自动豁免）；动态 dispatch、
  Rust 桥接等显式 boundary 来自 inventory。
- 结构/条件语义变化 → body hash 变化 → 新 content hash；
  ``topology_version`` 由人工在目录变更时递增，二者独立。
- ``--check``：重新生成并与已提交 manifest 比对，任何漂移（源码改动、
  目录改动、符号消失、闭包变化）以退出码 1 阻断——CI 漂移门禁。

用法::

    python scripts/generate_message_flow.py --check           # CI 门禁
    python scripts/generate_message_flow.py                   # 重新生成
    python scripts/generate_message_flow.py --output <dir>    # 自定义输出
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.observability import flow_catalog, internal_flow_catalog

DEFAULT_OUT = PROJECT_ROOT / "core" / "observability" / "flows"
GENERATOR_VERSION = 3
MANIFEST_SCHEMA_VERSION = 3

# 传递闭包边界：同文件可达符号数上限（超限截断并标 truncated）。
# schema 3（修复计划 §6.5）：24 → 96，memory consolidator 家族的四个核心
# 截断（consolidate.extract/preflight/write、memory.consolidate.entry）据实
# 收口——预算必须覆盖真实同文件方法数，而不是让截断常态化。
_REACHABLE_CAP = 256
# 单符号闭包条目上限（超大函数的诚实截断）
_CLOSURE_CAP = 200


# ============================================================
# AST 解析
# ============================================================

def _iter_named_defs(tree: ast.AST) -> Iterator[tuple[str, ast.AST]]:
    """(qualified-ish name, def) 对：模块级函数/类方法。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node


def find_symbol(file_path: Path, symbol: str) -> ast.AST | None:
    """在文件里定位符号：顶层函数、``Class.method``、或装饰器包裹的 handler。"""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    if "." in symbol:
        cls_name, method = symbol.split(".", 1)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == cls_name:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                            and item.name == method:
                        return item
        return None
    for name, node in _iter_named_defs(tree):
        if name == symbol:
            return node
    return None


def structural_features(node: ast.AST) -> dict:
    """符号内结构特征：call/分支/循环/异常/返回/await/spawn/raise 计数。"""
    counts = {
        "calls": 0, "branches": 0, "loops": 0, "try": 0,
        "returns": 0, "awaits": 0, "spawns": 0, "raises": 0,
    }
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            counts["calls"] += 1
            func = sub.func
            name = getattr(func, "attr", "") or getattr(func, "id", "")
            if name in ("create_task", "ensure_future", "run_in_executor"):
                counts["spawns"] += 1
        elif isinstance(sub, (ast.If, ast.IfExp, ast.Match)):
            counts["branches"] += 1
        elif isinstance(sub, (ast.For, ast.While, ast.AsyncFor)):
            counts["loops"] += 1
        elif isinstance(sub, ast.Try):
            counts["try"] += 1
        elif isinstance(sub, ast.Return):
            counts["returns"] += 0  # 语句级闭包另计（保持特征计数兼容）
        elif isinstance(sub, ast.Await):
            counts["awaits"] += 1
        elif isinstance(sub, ast.Raise):
            counts["raises"] += 1
    return counts


def _stable_dump(node: ast.AST) -> str:
    """版本稳定的 AST 序列化（跨 3.10–3.14 同源码同输出）。

    规则：节点类型名 + 逐字段递归；跳过高版本才有的字段（hasattr 判定）
    与空值字段（空列表/None——高版本新字段的缺省形态正是它们，跳过后
    与旧版本"字段不存在"等价）。不使用 ast.dump（其输出随版本新增字段
    变化）也不依赖 ast.unparse（3.10 与 3.11+ 对元组解包目标的括号选择
    不同——CI 实测 44 个节点漂移）。
    """
    if isinstance(node, ast.AST):
        parts = [type(node).__name__]
        for name in node._fields:
            if not hasattr(node, name):
                continue  # 旧版本没有的新字段
            value = getattr(node, name)
            if value is None or (isinstance(value, list) and not value):
                continue  # 新字段的缺省形态与"字段不存在"归一
            parts.append(f"{name}={_stable_dump(value)}")
        return "(" + ",".join(parts) + ")"
    if isinstance(node, list):
        return "[" + ",".join(_stable_dump(v) for v in node) + "]"
    # ascii() 而非 repr()：字符串常量的转义不随解释器内置 Unicode 版本变化
    # （U+9FFF 在 Unicode 14 才分配，3.10 的 repr 转义、3.14 的 repr 直出）
    return f"{type(node).__name__}:{node!a}"


def body_hash(node: ast.AST) -> str:
    """语义体 hash：自定义稳定序列化（与注释/空格/行号/Python 版本无关）。

    版本可移植性（CI 实测教训 2026-10-03）：``ast.dump`` 随版本新增字段
    漂移（3.12 给函数节点加 ``type_params``）；``ast.unparse`` 也有版本差
    （3.10 对元组解包目标输出 ``(a, b) =``，3.11+ 为 ``a, b =``）——本机
    生成、CI（3.10–3.12）校验必然漂移。改用 :func:`_stable_dump`。
    """
    return hashlib.sha256(_stable_dump(node).encode("utf-8")).hexdigest()[:16]


# ============================================================
# 语句级闭包（计划 §6.2 第 3 点）：调用点解析 + 分支/异常/spawn/with 结构
# ============================================================

class _ModuleContext:
    """单文件解析上下文：顶层 def、类方法、import 映射。"""

    def __init__(self, file_rel: str, tree: ast.AST) -> None:
        self.file_rel = file_rel
        self.tree = tree
        self.top_functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.classes: dict[str, ast.ClassDef] = {
            node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
        }
        # legacy 字符串映射（_resolve_call 兼容：绝对导入根 → 模块名）
        self.imports: dict[str, str] = {}
        # 完整导入来源（跨文件解析用）：别名 → (module, level, 原名)
        # 验收报告 M4：`from x import extract as extract_signals` 此前丢失
        # 原名 extract，闭包解析到不存在的 x#extract_signals
        self.import_sources: dict[str, tuple[str, int, str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name
                    self.imports[name.split(".")[0]] = alias.name
                    # `import pkg.helper as h`：别名是模块别名，original 记
                    # 完整模块路径（复验 A3：此前为空 → h.normalize 解析到
                    # 不存在的 helper.py#h.normalize，体变化不漂移）
                    self.import_sources[name.split(".")[0]] = (
                        alias.name, 0, alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    name = alias.asname or alias.name
                    self.imports[name] = module
                    self.import_sources[name] = (module, node.level or 0,
                                                 alias.name)

    def package_of(self) -> str:
        """当前文件所属包的模块名（相对导入的基准）。"""
        parent = self.file_rel.rsplit("/", 1)[0] if "/" in self.file_rel else ""
        if self.file_rel.endswith("/__init__.py"):
            return parent.replace("/", ".")
        return parent.replace("/", ".")


def _resolve_call(target_expr: str, ctx: _ModuleContext,
                  class_name: str | None) -> str:
    """调用目标解析：local/self/external/unresolved（UNKNOWN 不豁免）。"""
    root = target_expr.split(".")[0]
    if target_expr.startswith("self."):
        attr = target_expr.split(".", 1)[1].split("(")[0].split(".")[0]
        cls = ctx.classes.get(class_name) if class_name else None
        methods = set()
        if cls is not None:
            methods = {m.name for m in cls.body
                       if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if attr in methods:
            return f"local:{class_name}.{attr}"
        return f"self:{target_expr}"
    if root in ctx.top_functions and "." not in target_expr:
        return f"local:{target_expr}"
    if root in ctx.imports:
        return f"external:{ctx.imports[root]}.{target_expr}" if "." in target_expr \
            else f"external:{ctx.imports[root]}"
    return "unresolved"


def closure_of(func_node: ast.AST, ctx: _ModuleContext,
               class_name: str | None,
               index: "ProjectIndex | None" = None) -> dict:
    """符号内语句级结构：调用/分支/循环/try/return/raise/await/spawn/with。

    ``index``（schema 3，修复计划 §6.5）提供时用跨文件解析器标注调用点：
    项目内 import 解析为 `local:file#qual`，动态/原生边界显式标注，只有
    真第三方才落 external。
    """
    items: list[dict] = []
    truncated = False

    def add(kind: str, line: int, detail: dict) -> None:
        nonlocal truncated
        if len(items) >= _CLOSURE_CAP:
            truncated = True
            return
        items.append({"kind": kind, "line": line, **detail})

    class_name_holder = class_name

    for sub in ast.walk(func_node):
        if isinstance(sub, ast.Call):
            try:
                target = _ascii_safe(ast.unparse(sub.func))
            except Exception:
                target = "<complex>"
            resolved = (index.resolve_target(ctx, target, class_name_holder)
                        if index is not None
                        else _resolve_call(target, ctx, class_name_holder))
            add("call", getattr(sub, "lineno", 0),
                {"target": target[:80], "resolved": resolved})
        elif isinstance(sub, (ast.If, ast.IfExp)):
            # If 与 IfExp 的条件都在 .test（IfExp 的 .body 是「then」值）
            add("branch", getattr(sub, "lineno", 0),
                {"condition": _safe_unparse(sub.test)[:120]})
        elif isinstance(sub, ast.Match):
            add("branch", getattr(sub, "lineno", 0),
                {"condition": _safe_unparse(sub.subject)[:120]})
        elif isinstance(sub, (ast.For, ast.AsyncFor, ast.While)):
            kind = "loop"
            detail = {}
            if isinstance(sub, ast.While):
                detail["condition"] = _safe_unparse(sub.test)[:120]
            else:
                detail["iterate"] = _safe_unparse(sub.iter)[:120]
            add(kind, getattr(sub, "lineno", 0), detail)
        elif isinstance(sub, ast.Try):
            add("try", getattr(sub, "lineno", 0),
                {"handlers": [_safe_unparse(h.type)[:60] if h.type else "bare"
                              for h in sub.handlers],
                 "finally": bool(sub.orelse) or bool(sub.finalbody)})
        elif isinstance(sub, ast.Return):
            add("return", getattr(sub, "lineno", 0), {})
        elif isinstance(sub, ast.Raise):
            add("raise", getattr(sub, "lineno", 0),
                {"exception": _safe_unparse(sub.exc)[:60] if sub.exc else "bare"})
        elif isinstance(sub, ast.Await):
            add("await", getattr(sub, "lineno", 0), {})
        elif isinstance(sub, (ast.With, ast.AsyncWith)):
            add("with", getattr(sub, "lineno", 0),
                {"async": isinstance(sub, ast.AsyncWith),
                 "context": _safe_unparse(sub.items[0].context_expr)[:80]
                 if sub.items else ""})

    # spawn 站点：create_task/ensure_future/run_in_executor
    _spawn_names = ("create_task", "ensure_future", "run_in_executor")
    spawns = [
        i for i in items if i["kind"] == "call"
        and (i["target"].split(".")[0].split("(")[0] in _spawn_names
             or i["target"].rsplit(".", 1)[-1].split("(")[0] in _spawn_names)
    ]
    return {
        "items": items,
        "counts": _count_kinds(items),
        "spawn_lines": sorted({i["line"] for i in spawns}),
        "truncated": truncated,
    }


def _ascii_safe(text: str) -> str:
    r"""非 ASCII 统一 \uXXXX 转义：ast.unparse 的字符串转义随内置 Unicode
    版本变化（同 _stable_dump 叶子的 repr 问题），哈希前先归一。"""
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _safe_unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return _ascii_safe(ast.unparse(node))
    except Exception:
        return "<complex>"


def _count_kinds(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for i in items:
        counts[i["kind"]] = counts.get(i["kind"], 0) + 1
    return counts


def reachable_symbols(ctx: _ModuleContext, symbol: str,
                      cap: int = _REACHABLE_CAP) -> tuple[list[str], bool]:
    """同文件传递可达符号（计划 §6.2 三层目录的符号层）：递归/环去重。"""
    seen: list[str] = []
    queue: list[str] = [symbol]
    truncated = False
    while queue:
        current = queue.pop(0)
        node = _find_in_ctx(ctx, current)
        if node is None:
            continue
        class_name = current.split(".")[0] if "." in current else None
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            try:
                target = ast.unparse(sub.func)
            except Exception:
                continue
            resolved = _resolve_call(target, ctx, class_name)
            if not resolved.startswith("local:"):
                continue
            local = resolved.split(":", 1)[1]
            if local in (current, symbol) or local in seen:
                continue  # 递归/环去重
            if len(seen) >= cap:
                truncated = True
                continue
            seen.append(local)
            queue.append(local)
    return seen, truncated


def _find_in_ctx(ctx: _ModuleContext, symbol: str) -> ast.AST | None:
    if "." in symbol:
        cls_name, method = symbol.split(".", 1)
        cls = ctx.classes.get(cls_name)
        if cls is None:
            return None
        for item in cls.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and item.name == method:
                return item
        return None
    return ctx.top_functions.get(symbol)


# ============================================================
# 跨文件本地闭包（修复计划 §6.5，R4）：repo-local 模块/导入/别名索引
# ============================================================

# 显式动态/跨语言边界（不伪装 third_party、不静默豁免）
_DYNAMIC_BOUNDARIES = frozenset({
    "nonebot", "nonebot_plugin_apscheduler", "apscheduler",
})
_NATIVE_BOUNDARIES = frozenset({"memory_rust"})


class ProjectIndex:
    """repo-local Python 模块索引：包名 → 文件、每文件符号与导入。

    只索引生产源码目录；tests/scripts/deploy 工具不参与闭包展开（其排除
    规则进入 hash 语义——目录清单变化即 manifest 漂移）。
    """

    PACKAGE_DIRS = ("core", "memory", "capability", "cometa", "knowledge",
                    "webui", "config", "stella_project", "scripts",
                    "astrbot_compat")

    def __init__(self, root: Path, package_dirs=None) -> None:
        self.root = root
        self.package_dirs = tuple(package_dirs or self.PACKAGE_DIRS)
        self.modules: dict[str, "_ModuleContext"] = {}
        self._by_path: dict[str, _ModuleContext] = {}
        self._scan()

    def _scan(self) -> None:
        for pkg in self.package_dirs:
            base = self.root / pkg
            if not base.exists():
                continue
            for path in sorted(base.rglob("*.py")):
                rel = path.relative_to(self.root).as_posix()
                module = rel[:-3].replace("/", ".")
                module = module.removesuffix(".__init__")
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                except (OSError, SyntaxError):
                    continue
                ctx = _ModuleContext(rel, tree)
                self.modules[module] = ctx
                self._by_path[rel] = ctx

    def ctx_for(self, file_rel: str) -> _ModuleContext | None:
        return self._by_path.get(file_rel)

    def resolve_target(self, ctx: _ModuleContext, target: str,
                       class_name: str | None) -> str:
        """调用目标解析为 `local:<file>#<qualname>` / external / dynamic /
        native / unresolved（UNKNOWN 不豁免，修复计划 §6.5）。"""
        if target.startswith("self."):
            attr = target.split(".", 1)[1].split("(")[0].split(".")[0]
            cls = ctx.classes.get(class_name) if class_name else None
            methods = set()
            if cls is not None:
                methods = {m.name for m in cls.body
                           if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if attr in methods:
                return f"local:{ctx.file_rel}#{class_name}.{attr}"
            return f"self:{target}"
        root = target.split(".")[0]
        # 模块内顶层函数直接命中
        if "." not in target and root in ctx.top_functions:
            return f"local:{ctx.file_rel}#{root}"
        source = ctx.import_sources.get(root)
        if source is not None:
            module, level, original = source
            if level:
                # 相对导入：以当前包为基准上溯 level-1 层
                pkg = ctx.package_of()
                parts = pkg.split(".") if pkg else []
                for _ in range(level - 1):
                    if parts:
                        parts = parts[:-1]
                prefix = ".".join(parts)
                module = f"{prefix}.{module}" if (prefix and module) else (
                    module or prefix)
            if level == 0 and original and "." in original and original == module:
                # 模块别名（复验 A3）：`import pkg.helper as h` 的 h.normalize
                # → 模块 pkg.helper 的符号路径 normalize
                remainder = target[len(root):].lstrip(".")
                resolved = self._resolve_module_symbol(module, remainder)
            else:
                # 符号别名还原原名（M4）：调用走别名，模块内符号是原名
                if original and original != root:
                    target = original + target[len(root):]
                resolved = self._resolve_module_symbol(module, target)
            if resolved:
                file_rel, qual = resolved
                if qual:
                    return f"local:{file_rel}#{qual}"
                return f"local:{file_rel}"
            if module.split(".")[0] in _DYNAMIC_BOUNDARIES:
                return f"dynamic:{module}"
            if module.split(".")[0] in _NATIVE_BOUNDARIES:
                return f"native:{module}"
            return f"external:{module}"
        if root in _DYNAMIC_BOUNDARIES:
            return f"dynamic:{target}"
        return "unresolved"

    def _resolve_module_symbol(
            self, module: str, target: str) -> tuple[str, str] | None:
        """把 `module` + `target`（root.attr...）解析到 (file_rel, qualname)。

        先尝试把导入别名解释为子模块（`from pkg import helper` 后调
        `helper.fn` → pkg/helper.py#fn），再把别名解释为模块内符号
        （`from pkg.helper import shaped` → pkg/helper.py#shaped）。
        """
        chain = [p for p in module.split(".") if p]
        tparts = [p for p in target.split(".") if p]
        # 模块本身可能是包：`from pkg import mod` 后 mod.fn()
        while True:
            if chain:
                for i in range(1, len(tparts) + 1):
                    mod2 = ".".join(chain + tparts[:i])
                    if mod2 in self.modules:
                        rest = tparts[i:]
                        return (self.modules[mod2].file_rel,
                                ".".join(rest))
            mod_name = ".".join(chain)
            if mod_name and mod_name in self.modules:
                file_rel = self.modules[mod_name].file_rel
                # 符号在模块文件里逐段下探（类方法等由 find 处理）
                if tparts:
                    return (file_rel, ".".join(tparts))
                return (file_rel, "")
            if not chain:
                return None
            chain = chain[:-1]


def _qualname_of(node: ast.AST, name: str) -> str:
    return name


def reachable_symbols_cross(
    index: ProjectIndex,
    file_rel: str,
    symbol: str,
    cap: int = _REACHABLE_CAP,
) -> tuple[list[dict], list[dict], bool]:
    """跨文件传递可达符号（修复计划 §6.5）。

    返回 (helpers, boundaries, truncated)：每个 helper 携带
    file/qualname/body_hash/resolution（local|dynamic|native|external），
    实际函数体参与 hash——辅助函数实现变化即可漂移 manifest。
    """
    seen: dict[str, dict] = {}
    boundaries: dict[str, dict] = {}
    queue: list[tuple[str, str]] = [(file_rel, symbol)]
    truncated = False
    while queue:
        cur_file, cur_qual = queue.pop(0)
        ctx = index.ctx_for(cur_file)
        if ctx is None:
            continue
        node = _find_in_ctx(ctx, cur_qual)
        if node is None:
            continue
        class_name = cur_qual.split(".")[0] if "." in cur_qual else None
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            try:
                target = _ascii_safe(ast.unparse(sub.func))
            except Exception:
                continue
            resolved = index.resolve_target(ctx, target, class_name)
            kind, _, payload = resolved.partition(":")
            if kind == "local":
                if not payload:
                    continue
                f, qual = payload.split("#", 1)
                if not qual or (f, qual) in {(cur_file, cur_qual),
                                             (file_rel, symbol)}:
                    continue
                key = f"{f}#{qual}"
                if key in seen:
                    continue
                if len(seen) >= cap:
                    truncated = True
                    continue
                h_node = _find_in_ctx(index.ctx_for(f) or ctx, qual)
                if h_node is None:
                    # 解析为 repo-local 但符号不存在：显式 unresolved，
                    # 不静默跳过（验收报告 M4）
                    boundaries.setdefault(f"local:{f}#{qual}",
                                          {"target": f"{f}#{qual}",
                                           "resolution": "unresolved"})
                    continue
                seen[key] = {
                    "file": f, "qualname": qual,
                    "body_hash": body_hash(h_node),
                    "resolution": "local",
                }
                queue.append((f, qual))
            elif kind in ("dynamic", "native"):
                boundaries.setdefault(payload, {"target": payload,
                                                "resolution": kind})
    helpers = sorted(seen.values(), key=lambda h: (h["file"], h["qualname"]))
    ordered = sorted(boundaries.values(), key=lambda b: b["target"])
    return helpers, ordered, truncated


def analyze_project_closure(
    root: Path,
    *,
    entry_files: list[Path],
    entry_symbols: list[str],
    max_symbols: int = _REACHABLE_CAP,
    package_dirs=None,
) -> dict:
    """对任意源码树计算 canonical 本地闭包（修复计划 §6.5 公共 API）。

    返回：``symbols``（file/qualname/body_hash/resolution）、
    ``closure_hash``（全体符号体 hash 的确定性汇总——辅助函数体变化即
    漂移）、``boundaries``（显式动态/跨语言边界）、``truncated`` 与
    ``truncation_reason``。循环/重复符号用 (file, qualname) visited 去重。
    """
    index = ProjectIndex(root, package_dirs=package_dirs or ["pkg"])
    seen: dict[str, dict] = {}
    boundaries: dict[str, dict] = {}
    truncated = False
    for file_rel, symbol in zip(entry_files, entry_symbols, strict=False):
        queue: list[tuple[str, str]] = [(file_rel.as_posix(), symbol)]
        while queue:
            cur_file, cur_qual = queue.pop(0)
            ctx = index.ctx_for(cur_file)
            if ctx is None:
                continue
            node = _find_in_ctx(ctx, cur_qual)
            if node is None:
                continue
            class_name = cur_qual.split(".")[0] if "." in cur_qual else None
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                try:
                    target = _ascii_safe(ast.unparse(sub.func))
                except Exception:
                    continue
                resolved = index.resolve_target(ctx, target, class_name)
                kind, _, payload = resolved.partition(":")
                if kind == "local" and payload and "#" in payload:
                    f, qual = payload.split("#", 1)
                    key = f"{f}#{qual}"
                    if key in seen or (f, qual) == (cur_file, cur_qual):
                        continue
                    if len(seen) >= max_symbols:
                        truncated = True
                        continue
                    target_ctx = index.ctx_for(f)
                    h_node = _find_in_ctx(target_ctx, qual) if target_ctx else None
                    if h_node is None:
                        boundaries.setdefault(f"local:{f}#{qual}",
                                              {"target": f"{f}#{qual}",
                                               "resolution": "unresolved"})
                        continue
                    seen[key] = {
                        "file": f, "qualname": qual,
                        "body_hash": body_hash(h_node),
                        "resolution": "local",
                    }
                    queue.append((f, qual))
                elif kind in ("dynamic", "native") and payload:
                    boundaries.setdefault(payload, {"target": payload,
                                                    "resolution": kind})
                elif kind == "external" and payload:
                    boundaries.setdefault(payload, {"target": payload,
                                                    "resolution": "external"})
    symbols = sorted(seen.values(), key=lambda s: (s["file"], s["qualname"]))
    canonical = json.dumps(
        sorted(f"{s['file']}#{s['qualname']}:{s['body_hash']}" for s in symbols),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    closure_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "symbols": symbols,
        "closure_hash": closure_hash,
        "boundaries": sorted(boundaries.values(), key=lambda b: b["target"]),
        "truncated": truncated,
        "truncation_reason": "symbol_budget" if truncated else "",
    }


# ---- 入口发现（修复计划 §6.5）：独立扫描生产模块的注册语句 ----

# 匹配“真实运行入口”的确定性注册模式：matcher 创建、handler 装饰、
# 调度作业、生命周期钩子、事件前后处理器。发现集合与 inventory 双向对账。
_ENTRY_PATTERN_CALLS = frozenset({
    "on_message", "on_command", "on_regex", "on_notice", "on_request",
    "on_metaevent", "on_fullmatch", "on_startswith", "on_endswith",
    "on_keyword", "on_shell_command",
})
_ENTRY_PATTERN_DECORATORS = frozenset({
    "handle", "got", "receive",  # matcher handlers（xxx.handle）
    "event_preprocessor", "event_postprocessor",
    "run_preprocessor", "run_postprocessor",
})
_ENTRY_HOOK_DECORATORS = frozenset({
    "on_startup", "on_shutdown", "on_bot_connect", "on_bot_disconnect",
    "scheduled_job",
})
# 模块级 worker/任务注册表达式（验收报告 M3）：register_handler(...) 等
_ENTRY_REGISTRATION_CALLS = frozenset({
    "register_handler", "register_worker", "add_handler", "register_job",
})


def _file_declares_symbol(ctx: _ModuleContext, symbol: str) -> bool:
    """符号在本文件是否声明过（嵌套 def / 类方法 / 赋值目标都算）。"""
    if _find_in_ctx(ctx, symbol) is not None:
        return True
    if "." in symbol:
        symbol = symbol.split(".")[0]
    for node in ast.walk(ctx.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and node.name == symbol:
            return True
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == symbol:
                    return True
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == symbol:
            return True
    return False


def _decorator_name(deco: ast.AST) -> str:
    """装饰器名（验收报告 M3）：带参装饰器是 ast.Call，需下钻一层取 func
    （@scheduler.scheduled_job(...) / @matcher.handle() 此前全部漏检）。"""
    target = deco.func if isinstance(deco, ast.Call) else deco
    return getattr(target, "attr", "") or getattr(target, "id", "")


def _scan_entries_in_file(ctx: _ModuleContext) -> list[dict]:
    found: list[dict] = []
    for node in ast.walk(ctx.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                name = _decorator_name(deco)
                if name in _ENTRY_PATTERN_DECORATORS:
                    found.append({"symbol": node.name, "kind": "matcher_handler",
                                  "line": getattr(node, "lineno", 0)})
                    break
                if name in _ENTRY_HOOK_DECORATORS:
                    found.append({"symbol": node.name, "kind": "lifecycle_hook",
                                  "line": getattr(node, "lineno", 0)})
                    break
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            name = getattr(node.value.func, "attr", "") \
                or getattr(node.value.func, "id", "")
            if name in _ENTRY_PATTERN_CALLS:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        found.append({"symbol": t.id,
                                      "kind": "matcher",
                                      "line": getattr(node, "lineno", 0)})
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            # 模块级注册表达式（M3）：register_handler("x", handler) 等，
            # 不经赋值——此前完全漏检；符号取首个 Name 实参，否则取被调名
            call = node.value
            callee = getattr(call.func, "attr", "") \
                or getattr(call.func, "id", "")
            if callee in _ENTRY_REGISTRATION_CALLS:
                first = call.args[0] if call.args else None
                # 实参形状：Name（函数对象）或 str 常量（job 类型键，
                # 如 register_handler("resolve_effect", _handle)）
                if isinstance(first, ast.Name):
                    symbol = first.id
                elif isinstance(first, ast.Constant) and isinstance(
                        first.value, str):
                    symbol = first.value
                else:
                    symbol = (getattr(call.func, "attr", "")
                              or getattr(call.func, "id", ""))
                # handler 绑定（复验 A3）：第二个实参是被绑定的处理函数——
                # 同键换绑是生产行为变化，必须进入漂移合同
                second = call.args[1] if len(call.args) > 1 else None
                handler = (second.id if isinstance(second, ast.Name) else "")
                found.append({"symbol": symbol,
                              "kind": "worker_registration",
                              "handler": handler,
                              "line": getattr(node, "lineno", 0)})
    return found


def discovered_entries_diff(
    root: Path,
    *,
    declared: list[tuple[str, str]],
    package_dirs=None,
    declared_entries_meta: list[dict] | None = None,
) -> dict:
    """生产模块入口扫描 vs 声明 inventory 的双向差集（修复计划 §6.5）。

    返回 ``{"discovered": [...], "undeclared": [...], "missing": [...]}``：
    新增未登记入口（undeclared）与失效登记（missing）都视为漂移门禁失败；
    豁免必须给真实 external/intentional boundary 理由。
    """
    index = ProjectIndex(root, package_dirs=package_dirs or ["pkg"])
    declared_entries_meta = declared_entries_meta or []
    discovered: list[dict] = []
    for rel, ctx in sorted(index._by_path.items()):
        for hit in _scan_entries_in_file(ctx):
            record = {"file": rel, "symbol": hit["symbol"],
                      "kind": hit["kind"]}
            # handler 绑定进漂移合同（复验 A3）：同键换绑或 handler 体变化
            # 都改变 discovered 记录 → manifest hash 漂移
            handler = hit.get("handler", "")
            if handler:
                record["handler"] = handler
                h_node = _find_in_ctx(ctx, handler)
                if h_node is not None:
                    record["handler_body_hash"] = body_hash(h_node)
                else:
                    record["handler_body_hash"] = ""
            discovered.append(record)
    declared_set = {(f, s) for f, s in declared}
    undeclared = [d for d in discovered
                  if (d["file"], d["symbol"]) not in declared_set]
    # missing = 声明锚点在源码里已不存在（文件缺失或符号消失）；声明锚点是
    # 普通函数/嵌套 def/赋值目标都不算 missing——发现器只扫注册语句；
    # 非 Python 锚点（如 Rust）跳过存在性检查，由显式 boundary 承担。
    missing: list[dict] = []
    discovered_syms = {(d["file"], d["symbol"]) for d in discovered}
    for f, s in sorted(declared_set):
        if not f.endswith(".py"):
            continue
        if (f, s) in discovered_syms:
            # 发现器自己扫到的注册符号（如 register_handler("x", ...) 的
            # 字符串键）不要求函数声明存在
            continue
        ctx = index.ctx_for(f)
        if ctx is None or not _file_declares_symbol(ctx, s):
            missing.append({"file": f, "symbol": s})
    # 反向注销差集（复验 A3）：声明了 registration 期望的锚点，发现器却
    # 没扫到——注册被删除（即使函数保留）即漂移，阻断生成
    for entry in declared_entries_meta:
        key = (entry["file"], entry["symbol"])
        if key in discovered_syms:
            continue
        if entry.get("registration"):
            missing.append({"file": entry["file"], "symbol": entry["symbol"],
                            "reason": "registration_removed",
                            "expected": entry["registration"]})
    return {"discovered": discovered, "undeclared": undeclared,
            "missing": missing}


# ============================================================
# Manifest 组装
# ============================================================

def git_revision() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def build_manifest() -> tuple[dict, list[str]]:
    """返回 (manifest, problems)。problems 非空 = 核心 unresolved，阻断。"""
    problems = list(flow_catalog.validate())
    problems += list(internal_flow_catalog.validate_inventory())
    nodes = []
    resolved = 0
    source_closure: dict[str, dict] = {}
    unresolved_calls = 0
    reachable_total = 0
    truncated_nodes: list[str] = []

    # 每文件只解析一次（125 节点共享 AST 上下文）；schema 3 用 repo-local
    # 项目索引做跨文件解析（修复计划 §6.5）
    ctx_cache: dict[str, _ModuleContext] = {}
    project_index = ProjectIndex(PROJECT_ROOT)

    def module_ctx(file_rel: str) -> _ModuleContext | None:
        if file_rel not in ctx_cache:
            ctx = project_index.ctx_for(file_rel)
            if ctx is not None:
                ctx_cache[file_rel] = ctx
                return ctx
            path = PROJECT_ROOT / file_rel
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                ctx_cache[file_rel] = None  # type: ignore[assignment]
                return None
            ctx_cache[file_rel] = _ModuleContext(file_rel, tree)
        return ctx_cache[file_rel]

    for node_id, spec in sorted(flow_catalog.NODES.items()):
        entry: dict = {
            "id": node_id,
            "label": spec.label,
            "lane": spec.lane,
            "kind": spec.kind,
        }
        if spec.derived:
            entry["derived"] = True
        if spec.opaque:
            entry["opaque"] = True
        if spec.source:
            file_rel, symbol = spec.source
            ctx = module_ctx(file_rel)
            found = find_symbol(PROJECT_ROOT / file_rel, symbol) if ctx else None
            if found is None or ctx is None:
                problems.append(
                    f"node {node_id}: symbol {symbol} not found in {file_rel}")
            else:
                resolved += 1
                class_name = symbol.split(".")[0] if "." in symbol else None
                closure = closure_of(found, ctx, class_name, index=project_index)
                unresolved_calls += closure["counts"].get("unresolved", 0) + sum(
                    1 for i in closure["items"]
                    if i["kind"] == "call" and i["resolved"] == "unresolved")
                helpers, boundaries, reach_truncated = reachable_symbols_cross(
                    project_index, file_rel, symbol)
                if reach_truncated:
                    truncated_nodes.append(node_id)
                reachable_total += len(helpers)
                entry["source_ref"] = {
                    "file": file_rel,
                    "symbol": symbol,
                    "body_hash": body_hash(found),
                    "features": structural_features(found),
                }
                source_closure[node_id] = {
                    "entry": closure,
                    "reachable_symbols": helpers,
                    "reachable_truncated": reach_truncated,
                    "boundaries": boundaries,
                }
        nodes.append(entry)

    # 入口发现差集（修复计划 §6.5 R4）：独立扫描生产模块 vs 声明 inventory
    discovery = discovered_entries_diff(
        PROJECT_ROOT,
        declared=[(e.source[0], e.source[1])
                  for e in internal_flow_catalog.RUNTIME_ENTRY_INVENTORY],
        package_dirs=ProjectIndex.PACKAGE_DIRS,
        declared_entries_meta=[
            {"file": e.source[0], "symbol": e.source[1],
             "registration": e.registration}
            for e in internal_flow_catalog.RUNTIME_ENTRY_INVENTORY])
    for hit in discovery["undeclared"]:
        problems.append(
            f"undiscovered entry not in inventory: {hit['file']}#{hit['symbol']}")
    for miss in discovery["missing"]:
        problems.append(
            f"declared entry anchor missing in source: {miss['file']}#{miss['symbol']}")

    # 入口 inventory（计划 §6.2 第 1 点）：声明入口 + 流程族 + 显式边界
    def _contract_digests(
            entry) -> dict:
        """合同/配置依赖摘要（复验 A3）：(file, line_filter_regex) →
        LF 归一内容（可按行过滤）的 sha256——合同/配置变化漂移 manifest。"""
        out = {}
        for file_rel, line_filter in (entry.contract_files or ()):
            path = PROJECT_ROOT / file_rel
            try:
                if not path.exists():
                    out[f"{file_rel}#missing"] = ""
                    continue
                raw = path.read_bytes().replace(b"\r\n", b"\n")
                if line_filter:
                    pat = re.compile(line_filter)
                    kept = [ln for ln in raw.decode("utf-8", "replace").split("\n")
                            if pat.search(ln)]
                    raw = ("\n".join(kept)).encode("utf-8")
                out[file_rel] = hashlib.sha256(raw).hexdigest()
            except OSError:
                out[f"{file_rel}#error"] = ""
        return out

    def _source_digest(file_rel: str) -> str:
        """非 Python 锚点的确定性内容摘要（验收报告 M4）：Rust/配置/合同
        文件变化必须漂移 manifest——只有名称/路径不构成有效漂移合同。

        换行归一为 LF 再哈希：Windows autocrlf 检出 CRLF、CI 检出 LF，
        原始字节哈希会让同一提交在两端算出不同 digest（CI 实测）。
        """
        path = PROJECT_ROOT / file_rel
        try:
            raw = path.read_bytes().replace(b"\r\n", b"\n")
            return hashlib.sha256(raw).hexdigest() if path.exists() else ""
        except OSError:
            return ""

    discovered_records = {
        (d["file"], d["symbol"]): d for d in discovery["discovered"]}
    entries_serialized = []
    for e in internal_flow_catalog.RUNTIME_ENTRY_INVENTORY:
        record = {
            "entry_id": e.entry_id, "family": e.family, "root_kind": e.root_kind,
            "source": {"file": e.source[0], "symbol": e.source[1]},
            "origin": e.origin, "notes": e.notes, "boundary": e.boundary,
            # 注册证据期望（复验 A3）：反向差集的声明侧
            **({"registration": e.registration} if e.registration else {}),
            # 非 Python 锚点附源码摘要（空 = 文件缺失，同样可审计）
            **({"source_digest": _source_digest(e.source[0])}
               if not e.source[0].endswith(".py") else {}),
        }
        # worker 注册的 handler 绑定进 manifest（复验 A3）：同键换绑或
        # handler 体变化都会改变 discovered 记录 → hash 漂移
        d = discovered_records.get((e.source[0], e.source[1]))
        if d and d.get("handler"):
            record["registration_handler"] = d["handler"]
            record["registration_handler_body_hash"] = d.get(
                "handler_body_hash", "")
        # 合同/配置摘要（复验 A3 剩余合同）
        if e.contract_files:
            record["contract_digests"] = _contract_digests(e)
        entries_serialized.append(record)
    boundaries = [
        {"entry_id": e.entry_id, "boundary": e.boundary, "reason": e.notes,
         "source": {"file": e.source[0], "symbol": e.source[1]}}
        for e in internal_flow_catalog.RUNTIME_ENTRY_INVENTORY if e.boundary
    ]

    derived_or_opaque = sum(
        1 for n in flow_catalog.NODES.values() if n.derived or n.opaque)
    coverage = {
        "total_nodes": len(flow_catalog.NODES),
        "source_resolved": resolved,
        "derived_or_opaque": derived_or_opaque,
        "edges": len(flow_catalog.EDGES),
        "lanes": len(flow_catalog.LANES),
        "core_unresolved_allowed": 0,
        "closure_sites": sum(
            sum(c["entry"]["counts"].values()) for c in source_closure.values()
        ) if source_closure else 0,
        "unresolved_calls": unresolved_calls,
        "reachable_symbols": reachable_total,
        "reachable_truncated_nodes": truncated_nodes,
        "declared_runtime_entries": len(entries_serialized),
        "explicit_boundaries": len(boundaries),
    }

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "topology_version": flow_catalog.TOPOLOGY_VERSION,
        "generator_version": GENERATOR_VERSION,
        "canonicalization": "stella-flow-content-v1",
        "entry_discovery": {
            "discovered": discovery["discovered"],
            "undeclared": discovery["undeclared"],
            "missing": discovery["missing"],
            "note": "发现差集非空即门禁失败（problems）；豁免须给真实边界理由",
        },
        "lanes": [list(lane) for lane in flow_catalog.LANES],
        "nodes": nodes,
        "edges": [
            {
                "src": e.src, "dst": e.dst, "kind": e.kind, "label": e.label,
                # runtime_evidence（修复计划 §6.4）：explicit=已在真实控制
                # 边界埋点；static_only=静态目录关系，运行未确认
                "runtime_evidence": (
                    "explicit" if (e.src, e.dst) in flow_catalog.EXPLICIT_EDGES
                    else "static_only"),
            }
            for e in flow_catalog.EDGES
        ],
        "entry_roots": dict(flow_catalog.ENTRY_ROOTS),
        "hook_node_ids": dict(flow_catalog.HOOK_NODE_IDS),
        "post_hook_node_ids": dict(flow_catalog.POST_HOOK_NODE_IDS),
        "source_closure": source_closure,
        "entry_inventory": {
            "families": [
                {"family_id": f.family_id, "label": f.label,
                 "description": f.description, "milestone": f.milestone}
                for f in internal_flow_catalog.PROCESS_FAMILIES.values()
            ],
            "entries": entries_serialized,
            "boundaries": boundaries,
            "coverage_denominators":
                internal_flow_catalog.coverage_denominators(),
        },
        "coverage": coverage,
    }
    return manifest, problems


def content_hash(manifest: dict) -> str:
    """内容 hash：排除 source_revision（每次构建独立标识，计划 §6.1）。"""
    payload = {k: v for k, v in manifest.items() if k != "source_revision"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def with_revision(manifest: dict) -> dict:
    manifest["source_revision"] = git_revision()
    return manifest


def semantic_diff(old: dict, new: dict) -> dict:
    """两次 manifest 的语义差异（计划 §6.2 第 7 点）：节点/边/闭包签名。"""
    old_nodes = {n["id"]: n for n in old.get("nodes", [])}
    new_nodes = {n["id"]: n for n in new.get("nodes", [])}
    body_changed = [
        nid for nid, n in new_nodes.items()
        if nid in old_nodes
        and (n.get("source_ref") or {}).get("body_hash")
        != (old_nodes[nid].get("source_ref") or {}).get("body_hash")
    ]
    return {
        "nodes_added": sorted(set(new_nodes) - set(old_nodes)),
        "nodes_removed": sorted(set(old_nodes) - set(new_nodes)),
        "body_changed": sorted(body_changed),
        "edges_added": sorted(
            {(e["src"], e["dst"]) for e in new.get("edges", [])}
            - {(e["src"], e["dst"]) for e in old.get("edges", [])}),
        "edges_removed": sorted(
            {(e["src"], e["dst"]) for e in old.get("edges", [])}
            - {(e["src"], e["dst"]) for e in new.get("edges", [])}),
        "topology_changed": old.get("topology_version") != new.get("topology_version"),
    }


# ============================================================
# 命令行
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="与已提交 manifest 比对；漂移时退出码 1")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT,
                        help="manifest 输出目录")
    args = parser.parse_args()

    manifest, problems = build_manifest()
    if problems:
        for p in problems:
            print(f"COVERAGE PROBLEM: {p}", file=sys.stderr)
        print(f"generation blocked: {len(problems)} problem(s)", file=sys.stderr)
        return 2
    manifest = with_revision(manifest)
    digest = content_hash(manifest)

    if args.check:
        existing = sorted(args.output.glob("message-flow.*.json"))
        for path in existing:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("topology_version") == manifest["topology_version"]:
                if content_hash(data) == digest:
                    print(f"check ok: {path.name} matches current source")
                    return 0
                diff = semantic_diff(data, manifest)
                print(
                    f"DRIFT: {path.name} does not match current source.\n"
                    f"semantic diff: {json.dumps(diff, ensure_ascii=False)}\n"
                    "The flow catalog or instrumented sources changed; "
                    "regenerate with `python scripts/generate_message_flow.py` "
                    "and commit the new manifest.",
                    file=sys.stderr,
                )
                return 1
        print(
            f"DRIFT: no manifest for topology_version "
            f"{manifest['topology_version']} under {args.output}.\n"
            "Regenerate with `python scripts/generate_message_flow.py`.",
            file=sys.stderr,
        )
        return 1

    args.output.mkdir(parents=True, exist_ok=True)
    out_path = args.output / f"message-flow.{digest[:12]}.json"
    out_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"generated {out_path.relative_to(PROJECT_ROOT)} "
          f"(topology {manifest['topology_version']}, content {digest[:12]}, "
          f"{manifest['coverage']['total_nodes']} nodes, "
          f"{manifest['coverage']['source_resolved']} source-resolved, "
          f"{manifest['coverage']['closure_sites']} closure sites, "
          f"{manifest['coverage']['reachable_symbols']} reachable symbols)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
