# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""
memory 包：Stella 项目的记忆系统。

流水线概览：
- pre_processors：消息落库与上下文组装（短期摘要/用户画像/长期记忆检索）；
- consolidator：批量整合消息 → LLM JSON → 写库 → 推进 checkpoint；
- memory_manager：把记忆候选晋升/合并为长期记忆，并同步 FTS 索引；
- compressor：对长期记忆进行压缩/原子化；
- retriever：长期记忆与用户画像的检索（含关键词匹配与 SQLite FTS）；
- consolidation_prompt / prompt_builder：prompt 模板与上下文构建。
"""