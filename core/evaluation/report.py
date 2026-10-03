# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""评测报告（计划 §6.7.4）：维度状态机、稳定性账本、语义摘要。

合同：

- 每项结果为 ``PASS / FAIL / INSUFFICIENT_SAMPLES / SKIPPED / INCOMPLETE``；
  **样本数为 0 绝不允许 PASS**（必须是 INSUFFICIENT_SAMPLES 或 SKIPPED），
  :meth:`StabilityReport.finalize` 强制执行这条铁律。
- 报告总数、有效数、丢弃（带原因）、coverage；FAIL 维度必须带 ``sample_ids``
  让故障 case 直达样本（计划 §6.7.4 故障验证）。
- 同 fixtures 两次运行可比较：:meth:`ExperimentReport.semantic_digest` 忽略
  时间戳/UUID/路径/耗时等非语义字段，只对决策与结果做规范 JSON 摘要。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

__all__ = [
    "DimensionResult",
    "DimensionStatus",
    "ExperimentReport",
    "SampleRecord",
    "StabilityReport",
]


class DimensionStatus(str, Enum):
    """维度结果枚举（计划 §6.7.4，五值固定）。"""

    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_SAMPLES = "INSUFFICIENT_SAMPLES"
    SKIPPED = "SKIPPED"
    INCOMPLETE = "INCOMPLETE"


@dataclass
class SampleRecord:
    """逐样本（逐消息）结果：决策 + 发送回执 + 状态。"""

    event_id: str
    sequence: int
    group_id: str
    status: str = "ok"  # ok / dropped
    drop_reason: str | None = None
    decision_level: str | None = None
    score: float | None = None
    should_speak: bool = False
    flags: list[str] = field(default_factory=list)
    send_result: str | None = None

    def semantic_view(self) -> dict[str, Any]:
        """语义字段视图（digest 只看这里；score 舍入到 6 位防浮点毛刺）。"""
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "group_id": self.group_id,
            "status": self.status,
            "drop_reason": self.drop_reason,
            "decision_level": self.decision_level,
            "score": round(self.score, 6) if self.score is not None else None,
            "should_speak": self.should_speak,
            "flags": list(self.flags),
            "send_result": self.send_result,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.semantic_view()


@dataclass
class DimensionResult:
    """一个验证维度的结果；FAIL 时 ``sample_ids`` 必须能直达故障样本。"""

    name: str
    status: DimensionStatus
    detail: str = ""
    sample_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "sample_ids": list(self.sample_ids),
        }


@dataclass
class StabilityReport:
    """稳定性账本：total / valid / dropped（带原因）/ coverage + 维度列表。"""

    total: int = 0
    valid: int = 0
    dropped: list[dict[str, Any]] = field(default_factory=list)
    coverage: float = 0.0
    dimensions: list[DimensionResult] = field(default_factory=list)

    @classmethod
    def build(cls, samples: list[SampleRecord], *, total: int | None = None) -> "StabilityReport":
        """从逐样本记录汇总账本：丢弃带原因，coverage = valid / total。"""
        dropped = [
            {"event_id": s.event_id, "reason": s.drop_reason or "unspecified"}
            for s in samples
            if s.status != "ok"
        ]
        valid = sum(1 for s in samples if s.status == "ok")
        denominator = len(samples) if total is None else total
        coverage = (valid / denominator) if denominator > 0 else 0.0
        return cls(
            total=denominator,
            valid=valid,
            dropped=dropped,
            coverage=round(coverage, 6),
        )

    def add_dimension(self, name: str, status: DimensionStatus, detail: str = "", sample_ids: list[str] | None = None) -> None:
        self.dimensions.append(
            DimensionResult(name=name, status=status, detail=detail, sample_ids=list(sample_ids or []))
        )

    def finalize(self) -> None:
        """0 样本铁律：valid == 0 时任何 PASS 降级为 INSUFFICIENT_SAMPLES。"""
        if self.valid > 0:
            return
        for dimension in self.dimensions:
            if dimension.status is DimensionStatus.PASS:
                dimension.status = DimensionStatus.INSUFFICIENT_SAMPLES
                dimension.detail = (dimension.detail + "；" if dimension.detail else "") + "0 有效样本，不允许 PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "valid": self.valid,
            "dropped": list(self.dropped),
            "coverage": self.coverage,
            "dimensions": [d.to_dict() for d in self.dimensions],
        }


@dataclass
class ExperimentReport:
    """一次实验的完整报告（CLI ``--json`` 与 report.json 的持久形态）。"""

    run_id: str
    mode: str
    status: str  # completed / partial / cancelled / failed
    seed: int | None = None
    dataset_digest: str | None = None
    snapshot_partial: bool | None = None
    model_calls: int = 0
    send_calls: int = 0
    started_utc: str = ""
    finished_utc: str = ""
    duration_ms: int = 0
    workdir: str = ""
    samples: list[SampleRecord] = field(default_factory=list)
    stability: StabilityReport = field(default_factory=StabilityReport)
    errors: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def _utcnow() -> str:
        return datetime.now(timezone.utc).isoformat()

    def finalize(self) -> "ExperimentReport":
        """收尾：补时间戳并强制 0 样本铁律（不重建账本——维度登记在此前完成）。"""
        self.finished_utc = self.finished_utc or self._utcnow()
        self.stability.finalize()
        return self

    def semantic_digest(self) -> str:
        """同 fixtures 两次运行的语义摘要（忽略非语义字段）。

        忽略：run_id、workdir、started/finished_utc、duration_ms、dropped 的
        出现顺序（按 event_id 排序后比较）；保留：mode、seed、dataset 摘要、
        逐样本决策/回执、维度结论、模型/发送调用量。
        """
        dropped_view = sorted(
            ({"event_id": d["event_id"], "reason": d["reason"]} for d in self.stability.dropped),
            key=lambda d: (d["event_id"], d["reason"]),
        )
        view: dict[str, Any] = {
            "mode": self.mode,
            "status": self.status,
            "seed": self.seed,
            "dataset_digest": self.dataset_digest,
            "model_calls": self.model_calls,
            "send_calls": self.send_calls,
            "samples": [s.semantic_view() for s in sorted(self.samples, key=lambda s: s.sequence)],
            "dropped": dropped_view,
            "dimensions": sorted(
                (d.to_dict() for d in self.stability.dimensions), key=lambda d: d["name"]
            ),
        }
        payload = json.dumps(view, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """完整 dict（含非语义字段），供 ``--json`` 输出与 report.json 落盘。"""
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "status": self.status,
            "seed": self.seed,
            "dataset_digest": self.dataset_digest,
            "snapshot_partial": self.snapshot_partial,
            "model_calls": self.model_calls,
            "send_calls": self.send_calls,
            "started_utc": self.started_utc,
            "finished_utc": self.finished_utc,
            "duration_ms": self.duration_ms,
            "workdir": self.workdir,
            "semantic_digest": self.semantic_digest(),
            "samples": [s.to_dict() for s in self.samples],
            "stability": self.stability.to_dict(),
            "errors": list(self.errors),
        }
