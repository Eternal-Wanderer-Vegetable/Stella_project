# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""``python -m deploy plugin-scaffold``：给一个插件生成 ``capability.toml.draft``。

要解决的是**数据缺口**，不是 API 缺口。装完一个带 ``@llm_tool`` 的 AstrBot 插件，工具
照常注册，但聊天里永远不会被触发——因为 Router 拿用户的**问句**和能力原型算余弦，而未
声明的工具只有一句写给决策器的 ``description``（「当用户询问 X 时调用」）。两种文本不
同构，实测 12 条用例：拿工具描述当语料，负样本余量 **−0.024**（无关的话得分压过置信线）；
换成中文问句 examples，**+0.141**。所以缺的是「用户会怎么问」这份语料，而它今天要用户
自己手写。

**为什么这不违背「刻意不用生成的方式去补」**（``capability/adapters/astrbot.py`` 与
``docs/capability-system.md`` 里那句话）：那句话针对的是**运行期、无声、无人过目**的生成
——启动时调模型把 examples 直接灌进内存里的原型向量，错的语料没有任何一道关卡。本命令做
的是另一件事，三点差别都是刻意的：

1. **离线、产物是文件**。写的是 ``.draft``，磁盘上看得见、可以 diff、可以拒收；
2. **人审才生效**。``.draft`` 后缀与 ``reviewed = false`` 双闸门，两者任一成立都不会被
   加载（见 ``capability.loader.load_plugin_capabilities``）。生成物到不了 Router；
3. **生成完就量化**。用**路由自己那套** embedding 与原型算法打一份报告（同域原型最近间距、
   每条 example 与本能力原型的余弦、负样本余量），判据直接调
   ``plugin_check.check_separation()``。「生成质量无法验证」在有文件、有审阅、有基准的
   前提下不成立——那正是上面 −0.024 / +0.141 这一列的意思。

输入按信息量排序（``docs/plugin-spec.md`` §12 承诺的那张表）：插件 ``README.md`` → ``@command``
的指令名与说明 → ``@llm_tool`` 的 docstring ``Args`` → 工具 ``description`` 与工具名 →
``metadata.yaml``。**只喂工具描述正是 −0.024 那一行的成因**，所以前四项能拿到就一定拿。

事实采集整个复用 ``plugin_check.collect()``：它已经会 import 并实例化插件、枚举工具与参数、
读三层声明。两处各写一遍加载流程必然漂移，而漂移的表现是「校验器看到 5 个工具、生成器看到
3 个」。代价是本命令同样**会执行插件代码**，输出里必须说明这一点。
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from capability.loader import (
    PLUGIN_DECL_DOMAIN,
    PLUGIN_DECL_DRAFT_FILENAME,
    PLUGIN_DECL_FILENAME,
    parse_declaration,
)
from capability.registry import (
    AUTO_CAPABILITY_PREFIX,
    SOURCE_PLUGIN,
    Capability,
    CapabilityRegistry,
)

from . import plugin_check, report
from .plugin_check import MIN_KEYWORD_CHARS, PluginFacts, imperative_marker

# 生成时要求的 examples 条数。比校验器的下限（MIN_EXAMPLES = 3）高：那是「低于就报警」的
# 底线，这是「生成就按这个量给」的目标值，实测 4~6 句覆盖不同问法才稳。
TARGET_EXAMPLES = 5
MAX_EXAMPLES = 6
# 单条 example 的长度上限。用户的问句就是短句；长句会把原型均值拽向它自己那些修饰词。
MAX_EXAMPLE_CHARS = 30
# 允许模型选的域。刻意不含 ``memory``——那是 Stella 记忆系统自己的域，插件能力挤进去会
# 直接和「你还记得我说的旅行计划吗」这类请求抢判定。域同时是能力查询的分组依据与同域
# 分离度的分组依据，所以给一个封闭集合而不是让模型自由发挥：自由发挥的结果是每个插件
# 一个新域名，分组退化成「一域一条」，⑫ 那条检查就永远无话可说。
ALLOWED_DOMAINS = ("information", "entertainment", "utility", PLUGIN_DECL_DOMAIN)
# 喂进 prompt 的 README 上限。再多也进不了小模型的窗口，而且 README 越往后越是安装说明。
README_CHARS = 1500


@dataclass
class Draft:
    """一个工具生成出来的那条声明。字段与 ``[[capability]]`` 一一对应。"""

    tool: str
    id: str
    domain: str
    description: str
    examples: list[str] = field(default_factory=list)
    # 候选关键词。**只进注释**，不进 ``keywords =``——见 ``_render_capability``。
    keyword_candidates: list[str] = field(default_factory=list)
    # 生成失败的原因。非空时这条会带一个显眼的注释写进草稿，examples 为空。
    error: str = ""


# ---------- 输入采集（按信息量排序，见 docs/plugin-spec.md §12） ----------


def _read_readme(plugin_dir: Path) -> str:
    """插件 README 的开头一段。信息量最高的输入：里面通常有真实的使用示例。

    只取前 ``README_CHARS`` 个字符：README 越往后越是安装步骤与许可证，而那些对
    「用户会怎么问」没有任何贡献，还会把真正有用的示例挤出小模型的窗口。
    """
    for name in ("README.md", "readme.md", "README.MD", "README.rst", "README.txt"):
        path = plugin_dir / name
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            return text.strip()[:README_CHARS]
    return ""


