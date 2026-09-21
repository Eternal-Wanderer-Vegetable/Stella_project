# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""skills.selector 测试：确定性命中、候选预算、embedding 隔离与失败降级。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from skills.catalog import SkillCatalog
from skills.selector import SkillSelector

MAX_BYTES = 262144


@pytest.fixture
def catalog(tmp_path: Path) -> SkillCatalog:
    return SkillCatalog(
        builtin_dir=tmp_path / "builtin",
        user_dir=tmp_path / "user",
        plugins_dir=tmp_path / "plugins",
        manifest_max_bytes=MAX_BYTES,
    )


def _write_user_skill(tmp_path: Path, name: str, description: str) -> None:
    skill_dir = tmp_path / "user" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n正文（选择阶段不该读到这里）\n",
        encoding="utf-8",
    )


class TestDeterministicMatching:
    def test_name_token_hit(self, tmp_path, catalog):
        _write_user_skill(tmp_path, "pdf-extract", "从文档提取内容")
        assert catalog.refresh()
        candidates = asyncio.run(
            SkillSelector(catalog, max_candidates=3, description_max_chars=1024).select(
                "帮我处理 pdf 文件"
            )
        )
        assert len(candidates) == 1
        assert candidates[0].name == "pdf-extract"
        assert candidates[0].score == 1.0
        assert candidates[0].reason.startswith("name:")

    def test_description_latin_term_hit(self, tmp_path, catalog):
        _write_user_skill(tmp_path, "data-fix", "把 CSV 转成 markdown 表格")
        assert catalog.refresh()
        candidates = asyncio.run(
            SkillSelector(catalog, max_candidates=3, description_max_chars=1024).select(
                "帮我处理这份 csv 吧"
            )
        )
        assert candidates and candidates[0].name == "data-fix"

    def test_no_hit_returns_empty(self, tmp_path, catalog):
        _write_user_skill(tmp_path, "pdf-extract", "从文档提取内容")
        assert catalog.refresh()
        candidates = asyncio.run(
            SkillSelector(catalog, max_candidates=3, description_max_chars=1024).select(
                "今天天气怎么样"
            )
        )
        assert candidates == []


class TestBudget:
    def test_max_candidates_respected(self, tmp_path, catalog):
        for name in ("pdf-one", "pdf-two", "pdf-three", "pdf-four"):
            _write_user_skill(tmp_path, name, "处理文件")
        assert catalog.refresh()
        candidates = asyncio.run(
            SkillSelector(catalog, max_candidates=2, description_max_chars=1024).select(
                "pdf pdf"
            )
        )
        assert len(candidates) == 2
        # 确定性排序：同分按名称稳定排序
        assert [c.name for c in candidates] == [
            "pdf-four",
            "pdf-one",
        ]  # 同分按名称字母序

    def test_zero_budget_returns_empty(self, tmp_path, catalog):
        _write_user_skill(tmp_path, "pdf-extract", "处理 PDF")
        assert catalog.refresh()
        candidates = asyncio.run(
            SkillSelector(catalog, max_candidates=0, description_max_chars=1024).select(
                "pdf"
            )
        )
        assert candidates == []


class TestEmbeddingLayer:
    def test_cache_key_includes_catalog_version(self, catalog):
        selector = SkillSelector(catalog, max_candidates=3, description_max_chars=1024)
        key1 = selector._cache_key("v1", "文本")
        key2 = selector._cache_key("v2", "文本")
        assert key1.startswith("skills:v1:")
        assert key2.startswith("skills:v2:")
        assert key1 != key2

    def test_embedding_hit_fills_candidates(self, tmp_path, catalog, monkeypatch):
        _write_user_skill(tmp_path, "doc-sum", "总结长文档的要点")
        assert catalog.refresh()
        selector = SkillSelector(
            catalog,
            max_candidates=3,
            description_max_chars=1024,
            embedding=_FakeEmbedding(),
            embedding_enabled=True,
        )
        candidates = asyncio.run(selector.select("帮我把这篇文章缩写成几句话"))
        assert candidates and candidates[0].name == "doc-sum"
        assert candidates[0].reason.startswith("embedding:")

    def test_embedding_failure_falls_back_to_deterministic(self, tmp_path, catalog):
        _write_user_skill(tmp_path, "pdf-extract", "处理 PDF")
        assert catalog.refresh()

        class _Boom:
            model = ""
            dim = 0

            async def embed(self, text):
                raise RuntimeError("embedding 服务挂了")

        selector = SkillSelector(
            catalog,
            max_candidates=3,
            description_max_chars=1024,
            embedding=_Boom(),
            embedding_enabled=True,
        )
        candidates = asyncio.run(selector.select("pdf"))
        assert [c.name for c in candidates] == ["pdf-extract"]  # 确定性层不受影响

    def test_cache_is_private_not_memory_global(self, tmp_path, catalog):
        import memory.embeddings as embeddings_mod

        before = dict(embeddings_mod._CACHE)
        selector = SkillSelector(
            catalog,
            max_candidates=3,
            description_max_chars=1024,
            embedding=_FakeEmbedding(),
            embedding_enabled=True,
        )
        asyncio.run(selector.select("总结文档"))
        assert dict(embeddings_mod._CACHE) == before  # Router/记忆缓存零污染


class _FakeEmbedding:
    """把「总结/摘要」类语义映射到固定方向的假 embedding（可预测命中）。"""

    model = "fake"
    dim = 4

    async def embed(self, text: str) -> list[float]:
        text = text.lower()
        if any(w in text for w in ("总结", "摘要", "缩写", "doc-sum")):
            return [1.0, 0.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0, 0.0]
