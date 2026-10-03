# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""隔离验证执行器（计划 §6.7 / M5）：dataset/snapshot 只读导出、四实验模式、
报告与稳定性合同。

公共入口（计划 §6.7.2/§6.7.3/§6.7.4）：

- :func:`core.evaluation.dataset.export_dataset` / :func:`load_dataset`
  ——生产记忆库只读导出（manifest + JSONL，伪名 + 稳定 event_id + cutoff 防泄漏）；
- :func:`core.evaluation.snapshot.export_snapshot` / :func:`load_snapshot`
  ——SQLite backup API 沙箱快照（缺表标 partial 不报错）；
- :func:`core.evaluation.runner.run_experiment`
  ——trace_playback / decision_recompute / isolated_pipeline / model_validation
  四模式；全部状态在 workdir 沙箱内；
- :class:`core.evaluation.report.ExperimentReport`
  ——维度结果（0 样本绝不 PASS）+ semantic digest（同 fixtures 可比较）。

时钟与适配器（评测专用的依赖边界）：

- :class:`core.evaluation.clock.SystemClock` / :class:`VirtualClock`
  ——业务 TTL/冷却/配额走虚拟时钟；性能计时恒走真实 monotonic；
- :class:`core.evaluation.adapters.FixtureModel` / :class:`FixtureEmbedder` /
  :class:`FakeSender` / :class:`ExperimentPaths`
  ——零网络的模型/向量/发送桩与路径沙箱（防逃逸）。

CLI 见 ``scripts/run_flow_evaluation.py``（固定参数 schema，无生产默认路径）；
Dashboard 适配见 ``webui/services/evaluation.py``（实验并发上限 1）。
"""

from __future__ import annotations

from core.evaluation.adapters import (
    ExperimentPaths,
    FakeSender,
    FixtureEmbedder,
    FixtureModel,
    PathEscapeError,
    resolve_under,
)
from core.evaluation.clock import Clock, SystemClock, VirtualClock
from core.evaluation.dataset import (
    DatasetMessage,
    dataset_digest,
    export_dataset,
    load_dataset,
    pseudonymize_user,
)
from core.evaluation.report import (
    DimensionResult,
    DimensionStatus,
    ExperimentReport,
    SampleRecord,
    StabilityReport,
)
from core.evaluation.runner import (
    MODES,
    ExperimentConfig,
    run_experiment,
)
from core.evaluation.snapshot import export_snapshot, load_snapshot

__all__ = [
    "MODES",
    "Clock",
    "DatasetMessage",
    "DimensionResult",
    "DimensionStatus",
    "ExperimentConfig",
    "ExperimentPaths",
    "ExperimentReport",
    "FakeSender",
    "FixtureEmbedder",
    "FixtureModel",
    "PathEscapeError",
    "SampleRecord",
    "StabilityReport",
    "SystemClock",
    "VirtualClock",
    "dataset_digest",
    "export_dataset",
    "export_snapshot",
    "load_dataset",
    "load_snapshot",
    "pseudonymize_user",
    "resolve_under",
    "run_experiment",
]