def _plugin_desc(plugin_dir: Path) -> str:
    """``metadata.yaml`` 的 ``desc``。信息量最低的那一项，兜底用。"""
    try:
        from astrbot_compat.loader import _read_metadata

        meta = _read_metadata(plugin_dir) or {}
    except Exception:
        return ""
    return str(meta.get("desc") or meta.get("description") or "").strip()[:200]


def _clip(text: str, limit: int) -> str:
    """压成一行并截断。指令的 ``desc`` 常常是整段 docstring（模板插件那条 150 字符、
    还带示例），原样塞进 prompt 会把真正的输入淹掉。"""
    flat = " ".join(str(text or "").split())
    return flat[:limit] + "…" if len(flat) > limit else flat


def _tool_block(tool: plugin_check.ToolFact) -> str:
    """一个工具在 prompt 里的呈现。参数带说明——``city(城市名，如「杭州」)`` 直接告诉
    模型「用户的问法里会带地名」，而这是光看工具名与 description 拿不到的。"""
    lines = [f"- 工具名：{tool.name}", f"  用途：{_clip(tool.description, 200) or '（未写）'}"]
    if tool.params:
        for name, desc in tool.params:
            flag = "必填" if name in tool.required else "可选"
            lines.append(f"  参数 {name}（{flag}）：{_clip(desc, 80) or '（未写说明）'}")
    else:
        lines.append("  参数：无")
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "你在为一个中文 QQ 群机器人整理「能力声明」。"
    "机器人靠 embedding 把**用户的原话**和每条能力的示例问句算余弦相似度，来决定要不要调用某个工具。"
    "所以你写的示例必须是**用户会怎么问**的口语句子，不是写给程序看的调用说明。"
    "只输出 JSON，不要任何解释文字，不要 Markdown 代码块。"
)


def _build_prompt(
    facts: PluginFacts,
    tool: plugin_check.ToolFact,
    *,
    readme: str,
    plugin_desc: str,
) -> str:
    """给一个工具拼 prompt。输入顺序就是 ``docs/plugin-spec.md`` §12 那张信息量排序表。

    **兄弟工具也要给**：同一个插件里的工具往往同域（5 个 ACG 工具那个实测形态），模型
    看不到彼此就会给每个工具写一批雷同的问句，于是同域原型挤成一个点——⑫ 那条检查报的
    正是这个。把兄弟工具的名字与用途摆出来并明确要求「只覆盖本工具、不要写成兄弟工具也
    能接的问法」，是唯一能在生成阶段就避开它的办法。
    """
    siblings = [t for t in facts.tools if t.name != tool.name]
    parts: list[str] = []
    if readme:
        parts.append(f"## 插件 README（节选）\n{readme}")
    if facts.commands:
        listed = "\n".join(f"- /{name}：{_clip(desc, 100)}" for name, desc in facts.commands)
        parts.append(
            "## 这个插件的指令（指令名本身往往就是用户的自然说法，可作为措辞参考）\n" + listed,
        )
    parts.append("## 要写声明的工具\n" + _tool_block(tool))
    if siblings:
        parts.append(
            "## 同一插件里的其它工具（**不要**为它们写，只用来划清界线）\n"
            + "\n".join(f"- {t.name}：{_clip(t.description, 120) or '（未写）'}" for t in siblings),
        )
    if plugin_desc:
        parts.append(f"## 插件简介\n{plugin_desc}")

    required = "、".join(tool.required) or "无"
    parts.append(
        f"""## 你要输出的 JSON

{{
  "id": "小写英文点分 id，形如 weather.query / anime.search，不要用 tool. 开头",
  "domain": "从 {'/'.join(ALLOWED_DOMAINS)} 里选一个",
  "description": "一句话名词短语，说明这条能力是什么（不要写「当用户……时调用」）",
  "examples": ["{TARGET_EXAMPLES} 到 {MAX_EXAMPLES} 条中文口语问句"],
  "keyword_candidates": ["0 到 4 个候选关键词，见下面的规则"]
}}

## 硬性要求

1. `examples` 写**用户会怎么问**：「明天天气怎么样」「会不会下雨」这种。
   绝对不要写「当用户询问天气时调用本工具」「用于查询天气」这类指令句。
2. 每条 example 是一句话，{MAX_EXAMPLE_CHARS} 字以内，彼此**换一种问法**（不同措辞、
   不同句式、有的带具体对象有的不带），不要把同一句话改个标点重复几遍。
3. 只覆盖这个工具能做的事。写得太宽会把该给别人的请求吸过来。
4. `description` 会和 examples 一起参与语义比对，所以也要写成人话的名词短语，
   不要写调用条件。
5. `keyword_candidates` 是「命中即直接执行、没有二次判定」的字面词，因此宁缺勿滥：
   必须是 {MIN_KEYWORD_CHARS} 个汉字以上的名词短语（「番剧推荐」可以，「新番」不行），
   **绝不能是某条 example 的片段**（从「会不会下雨」里切出的「不会」会命中几乎任何句子）。
   本工具的必填参数是：{required}。有必填参数时 `keyword_candidates` 一律给空数组
   ——字面命中不抽取参数，直接执行只会让下游去猜那个必填值。
   想不出足够好的词就给空数组，这是完全正常的结果。

只输出那个 JSON 对象。""",
    )
    return "\n\n".join(parts)


