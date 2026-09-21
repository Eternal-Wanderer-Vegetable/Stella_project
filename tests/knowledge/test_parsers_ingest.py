# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""解析器 / 切块 / 导入管道测试（不触网、不依赖可选解析库的用例为主）。"""

from __future__ import annotations

import pytest

from knowledge.chunking import CHUNK_HARD_LIMIT_CHARS, chunk_sections
from knowledge.domain import (
    DOC_STATE_DRAFT,
    DOC_STATE_IN_REVIEW,
    ChunkLocator,
    ParsedSection,
)
from knowledge.ingest import content_fingerprint, ingest_content
from knowledge.parsers import (
    ParseError,
    parse_content,
    parse_html_text,
    parse_markdown,
    parse_text,
)
from knowledge.store import KnowledgeStore


@pytest.fixture()
def store(tmp_path) -> KnowledgeStore:
    return KnowledgeStore(tmp_path / "knowledge.db")


MD_DOC = """# 部署手册

## 安装

先安装 Python 3.10 及以上版本。

然后安装依赖包。

## 配置

编辑 .env 文件设置 STELLA_HOME。

### 端口

默认端口 8080。
"""


# ── Markdown / Text 解析 ──────────────────────────────────


def test_markdown_sections_carry_heading_paths() -> None:
    parsed = parse_markdown(MD_DOC)
    assert parsed.title == "部署手册"
    paths = [s.locator.section_path for s in parsed.sections]
    # section_path 是完整标题路径（含 # 根标题），命中后能直接指回阅读位置
    assert "部署手册 > 安装" in paths
    assert "部署手册 > 配置 > 端口" in paths
    # 每节都有段落号与字符区间
    for section in parsed.sections:
        assert section.locator.paragraph >= 1
        assert section.locator.char_end > section.locator.char_start


def test_markdown_rejects_empty() -> None:
    with pytest.raises(ParseError):
        parse_markdown("   \n\n  ")


def test_text_paragraph_locators() -> None:
    parsed = parse_text("第一段。\n\n第二段。\n\n\n\n第四段。")
    assert [s.locator.paragraph for s in parsed.sections] == [1, 2, 4]


# ── HTML / URL 解析（不发请求）────────────────────────────


def test_html_strips_scripts_and_extracts_title() -> None:
    html = (
        "<html><head><title>接口文档</title><style>body{}</style></head>"
        "<body><script>var x=1;</script>"
        "<p>第一段正文内容。</p><div>第二段正文内容。</div></body></html>"
    )
    parsed = parse_html_text(html, uri="https://example.com/doc")
    assert parsed.title == "接口文档"
    joined = "\n".join(s.text for s in parsed.sections)
    assert "var x=1" not in joined
    assert "第一段正文内容" in joined and "第二段正文内容" in joined
    assert parsed.source_uri == "https://example.com/doc"


def test_parse_content_rejects_unknown_type() -> None:
    with pytest.raises(ParseError, match="不支持的来源类型"):
        parse_content("epub", "x")


def test_parse_content_size_cap(monkeypatch) -> None:
    monkeypatch.setattr("config.settings.KNOWLEDGE_IMPORT_MAX_BYTES", 10)
    with pytest.raises(ParseError, match="上限"):
        parse_content("pdf", b"x" * 100)


def test_pdf_missing_text_layer_is_explicit_failure() -> None:
    """无 pypdf 库 → 明确失败提示（安装依赖），而不是静默空文档。"""
    try:
        import pypdf  # noqa: F401
    except ImportError:
        fake_pdf = b"%PDF-1.4 fake"
        with pytest.raises(ParseError, match="pypdf"):
            parse_content("pdf", fake_pdf)


# ── 切块 ─────────────────────────────────────────────────


def test_chunking_packs_paragraphs_within_limit() -> None:
    section = ParsedSection(
        text="\n\n".join(f"段落{i}，" + "内容" * 60 for i in range(6)),
        locator=ChunkLocator(section_path="一", paragraph=1),
    )
    chunks = chunk_sections([section], target_chars=200)
    assert len(chunks) >= 2
    for seq, text, loc in chunks:
        assert seq >= 0
        assert len(text) <= int(200 * 1.4) + 10
        assert loc.section_path == "一"


