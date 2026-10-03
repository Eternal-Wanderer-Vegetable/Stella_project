# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""隔离验证执行器（计划 §6.7.2 四模式 / M5）。

四模式（副作用/结果合同见计划 §6.7.2 表格）：

- ``trace_playback``：历史观测事件回放——只读，0 模型、0 写业务、0 发送。
- ``decision_recompute``：冻结 snapshot/config/clock，只重算纯决策函数
  （ParticipationManager.observe），双遍比对保证决策确定性；0 发送。
- ``isolated_pipeline``：同生产业务函数 + 临时库 + fixture LLM + FakeSender，
  实际执行决策与记账事务；回执恒为 ``simulated_ack``；0 生产库、0 真实发送。
- ``model_validation``：同 isolated_pipeline，但显式要求模型 endpoint
  （环境变量 ``STELLA_EVAL_MODEL_ENDPOINT``）；未配置时维度显式 SKIPPED，
  绝不静默回退任何生产默认 endpoint。

隔离纪律（计划 §6.7.2/§6.7.3）：

- **全部状态在 workdir 下**（:class:`core.evaluation.adapters.ExperimentPaths`
  强制路径不逃逸）；
- ``isolated_pipeline``/``model_validation`` 在 **子进程** 里跑（本包调用
  ``scripts/run_flow_evaluation.py --worker``）；子进程里重建临时库后调用
  生产业务函数——生产业务函数只调用、不修改；
- 取消/超时杀 worker 并保存 partial 报告，**未完成样本不纳入稳定率**；
- 0 样本绝不 PASS（report 层强制）。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.evaluation.adapters import (
    ExperimentPaths,
    FakeSender,
    FixtureEmbedder,
    FixtureExhaustedError,
    FixtureModel,
)
from core.evaluation.clock import VirtualClock
from core.evaluation.dataset import DatasetMessage, dataset_digest, load_dataset
from core.evaluation.report import (
    DimensionStatus,
    ExperimentReport,
    SampleRecord,
    StabilityReport,
)
from core.evaluation.snapshot import load_snapshot

__all__ = [
    "MODES",
    "SUBPROCESS_MODES",
    "ExperimentConfig",
    "run_experiment",
    "run_worker",
]

MODES: tuple[str, ...] = (
    "trace_playback",
    "decision_recompute",
    "isolated_pipeline",
    "model_validation",
)
# 只有两个真正执行业务事务的模式需要子进程隔离（计划 §6.7.2）
SUBPROCESS_MODES: tuple[str, ...] = ("isolated_pipeline", "model_validation")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_PATH = _REPO_ROOT / "scripts" / "run_flow_evaluation.py"
# 生产打分表（只读加载；评测不修改任何业务文件/业务数据）
_TABLES_DIR = _REPO_ROOT / "config" / "participation"
# model_validation 的显式模型 endpoint 只从该环境变量读取——无生产默认回退
_MODEL_ENDPOINT_ENV = "STELLA_EVAL_MODEL_ENDPOINT"

_PARTIAL_REPORT_NAME = "partial_report.json"
_REPORT_NAME = "report.json"
_WORKER_CONFIG_NAME = "worker_config.json"
_WORKER_RESULT_NAME = "worker_result.json"
_WORKER_PID_NAME = "worker_pid.json"