# ---------- 解析模型输出 ----------

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """从模型输出里抠出一个 JSON 对象。宽容一点，但不自己发明字段。

    ``memory/consolidator.py`` 里有一份同类的容错解析器，这里刻意不 import 它：那个模块
    一旦被 import 就会拉起数据库连接与 schema 迁移，而 ``deploy`` 的子命令必须能在一个
    还没建库的新装实例上跑。两处都短，各自持有比互相耦合便宜。
    """
    raw = _FENCE_RE.sub("", str(text or "").strip())
    try:
        parsed = json.loads(raw)
    except Exception:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(raw[start : end + 1])
        except Exception:
            return None
    return parsed if isinstance(parsed, dict) else None


def _sanitize_id(value: str, tool: str) -> str:
    """点分小写 ASCII id。取不出合法 id 时退到 ``plugin.<工具名>``。

    **退路刻意不用 ``tool.`` 前缀**：那个前缀是自动派生能力的标记
    （``AUTO_CAPABILITY_PREFIX``，``Capability.is_auto`` 与 ``inventory.snapshot()`` 都据
    它分类）。一条**手写/生成并经人审**的声明用上它，能力清单会把它报成「无能力声明（自动
    派生）」——用户看到的结论与事实相反，而这不报错。
    """
    cleaned = re.sub(r"[^a-z0-9._-]+", "", str(value or "").strip().lower()).strip("._-")
    if not cleaned or cleaned.startswith(AUTO_CAPABILITY_PREFIX):
        cleaned = ""
    if not cleaned:
        stem = re.sub(r"[^a-z0-9]+", "_", tool.lower()).strip("_") or "capability"
        cleaned = f"{PLUGIN_DECL_DOMAIN}.{stem}"
    return cleaned


def _clean_examples(values: Any) -> list[str]:
    """挑出能用的 example：口语问句、不重复、不太长、不是指令句。

    指令句用 ``plugin_check.imperative_marker()`` 判——生成侧与校验侧共用**判据本身**，
    才不会出现「生成器放过、校验器报警」这种谁都不信的组合。
    """
    out: list[str] = []
    for item in values if isinstance(values, list) else []:
        text = " ".join(str(item or "").split())
        if not text or len(text) > MAX_EXAMPLE_CHARS or imperative_marker(text):
            continue
        if text not in out:
            out.append(text)
    return out[:MAX_EXAMPLES]


def _clean_keywords(values: Any, examples: list[str], *, required: bool) -> list[str]:
    """候选关键词。有必填参数时直接清空——规则见 ``docs/plugin-spec.md`` §6.4 第 4 条。

    「是某条 example 的子串」也一律扔掉：那正是「绝不从 examples 里切词」这条规则的机械化，
    模型很容易违反它（它看得见 examples，切词是最省力的凑数方式）。
    """
    if required:
        return []
    out: list[str] = []
    for item in values if isinstance(values, list) else []:
        word = "".join(str(item or "").split())
        if len(word) < MIN_KEYWORD_CHARS or word in out:
            continue
        if any(word in ex for ex in examples):
            continue
        out.append(word)
    return out[:4]


# ---------- 生成 ----------

_RETRY_SUFFIX = (
    "\n\n上一次的输出无法解析。请**只**输出那一个 JSON 对象本身，"
    "第一个字符是 {，最后一个字符是 }，中间不要有任何解释、标题或代码块标记。"
)


async def _generate_one(
    backend: Any,
    facts: PluginFacts,
    tool: plugin_check.ToolFact,
    *,
    readme: str,
    plugin_desc: str,
) -> Draft:
    """一个工具一次调用（解析失败时再收紧重试一次）。

    失败不抛：**部分成功要能落盘**。5 个工具里 1 个解析不出来时，把那 4 条写出来、
    第 5 条留一个显眼的空壳与注释，比整份草稿都不生成有用得多——人审本来就要逐条看。
    """
    prompt = _build_prompt(facts, tool, readme=readme, plugin_desc=plugin_desc)
    last = ""
    for attempt in (1, 2):
        try:
            text = await backend.generate(
                prompt if attempt == 1 else prompt + _RETRY_SUFFIX,
                SYSTEM_PROMPT,
            )
        except Exception as exc:  # 网络 / 端点 / 超时——都只影响这一条
            last = f"模型调用失败：{type(exc).__name__}: {exc}"
            continue
        data = _parse_json_object(text)
        if data is None:
            last = "模型输出不是 JSON 对象"
            continue
        examples = _clean_examples(data.get("examples"))
        if not examples:
            # 一条 example 都没留下：多半整批写成了指令句，重试一次比写个空壳强
            last = "模型没有给出可用的示例问句（可能全写成了指令句）"
            continue
        domain = str(data.get("domain") or "").strip().lower()
        return Draft(
            tool=tool.name,
            id=_sanitize_id(str(data.get("id") or ""), tool.name),
            domain=domain if domain in ALLOWED_DOMAINS else PLUGIN_DECL_DOMAIN,
            description=_clip(data.get("description") or tool.description, 60),
            examples=examples,
            keyword_candidates=_clean_keywords(
                data.get("keyword_candidates"),
                examples,
                required=bool(tool.required),
            ),
        )
    return Draft(
        tool=tool.name,
        id=_sanitize_id("", tool.name),
        domain=PLUGIN_DECL_DOMAIN,
        description=_clip(tool.description, 60),
        error=last or "生成失败",
    )


