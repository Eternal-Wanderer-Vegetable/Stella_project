# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""``python -m deploy plugin-check <插件目录>``：插件接入规范的自检器。

分层照 doctor 的惯例（``probe.collect`` → ``checks.run_all`` → ``report``）：

| 层 | 这里的东西 | 有无副作用 |
|---|---|---|
| 事实采集 | ``collect(plugin_dir) -> PluginFacts`` | 有（读盘 + **import 并实例化插件**）|
| 判定 | ``check_*(facts)`` / ``run_all`` | 无，纯函数 |
| 渲染 | ``to_terminal`` / ``to_json`` | 无 |

分层的收益全在中间那层：每条检查都能在单测里**凭空构造事实**来验证，不需要真插件、
不需要 embedding 服务、不需要事件循环。``PluginFacts`` 的字段缺省值一律取「合规插件」
（同 ``deploy/models.py::Snapshot`` 的惯例），所以一份空事实跑出来是零条结论。

**本模块会执行被检查的插件代码**：枚举 ``@llm_tool`` 工具的唯一办法是 import 插件模块并
实例化它的 ``Star`` 子类——``@llm_tool`` 是在类体执行时才往 ``llm_tools`` 登记的。这与启动时
``loader.load_plugin()`` 做的事完全同类，不是新增的风险面，但**必须在输出里说出来**
（终端头部一行 + JSON 的 ``executed_plugin_code``），否则用户以为自己只是跑了个静态检查。