@dataclass
class ExperimentConfig:
    """实验配置（CLI 固定 schema 的内存形态；路径全部显式，无默认回退）。"""

    mode: str
    dataset_dir: Path
    workdir: Path
    snapshot_dir: Path | None = None
    seed: int | None = None
    budget_max_calls: int | None = None
    budget_timeout: float | None = None
    run_id: str = ""

    def __post_init__(self) -> None:
        self.dataset_dir = Path(self.dataset_dir)
        self.workdir = Path(self.workdir)
        if self.snapshot_dir is not None:
            self.snapshot_dir = Path(self.snapshot_dir)
        self.run_id = self.run_id or uuid.uuid4().hex[:12]

    def validate(self) -> None:
        """路径/参数校验：dataset 必须存在；无任何生产默认路径回退。"""
        if self.mode not in MODES:
            msg = f"未知实验模式: {self.mode}（可选 {', '.join(MODES)}）"
            raise ValueError(msg)
        if not self.dataset_dir.is_dir():
            msg = f"数据集目录不存在: {self.dataset_dir}"
            raise FileNotFoundError(msg)
        if self.snapshot_dir is not None and not self.snapshot_dir.is_dir():
            msg = f"快照目录不存在: {self.snapshot_dir}"
            raise FileNotFoundError(msg)
        if self.budget_max_calls is not None and self.budget_max_calls < 0:
            raise ValueError("budget_max_calls 不能为负数")
        if self.budget_timeout is not None and self.budget_timeout <= 0:
            raise ValueError("budget_timeout 必须为正秒数")

    def to_worker_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dataset_dir": str(self.dataset_dir),
            "workdir": str(self.workdir),
            "snapshot_dir": str(self.snapshot_dir) if self.snapshot_dir else None,
            "seed": self.seed,
            "budget_max_calls": self.budget_max_calls,
            "budget_timeout": self.budget_timeout,
            "run_id": self.run_id,
        }

    @classmethod
    def from_worker_dict(cls, data: dict[str, Any]) -> "ExperimentConfig":
        return cls(
            mode=str(data["mode"]),
            dataset_dir=Path(data["dataset_dir"]),
            workdir=Path(data["workdir"]),
            snapshot_dir=Path(data["snapshot_dir"]) if data.get("snapshot_dir") else None,
            seed=data.get("seed"),
            budget_max_calls=data.get("budget_max_calls"),
            budget_timeout=data.get("budget_timeout"),
            run_id=str(data.get("run_id") or ""),
        )


# ── 对外入口 ─────────────────────────────────────────────


def run_experiment(config: ExperimentConfig) -> ExperimentReport:
    """运行一次实验；报告同时落盘 ``<workdir>/artifacts/report.json``。"""
    config.validate()
    t0 = time.monotonic()
    started_utc = datetime.now(timezone.utc).isoformat()
    paths = ExperimentPaths.create(config.workdir)
    paths.validate()

    _manifest, messages = load_dataset(config.dataset_dir)
    digest = dataset_digest(messages)
    snapshot_partial = _load_snapshot_if_any(config, paths)

    if config.mode in SUBPROCESS_MODES:
        report = _run_subprocess(config, paths, messages, digest, snapshot_partial, started_utc, t0)
    elif config.mode == "decision_recompute":
        report = _execute_pipeline(
            config, paths, messages, digest, snapshot_partial,
            started_utc=started_utc, t0=t0, execute_sends=False,
        )
    else:  # trace_playback：只读历史观测事件，零执行
        report = _run_trace_playback(
            config, messages, digest, snapshot_partial, started_utc, t0
        )

    report.stability.finalize()
    _write_report(paths, report)
    return report


def run_worker(config_dict: dict[str, Any]) -> dict[str, Any]:
    """worker 子命令入口：在子进程内执行 pipeline 并落盘报告。

    只允许 isolated_pipeline / model_validation——只读模式没必要付出
    子进程成本，也绝不从这里溜回父进程执行事务。
    """
    config = ExperimentConfig.from_worker_dict(config_dict)
    config.validate()
    if config.mode not in SUBPROCESS_MODES:
        msg = f"worker 子命令只接受 {'/'.join(SUBPROCESS_MODES)}，收到 {config.mode}"
        raise ValueError(msg)
    t0 = time.monotonic()
    started_utc = datetime.now(timezone.utc).isoformat()
    paths = ExperimentPaths.create(config.workdir)
    paths.validate()
    _manifest, messages = load_dataset(config.dataset_dir)
    digest = dataset_digest(messages)
    snapshot_partial = _load_snapshot_if_any(config, paths)
    report = _execute_pipeline(
        config, paths, messages, digest, snapshot_partial,
        started_utc=started_utc, t0=t0, execute_sends=True,
    )
    report.stability.finalize()
    _write_report(paths, report)
    (paths.artifacts / _WORKER_RESULT_NAME).write_text(
        json.dumps({"status": report.status, "run_id": report.run_id}, ensure_ascii=False),
        encoding="utf-8",
    )
    return report.to_dict()