def test_chunking_hard_limit_split() -> None:
    long_para = "很长的句子。" * 500
    section = ParsedSection(text=long_para, locator=ChunkLocator(page=3))
    chunks = chunk_sections([section], target_chars=500)
    assert all(len(text) <= CHUNK_HARD_LIMIT_CHARS for _, text, _ in chunks)


def test_chunking_seq_continuous() -> None:
    parsed = parse_markdown(MD_DOC)
    chunks = chunk_sections(parsed.sections)
    assert [seq for seq, _, _ in chunks] == list(range(len(chunks)))


# ── 导入管道 ──────────────────────────────────────────────


def test_ingest_creates_document_and_ready_version(store) -> None:
    from knowledge.domain import KnowledgeBase

    kb = KnowledgeBase(id="kb1", name="库", owner_user_id="1")
    store.create_kb(kb)
    outcome = ingest_content(store, kb, "markdown", MD_DOC, submitted_by="1")
    assert outcome.ok and outcome.state == "ready"
    doc = store.get_document(outcome.doc_id)
    assert doc.status == DOC_STATE_DRAFT  # 导入从不自动发布
    version = store.get_version(outcome.doc_id, outcome.version_no)
    assert version.state == "ready"
    assert version.index_complete
    assert outcome.vectorized == 0  # 无 embedder：纯文本索引


def test_ingest_duplicate_hash_is_idempotent(store) -> None:
    from knowledge.domain import KnowledgeBase

    kb = KnowledgeBase(id="kb1", name="库", owner_user_id="1")
    store.create_kb(kb)
    first = ingest_content(store, kb, "text", "同一份内容", submitted_by="1")
    second = ingest_content(store, kb, "text", "同一份内容", submitted_by="1")
    assert first.state == "ready"
    assert second.state == "duplicate"
    assert second.duplicate_of == first.doc_id
    # 只有第一个版本存在
    assert len(store.list_versions(first.doc_id)) == 1


def test_ingest_same_title_replacement_makes_new_version(store) -> None:
    from knowledge.domain import KnowledgeBase

    kb = KnowledgeBase(id="kb1", name="库", owner_user_id="1")
    store.create_kb(kb)
    v1 = ingest_content(store, kb, "text", "第一版内容", title="手册", submitted_by="1")
    v2 = ingest_content(
        store, kb, "text", "第二版全新内容", title="手册", submitted_by="1"
    )
    assert v1.ok and v2.ok
    assert v2.doc_id == v1.doc_id
    assert v2.version_no == v1.version_no + 1
    versions = store.list_versions(v1.doc_id)
    assert {v.version_no for v in versions} == {1, 2}


def test_ingest_needs_review_puts_doc_in_review(store) -> None:
    from knowledge.domain import KnowledgeBase

    kb = KnowledgeBase(id="kb1", name="库", owner_user_id="1")
    store.create_kb(kb)
    outcome = ingest_content(
        store, kb, "text", "投稿内容", submitted_by="2", needs_review=True
    )
    doc = store.get_document(outcome.doc_id)
    assert doc.status == DOC_STATE_IN_REVIEW


def test_ingest_failure_records_error_and_job(store) -> None:
    from knowledge.domain import KnowledgeBase

    kb = KnowledgeBase(id="kb1", name="库", owner_user_id="1")
    store.create_kb(kb)
    outcome = ingest_content(store, kb, "text", "   ", submitted_by="1")
    assert outcome.state == "failed"
    assert outcome.error
    jobs = store.recent_jobs("kb1")
    assert jobs[0]["state"] == "failed"


def test_ingest_embedder_receives_chunk_texts(store) -> None:
    from knowledge.domain import KnowledgeBase

    kb = KnowledgeBase(id="kb1", name="库", owner_user_id="1")
    store.create_kb(kb)
    seen: list[list[str]] = []

    def fake_embedder(texts: list[str]) -> list[bytes | None]:
        seen.append(texts)
        return [b"\x00" * 8] * len(texts)

    outcome = ingest_content(
        store,
        kb,
        "text",
        "段落一。\n\n段落二。",
        submitted_by="1",
        embedder=fake_embedder,
    )
    assert outcome.ok and outcome.vectorized == outcome.chunk_count == 2
    assert len(seen) == 1


def test_fingerprint_normalizes_line_endings() -> None:
    assert content_fingerprint("a\r\nb") == content_fingerprint("a\nb")