级别语义沿用 ``deploy/checks.py``：``error`` = 不符合规范（退出码非零）、``warn`` = 有隐患、
``info`` = 纯告知（如「这条会被用户层顶掉」）。``None`` = 该检查不适用，跳过。
"""

from __future__ import annotations

import asyncio
import contextlib
import difflib
import importlib
import io
import json
import re
import sys
import tokenize
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

from capability.loader import (
    PLUGIN_DECL_DOMAIN,
    PLUGIN_DECL_DRAFT_FILENAME,
    PLUGIN_DECL_FILENAME,
    load_capabilities,
    parse_declaration,
)
from capability.registry import (
    KIND_ASTRBOT_TOOL,
    SOURCE_PLUGIN,
    Capability,
    CapabilityRegistry,
)

from . import report
from .models import CheckResult

# ---------- 标定常量 ----------

# examples 条数下限。实测 4~6 句才稳（见 docs/plugin-spec.md §6.3），少于 3 条时
# 原型均值几乎等于单句，一条跑偏的 example 就能把整个能力的原型拽走。
MIN_EXAMPLES = 3
# 关键词长度下限。「新番」这种两字词会命中「新番组」「更新番外」；教训见
# config/capabilities/entertainment.toml 里 anime.recommend 用「番剧推荐」而不是「新番」。
MIN_KEYWORD_CHARS = 3
# 同域原型**最近间距**（1 − 同域两两原型余弦的最大值）的下限。0.06 这个数来自首轮实测：
# 5 个 ACG 工具对一句「主管，这是？」给出 0.443/0.412/0.388/0.386/0.385，彼此差不到 0.06
# —— 那就是「同域能力在语义空间里挤成一个点」的形态，首位选谁基本靠掷骰子。
SEPARATION_MIN_SPREAD = 0.06
# 负样本最高分与置信线的余量下限。工具描述当语料时实测 −0.024（负样本压过置信线，
# 即无关请求会触发工具）；换成中文问句 examples 后 +0.141。低于 0 一定要报。
NEGATIVE_MARGIN_MIN = 0.0

# examples 疑似「指令句」的字面标记。用途错配是整条设计的起点：工具 description 是写给
# 决策器的指令句（「当用户询问 X 时调用」），而 examples 要写用户**会怎么问**。
IMPERATIVE_MARKERS = ("当用户", "时调用", "本工具", "用于", "该工具", "调用此")
# 出网库。命中即要求 metadata.yaml 里有 stella.egress 声明（披露契约，不是沙箱）。
_EGRESS_LIBS = ("httpx", "aiohttp", "requests", "urllib3", "websockets")


def imperative_marker(text: str) -> str:
    """命中的第一个「指令句」标记，没命中返回空串。

    ``plugin-scaffold`` 用同一个判据把模型偶发写成指令句的 example 直接扔掉：生成侧
    与校验侧共用**判据本身**而不是各自拿着同一张词表，才不会出现「生成器放过、校验器
    报警」这种谁都不信的组合。
    """
    return next((m for m in IMPERATIVE_MARKERS if m in text), "")

_SKIP_DIRS = frozenset({"__pycache__", ".venv", "venv", "node_modules", ".git", ".idea"})
_REQ_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+")
_URL_IMAGE_RE = re.compile(r"\burl_image\s*\(")
_CREATE_TASK_RE = re.compile(r"\bcreate_task\s*\(")
_REGISTER_TASK_RE = re.compile(r"\bregister_task\s*\(")
_EGRESS_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+(" + "|".join(_EGRESS_LIBS) + r")\b",
)

# ---------- 事实 ----------


class ToolFact(NamedTuple):
    """一个 ``@llm_tool`` 工具的事实。``required`` 取 ``parameters["required"]``。

    ``params`` 是 ``(参数名, 参数说明)``，取自 ``parameters["properties"]``——它不产生任何
    结论，只喂 ``plugin-scaffold``：必填 ``city(城市名，如「杭州」)`` 直接告诉生成器「用户的
    问法里会带地名」，而这是光看工具名与 description 拿不到的信息（``docs/plugin-spec.md``
    §12 那张输入排序表把 docstring 的 ``Args`` 排在工具描述之前，就是这个原因）。
    """

    name: str
    description: str = ""
    required: tuple[str, ...] = ()
    params: tuple[tuple[str, str], ...] = ()


@dataclass
class PluginFacts:
    """一个插件目录的全部事实。**缺省值一律是「合规插件」**。

    与 ``deploy/models.py::Snapshot`` 同一个惯例：一份没填过的事实跑完 ``run_all``
    应当零条结论。这让每条检查的单测只需要填它自己关心的那一两个字段，读起来就是
    「什么情况下会报什么」，不会被一堆无关的构造代码埋掉。
    """

    plugin_dir: Path = field(default_factory=Path)
    dir_name: str = ""
    # 目录布局
    has_main_py: bool = True
    archives: list[str] = field(default_factory=list)
    # 加载结果。``executed_plugin_code`` 为假时，凡是依赖工具清单的检查一律跳过——
    # 拿不到工具清单却去判「provider 指向的工具不存在」，会把每条声明都报成拼写错。
    executed_plugin_code: bool = False
    load_error: str = ""
    plugin_name: str = ""
    plugin_version: str = ""
    tools: list[ToolFact] = field(default_factory=list)
    # 该插件新增的 ``(指令名, 说明)``。同样不产生结论：指令走唤醒前缀显式触发，写不写
    # 声明都照样能用。收进来只为喂生成器——``/天气`` 这种指令名本身就是用户的自然说法。
    commands: list[tuple[str, str]] = field(default_factory=list)
    # 依赖
    requirements: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    # 声明
    declaration_present: bool = True
    draft_present: bool = False
    declaration_error: str = ""
    reviewed: bool | None = None
    capabilities: list[Capability] = field(default_factory=list)
    # 用户层 / 出厂层的既有归属，用来判断「会被谁顶掉」
    config_claims: dict[str, str] = field(default_factory=dict)
    config_capability_ids: list[str] = field(default_factory=list)
    # 源码扫描（值形如 ``main.py:42``）
    url_image_hits: list[str] = field(default_factory=list)
    bare_create_task_hits: list[str] = field(default_factory=list)
    uses_register_task: bool = False
    # 出网披露
    egress_libs: list[str] = field(default_factory=list)
    egress_declared: list[str] = field(default_factory=list)
    # 量化指标。第 3 期由 plugin-scaffold 填（它算完 embedding 顺手带过来），
    # 为 ``None`` 时对应检查跳过——本命令自己不拉起 embedding 服务。
    separation: dict[str, Any] | None = None

    def declared_tools(self) -> set[str]:
        """本插件自带声明认领的工具名。"""
        return {
            p.tool_name
            for c in self.capabilities
            for p in c.providers
            if p.kind == KIND_ASTRBOT_TOOL and p.tool_name
        }

    def required_by_tool(self) -> dict[str, tuple[str, ...]]:
        return {t.name: t.required for t in self.tools}


# ---------- 事实采集（有副作用） ----------


def _archives_in(plugin_dir: Path) -> list[str]:
    """插件目录**顶层**没解压的压缩包。

    只看顶层：``astrbot_compat.loader.unextracted_archives()`` 扫的是插件根目录
    （用于「插件放进去了却 discovered=[]」），这里换成扫单个插件目录，判据（后缀表）
    仍复用它那一份，两处各写一张表必然漂移。递归会把插件自带的资源包也报出来。
    """
    from astrbot_compat.loader import _ARCHIVE_SUFFIXES

    found: list[str] = []
    try:
        entries = list(plugin_dir.iterdir())
    except OSError:
        return found
    for p in entries:
        if p.suffix.lower() not in _ARCHIVE_SUFFIXES:
            continue
        with contextlib.suppress(OSError):
            if p.is_file():
                found.append(p.name)
    return sorted(found)


def _read_requirements(plugin_dir: Path) -> list[str]:
    """``requirements.txt`` 里的**分发包名**（不是模块名）。

    只取包名，版本约束一律丢掉：这里要回答的是「装了没有」，而不是「版本对不对」——
    后者由 pip 自己在安装时把关，我们再判一遍只会与 pip 的解析规则漂移。
    """
    try:
        raw = (plugin_dir / "requirements.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    names: list[str] = []
    for line in raw.splitlines():
        body = line.split("#", 1)[0].strip()
        # ``-r other.txt`` / ``--index-url ...`` 这类选项行不是包名
        if not body or body.startswith("-"):
            continue
        # ``;`` 之后是环境标记，``@`` 之后是 PEP 508 直接引用，都不属于包名
        body = body.split(";", 1)[0].split("@", 1)[0].strip()
        matched = _REQ_NAME_RE.match(body)
        if matched:
            names.append(matched.group(0))
    return list(dict.fromkeys(names))


def _is_installed(name: str) -> bool:
    """按**分发包名**查是否已安装。

    刻意不用 ``importlib.util.find_spec``：模块名与分发包名经常不同
    （PyYAML→yaml、Pillow→PIL、beautifulsoup4→bs4），按模块名查会把装好的依赖
    报成缺失——一条假的 error 比没有这条检查更糟。``distribution()`` 自带
    PEP 503 名称归一化，``Foo_Bar`` 与 ``foo-bar`` 都能查到。
    """
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        distribution(name)
    except PackageNotFoundError:
        return False
    except Exception:
        # 探测本身出错（元数据损坏等）时宁可漏报：这条检查是 error 级的
        return True
    return True


def _blank_literals(text: str) -> list[str]:
    """把源码里的字符串与注释涂成空白，返回逐行文本。

    为什么要涂：底下三条检查（``url_image``、裸 ``create_task``、出网 import）都是
    **字面**匹配，而讲这些坑的文档往往就写在 docstring 里——本目录下的模板插件正是
    这样，它的 ``initialize`` docstring 里写着「裸 ``asyncio.create_task(...)`` 会残留」。
    不涂的话校验器会把「说明为什么不该这么写」判成「这么写了」。会把参考写法判成
    违规的检查比没有这条检查更糟：它教用户忽略警告。

    用 ``tokenize`` 而不是逐行判 ``#``：多行 docstring 跨行，逐行判据抓不到。
    f-string 里的插值表达式是真代码，Py3.12+ 把它拆成 ``FSTRING_MIDDLE``（只有文本部分
    是字面量），因此照 token 类型涂正好是对的。文件语法错时原样返回——这一层不负责报语法错，
    真有语法错的话 import 那步会报 error。
    """
    lines = text.splitlines()
    fstring_middle = getattr(tokenize, "FSTRING_MIDDLE", None)
    blank_types = {tokenize.STRING, tokenize.COMMENT}
    if fstring_middle is not None:
        blank_types.add(fstring_middle)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except Exception:
        return lines
    for tok in tokens:
        if tok.type not in blank_types:
            continue
        (srow, scol), (erow, ecol) = tok.start, tok.end
        for row in range(srow, erow + 1):
            index = row - 1
            if not 0 <= index < len(lines):
                continue
            line = lines[index]
            start = scol if row == srow else 0
            end = ecol if row == erow else len(line)
            lines[index] = line[:start] + " " * max(0, end - start) + line[end:]
    return lines


def _iter_sources(plugin_dir: Path):
    """插件目录下的 ``.py``，跳过缓存与虚拟环境。产出 ``(相对路径, 行号, 代码行)``。

    产出的是 ``_blank_literals`` 处理过的行——字符串与注释已涂白，行号与列位仍与原文对齐。
    """
    for path in sorted(plugin_dir.rglob("*.py")):
        if _SKIP_DIRS.intersection(path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(plugin_dir).as_posix()
        for lineno, line in enumerate(_blank_literals(text), start=1):
            yield rel, lineno, line


def _scan_sources(plugin_dir: Path, facts: PluginFacts) -> None:
    """字面扫描源码（字符串与注释已由 ``_iter_sources`` 涂白）。

    这是**字面**匹配而不是 AST 分析：要判的三件事（``url_image`` 调用、裸
    ``create_task``、出网 import）都是「出现即需要提醒」，而 AST 分析要正确处理别名、
    动态属性、间接调用，复杂度换不来准确度——这几条本来就是 warn 级的提示。
    """
    egress: list[str] = []
    for rel, lineno, line in _iter_sources(plugin_dir):
        where = f"{rel}:{lineno}"
        if _URL_IMAGE_RE.search(line):
            facts.url_image_hits.append(where)
        if _REGISTER_TASK_RE.search(line):
            facts.uses_register_task = True
        elif _CREATE_TASK_RE.search(line):
            # 同一行里既有 register_task 又有 create_task 的写法
            # （``register_task(asyncio.create_task(...))``）是合规的，上面的 elif 已放过
            facts.bare_create_task_hits.append(where)
        matched = _EGRESS_IMPORT_RE.match(line)
        if matched:
            egress.append(matched.group(1))
    facts.egress_libs = sorted(set(egress))


def _declared_egress(plugin_dir: Path) -> list[str]:
    """``metadata.yaml`` 里 ``stella.egress`` 声明的 host 列表。

    两种写法都收：``- host: api.example.com`` 的表，或直接一个字符串。
    """
    from astrbot_compat.loader import _read_metadata

    meta = _read_metadata(plugin_dir) or {}
    stella = meta.get("stella")
    entries = stella.get("egress") if isinstance(stella, dict) else None
    if not isinstance(entries, list):
        return []
    hosts: list[str] = []
    for item in entries:
        if isinstance(item, str) and item.strip():
            hosts.append(item.strip())
        elif isinstance(item, dict):
            host = str(item.get("host") or "").strip()
            if host:
                hosts.append(host)
    return hosts


def _read_declaration(plugin_dir: Path, facts: PluginFacts) -> None:
    """读插件自带声明。**必须走 ``capability.loader.parse_declaration``**。

    自己再解析一遍 TOML 的话两套解析必然漂移，而漂移的表现是「校验说没问题、
    运行期却少一条能力」——校验器一旦不可信就没有意义了。
    """
    facts.declaration_present = (plugin_dir / PLUGIN_DECL_FILENAME).is_file()
    facts.draft_present = (plugin_dir / PLUGIN_DECL_DRAFT_FILENAME).is_file()
    if not facts.declaration_present:
        return
    parsed = parse_declaration(
        plugin_dir / PLUGIN_DECL_FILENAME,
        source=SOURCE_PLUGIN,
        domain=PLUGIN_DECL_DOMAIN,
    )
    facts.declaration_error = parsed.error
    facts.reviewed = parsed.reviewed
    facts.capabilities = list(parsed.capabilities)


def _read_config_tiers(facts: PluginFacts) -> None:
    """把用户层与出厂层载进一个**临时**注册表，取它们已经认领的工具。

    绝不碰模块级单例：本命令与运行期共用同一个进程内单例，往里灌一遍声明会让后续
    任何在同进程里跑的东西看到一个半装配的注册表。归属用公开的 ``claimed_by()`` 反查，
    先到先得的语义因此与运行期完全一致。
    """
    scratch = CapabilityRegistry()
    try:
        load_capabilities(target=scratch)
    except Exception:
        return
    facts.config_capability_ids = scratch.ids()
    claims: dict[str, str] = {}
    for cap in scratch.all():
        for provider in cap.providers:
            if not provider.tool_name:
                continue
            owner = scratch.claimed_by(provider.tool_name)
            if owner:
                claims[provider.tool_name] = owner
    facts.config_claims = claims


def _tool_params(parameters: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
    """``parameters["properties"]`` → ``(参数名, 说明)``，按 ``@llm_tool`` 的声明顺序。

    顺序照 dict 的插入序而不是排序：``add_func`` 是按 docstring ``Args`` 段逐条填进去的，
    那个顺序就是作者写的顺序，也是「必填的先出现」这个惯例所在。
    """
    props = ((parameters or {}).get("properties") or {})
    if not isinstance(props, dict):
        return ()
    return tuple(
        (str(name), str((spec or {}).get("description") or "").strip())
        for name, spec in props.items()
        if isinstance(spec, dict) or spec is None
    )


def _new_command_specs(handlers_before: set[str]) -> list[tuple[str, str]]:
    """本插件新增的 ``(指令名, 说明)``。解析规则复用 ``capability.inventory``。"""
    from astrbot_compat.registry import star_handlers_registry
    from capability.inventory import command_specs_of

    added = [h for h in star_handlers_registry if h.handler_full_name not in handlers_before]
    return command_specs_of(added)


async def _load_and_enumerate(plugin_dir: Path, facts: PluginFacts) -> None:
    """在事件循环内加载插件并枚举它新增的工具。

    必须在循环内：插件的 ``__init__`` 里 ``asyncio.create_task`` 是被允许的写法
    （见 ``loader._instantiate_failure_reason``），循环外加载会把合规插件报成实例化失败。
    """
    from astrbot_compat.llm.tool import llm_tools
    from astrbot_compat.loader import (
        get_failed_plugins,
        initialize_plugins,
        load_plugin,
        terminate_plugins,
    )
    from astrbot_compat.registry import star_handlers_registry

    before = set(llm_tools.names())
    # 指令要靠前后差集取：``md.star_handler_full_names`` 只收本模块登记的 handler，
    # 定义在插件子模块里的那些不在其中（``base._resolve_plugin_dir_name`` 做前缀匹配
    # 正是为此）。差集不依赖 handler 定义在哪个模块，本插件新增了什么就是什么。
    handlers_before = {h.handler_full_name for h in star_handlers_registry}
    try:
        md = load_plugin(plugin_dir)
        if md is None:
            facts.load_error = get_failed_plugins().get(plugin_dir.name) or (
                f"{plugin_dir.name}/main.py 里没有继承 Star 的插件类"
            )
            return
        facts.plugin_name = md.name
        facts.plugin_version = md.version
        # 工具可能在 initialize() 里才登记（bot.py 的装配序也是先 initialize 后同步能力），
        # 所以枚举必须在它之后
        await initialize_plugins()
        if not md.activated:
            key = md.root_dir_name or plugin_dir.name
            facts.load_error = get_failed_plugins().get(key) or "initialize() 未成功"
        facts.tools = sorted(
            ToolFact(
                name=t.name,
                description=(t.description or "").strip(),
                required=tuple((t.parameters or {}).get("required") or ()),
                params=_tool_params(t.parameters),
            )
            for t in llm_tools.tools
            if t.name not in before
        )
        facts.commands = _new_command_specs(handlers_before)
    finally:
        # 插件在 initialize 里起的后台任务不该活过这条命令
        with contextlib.suppress(Exception):
            await terminate_plugins()


def _load_plugin(plugin_dir: Path, facts: PluginFacts) -> None:
    """装 shim、复刻 ``load_all_plugins()`` 的前置动作，然后加载这一个插件。

    前置动作必须一样（sys.path 插项目根 → 清 import 缓存 → ``StarTools.initialize``），
    否则校验器的加载环境与启动时不同，就会出现「校验通过但启动失败」或反之。
    """
    from astrbot_compat import install_shim

    install_shim()
    facts.executed_plugin_code = True
    try:
        from config import PROJECT_ROOT

        root = str(PROJECT_ROOT)
        if root not in sys.path:
            sys.path.insert(0, root)
    except Exception:
        pass
    importlib.invalidate_caches()
    with contextlib.suppress(Exception):
        from astrbot_compat.base import StarTools
        from astrbot_compat.context import get_context

        StarTools.initialize(get_context())
    try:
        asyncio.run(_load_and_enumerate(plugin_dir, facts))
    except Exception as e:
        # 加载器自己抛出来的（挂载失败等）——照 load_all_plugins 的兜底记 repr
        facts.load_error = facts.load_error or repr(e)


@contextlib.contextmanager
def _logs_to_stderr():
    """把 nonebot 的日志从 stdout 挪到 stderr，只在采集期间生效。

    ``collect()`` 会拉起三层能力加载与插件 import，两者都往 nonebot 的 logger 写，
    而 nonebot 默认把 sink 挂在 ``sys.stdout``（``nonebot/log.py`` 的 ``logger_id``）。
    不挪的话 ``--json`` 的输出里会混进带 ANSI 转义的日志行，GUI 那侧 ``json.loads``
    直接失败。stdout 只留报告、日志走 stderr——终端里两者照旧都看得见。

    不能用 ``contextlib.redirect_stdout``：loguru 在 ``add()`` 时就捕获了流对象，
    之后替换 ``sys.stdout`` 影响不到已经挂上的 sink。
    """
    try:
        from nonebot import log as nb_log
        from nonebot import logger
    except Exception:  # 没装 nonebot 的环境（纯逻辑测试）——本就没有日志要挪
        yield
        return
    handler_id = getattr(nb_log, "logger_id", None)
    if handler_id is None:
        yield
        return
    try:
        logger.remove(handler_id)
    except ValueError:  # 已被别处摘掉（如 bot.py 重配过日志）
        yield
        return
    new_id = logger.add(
        sys.stderr,
        level=0,
        diagnose=False,
        filter=nb_log.default_filter,
        format=nb_log.default_format,
    )
    try:
        yield
    finally:
        logger.remove(new_id)
        nb_log.logger_id = logger.add(
            sys.stdout,
            level=0,
            diagnose=False,
            filter=nb_log.default_filter,
            format=nb_log.default_format,
        )


def collect(plugin_dir: Path) -> PluginFacts:
    """采集一个插件目录的全部事实。命名对齐 ``probe.collect()``。

    顺序有讲究：先做纯读盘的部分，**最后**才 import 插件。这样目录里连 ``main.py``
    都没有时不会白执行一次 import，声明写错时也仍能拿到 TOML 的解析结论。
    """
    plugin_dir = Path(plugin_dir)
    facts = PluginFacts(plugin_dir=plugin_dir, dir_name=plugin_dir.name)
    facts.has_main_py = (plugin_dir / "main.py").is_file()
    facts.archives = _archives_in(plugin_dir)
    facts.requirements = _read_requirements(plugin_dir)
    facts.missing_requirements = [n for n in facts.requirements if not _is_installed(n)]
    _scan_sources(plugin_dir, facts)
    facts.egress_declared = _declared_egress(plugin_dir)
    _read_declaration(plugin_dir, facts)
    with _logs_to_stderr():
        _read_config_tiers(facts)
        if facts.has_main_py:
            _load_plugin(plugin_dir, facts)
    return facts


# ---------- 判定（纯函数） ----------


def check_layout(facts: PluginFacts) -> CheckResult | None:
    """① 目录布局：``main.py`` 是插件的唯一入口判据。"""
    if not facts.has_main_py:
        if facts.archives:
            return CheckResult(
                id="plugin_layout",
                level="error",
                title=f"{facts.dir_name} 里没有 main.py，只有未解压的压缩包",
                detail=f"发现压缩包：{'、'.join(facts.archives)}",
                fix_hint="把压缩包解压出来，让插件目录里直接有 main.py（解压后可删除压缩包）",
            )
        return CheckResult(
            id="plugin_layout",
            level="error",
            title=f"{facts.dir_name} 里没有 main.py",
            detail="加载器按 main.py 判定一个目录是不是插件，没有它的目录会被直接跳过。",
            fix_hint="确认传入的是插件自己的目录（而不是它的父目录），且目录里有 main.py",
        )
    if facts.archives:
        return CheckResult(
            id="plugin_layout",
            level="warn",
            title="插件目录里残留了压缩包",
            detail=f"{'、'.join(facts.archives)}——插件本身能加载，但这些文件不会被用到。",
            fix_hint="删掉残留的压缩包，免得下次误以为插件没解压",
        )
    return None


def check_load(facts: PluginFacts) -> CheckResult | None:
    """② 能否在 shim 下加载并 ``initialize()``。"""
    if not facts.executed_plugin_code:
        return None
    if facts.load_error:
        return CheckResult(
            id="plugin_load",
            level="error",
            title="插件加载失败",
            detail=facts.load_error,
            fix_hint=(
                "按上面的原因修复。缺第三方依赖是最常见的一类："
                "把它写进插件的 requirements.txt 并安装"
            ),
        )
    return None


def check_requirements(facts: PluginFacts) -> CheckResult | None:
    """③ ``requirements.txt`` 声明的依赖是否已装。"""
    if not facts.missing_requirements:
        return None
    return CheckResult(
        id="plugin_requirements",
        level="error",
        title=f"缺少 {len(facts.missing_requirements)} 个已声明的依赖",
        detail="、".join(facts.missing_requirements),
        fix_hint=f'pip install -r "{facts.plugin_dir / "requirements.txt"}"',
    )


def check_tool_undeclared(facts: PluginFacts) -> CheckResult | None:
    """④ 有 ``@llm_tool`` 却没有任何声明认领它 —— **本规范的核心检查**。

    运行期对这种插件是放过的（照常注册、不参与路由、启动时 WARNING 点名），因为拦下来
    只会让能用的插件变不能用。但校验器必须报 error：现象是「插件装了、日志说派生成功了、
    可就是从来不被调用」，而这在运行期只是一条容易被划过去的警告。

    「被认领」含用户层与出厂层：本项目自带的 ``entertainment.toml`` 就替
    ``astrbot_plugin_bilibili`` 写了声明，那种插件不该被报错。
    """
    if not facts.executed_plugin_code or facts.load_error:
        return None
    own = facts.declared_tools()
    undeclared = [
        t.name for t in facts.tools if t.name not in own and t.name not in facts.config_claims
    ]
    if not undeclared:
        return None
    return CheckResult(
        id="plugin_tool_undeclared",
        level="error",
        title=f"{len(undeclared)} 个工具没有能力声明，聊天中不会被触发",
        detail=(
            f"{'、'.join(undeclared)}。这些工具照常注册、仍可被显式执行，"
            f"但不参与语义路由（Router 的候选集只取 routable() 的能力）。"
        ),
        fix_hint=(
            f"在插件目录里放一份 {PLUGIN_DECL_FILENAME}，为每个工具写一条 [[capability]]"
            f"（带中文 examples）；格式见 docs/plugin-spec.md，"
            f"可用 python -m deploy plugin-scaffold 生成初稿"
        ),
    )


def check_provider_missing(facts: PluginFacts) -> CheckResult | None:
    """⑤ 声明里的 ``providers`` 指向了不存在的工具名。

    工具名拼错是静默失效的头号原因：``routable()`` 只查 enabled/backoff、不查工具是否
    存在，于是那条能力照常参与路由竞争、抢走 ``ROUTER_CAPABILITY_MARGIN`` 的间距，
    最后必然在 Comes 里 failed。
    """
    if not facts.executed_plugin_code or facts.load_error:
        return None
    known = {t.name for t in facts.tools}
    if not known:
        return None
    problems: list[str] = []
    for cap in facts.capabilities:
        for provider in cap.providers:
            if provider.kind != KIND_ASTRBOT_TOOL or not provider.tool_name:
                continue
            if provider.tool_name in known:
                continue
            near = difflib.get_close_matches(provider.tool_name, sorted(known), n=1, cutoff=0.6)
            suffix = f"（你可能想写的是 {near[0]}）" if near else ""
            problems.append(f"{cap.id} → {provider.tool_name}{suffix}")
    if not problems:
        return None
    return CheckResult(
        id="plugin_provider_missing",
        level="error",
        title=f"{len(problems)} 个 provider 指向本插件没有的工具",
        detail="；".join(problems) + f"。本插件实际登记的工具：{'、'.join(sorted(known))}",
        fix_hint=(
            "把 providers 里的工具名改成 @llm_tool 的函数名。"
            f"若本意是给**别的**插件的工具写声明，那份声明应当放在 "
            f"config/capabilities/ 而不是本插件的 {PLUGIN_DECL_FILENAME}"
        ),
    )


def check_declaration(facts: PluginFacts) -> CheckResult | None:
    """⑥ 声明文件本身可用吗：能解析、不是草稿、已过人审。

    三个分支合成一条检查而不是三条：它们互斥，且用户要做的下一步都在同一句话里——
    「让这个目录里有一份能被载入的 capability.toml」。
    """
    if facts.declaration_present and facts.declaration_error:
        return CheckResult(
            id="plugin_declaration",
            level="error",
            title=f"{PLUGIN_DECL_FILENAME} 无法解析，整份不会被载入",
            detail=facts.declaration_error,
            fix_hint="按报错修 TOML 语法；至少要有一个 [[capability]] 段",
        )
    if not facts.declaration_present and facts.draft_present:
        return CheckResult(
            id="plugin_declaration",
            level="error",
            title=f"只有草稿 {PLUGIN_DECL_DRAFT_FILENAME}，它一律不会被载入",
            detail=(
                "文件名不匹配是 reviewed 之外的第一道闸门——生成的 examples 与 keywords "
                "没有人过目，而错的 examples 会把不相关的请求吸进来，比没有 examples 更糟。"
            ),
            fix_hint=(
                f"逐条核对 examples（写的是「用户会怎么问」）与 keywords，"
                f"改名为 {PLUGIN_DECL_FILENAME} 并把 reviewed 改成 true"
            ),
        )
    if facts.declaration_present and facts.reviewed is False:
        return CheckResult(
            id="plugin_declaration",
            level="error",
            title=f"{PLUGIN_DECL_FILENAME} 标记为 reviewed = false，整份不会被载入",
            detail="这是 plugin-scaffold 生成的草稿状态，等待人工核对。",
            fix_hint="核对完 examples 与 keywords 后把 reviewed 改成 true",
        )
    return None


def check_examples_count(facts: PluginFacts) -> CheckResult | None:
    """⑦ ``examples`` 太少。原型是**均值**，句子少时一条跑偏的就能把它拽走。"""
    thin = [
        f"{c.id}({len(c.examples)} 条)"
        for c in facts.capabilities
        if len(c.examples) < MIN_EXAMPLES
    ]
    if not thin:
        return None
    return CheckResult(
        id="plugin_examples_count",
        level="warn",
        title=f"{len(thin)} 条能力的 examples 少于 {MIN_EXAMPLES} 条",
        detail="、".join(thin),
        fix_hint="每条能力写 4~6 句中文问句，覆盖不同的问法（实测这个量级才稳）",
    )


def check_examples_style(facts: PluginFacts) -> CheckResult | None:
    """⑧ ``examples`` 疑似指令句 —— 用途错配是整条设计的起点。"""
    offenders: list[str] = []
    for cap in facts.capabilities:
        for example in cap.examples:
            hit = imperative_marker(example)
            if hit:
                offenders.append(f"{cap.id}：「{example}」含「{hit}」")
    if not offenders:
        return None
    return CheckResult(
        id="plugin_examples_style",
        level="warn",
        title=f"{len(offenders)} 条 example 像是写给决策器的指令句",
        detail="；".join(offenders),
        fix_hint=(
            "examples 要写**用户会怎么问**（「明天天气怎么样」），"
            "不是「什么时候该调用我」（「当用户询问天气时调用」）——"
            "Router 拿它和用户的问句算余弦，两种文本形态不同构"
        ),
    )


def check_keywords_overlap(facts: PluginFacts) -> CheckResult | None:
    """⑨ 某条能力的 keyword 出现在**别的**能力的 example 里 —— 跨能力字面泄漏。

    Level 0 命中即执行、不做二次判定，所以一个泄漏的关键词就是一次高代价的工具假阳：
    用户问的是 A，L0 却拿 B 的关键词把 B 拍板执行了。

    **本检查刻意不是「keyword 是本能力某条 example 的子串」**。那个写法看着更机械化，
    但拿本项目出厂、带实测标定的 ``config/capabilities/entertainment.toml`` 一量就知道
    它会命中正确写法：``anime.recommend`` 的「番剧推荐」正是它自己 example
    「有什么新番推荐吗」的子串，``anime.schedule`` 的「放送」也是「星期一放送哪些番」的
    子串。会把参考标准判成违规的检查比没有这条检查更糟——它教用户忽略警告。
    要防的从来不是「keyword 与自己的 example 有重叠」（那本就正常），而是跨能力串味。
    """
    offenders: list[str] = []
    for cap in facts.capabilities:
        for keyword in cap.keywords:
            for other in facts.capabilities:
                if other.id == cap.id:
                    continue
                leaked = next((e for e in other.examples if keyword in e), "")
                if leaked:
                    offenders.append(f"{cap.id} 的「{keyword}」命中 {other.id} 的「{leaked}」")
    if not offenders:
        return None
    return CheckResult(
        id="plugin_keywords_overlap",
        level="warn",
        title=f"{len(offenders)} 处关键词跨能力泄漏",
        detail="；".join(offenders),
        fix_hint=(
            "把关键词收窄成只属于这一条能力的名词短语，"
            "或者干脆删掉让它走 Level 1 语义匹配——Level 0 命中就直接执行，没有兜底"
        ),
    )


def check_keywords_short(facts: PluginFacts) -> CheckResult | None:
    """⑩ 关键词太短。两字词在中文里几乎必然出现在别的词里。"""
    offenders = [
        f"{c.id}：「{k}」"
        for c in facts.capabilities
        for k in c.keywords
        if len(k) < MIN_KEYWORD_CHARS
    ]
    if not offenders:
        return None
    return CheckResult(
        id="plugin_keywords_short",
        level="warn",
        title=f"{len(offenders)} 个关键词短于 {MIN_KEYWORD_CHARS} 个字",
        detail="；".join(offenders),
        fix_hint=(
            "换成更长的名词短语。出厂声明里用「番剧推荐」而不是「新番」"
            "（后者会命中「新番组」「更新番外」），用「条动态」「的动态」而不是「动态」"
            "（后者会命中「动态壁纸」「动态规划」）"
        ),
    )


def check_keywords_required_args(facts: PluginFacts) -> CheckResult | None:
    """⑪ 工具有必填参数却给了 keywords。Level 0 取不出参数，拍板只是让 Comes 去猜。"""
    if not facts.executed_plugin_code or facts.load_error:
        return None
    required_by_tool = facts.required_by_tool()
    offenders: list[str] = []
    for cap in facts.capabilities:
        if not cap.keywords:
            continue
        for provider in cap.providers:
            params = required_by_tool.get(provider.tool_name)
            if params:
                offenders.append(f"{cap.id} → {provider.tool_name}(必填 {'、'.join(params)})")
    if not offenders:
        return None
    return CheckResult(
        id="plugin_keywords_required_args",
        level="warn",
        title=f"{len(offenders)} 条能力给了 keywords，但它的工具有必填参数",
        detail="；".join(offenders),
        fix_hint=(
            "Level 0 只做字面命中、不抽取参数，拍板执行等于让 Comes 去猜必填值。"
            "出厂声明里 anime.search（必填 keyword）刻意不给 keywords，"
            "而 video.dynamics 破例是因为它的参数有合理默认值——按这个标准取舍"
        ),
    )


def check_separation(facts: PluginFacts) -> CheckResult | None:
    """⑫ 同域原型分离度 / 负样本余量。事实由 ``plugin-scaffold`` 算完带过来。

    ``separation`` 为 ``None`` 时跳过：本命令不拉起 embedding 服务（那要下模型、要显存，
    而校验器必须能在任何机器上秒回）。阈值常量定在本模块，生成侧 import 它，标定只一份。
    """
    if not facts.separation:
        return None
    problems: list[str] = []
    spread = facts.separation.get("spread")
    margin = facts.separation.get("negative_margin")
    if isinstance(spread, (int, float)) and spread < SEPARATION_MIN_SPREAD:
        problems.append(
            f"同域原型最近间距仅 {spread:.3f}（下限 {SEPARATION_MIN_SPREAD}）——"
            f"同域能力之间几乎没有区分度，首位很容易选错",
        )
    if isinstance(margin, (int, float)) and margin < NEGATIVE_MARGIN_MIN:
        problems.append(
            f"负样本余量 {margin:+.3f}——无关请求的最高分已经压过置信线，会触发工具假阳",
        )
    if not problems:
        return None
    return CheckResult(
        id="plugin_separation",
        level="warn",
        title="原型语料的量化指标不达标",
        detail="；".join(problems),
        fix_hint=(
            "删掉或改写与本能力主题偏离的 example；同域能力挨得太近时，"
            "让每条 examples 只覆盖自己那个子意图，别互相包含"
        ),
    )


def check_collision(facts: PluginFacts) -> CheckResult | None:
    """⑬ 能力 id 或工具与用户层/出厂层撞名 —— 纯告知，不是错。

    级别是 ``info`` 而不是 ``warn``：撞名本身合法，三层优先级就是为它设计的
    （用户想改插件写歪的 examples，正是靠在 ``config/capabilities/`` 里覆盖一条）。
    但插件作者必须知道「我这条不会生效」，否则改了半天 examples 没有任何效果。
    """
    notes: list[str] = []
    for cap in facts.capabilities:
        if cap.id in facts.config_capability_ids:
            notes.append(f"能力 id {cap.id} 已被用户层/出厂层声明，插件这条整条跳过")
            continue
        for provider in cap.providers:
            owner = facts.config_claims.get(provider.tool_name)
            if owner and owner != cap.id:
                notes.append(
                    f"工具 {provider.tool_name} 已被用户层/出厂层的 {owner} 认领，"
                    f"插件的 {cap.id} 整条跳过",
                )
    if not notes:
        return None
    return CheckResult(
        id="plugin_collision",
        level="info",
        title=f"{len(notes)} 条声明会被更高优先层顶掉",
        detail="；".join(dict.fromkeys(notes)),
        fix_hint=(
            "优先级是 用户 > 出厂 > 插件自带。想让插件这条生效，"
            "就删掉 config/capabilities/ 里对应的那条；想保留覆盖则无需处理"
        ),
    )


def check_url_image(facts: PluginFacts) -> CheckResult | None:
    """⑭ 源码里出现 ``url_image(``。

    ``html_render`` 在 Stella 这边返回的是**本地路径**（本地 Chromium 渲染，不上传图床），
    塞给 ``url_image`` 会直接 ValueError。
    """
    if not facts.url_image_hits:
        return None
    return CheckResult(
        id="plugin_url_image",
        level="warn",
        title=f"{len(facts.url_image_hits)} 处使用了 url_image",
        detail="；".join(facts.url_image_hits),
        fix_hint=(
            "改用 Comp.Image.fromFileSystem(path)。html_render 返回本地路径而非 URL，"
            "且渲染不可用时返回**空串而不抛异常**，所以还要写 if path: 的降级分支"
        ),
    )


def check_bare_task(facts: PluginFacts) -> CheckResult | None:
    """⑮ 裸 ``asyncio.create_task`` 而没走 ``context.register_task``。"""
    if not facts.bare_create_task_hits:
        return None
    detail = "；".join(facts.bare_create_task_hits)
    if facts.uses_register_task:
        detail += "（本插件别处用了 register_task，这几处漏了）"
    return CheckResult(
        id="plugin_bare_task",
        level="warn",
        title=f"{len(facts.bare_create_task_hits)} 处裸 create_task",
        detail=detail,
        fix_hint=(
            "换成 self.context.register_task(coro, name)。只有登记过的任务在插件卸载与"
            "热重载时收得回；裸 task 会在重载后残留并继续跑，而这不报错"
        ),
    )


def check_egress(facts: PluginFacts) -> CheckResult | None:
    """⑯ import 了出网库但 ``metadata.yaml`` 没声明 ``stella.egress``。

    这是**披露契约，不是沙箱**：未声明的请求照样发得出去，我们不拦。它存在的理由是
    Stella 的「零出网」承诺——判断该不该用工具、压缩结果、渲染卡片全在本地——而插件是
    唯一被允许出网的环节，所以出网的插件必须自己说出来。
    """
    if not facts.egress_libs or facts.egress_declared:
        return None
    return CheckResult(
        id="plugin_egress",
        level="warn",
        title=f"用了 {'、'.join(facts.egress_libs)} 但未声明出网",
        detail=(
            "metadata.yaml 里没有 stella.egress。用户无从得知这个插件会把请求发去哪里，"
            "而 Stella 除插件之外不出网，插件是唯一的出口"
        ),
        fix_hint=(
            "在 metadata.yaml 里加：\n"
            "stella:\n"
            "  egress:\n"
            "    - host: api.example.com\n"
            "      purpose: 查询天气"
        ),
    )


# ---------- 运行与渲染 ----------

_ALL_CHECKS: tuple[Callable[[PluginFacts], CheckResult | Sequence[CheckResult] | None], ...] = (
    check_layout,
    check_load,
    check_requirements,
    check_tool_undeclared,
    check_provider_missing,
    check_declaration,
    check_examples_count,
    check_examples_style,
    check_keywords_overlap,
    check_keywords_short,
    check_keywords_required_args,
    check_separation,
    check_collision,
    check_url_image,
    check_bare_task,
    check_egress,
)

# error → warn → info → ok。``info`` 插在 warn 之后：它是纯告知（「这条会被用户层顶掉」），
# 不该排在真问题前面抢注意力，但也不能和 ok 混在一起——它有内容要读。
_LEVEL_ORDER = {"error": 0, "warn": 1, "info": 2, "ok": 3}


def total_checks() -> int:
    """检查项总数。渲染层用它推算通过数——检查通过时返回 ``None``、不产出结论，
    所以「通过了多少项」无法从结果列表反推，分母必须由这里给（同 ``checks.total_checks``）。"""
    return len(_ALL_CHECKS)


def run_all(facts: PluginFacts) -> list[CheckResult]:
    """跑全部检查，按 error→warn→info→ok 排序（同级保持登记顺序，稳定排序）。"""
    results: list[CheckResult] = []
    for check in _ALL_CHECKS:
        out = check(facts)
        if out is None:
            continue
        if isinstance(out, CheckResult):
            results.append(out)
        else:
            results.extend(out)
    results.sort(key=lambda r: _LEVEL_ORDER.get(r.level, 4))
    return results


def _summarize(results: list[CheckResult]) -> dict:
    """本地的汇总。**不能用 ``report._summarize``**：那个把分母写死成
    ``checks.total_checks()``（doctor 的项数），拿来汇总插件检查会得出一个荒谬的通过数。
    """
    total = total_checks()
    n_error = sum(1 for r in results if r.level == "error")
    n_warn = sum(1 for r in results if r.level == "warn")
    n_info = sum(1 for r in results if r.level == "info")
    return {
        # 与 doctor 同样的近似：跳过（不适用）的检查也算进 ok，单个检查产出多条时 ok 偏小。
        # info 不减——它不表示这项没通过。
        "ok": max(0, total - n_error - n_warn),
        "warn": n_warn,
        "info": n_info,
        "error": n_error,
        "blocking": report.has_blocking(results),
        "total": total,
    }


def _plugin_section(facts: PluginFacts) -> dict:
    """被检查插件的**事实**（不是结论）。GUI 照它渲染插件卡片。

    只放结构化字段：名字、版本、工具名与必填参数、能力 id 与声明来源。
    不放 ``description`` / ``examples`` 原文——那些是自由文本，本地读 TOML 就有，
    没有理由从这里再吐一份（同 ``status_api`` 那条「结构化字段 only」的惯例）。
    """
    return {
        "dir": str(facts.plugin_dir),
        "dir_name": facts.dir_name,
        "name": facts.plugin_name,
        "version": facts.plugin_version,
        # 这个字段是承诺的一部分：调用方（含 GUI）必须能知道本次检查执行过插件代码。
        "executed_plugin_code": facts.executed_plugin_code,
        "load_error": facts.load_error,
        "tools": [
            {"name": t.name, "required": list(t.required)} for t in facts.tools
        ],
        "declaration": {
            "present": facts.declaration_present,
            "draft_present": facts.draft_present,
            "reviewed": facts.reviewed,
            "error": facts.declaration_error,
            "capabilities": [
                {
                    "id": c.id,
                    "domain": c.domain,
                    "source": c.source or SOURCE_PLUGIN,
                    "examples": len(c.examples),
                    "keywords": len(c.keywords),
                    "providers": [p.tool_name for p in c.providers],
                }
                for c in facts.capabilities
            ],
        },
        "requirements": {
            "declared": facts.requirements,
            "missing": facts.missing_requirements,
        },
        "egress": {
            "libs": facts.egress_libs,
            "declared": facts.egress_declared,
        },
        "separation": facts.separation,
    }


def to_json(facts: PluginFacts, results: list[CheckResult]) -> str:
    """序列化为结构化 JSON（供 GUI）。条目字段与 doctor 完全一致，共用 ``result_items``。"""
    return json.dumps(
        {
            "version": 1,
            "plugin": _plugin_section(facts),
            "executed_plugin_code": facts.executed_plugin_code,
            "summary": _summarize(results),
            "items": report.result_items(results),
        },
        ensure_ascii=False,
        indent=2,
    )


def _overview(facts: PluginFacts) -> list[str]:
    """插件事实概览：几行小表，放在结论前面。"""
    title = facts.plugin_name or facts.dir_name
    # metadata.yaml 里的版本号按上游惯例常已带 v 前缀（``version: v1.6.4``），
    # 无条件再加一个会打出 ``vv1.6.4``
    raw_version = facts.plugin_version.strip()
    if not raw_version:
        version = ""
    elif raw_version[:1] in ("v", "V"):
        version = f" {raw_version}"
    else:
        version = f" v{raw_version}"
    lines = [f"插件 {title}{version}", f"  目录：{facts.plugin_dir}"]
    if facts.executed_plugin_code:
        # 必须说出来。枚举 @llm_tool 的唯一办法是 import 并实例化插件类，
        # 用户不该以为自己只跑了个静态检查。
        lines.append("  注意：本次检查已 import 并实例化该插件代码（与启动时相同的动作）。")
    if facts.tools:
        listed = ", ".join(
            f"{t.name}({'必填 ' + '、'.join(t.required) if t.required else '无必填参数'})"
            for t in facts.tools
        )
        lines.append(f"  工具（{len(facts.tools)}）：{listed}")
    elif facts.executed_plugin_code and not facts.load_error:
        lines.append("  工具：无 @llm_tool（只走指令通路的插件不需要声明）")
    if facts.capabilities:
        listed = ", ".join(
            f"{c.id}[{c.domain or PLUGIN_DECL_DOMAIN}]"
            f"(examples {len(c.examples)}/keywords {len(c.keywords)})"
            for c in facts.capabilities
        )
        lines.append(f"  自带声明（{len(facts.capabilities)}）：{listed}")
    else:
        lines.append(f"  自带声明：无（{PLUGIN_DECL_FILENAME} 不存在或不可用）")
    if facts.egress_declared:
        lines.append(f"  声明的出网目标：{'、'.join(facts.egress_declared)}")
    lines.append("")
    return lines


def to_terminal(facts: PluginFacts, results: list[CheckResult]) -> str:
    """人类可读文本。级别标签与配色走 ``report.format_results``，与 doctor 一致。"""
    lines = _overview(facts)
    lines += report.format_results(results)
    lines.append("")
    summary = _summarize(results)
    lines.append(
        f"共 {summary['total']} 项检查：错误 {summary['error']}、"
        f"警告 {summary['warn']}、提示 {summary['info']}。",
    )
    if summary["blocking"]:
        lines.append("存在不符合规范之处（error），修好后再发布。完整规范见 docs/plugin-spec.md。")
    else:
        lines.append("未发现不符合规范之处。完整规范见 docs/plugin-spec.md。")
    return "\n".join(lines)


__all__ = [
    "IMPERATIVE_MARKERS",
    "MIN_EXAMPLES",
    "MIN_KEYWORD_CHARS",
    "NEGATIVE_MARGIN_MIN",
    "SEPARATION_MIN_SPREAD",
    "PluginFacts",
    "ToolFact",
    "collect",
    "imperative_marker",
    "run_all",
    "to_json",
    "to_terminal",
    "total_checks",
]