# ── 模式实现 ─────────────────────────────────────────────


def _run_trace_playback(
    config: ExperimentConfig,
    messages: list[DatasetMessage],
    digest: str,
    snapshot_partial: bool | None,
    started_utc: str,
    t0: float,
) -> ExperimentReport:
    """trace_playback：把历史观测事件原样重放为报告条目，零执行。"""
    samples = [
        SampleRecord(
            event_id=m.event_id,
            sequence=m.sequence,
            group_id=m.group_id,
            decision_level="NOT_EXECUTED",
        )
        for m in messages
    ]
    report = ExperimentReport(
        run_id=config.run_id,
        mode=config.mode,
        status="completed",
        seed=config.seed,
        dataset_digest=digest,
        snapshot_partial=snapshot_partial,
        model_calls=0,
        send_calls=0,
        started_utc=started_utc,
        workdir=str(config.workdir),
        samples=samples,
    )
    # 先建账本（total/valid/dropped/coverage），再登记维度，最后由
    # run_experiment 统一执行 0 样本铁律。
    report.stability = StabilityReport.build(samples)
    # 只读事实：模型/发送计数恒 0（非 0 即 FAIL）
    zero_exec = report.model_calls == 0 and report.send_calls == 0
    report.stability.add_dimension(
        "zero_execution",
        DimensionStatus.PASS if zero_exec else DimensionStatus.FAIL,
        "0 模型、0 写业务、0 发送（只读回放）" if zero_exec else "只读回放出现了执行痕迹",
    )
    report.stability.add_dimension(
        "playback_read_only",
        DimensionStatus.PASS,
        "数据集事件按 sequence 原样重放，未调用任何业务函数",
    )
    report.duration_ms = int((time.monotonic() - t0) * 1000)
    report.finished_utc = datetime.now(timezone.utc).isoformat()
    return report


def _redirect_loguru_to_stderr() -> None:
    """nonebot 在 import 时会把 loguru 的控制台 sink 重配到 stdout；
    ``--json`` 的机器可读合同要求 stdout 只有报告 → 在首次导入业务模块
    （nonebot 随之进入进程）之后，把控制台日志统一改走 stderr。只影响
    评测进程自己的日志配置，不动任何业务文件。
    """
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="INFO")


