# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""
memory 包：Stella 项目的记忆系统。

流水线概览：
- pre_processors：消息落库与上下文组装（短期摘要/用户画像/长期记忆检索）；
- consolidator：批量整合消息 → LLM JSON → 写库 → 推进 checkpoint；
- memory_manager：把记忆候选晋升/合并为长期记忆，并同步 FTS 索引；
- compressor：对长期记忆进行压缩/原子化/按类型衰减；
- retriever：长期记忆与用户画像的检索（含关键词匹配与 SQLite FTS）；
- retrieval_v2：记忆系统 v2 检索（Policy 优先的 Context-aware Memory Activation）；
- policy：Memory Policy Engine（模式检测 / Usage 过滤 / Visibility 访问控制 / 排序 / 候选审核）；
- schema：数据库增量迁移（Additive Migration，备份 + 加列 + 索引）；
- trace：Memory Decision Trace（决策追踪，供 Evaluation & Debug）；
- benchmark：Memory Benchmark（测试集与指标计算）；
- consolidation_prompt / prompt_builder：prompt 模板与上下文构建（v2 分区注入）。
"""