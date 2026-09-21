# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""导入解析器：Markdown/TXT 原生、文本型 PDF、DOCX、显式选择的 URL。

统一产出 ``ParsedSource``：标题 + 一串带定位符的 ``ParsedSection``。
**定位符是导入契约的核心**（plan 验收：每个摘录都有稳定引用与定位）——
解析层负责把它从原文里挖出来，检索层只消费不解释。

失败语义（plan 测试策略：parse/embedding failure 落到明确的失败态）：
所有解析失败抛 ``ParseError``，message 面向操作者（哪一步、为什么、
怎么办），ingest 层原样落库到 job.error / version.error。

安全边界（plan §9：import security）：

- PDF/DOCX 走第三方解析库（pypdf / python-docx，可选依赖，缺了报错而不是崩）；
- URL 只取单页：httpx 显式超时 + ``KNOWLEDGE_URL_MAX_BYTES`` 硬上限 +
  Content-Type 白名单（html/plain），不跟随非 HTTP(S) 协议，不做递归爬取；
- 所有上游体积先过 ``KNOWLEDGE_IMPORT_MAX_BYTES`` 兜底。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from knowledge.domain import ChunkLocator, ParsedSection, ParsedSource

SOURCE_MARKDOWN = "markdown"
SOURCE_TEXT = "text"
SOURCE_PDF = "pdf"
SOURCE_DOCX = "docx"
SOURCE_URL = "url"
SUPPORTED_TYPES = frozenset(
    {SOURCE_MARKDOWN, SOURCE_TEXT, SOURCE_PDF, SOURCE_DOCX, SOURCE_URL}
)


class ParseError(Exception):
    """解析失败（含原因与建议）。ingest 层捕获后落库，不进重试。"""


def _settings():
    from config import settings

    return settings