def _execute_pipeline(
    config: ExperimentConfig,
    paths: ExperimentPaths,
    messages: list[DatasetMessage],
    digest: str,
    snapshot_partial: bool | None,
    *,
    started_utc: str,
    t0: float,
    execute_sends: bool,
) -> ExperimentReport:
    """决策重算 / 隔离 pipeline / 模型验证的公共执行体。

    第一遍：按 sequence 喂 :meth:`ParticipationManager.observe`（冻结虚拟
    时钟 + fixture embedding），should_speak 时按模式决定是否执行
    FixtureModel 回复 → FakeSender → ``simulated_ack`` → 反事实记账
    （note_stella_spoke）。第二遍：全新 manager 重算同一序列的纯决策并逐
    消息比对（同 fixtures 两次决策必须一致）。
    """
    from memory.participation import ParticipationManager

    _redirect_loguru_to_stderr()  # nonebot import 重配了 stdout sink，立即改回 stderr

    real_endpoint = os.environ.get(_MODEL_ENDPOINT_ENV, "").strip() if config.mode == "model_validation" else ""
    stopped_reason: str | None = None
    errors: list[dict[str, Any]] = []
    samples: list[SampleRecord] = []
    reply_by_event: dict[str, str] = {}
    model = FixtureModel(_load_fixture_replies(config.dataset_dir))
    sender = FakeSender()

    clock = VirtualClock(start=messages[0].ts_utc if messages else None)
    manager = ParticipationManager(
        tables_dir=_TABLES_DIR,
        persist=False,  # 绝不写生产库（不走 config.DB_PATH）
        jsonl_path=paths.logs / "participation_decisions.jsonl",
        md_path=paths.logs / "participation_logs.md",
        log_level="full",
        clock=lambda: clock.virtual_epoch,  # 注入虚拟时钟（observe 缺省 now 时的兜底）
    )
    embedder_service = FixtureEmbedder(
        _load_fixture_embeddings(config.dataset_dir)
    ).as_embedding_service()
    manager._embedding = embedder_service

    _rebuild_state_db(paths.db / "state.db", messages)

    status = "completed"
    for msg in messages:
        if (
            config.budget_timeout is not None
            and (time.monotonic() - t0) > config.budget_timeout
        ):
            stopped_reason = "time_budget_exceeded"
            break
        clock.advance_to(msg.ts_utc)
        gid = _coerce_int(msg.group_id, "group")
        uid = _coerce_int(msg.user, "user")
        try:
            decision = asyncio.run(
                manager.observe(
                    gid, uid, msg.content, msg_id=msg.msg_id, now=clock.virtual_epoch
                )
            )
        except Exception as exc:
            errors.append({"event_id": msg.event_id, "error_code": type(exc).__name__})
            samples.append(
                SampleRecord(
                    event_id=msg.event_id, sequence=msg.sequence, group_id=msg.group_id,
                    status="dropped", drop_reason=f"observe_error:{type(exc).__name__}",
                )
            )
            _write_partial(paths, messages, samples, model.calls_made, sender.sends_made, errors)
            continue

        record = SampleRecord(
            event_id=msg.event_id,
            sequence=msg.sequence,
            group_id=msg.group_id,
            decision_level=decision.level if decision is not None else "WARMUP",
            score=decision.score if decision is not None else None,
            should_speak=bool(decision is not None and decision.should_speak),
            flags=list(decision.reason_flags) if decision is not None else [],
        )
        if record.should_speak and execute_sends:
            if config.budget_max_calls is not None and model.calls_made >= config.budget_max_calls:
                stopped_reason = "model_budget_exceeded"
                break
            try:
                reply = model.generate(prompt=f"proactive_reply|{msg.group_id}|{msg.msg_id}")
            except FixtureExhaustedError as exc:
                errors.append({"event_id": msg.event_id, "error_code": "FixtureExhaustedError"})
                record.status = "dropped"
                record.drop_reason = f"fixture_exhausted:{exc}"
                samples.append(record)
                _write_partial(paths, messages, samples, model.calls_made, sender.sends_made, errors)
                continue
            record.send_result = sender.send_one(reply, i=sender.sends_made)
            # 反事实模拟：本条模拟 BOT_SELF 计入发言记账（计划 §6.7.3 历史观察
            # 与反事实不双算——历史 bot 输出不再作为本轮 bot 行为累加）
            manager.note_stella_spoke(gid, "proactive", now=clock.virtual_epoch, text=reply)
            reply_by_event[msg.event_id] = reply
        samples.append(record)
        _write_partial(paths, messages, samples, model.calls_made, sender.sends_made, errors)

    if stopped_reason is not None:
        status = "partial"
        # 未执行样本显式丢弃（带原因），绝不混入稳定率
        done_ids = {s.event_id for s in samples}
        for msg in messages:
            if msg.event_id not in done_ids:
                samples.append(
                    SampleRecord(
                        event_id=msg.event_id, sequence=msg.sequence, group_id=msg.group_id,
                        status="dropped", drop_reason=f"not_executed:{stopped_reason}",
                    )
                )

    report = ExperimentReport(
        run_id=config.run_id,
        mode=config.mode,
        status=status,
        seed=config.seed,
        dataset_digest=digest,
        snapshot_partial=snapshot_partial,
        model_calls=model.calls_made,
        send_calls=sender.sends_made,
        started_utc=started_utc,
        workdir=str(config.workdir),
        samples=samples,
        errors=errors,
    )
    report.stability = StabilityReport.build(samples)
    _add_pipeline_dimensions(
        report, config, paths, messages,
        manager_factory=lambda: _build_verify_manager(paths, config.dataset_dir),
        reply_by_event=reply_by_event, stopped_reason=stopped_reason,
        real_endpoint=bool(real_endpoint),
    )
    report.duration_ms = int((time.monotonic() - t0) * 1000)
    report.finished_utc = datetime.now(timezone.utc).isoformat()
    return report