async def generate_drafts(facts: PluginFacts, backend: Any) -> list[Draft]:
    """逐个工具生成。串行：本命令是一次性离线活，而 EXTRACT 角色常绑本机小模型
    （并发打满只会让它排队），换来的是进度输出与失败归属都按工具顺序，可读。"""
    readme = _read_readme(facts.plugin_dir)
    plugin_desc = _plugin_desc(facts.plugin_dir)
    drafts: list[Draft] = []
    for index, tool in enumerate(facts.tools, start=1):
        print(f"  [{index}/{len(facts.tools)}] {tool.name} …", flush=True)
        drafts.append(
            await _generate_one(
                backend, facts, tool, readme=readme, plugin_desc=plugin_desc,
            ),
        )
    return drafts


# ---------- 渲染草稿 ----------

_TOML_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _toml_str(value: str) -> str:
    """TOML 基本字符串。手写而不是引一个 TOML 写库：整个项目只**读** TOML
    （``tomllib`` 在标准库里，写库不在），为一条离线命令新增一个运行期依赖不值得。"""
    out = "".join(_TOML_ESCAPES.get(c, c) for c in str(value))
    # 其余控制字符按 TOML 规范转义（模型偶尔会吐出 \x0b 之类）
    out = _CONTROL_RE.sub(lambda m: f"\\u{ord(m.group()):04X}", out)
    return f'"{out}"'


_HEADER = f"""# Stella 能力声明【自动生成的草稿，未经人审】
#
# 这份文件由 python -m deploy plugin-scaffold 生成，**现在还不会生效**：
#   1. 文件名带 .{PLUGIN_DECL_DRAFT_FILENAME.split(".")[-1]} 后缀 —— 加载器一律跳过；
#   2. 下面的 reviewed = false —— 即使改了文件名也仍然不载入。
# 两道闸门都是刻意的：examples 决定 Router 会把哪些请求吸到这个插件上，写歪的语料
# 比没有语料更糟（会凭空调用工具），所以生成物必须有人过目一遍才允许进路由。
#
# 人审要做的事，按重要性排序：
#   a. 逐条读 examples，问自己「用户真的会这么说吗」。像指令句（「当用户询问 X 时」）
#      或者太宽（把该给别的能力的请求也接了）的，直接删掉或改写；
#   b. 4~6 句、每句一种不同问法。不够就自己补，重复的删掉——原型是全部 examples 的
#      **均值**，重复不增加信息，只会让这个能力的中心偏向重复的那句；
#   c. 需要 keywords 的话，从下面注释里的候选词里挑，**自己确认**每个词不会串进无关
#      句子。想不出好词就别写，Level 1 照样能路由到；
#   d. 确认 domain 与 description 合适（description 也参与语义比对，写成名词短语）。
# 审完：把 reviewed 改成 true，去掉文件名的 .draft 后缀，再跑一遍
#   python -m deploy plugin-check <插件目录>
#
# 格式与 config/capabilities/*.toml 完全一致，三层优先级见 docs/plugin-spec.md §6.2。

reviewed = false
"""


def _render_capability(draft: Draft, tool: plugin_check.ToolFact) -> str:
    """一条 ``[[capability]]``。候选关键词**只进注释**。

    不直接写成 ``keywords = [...]``：Level 0 命中即拍板执行、没有二次判定，一个串味的
    关键词就是一次凭空调用。而中文没有词边界，模型给的候选里必然混着能命中任何句子的
    短词——那一步判断只能由人做，所以生成器把它摆在人眼前，但不替人按下开关。
    """
    lines = ["", "[[capability]]", f"id = {_toml_str(draft.id)}"]
    if draft.error:
        # description 也留空：``prototype_texts()`` 没有 examples 时**会退到 description**，
        # 所以写着工具描述的空壳并不惰性——人审时一路点头改成 reviewed = true，得到的恰好
        # 是「拿工具描述当语料」那一种配置（负样本余量 −0.024，本模块开头那一段）。
        # 工具自己的描述改放进注释：给人看是有用的起点，给 embedding 看是已知的坑。
        hint = _clip(tool.description or draft.description, 100)
        lines.insert(
            1,
            f"# ⚠ 这条没能生成出来：{draft.error}\n"
            f"#   examples 与 description 都留空了——这条能力没有任何原型语料，不会被路由\n"
            f"#   （也不会有任何害处）。补上 4~6 句用户问句才会生效。\n"
            + (f"#   工具自己的描述是：{hint}\n" if hint else "")
            + "#   **别把那句描述直接抄成 example**：写给决策器的指令句与用户的问句不同构，\n"
            "#   实测负样本余量 −0.024（凭空调工具只是时间问题）。\n"
            "#   也可以重跑一次 plugin-scaffold。",
        )
    lines.append(f"domain = {_toml_str(draft.domain)}")
    lines.append(f"description = {_toml_str('' if draft.error else draft.description)}")
    lines.append("# Level 1 语义原型语料：写「用户会怎么问」，不是写给决策器的指令句。")
    if draft.examples:
        lines.append("examples = [")
        lines.extend(f"    {_toml_str(e)}," for e in draft.examples)
        lines.append("]")
    else:
        lines.append("examples = []")
    lines.append(_keyword_comment(draft, tool))
    lines.append(f"providers = [{_toml_str(draft.tool)}]")
    return "\n".join(lines)