def _meta(**kw: Any) -> dict[str, Any]:
    meta = {"imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    meta.update({k: v for k, v in kw.items() if v is not None})
    return meta


# ── Markdown ──────────────────────────────────────────────

_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def parse_markdown(text: str, *, title: str = "", uri: str = "") -> ParsedSource:
    """按 ATX 标题（#~######）切节，节内按空行切段。

    ``section_path`` 记录「第N章 > 第M节」式的标题路径——检索命中后引用
    能直接指回原文的阅读位置。代码块整体保留（里面的内容也可能是知识）。
    """
    sections: list[ParsedSection] = []
    heading_stack: list[str] = []
    current: list[str] = []
    cursor = 0

    def flush() -> None:
        nonlocal cursor
        body = "\n\n".join(part.strip() for part in current if part.strip())
        if not body:
            return
        locator = ChunkLocator(
            section_path=" > ".join(heading_stack) if heading_stack else "",
            paragraph=len(sections) + 1,
            char_start=cursor,
            char_end=cursor + len(body),
        )
        sections.append(ParsedSection(text=body, locator=locator))
        cursor += len(body) + 2
        current.clear()

    for line in text.splitlines():
        match = _ATX_HEADING.match(line.strip())
        if match:
            flush()
            level = len(match.group(1))
            title_text = match.group(2).strip()
            # 回退到正确的层级（跳级标题 # 直接跟 ### 时不串层）
            del heading_stack[level - 1 :]
            heading_stack.append(title_text)
            cursor += len(line) + 1
            continue
        current.append(line)
        cursor += len(line) + 1
    flush()

    if not sections:
        raise ParseError("Markdown 内容为空或没有任何有效文本")
    return ParsedSource(
        title=title or _first_heading_or_prefix(text),
        source_type=SOURCE_MARKDOWN,
        source_uri=uri,
        sections=sections,
        meta=_meta(section_count=len(sections)),
    )


def _first_heading_or_prefix(text: str) -> str:
    for line in text.splitlines():
        match = _ATX_HEADING.match(line.strip())
        if match:
            return match.group(2)
    stripped = text.strip()
    return stripped[:30] if stripped else "未命名文档"


# ── 纯文本 ────────────────────────────────────────────────


def parse_text(text: str, *, title: str = "", uri: str = "") -> ParsedSource:
    """按空行切段；段号即定位符（纯文本没有标题结构可依赖）。"""
    sections: list[ParsedSection] = []
    cursor = 0
    for idx, para in enumerate(text.split("\n\n"), start=1):
        body = para.strip()
        if not body:
            cursor += len(para) + 2
            continue
        sections.append(
            ParsedSection(
                text=body,
                locator=ChunkLocator(
                    paragraph=idx, char_start=cursor, char_end=cursor + len(body)
                ),
            )
        )
        cursor += len(para) + 2
    if not sections:
        raise ParseError("文本内容为空")
    return ParsedSource(
        title=title or text.strip()[:30],
        source_type=SOURCE_TEXT,
        source_uri=uri,
        sections=sections,
        meta=_meta(section_count=len(sections)),
    )


# ── PDF（文本型，可选依赖 pypdf）──────────────────────────


def parse_pdf(data: bytes, *, title: str = "", uri: str = "") -> ParsedSource:
    """逐页抽取文本层；页码即定位符。

    扫描版（无文本层）是**明确的失败**而不是空文档——静默产出空索引会让
    「导入成功但什么都搜不到」变成无头案。
    """
    try:
        from io import BytesIO

        from pypdf import PdfReader
    except ImportError as e:
        raise ParseError("缺少 PDF 解析依赖 pypdf，请安装：pip install pypdf") from e

    try:
        reader = PdfReader(BytesIO(data))
        pages: list[str] = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
    except Exception as e:
        raise ParseError(f"PDF 解析失败（文件可能损坏或加密）: {e}") from e

    sections: list[ParsedSection] = []
    for page_no, page_text in enumerate(pages, start=1):
        cleaned = page_text.strip()
        if not cleaned:
            continue
        sections.append(
            ParsedSection(
                text=cleaned,
                locator=ChunkLocator(page=page_no, paragraph=0),
            )
        )
    if not sections:
        raise ParseError(
            "PDF 没有可提取的文本层（可能是扫描版/图片型）。OCR 不受支持，"
            "请先用文字识别工具转换后再导入"
        )
    first = sections[0].text[:40].replace("\n", " ")
    return ParsedSource(
        title=title or first,
        source_type=SOURCE_PDF,
        source_uri=uri,
        sections=sections,
        meta=_meta(page_count=len(pages), text_pages=len(sections)),
    )


# ── DOCX（可选依赖 python-docx）──────────────────────────


def parse_docx(data: bytes, *, title: str = "", uri: str = "") -> ParsedSource:
    """标题段落建节、正文段落与表格进节；heading 层级即 section_path。

    表格按「单元格 | 单元格」的行形式摊平——检索命中表格内容时，
    引用仍指向它所在的节。
    """
    try:
        from io import BytesIO

        import docx
    except ImportError as e:
        raise ParseError(
            "缺少 DOCX 解析依赖 python-docx，请安装：pip install python-docx"
        ) from e

    try:
        document = docx.Document(BytesIO(data))
    except Exception as e:
        raise ParseError(f"DOCX 解析失败（文件可能损坏）: {e}") from e

    sections: list[ParsedSection] = []
    heading_stack: list[str] = []
    current: list[str] = []
    table_idx = 0

    def flush() -> None:
        body = "\n".join(part for part in current if part.strip())
        if not body:
            return
        sections.append(
            ParsedSection(
                text=body,
                locator=ChunkLocator(
                    section_path=" > ".join(heading_stack) if heading_stack else "",
                    paragraph=len(sections) + 1,
                ),
            )
        )
        current.clear()

    # document.element.body 顺序遍历段落与表格（python-docx 的 Document.paragraphs
    # 会丢掉表格在文中的位置，必须走 body 迭代）
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            para = Paragraph(child, document)
            style = (para.style.name or "").lower() if para.style is not None else ""
            if style.startswith("heading"):
                flush()
                try:
                    level = int(style.rsplit(" ", 1)[-1])
                except ValueError:
                    level = len(heading_stack) + 1
                del heading_stack[max(level - 1, 0) :]
                heading_stack.append(para.text.strip() or "（无标题）")
                continue
            if para.text.strip():
                current.append(para.text.strip())
        elif child.tag.endswith("}tbl"):
            flush()
            table_idx += 1
            table = Table(child, document)
            rows: list[str] = []
            for row in table.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                rows.append(" | ".join(cells))
            body = "\n".join(rows)
            if body.strip():
                sections.append(
                    ParsedSection(
                        text=body,
                        locator=ChunkLocator(
                            section_path=" > ".join(heading_stack)
                            if heading_stack
                            else "",
                            paragraph=table_idx,
                        ),
                    )
                )
    flush()

    if not sections:
        raise ParseError("DOCX 没有可提取的文本内容")
    return ParsedSource(
        title=title or (document.core_properties.title or sections[0].text[:30]),
        source_type=SOURCE_DOCX,
        source_uri=uri,
        sections=sections,
        meta=_meta(section_count=len(sections), table_count=table_idx),
    )


# ── URL（显式选择、单页、限量）────────────────────────────

_ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript|svg|head)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_BLOCK_RE = re.compile(
    r"</(p|div|h[1-6]|li|tr|section|article|blockquote)>", re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def parse_url_fetch(url: str) -> ParsedSource:
    """抓取并解析单个 URL（用户显式给出的；不递归、不改写协议）。"""
    import httpx

    s = _settings()
    if not url.startswith(("http://", "https://")):
        raise ParseError("URL 仅支持 http/https 协议")
    max_bytes = int(s.KNOWLEDGE_URL_MAX_BYTES)
    try:
        with (
            httpx.Client(
                timeout=httpx.Timeout(float(s.KNOWLEDGE_URL_TIMEOUT)),
                trust_env=False,
                follow_redirects=True,
                headers={"User-Agent": "StellaKnowledgeBot/1.0 (+document-import)"},
            ) as client,
            client.stream("GET", url) as resp,
        ):
            resp.raise_for_status()
            content_type = (
                (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            )
            if content_type and content_type not in _ALLOWED_CONTENT_TYPES:
                raise ParseError(
                    f"不支持的内容类型 {content_type}（仅支持网页与纯文本；"
                    "PDF 请下载后用文件导入）"
                )
            body = b""
            for chunk in resp.iter_bytes():
                body += chunk
                if len(body) > max_bytes:
                    raise ParseError(f"页面超过 {max_bytes} 字节上限，已中止抓取")
    except ParseError:
        raise
    except Exception as e:
        raise ParseError(f"URL 抓取失败: {e}") from e

    charset = resp.charset_encoding or "utf-8"
    try:
        text = body.decode(charset, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")

    if content_type == "text/plain":
        return parse_text(text, title="", uri=url)

    title_match = _TITLE_RE.search(text)
    page_title = ""
    if title_match:
        page_title = _TAG_RE.sub("", title_match.group(1)).strip()
    # 标题提取已下沉到 parse_html_text（对 raw html 做），这里直接透传
    return parse_html_text(text, title=page_title, uri=url)


def parse_html_text(html: str, *, title: str = "", uri: str = "") -> ParsedSource:
    """极简 HTML → 文本：去掉不可见块，块级标签转段落边界。

    不追求排版还原——知识库要的是可检索、可引用的文本，不是网页快照。
    """
    if not title:
        title_match = _TITLE_RE.search(html)
        if title_match:
            title = _TAG_RE.sub("", title_match.group(1)).strip()
    text = _COMMENT_RE.sub(" ", html)
    text = _SCRIPT_STYLE_RE.sub(" ", text)
    text = _BLOCK_RE.sub("\n\n", text)
    text = _TAG_RE.sub(" ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    paras = [p.strip() for p in text.split("\n\n")]
    paras = [p for p in paras if p and len(p.strip()) > 1]
    if not paras:
        raise ParseError("页面没有可提取的正文（可能是纯脚本渲染页）")
    sections = [
        ParsedSection(
            text=para,
            locator=ChunkLocator(paragraph=idx),
        )
        for idx, para in enumerate(paras, start=1)
    ]
    return ParsedSource(
        title=title or paras[0][:30],
        source_type=SOURCE_URL,
        source_uri=uri,
        sections=sections,
        meta=_meta(section_count=len(sections)),
    )


# ── 统一入口 ──────────────────────────────────────────────


def parse_content(
    source_type: str,
    data: bytes | str,
    *,
    title: str = "",
    uri: str = "",
) -> ParsedSource:
    """按来源类型分派解析；未知类型与超限体积在此统一拒绝。"""
    s = _settings()
    if source_type not in SUPPORTED_TYPES:
        raise ParseError(f"不支持的来源类型: {source_type}")
    if isinstance(data, bytes):
        max_bytes = int(s.KNOWLEDGE_IMPORT_MAX_BYTES)
        if len(data) > max_bytes:
            raise ParseError(
                f"文件超过 {max_bytes} 字节上限（KNOWLEDGE_IMPORT_MAX_BYTES）"
            )
    if source_type == SOURCE_MARKDOWN:
        return parse_markdown(str(data), title=title, uri=uri)
    if source_type == SOURCE_TEXT:
        return parse_text(str(data), title=title, uri=uri)
    if source_type == SOURCE_PDF:
        return parse_pdf(bytes(data), title=title, uri=uri)
    if source_type == SOURCE_DOCX:
        return parse_docx(bytes(data), title=title, uri=uri)
    if source_type == SOURCE_URL:
        return parse_url_fetch(uri or str(data))
    raise ParseError(f"不支持的来源类型: {source_type}")  # pragma: no cover（防御）


__all__ = [
    "SOURCE_DOCX",
    "SOURCE_MARKDOWN",
    "SOURCE_PDF",
    "SOURCE_TEXT",
    "SOURCE_URL",
    "SUPPORTED_TYPES",
    "ParseError",
    "parse_content",
    "parse_docx",
    "parse_html_text",
    "parse_markdown",
    "parse_pdf",
    "parse_text",
    "parse_url_fetch",
]