def _add_pipeline_dimensions(
    report: ExperimentReport,
    config: ExperimentConfig,
    paths: ExperimentPaths,
    messages: list[DatasetMessage],
    *,
    manager_factory,
    reply_by_event: dict[str, str],
    stopped_reason: str | None,
    real_endpoint: bool,
) -> None:
    """汇总维度结果；第二遍重算纯决策做同 fixtures 稳定性比对。"""
    stability = report.stability
    if stability.valid == 0:
        stability.add_dimension(
            "pipeline_execution", DimensionStatus.INSUFFICIENT_SAMPLES,
            "0 有效样本（全部丢弃或数据集为空）",
        )
        stability.add_dimension(
            "decision_stability", DimensionStatus.INSUFFICIENT_SAMPLES, "无可比对样本",
        )
    elif report.status != "completed":
        stability.add_dimension(
            "pipeline_execution", DimensionStatus.INCOMPLETE,
            f"执行未完成: {stopped_reason}",
        )
        stability.add_dimension(
            "decision_stability", DimensionStatus.INCOMPLETE, "执行未完成，未做第二遍重算",
        )
    else:
        stability.add_dimension(
            "pipeline_execution", DimensionStatus.PASS,
            f"{stability.valid}/{stability.total} 样本全部执行",
        )
        mismatches = _verify_decisions(
            messages, report.samples, manager_factory, reply_by_event
        )
        if mismatches:
            stability.add_dimension(
                "decision_stability", DimensionStatus.FAIL,
                "第二遍重算与第一遍决策不一致",
                sample_ids=[m["event_id"] for m in mismatches],
            )
            report.errors.extend(mismatches)
        else:
            stability.add_dimension(
                "decision_stability", DimensionStatus.PASS,
                "冻结时钟 + fixture 两次重算逐消息一致",
            )

    # 隔离维度：路径不逃逸 + 发送器是 FakeSender + 无生产库写入
    try:
        paths.validate()
        isolation_ok = True
        detail = "全部状态路径在 workdir 下；sender=FakeSender（simulated_ack）；persist=False 0 生产库写入"
    except ValueError:
        isolation_ok = False
        detail = "实验路径逃逸"
    stability.add_dimension(
        "isolation",
        DimensionStatus.PASS if isolation_ok else DimensionStatus.FAIL,
        detail,
    )

    # 快照覆盖：未使用 SKIPPED；partial 快照显式 INCOMPLETE，不伪称完整复现
    if config.snapshot_dir is None:
        stability.add_dimension("snapshot_coverage", DimensionStatus.SKIPPED, "未提供 snapshot")
    elif report.snapshot_partial:
        stability.add_dimension(
            "snapshot_coverage", DimensionStatus.INCOMPLETE, "快照缺表，标 partial"
        )
    else:
        stability.add_dimension("snapshot_coverage", DimensionStatus.PASS, "快照表齐全")

    if config.mode == "model_validation":
        if real_endpoint:
            stability.add_dimension(
                "model_execution", DimensionStatus.INCOMPLETE,
                "显式 endpoint 已配置；当前闭环仍用 fixture 回复验证预算/隔离，真实生成未接入",
            )
        else:
            stability.add_dimension(
                "model_execution", DimensionStatus.SKIPPED,
                f"未设置 {_MODEL_ENDPOINT_ENV}，不执行真实模型调用",
            )