def _keyword_comment(draft: Draft, tool: plugin_check.ToolFact) -> str:
    """``keywords`` 那一段注释。三种情形分开写，因为要教的规则不一样。

    有必填参数时**连候选词都不给**：Level 0 只做字面命中、不抽取参数，给了候选就等于
    引诱人去打开一个必然让下游猜参数的开关（``plugin-check`` 第 ⑪ 项报的正是这个）。
    """
    head = (
        "# keywords 是 Level 0 的确定性字面词：命中即拍板执行，**没有二次判定**，"
        "所以宁缺勿滥。"
    )
    if tool.required:
        return (
            f"{head}\n"
            f"# 本条**刻意不给**，也不列候选：{draft.tool} 有必填参数"
            f"（{'、'.join(tool.required)}），\n"
            f"# 而 Level 0 不抽取参数，拍板执行只会让 Comes 去猜那个必填值。\n"
            f"# 不写完全没问题——Level 1 照样能路由到，只是多花一次 embedding。"
        )
    if not draft.keyword_candidates:
        return (
            f"{head}\n"
            f"# 生成时没有给出够格的候选词（要求：{MIN_KEYWORD_CHARS} 字以上的名词短语、"
            f"不是任何一条 example 的片段）。\n"
            f"# 保持不写是完全正常的结果。"
        )
    listed = ", ".join(_toml_str(w) for w in draft.keyword_candidates)
    return (
        f"{head}\n"
        f"# 下面是**候选**，需要你逐个确认后再取用：一个会串进无关句子的词，"
        f"代价是一次凭空调用工具。\n"
        f"# 判据：名词短语、{MIN_KEYWORD_CHARS} 字以上、不与别的能力的 examples 串味。\n"
        f"# keywords = [{listed}]"
    )


def render_draft(facts: PluginFacts, drafts: list[Draft]) -> str:
    """整份 ``capability.toml.draft``。"""
    by_name = {t.name: t for t in facts.tools}
    body = [_HEADER.rstrip()]
    for draft in drafts:
        tool = by_name.get(draft.tool) or plugin_check.ToolFact(name=draft.tool)
        body.append(_render_capability(draft, tool))
    return "\n".join(body) + "\n"


# ---------- 量化报告（方案 §2.3） ----------

# 负样本里报几条最高分。3 条足够指出「是哪句话压过了置信线」，再多只是刷屏。
NEGATIVE_REPORT_TOP = 3


@dataclass
class Measurement:
    """量化结果。**刻意分成两半。**

    ``separation`` 会被原样塞进 ``PluginFacts.separation``，而
    ``plugin_check._plugin_section()`` 把那个字段**原样序列化进 ``--json``**。所以这半边
    只放数字与能力 id：benchmark 的负样本里有好几条标注着「线上真实消息」的真实群聊原文
    （`主管，这是？` 这种），把它们放进一个会被序列化的字段，等于让一条校验输出夹带聊天
    内容——``status_api`` 与 ``_plugin_section`` 都有「结构化字段 only」的硬约束。

    ``lines`` 是给人看的那半边（哪条 example 跑偏了、哪句负样本压过了线），只进终端。
    """

    separation: dict[str, Any] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)


def _temp_registry(capabilities: list[Capability]) -> CapabilityRegistry:
    """把解析出来的能力装进一个**临时**注册表。

    不用全局那个 ``capability.registry.registry``：本命令跑在一个刚起的
    ``deploy`` 进程里，全局注册表是空的，但**测试**不是——同进程里跑过别的用例后它可能
    带着别人的能力，量化结果就会掺进不属于这个插件的原型。临时注册表让这份报告只受
    被测插件影响。
    """
    reg = CapabilityRegistry()
    for capability in capabilities:
        reg.register(capability)
    return reg


def _negative_messages() -> list[tuple[str, str]]:
    """路由基准里全部 ``tool=False`` 的用例，去重后返回 ``(消息, 备注)``。

    复用 ``capability.router.benchmark`` 而不另建一套负样本：那 20 多句是有来历的
    ——切词坏词护栏、寒暄整句匹配、以及几条标着「线上真实消息」的真实群聊原文。
    另建一套的结果是「生成器自测通过、benchmark 仍然回归」。
    """
    from capability.router import benchmark

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for case in benchmark.load_cases():
        if case.tool or case.message in seen:
            continue
        seen.add(case.message)
        out.append((case.message, case.note))
    return out


