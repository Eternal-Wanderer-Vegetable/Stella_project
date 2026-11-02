# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""memory_eval：公开数据集 × 真实记忆链路的端到端评测（MBENCH-002）。

职责（计划 docs/plans/2026-10-31-memory-benchmark-public-datasets.md）：
- ``scripts/fetch_locomo.py`` / ``scripts/adapt_locomo.py`` 负责数据获取与适配；
- 本包负责：隔离回放摄入（ingest/isolation）→ 生产检索与记忆包（answer）→
  LLM-as-judge 判分（judge）→ 指标聚合与报告（metrics/report/runner）。

评测入口：``python -m memory_eval --help``（须在仓库根目录运行）。
"""

__version__ = "1.0.0"