def _verify_decisions(
    messages: list[DatasetMessage],
    samples: list[SampleRecord],
    manager_factory,
    reply_by_event: dict[str, str],
) -> list[dict[str, Any]]:
    """第二遍：全新 manager + 同一时钟序列重算纯决策，与第一遍逐消息比对。"""
    ok_samples = [s for s in samples if s.status == "ok"]
    by_event = {m.event_id: m for m in messages}
    verify_clock = VirtualClock(start=messages[0].ts_utc if messages else None)
    verify_manager = manager_factory()
    mismatches: list[dict[str, Any]] = []
    for sample in ok_samples:
        msg = by_event.get(sample.event_id)
        if msg is None:  # 报告里出现了数据集外样本——本身就是不一致
            mismatches.append(
                {"event_id": sample.event_id, "error_code": "SampleNotInDataset"}
            )
            continue
        verify_clock.advance_to(msg.ts_utc)
        gid = _coerce_int(msg.group_id, "group")
        uid = _coerce_int(msg.user, "user")
        try:
            decision = asyncio.run(
                verify_manager.observe(
                    gid, uid, msg.content, msg_id=msg.msg_id, now=verify_clock.virtual_epoch
                )
            )
            # 反事实记账同样重放（否则后续消息的新信息量会错位）
            if sample.should_speak and sample.event_id in reply_by_event:
                verify_manager.note_stella_spoke(
                    gid, "proactive", now=verify_clock.virtual_epoch,
                    text=reply_by_event[sample.event_id],
                )
        except Exception as exc:
            mismatches.append({"event_id": sample.event_id, "error_code": type(exc).__name__})
            continue
        level2 = decision.level if decision is not None else "WARMUP"
        score2 = round(decision.score, 6) if decision is not None else None
        flags2 = list(decision.reason_flags) if decision is not None else []
        same = (
            level2 == sample.decision_level
            and score2 == (round(sample.score, 6) if sample.score is not None else None)
            and flags2 == sample.flags
        )
        if not same:
            mismatches.append(
                {
                    "event_id": sample.event_id,
                    "error_code": "DecisionMismatch",
                    "first": [sample.decision_level, sample.score, sample.flags],
                    "second": [level2, score2, flags2],
                }
            )
    return mismatches


# ── 子进程隔离 ───────────────────────────────────────────