def _same_domain_pairs(
    reg: CapabilityRegistry,
    prototypes: dict[str, list[float]],
) -> list[tuple[float, str, str, str]]:
    """同域原型两两余弦，**最近的排在最前**。返回 ``(余弦, 域, id_a, id_b)``。

    只比同域的：域是能力查询的分组依据，也是路由竞争最激烈的地方（同域的两条能力争的是
    同一批问句）。跨域挨得近不一定有害——「天气」与「番剧」本来就不会被同一句话触发。
    """
    from memory.embeddings import cosine_similarity

    by_domain: dict[str, list[str]] = {}
    for capability in reg.routable():
        if capability.id in prototypes:
            domain = capability.domain or PLUGIN_DECL_DOMAIN
            by_domain.setdefault(domain, []).append(capability.id)

    pairs: list[tuple[float, str, str, str]] = []
    for domain, ids in sorted(by_domain.items()):
        for index, first in enumerate(ids):
            for second in ids[index + 1 :]:
                cos = cosine_similarity(prototypes[first], prototypes[second])
                pairs.append((cos, domain, first, second))
    pairs.sort(key=lambda row: (-row[0], row[2], row[3]))
    return pairs


async def _per_capability(
    reg: CapabilityRegistry,
    service: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """每条原型语料与**本能力**原型的余弦。返回（结构化行, 人读行）。

    走 ``score_capabilities()`` 而不是自己算一遍余弦：它顺带给出这条文本在**别的**能力
    上的得分，于是「这条 example 在兄弟能力上得分更高」这个最要紧的诊断是免费的——那正是
    两条能力语料串味的直接证据，而它光看「与本能力的余弦」是看不出来的。

    编码全部命中 ``EmbeddingService`` 的缓存（原型刚用同一批文本算过），所以这一段不打网络。

    只有一条语料的能力必然得 1.000（原型就是它自己），这个数只在 4~6 条时有意义。
    """
    from capability.router import semantic

    rows: list[dict[str, Any]] = []
    lines: list[str] = []
    for capability in reg.routable():
        scored: list[tuple[float, str]] = []
        stolen: list[tuple[str, str, float]] = []
        for text in capability.prototype_texts():
            hits = await semantic.score_capabilities(text, reg, service)
            if not hits:
                continue
            own = next((h.score for h in hits if h.capability_id == capability.id), None)
            if own is None:
                continue
            scored.append((own, text))
            if hits[0].capability_id != capability.id:
                stolen.append((text, hits[0].capability_id, hits[0].score))
        if not scored:
            continue
        values = [value for value, _ in scored]
        mean = sum(values) / len(values)
        worst, worst_text = min(scored)
        rows.append(
            {
                "id": capability.id,
                "texts": len(values),
                "mean": round(mean, 3),
                "min": round(worst, 3),
            },
        )
        lines.append(
            f"  {capability.id}：{len(values)} 条语料，均值 {mean:.3f}，"
            f"最低 {worst:.3f}（「{worst_text}」）",
        )
        for text, other, score in stolen:
            lines.append(
                f"    ⚠ 「{text}」在 {other} 上得分更高（{score:.3f}）——两条的语料串味了",
            )
    return rows, lines


_NEGATIVE_CAVEAT = (
    "  说明：负样本里有两类句子**合理地**会得高分——一是「有明确工具意图但本机没装对应"
    "插件」的护栏（`帮我查一下今天的天气`），被测插件正好提供这个能力时它得高分是对的；"
    "二是已记录的已知失败（`我最近在追新番` 0.835，余弦分不开「陈述 X」与「请求 X」，"
    "那是 Level 2 该接的活）。所以余量为负时先看是哪一句，再决定动不动 examples。"
)


async def _negatives(
    reg: CapabilityRegistry,
    service: Any,
) -> list[tuple[float, str, str, str]]:
    """每条负样本在本插件能力上的**最高分**，降序。返回 ``(分数, 能力 id, 消息, 备注)``。"""
    from capability.router import semantic

    scored: list[tuple[float, str, str, str]] = []
    for message, note in _negative_messages():
        hits = await semantic.score_capabilities(message, reg, service)
        if not hits:
            continue
        scored.append((hits[0].score, hits[0].capability_id, message, note))
    scored.sort(key=lambda row: (-row[0], row[2]))
    return scored


async def measure(
    capabilities: list[Capability],
    *,
    service: Any = None,
) -> Measurement | None:
    """用**路由自己那套** embedding 与原型算法量化一份声明。不可用时返回 ``None``。

    「不可用」= 没起 embedding 服务 / 全部编码失败。那时命令照旧成功（草稿已经落盘），
    只是少一份报告——量化是**验收手段**，不是生成的前置条件。

    刻意走 ``semantic.build_prototypes`` / ``score_capabilities``（而不是自己实现均值与
    余弦）：这份报告要说的话是「路由会怎么看这份语料」，用另一套实现算出来的数说不了这句。
    进门先 ``reset_prototype_cache()``——那个缓存按 ``(registry.version, model)`` 作键，
    而临时注册表的版本号从头数，同进程里跑过第二次就可能撞上上一次的键，拿到别的插件的原型。
    """
    from capability.router import semantic
    from config import settings

    semantic.reset_prototype_cache()
    reg = _temp_registry(capabilities)
    if not reg.routable():
        return None
    prototypes = await semantic.build_prototypes(reg, service)
    if not prototypes:
        return None

    threshold = float(getattr(settings, "ROUTER_TOOL_THRESHOLD", 0.70))
    model = getattr(service, "model", "") or getattr(settings, "MEMORY_EMBEDDING_MODEL", "")
    separation: dict[str, Any] = {
        "model": str(model),
        "tool_threshold": threshold,
        "prototypes": len(prototypes),
    }
    lines = [f"量化报告（embedding 模型 {model or '未知'}，工具置信线 {threshold:.2f}）："]

    pairs = _same_domain_pairs(reg, prototypes)
    if pairs:
        cos, domain, first, second = pairs[0]
        separation["spread"] = round(1.0 - cos, 3)
        separation["closest_pair"] = [first, second]
        lines.append(
            f"  同域原型最近间距：{1.0 - cos:.3f}"
            f"（{first} ↔ {second}，域 {domain}；下限 "
            f"{plugin_check.SEPARATION_MIN_SPREAD}）",
        )
    else:
        # 键**不写**：写个 1.0 之类的假值会让 ⑫ 那条检查以为量过了
        lines.append("  同域原型最近间距：不适用（没有两条能力落在同一个域）")

    rows, per_lines = await _per_capability(reg, service)
    if rows:
        separation["per_capability"] = rows
        lines.append("  每条语料与本能力原型的余弦：")
        lines.extend(per_lines)

    scored = await _negatives(reg, service)
    if scored:
        top = scored[0][0]
        separation["negative_top"] = round(top, 3)
        separation["negative_margin"] = round(threshold - top, 3)
        separation["negatives_checked"] = len(scored)
        lines.append(
            f"  负样本余量：{threshold - top:+.3f}"
            f"（{len(scored)} 句无关请求里最高 {top:.3f}）",
        )
        for score, cid, message, note in scored[:NEGATIVE_REPORT_TOP]:
            tail = f"｜基准备注：{note}" if note else ""
            lines.append(f"    {score:.3f} {cid} ← 「{message}」{tail}")
        lines.append(_NEGATIVE_CAVEAT)

    return Measurement(separation=separation, lines=lines)


# ---------- 命令入口 ----------


def _existing_declaration(plugin_dir: Path) -> Path | None:
    """``--measure`` 量哪个文件：优先已审的正式声明，其次草稿。"""
    for name in (PLUGIN_DECL_FILENAME, PLUGIN_DECL_DRAFT_FILENAME):
        path = plugin_dir / name
        if path.is_file():
            return path
    return None


def _parse_for_measure(path: Path) -> tuple[list[Capability], str]:
    """解析一份声明供量化；第二个返回值非空时是错误说明。

    走 ``parse_declaration`` 而不是自己读一遍 TOML：量化前先过**加载器**的解析器，等于
    顺手自检了本模块手写的那套 TOML 转义。渲染出来的东西加载器读不进去的话，报告里那些
    数与运行期就没关系了——而那种漂移不会报错。
    """
    parsed = parse_declaration(path, source=SOURCE_PLUGIN, domain=PLUGIN_DECL_DOMAIN)
    if parsed.error:
        return [], parsed.error
    if not parsed.capabilities:
        return [], f"{path.name} 里没有可用的 [[capability]] 段"
    return parsed.capabilities, ""


async def _measure_and_report(capabilities: list[Capability], *, service: Any = None) -> int:
    """量化 + 按 ``plugin-check`` 的措辞打出 ⑫ 那条结论。恒返回 0。

    ⑫ 是 warn 不是 error，所以它**不改退出码**：达不到分离度的语料仍然可以是有意的
    （出厂声明里就有一个经实测确认的破例），判断的是人。
    """
    result = await measure(capabilities, service=service)
    if result is None:
        print(
            "\n没有量化报告：embedding 服务不可用（MEMORY_EMBEDDING_BASE_URL 没起，"
            "或全部编码失败）。草稿本身不受影响；服务起来之后可以只跑量化：\n"
            "  python -m deploy plugin-scaffold <插件目录> --measure",
        )
        return 0
    print()
    print("\n".join(result.lines))
    verdict = plugin_check.check_separation(PluginFacts(separation=result.separation))
    print()
    if verdict is None:
        print("量化指标达标（⑫ 项无告警）。人审仍然必需——数字达标不代表句子像人话。")
    else:
        print("\n".join(report.format_results([verdict])))
    return 0


def _resolve_backend(endpoint: str) -> tuple[Any, str]:
    """取生成用的后端。第二个返回值非空时是**给用户的**错误说明。

    默认走 ``ROLE_EXTRACT``：生成 examples 是离线一次性的活，和记忆抽取同一档需求
    （结构化输出、不要发挥）。``--endpoint`` 存在的理由是那个角色平时常绑本机小模型，
    而这一次值得临时换台更强的。
    """
    from core.llm.registry import ROLE_EXTRACT, backend_for, backend_for_endpoint

    if endpoint:
        backend = backend_for_endpoint(ROLE_EXTRACT, endpoint)
        if backend is None:
            return None, (
                f"端点槽 {endpoint} 不可用（槽名只能是 LOCAL / ONLINE_CHAT / "
                f"ONLINE_MEMORY / EXTRA，且那张卡必须配了 BASE_URL）。"
            )
        return backend, ""
    backend = backend_for(ROLE_EXTRACT)
    if backend is None:
        return None, (
            "EXTRACT 角色没有绑定可用端点，生成不了。配 LLM_ROLE_EXTRACT_ENDPOINT "
            "（默认 LOCAL）与那个槽的 BASE_URL，或者用 --endpoint 指定另一个槽。"
        )
    return backend, ""


async def _generate_and_measure(
    facts: PluginFacts,
    backend: Any,
    *,
    target: Path,
    dry_run: bool,
) -> int:
    """生成 → 落盘 → 量化。返回退出码。"""
    drafts = await generate_drafts(facts, backend)
    text = render_draft(facts, drafts)
    failed = [d for d in drafts if d.error]

    if dry_run:
        print()
        print(text)
    else:
        target.write_text(text, encoding="utf-8")
        print(f"\n已写入 {target}")

    if len(failed) == len(drafts):
        print("每个工具都没生成出来，逐条原因写在文件里：")
        for draft in failed:
            print(f"  {draft.tool}：{draft.error}")
        return 1
    if failed:
        names = "、".join(d.tool for d in failed)
        print(f"其中 {len(failed)} 条没生成出来（文件里带 ⚠ 注释）：{names}")

    # 量化的是**解析回来**的那份，理由见 _parse_for_measure。dry-run 时落到临时目录，
    # 免得为了看一眼报告就往插件目录里写东西。
    if dry_run:
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / PLUGIN_DECL_FILENAME
            probe.write_text(text, encoding="utf-8")
            capabilities, error = _parse_for_measure(probe)
    else:
        capabilities, error = _parse_for_measure(target)
    if error:
        # 加载器读不进本模块自己渲染的东西——这是生成器的 bug，不是用户写错了
        print(f"\n⚠ 渲染出来的声明解析不过：{error}\n  这是 plugin-scaffold 自己的缺陷，"
              f"请带上这份文件报一个 issue。")
        return 1
    code = await _measure_and_report(capabilities)
    print(
        f"\n下一步：这是**草稿**，{PLUGIN_DECL_DRAFT_FILENAME} 的 .draft 后缀与 "
        f"reviewed = false 两道闸门都拦着它，现在一条都不会进路由。\n"
        f"  1. 逐条读 examples，问自己「用户真的会这么说吗」；\n"
        f"  2. 需要 keywords 的话从注释里的候选词挑，自己确认每个词不会串味；\n"
        f"  3. reviewed 改成 true、去掉 .draft 后缀；\n"
        f"  4. python -m deploy plugin-check {facts.plugin_dir}",
    )
    return code


def run(
    plugin_dir: Path | str,
    *,
    endpoint: str = "",
    force: bool = False,
    dry_run: bool = False,
    measure_only: bool = False,
) -> int:
    """``python -m deploy plugin-scaffold`` 的全部实现，返回退出码。

    ``plugin_check.collect()`` 自己会 ``asyncio.run`` 一次（它要 await 插件的
    ``initialize()``），所以它必须留在协程**外面**——放进 ``asyncio.run`` 里就是
    「事件循环已在运行」。
    """
    directory = Path(plugin_dir).expanduser()
    if not directory.is_dir():
        print(f"{directory} 不是一个目录。")
        return 1

    if measure_only:
        path = _existing_declaration(directory)
        if path is None:
            print(
                f"{directory} 里既没有 {PLUGIN_DECL_FILENAME} 也没有 "
                f"{PLUGIN_DECL_DRAFT_FILENAME}，没有可量化的声明。",
            )
            return 1
        capabilities, error = _parse_for_measure(path)
        if error:
            print(f"{path.name}: {error}")
            return 1
        print(f"量化 {path}（{len(capabilities)} 条能力）")
        return asyncio.run(_measure_and_report(capabilities))

    target = directory / PLUGIN_DECL_DRAFT_FILENAME
    if target.exists() and not force and not dry_run:
        print(f"{target} 已存在。覆盖它加 --force，只想看看加 --dry-run。")
        return 1
    if (directory / PLUGIN_DECL_FILENAME).is_file():
        print(
            f"提示：{PLUGIN_DECL_FILENAME} 已经存在。草稿不会顶掉它（.draft 一律不加载），"
            f"审完想用新的就自己覆盖过去。",
        )

    backend, error = _resolve_backend(endpoint)
    if backend is None:
        print(error)
        return 1

    # 必须说出来：枚举 @llm_tool 只有 import 并实例化插件这一个办法。
    print(f"加载 {directory}")
    print("  注意：本命令会 import 并实例化该插件代码（与启动时相同的动作）。")
    facts = plugin_check.collect(directory)
    if facts.load_error:
        print(f"插件加载失败，枚举不到工具：{facts.load_error}")
        print("先用 python -m deploy plugin-check 把加载问题解决掉。")
        return 1
    if not facts.tools:
        print("这个插件没有 @llm_tool 工具，不需要能力声明——只走指令通路的插件本来就不用。")
        return 1

    model = getattr(backend, "model", "") or "未知模型"
    print(f"  {len(facts.tools)} 个工具，逐个生成（模型 {model}）：")
    return asyncio.run(
        _generate_and_measure(facts, backend, target=target, dry_run=dry_run),
    )


__all__ = [
    "ALLOWED_DOMAINS",
    "MAX_EXAMPLES",
    "MAX_EXAMPLE_CHARS",
    "TARGET_EXAMPLES",
    "Draft",
    "Measurement",
    "generate_drafts",
    "measure",
    "render_draft",
    "run",
]