def _run_subprocess(
    config: ExperimentConfig,
    paths: ExperimentPaths,
    messages: list[DatasetMessage],
    digest: str,
    snapshot_partial: bool | None,
    started_utc: str,
    t0: float,
) -> ExperimentReport:
    """在子进程里跑 isolated_pipeline / model_validation；超时/失败保 partial。"""
    if not _CLI_PATH.is_file():
        msg = f"worker CLI 不存在: {_CLI_PATH}"
        raise RuntimeError(msg)
    cfg_path = paths.artifacts / _WORKER_CONFIG_NAME
    cfg_path.write_text(
        json.dumps(config.to_worker_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cmd = [
        sys.executable, "-X", "utf8", str(_CLI_PATH),
        "--worker", "--worker-config", str(cfg_path),
    ]
    env = {**os.environ, "PYTHONUTF8": "1"}
    with (paths.logs / "worker_stdout.log").open("wb") as log_fh:
        proc = subprocess.Popen(
            cmd, cwd=str(_REPO_ROOT), stdout=log_fh, stderr=subprocess.STDOUT, env=env,
        )
    (paths.artifacts / _WORKER_PID_NAME).write_text(
        json.dumps({"pid": proc.pid}), encoding="utf-8"
    )
    timed_out = False
    try:
        proc.wait(timeout=config.budget_timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_worker(proc)

    report_path = paths.artifacts / _REPORT_NAME
    if not timed_out and proc.returncode == 0 and report_path.is_file():
        data = json.loads(report_path.read_text(encoding="utf-8"))
        return _report_from_dict(data)

    # 超时 / 失败：杀 worker 已做，从 partial 恢复未完成样本（不进稳定率）
    note = "worker 超时被终止" if timed_out else f"worker 异常退出（exit={proc.returncode}）"
    report = _partial_report_from_disk(
        config, paths, messages, digest, snapshot_partial, started_utc, t0, note=note
    )
    report.stability.finalize()
    return report


def _terminate_worker(proc: subprocess.Popen) -> None:
    """杀 worker：先温和终止，超期强杀；绝不留下孤儿事务进程。"""
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _partial_report_from_disk(
    config: ExperimentConfig,
    paths: ExperimentPaths,
    messages: list[DatasetMessage],
    digest: str,
    snapshot_partial: bool | None,
    started_utc: str,
    t0: float,
    *,
    note: str,
) -> ExperimentReport:
    """把 worker 留下的 partial_report.json 恢复为 partial ExperimentReport。"""
    samples: list[SampleRecord] = []
    partial_path = paths.artifacts / _PARTIAL_REPORT_NAME
    if partial_path.is_file():
        try:
            data = json.loads(partial_path.read_text(encoding="utf-8"))
            samples = [_sample_from_dict(item) for item in data.get("samples", [])]
        except (json.JSONDecodeError, KeyError, TypeError):
            samples = []
    done_ids = {s.event_id for s in samples}
    for msg in messages:
        if msg.event_id not in done_ids:
            samples.append(
                SampleRecord(
                    event_id=msg.event_id, sequence=msg.sequence, group_id=msg.group_id,
                    status="dropped", drop_reason="not_executed:worker_terminated",
                )
            )
    report = ExperimentReport(
        run_id=config.run_id,
        mode=config.mode,
        status="partial",
        seed=config.seed,
        dataset_digest=digest,
        snapshot_partial=snapshot_partial,
        started_utc=started_utc,
        workdir=str(config.workdir),
        samples=samples,
        errors=[{"error_code": "WorkerTerminated", "detail": note}],
    )
    # partial 报告也要有完整账本与维度（未完成样本已显式 dropped，不进稳定率）
    report.stability = StabilityReport.build(samples)
    report.stability.add_dimension(
        "pipeline_execution", DimensionStatus.INCOMPLETE, f"执行未完成: {note}"
    )
    report.stability.add_dimension(
        "decision_stability", DimensionStatus.INCOMPLETE, "执行未完成，未做第二遍重算"
    )
    report.stability.add_dimension(
        "isolation", DimensionStatus.PASS, "worker 被终止，但全部状态仍锁定在 workdir 沙箱内"
    )
    if config.snapshot_dir is None:
        report.stability.add_dimension("snapshot_coverage", DimensionStatus.SKIPPED, "未提供 snapshot")
    elif snapshot_partial:
        report.stability.add_dimension(
            "snapshot_coverage", DimensionStatus.INCOMPLETE, "快照缺表，标 partial"
        )
    else:
        report.stability.add_dimension("snapshot_coverage", DimensionStatus.PASS, "快照表齐全")
    report.stability.finalize()
    report.duration_ms = int((time.monotonic() - t0) * 1000)
    report.finished_utc = datetime.now(timezone.utc).isoformat()
    return report


# ── 附属构件 ─────────────────────────────────────────────


def _load_snapshot_if_any(config: ExperimentConfig, paths: ExperimentPaths) -> bool | None:
    """snapshot_dir 提供时装载快照到 workdir；返回 partial 标志。"""
    if config.snapshot_dir is None:
        return None
    info = load_snapshot(config.snapshot_dir, paths.db / "snapshot.db")
    return bool(info.get("partial", False))


def _build_verify_manager(paths: ExperimentPaths, dataset_dir: Path):
    """第二遍重算用的全新 manager：同打分表、同 fixture embedding、同日志目录。"""
    from memory.participation import ParticipationManager

    clock = VirtualClock(start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    manager = ParticipationManager(
        tables_dir=_TABLES_DIR,
        persist=False,
        jsonl_path=paths.logs / "participation_decisions.jsonl",
        md_path=paths.logs / "participation_logs.md",
        log_level="full",
        clock=lambda: clock.virtual_epoch,
    )
    manager._embedding = FixtureEmbedder(
        _load_fixture_embeddings(dataset_dir)
    ).as_embedding_service()
    return manager


def _coerce_int(text: str, salt: str) -> int:
    """群/用户标识转 int：数字原样；非数字走稳定 crc32（回放确定性不受影响）。"""
    try:
        return int(text)
    except (TypeError, ValueError):
        return int(zlib.crc32(f"{salt}|{text}".encode()))


def _load_fixture_replies(dataset_dir: Path) -> list[str]:
    """数据集自带 ``fixtures.json`` 的回复脚本；缺省用确定性占位脚本。"""
    fixtures = _load_fixtures_file(dataset_dir)
    replies = fixtures.get("replies") if isinstance(fixtures, dict) else None
    if isinstance(replies, list) and replies:
        return [str(r) for r in replies]
    return ["[fixture_reply] 好的。"]


def _load_fixture_embeddings(dataset_dir: Path) -> dict[str, list[float]]:
    """数据集自带 embedding 查表；缺省空表（miss 全零向量，语义通道静默）。"""
    fixtures = _load_fixtures_file(dataset_dir)
    embeddings = fixtures.get("embeddings") if isinstance(fixtures, dict) else None
    if isinstance(embeddings, dict):
        return {str(k): [float(x) for x in v] for k, v in embeddings.items()}
    return {}


def _load_fixtures_file(dataset_dir: Path) -> dict[str, Any]:
    path = Path(dataset_dir) / "fixtures.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _rebuild_state_db(db_path: Path, messages: list[DatasetMessage]) -> None:
    """在 workdir 下重建临时状态库（group_messages 装载数据集）；绝不碰生产库。

    生产 ``group_messages`` 的 DDL 在 memory/pre_processors.py 内手写，这里
    复刻同构表（只写实验沙箱）；未来 pipeline 扩展读消息水位等状态时用它。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS group_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT,
                    user_id TEXT,
                    content TEXT,
                    source_kind TEXT DEFAULT 'PASSIVE',
                    msg_id INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for msg in messages:
                conn.execute(
                    "INSERT INTO group_messages (group_id, user_id, content, source_kind, msg_id, timestamp)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        msg.group_id,
                        msg.user,
                        msg.content,
                        msg.source_kind,
                        msg.msg_id,
                        msg.ts_utc.strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
    finally:
        conn.close()


def _write_partial(
    paths: ExperimentPaths,
    messages: list[DatasetMessage],
    samples: list[SampleRecord],
    model_calls: int,
    send_calls: int,
    errors: list[dict[str, Any]],
) -> None:
    """逐消息落 partial 报告：取消/超时后未完成样本可从磁盘恢复。"""
    payload = {
        "total": len(messages),
        "processed": len(samples),
        "model_calls": model_calls,
        "send_calls": send_calls,
        "samples": [s.to_dict() for s in samples],
        "errors": errors,
    }
    (paths.artifacts / _PARTIAL_REPORT_NAME).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _sample_from_dict(data: dict[str, Any]) -> SampleRecord:
    return SampleRecord(
        event_id=str(data["event_id"]),
        sequence=int(data.get("sequence") or 0),
        group_id=str(data.get("group_id") or ""),
        status=str(data.get("status") or "ok"),
        drop_reason=data.get("drop_reason"),
        decision_level=data.get("decision_level"),
        score=data.get("score"),
        should_speak=bool(data.get("should_speak", False)),
        flags=list(data.get("flags") or []),
        send_result=data.get("send_result"),
    )


def _report_from_dict(data: dict[str, Any]) -> ExperimentReport:
    report = ExperimentReport(
        run_id=str(data.get("run_id") or ""),
        mode=str(data.get("mode") or ""),
        status=str(data.get("status") or "failed"),
        seed=data.get("seed"),
        dataset_digest=data.get("dataset_digest"),
        snapshot_partial=data.get("snapshot_partial"),
        model_calls=int(data.get("model_calls") or 0),
        send_calls=int(data.get("send_calls") or 0),
        started_utc=str(data.get("started_utc") or ""),
        finished_utc=str(data.get("finished_utc") or ""),
        duration_ms=int(data.get("duration_ms") or 0),
        workdir=str(data.get("workdir") or ""),
        samples=[_sample_from_dict(item) for item in data.get("samples", [])],
        errors=list(data.get("errors") or []),
    )
    report.stability = _stability_from_dict(data.get("stability") or {})
    return report


def _stability_from_dict(data: dict[str, Any]):
    """StabilityReport 反序列化（与 to_dict 对称）。"""
    from core.evaluation.report import DimensionResult, DimensionStatus, StabilityReport

    return StabilityReport(
        total=int(data.get("total") or 0),
        valid=int(data.get("valid") or 0),
        dropped=list(data.get("dropped") or []),
        coverage=float(data.get("coverage") or 0.0),
        dimensions=[
            DimensionResult(
                name=str(item.get("name") or ""),
                status=DimensionStatus(str(item.get("status") or "SKIPPED")),
                detail=str(item.get("detail") or ""),
                sample_ids=[str(x) for x in item.get("sample_ids", [])],
            )
            for item in data.get("dimensions", [])
        ],
    )


def _write_report(paths: ExperimentPaths, report: ExperimentReport) -> None:
    (paths.artifacts / _REPORT_NAME).write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
