# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""B04 dual-track, source-lineage memory benchmark.

Run with ``python -m memory_eval.b04 --help``. The existing ``memory_eval``
CLI and report/1 contract remain unchanged and read-only to this experiment.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from memory_eval.b04_ingress import ProductionReplayEnv
from memory_eval.b04_lineage import build_lineage, retrieval_source_alignment
from memory_eval.isolation import ReplayEnv, ensure_eval_home
from memory_eval.scenarios import load_index, load_scenarios

REPORT_SCHEMA = "memory-eval-report/2"
FINGERPRINT_SCHEMA = "memory-eval-resume/2"
ANSWER_PROMPT_VERSION = "memory-eval-answer-v1"
JUDGE_PROMPT_VERSION = "locomo-judge-v1"
DEFAULT_CALL_BUDGET = 200
DEFAULT_RUNTIME_SECONDS = 30 * 60


class BudgetExceededError(RuntimeError):
    """The local model-call or wall-time budget would be exceeded."""


class RunBudget:
    def __init__(self, max_calls: int, max_seconds: int):
        self.max_calls = int(max_calls)
        self.max_seconds = int(max_seconds)
        if self.max_calls < 1:
            raise ValueError("max_calls must be at least 1")
        if self.max_seconds < 1:
            raise ValueError("max_runtime_seconds must be at least 1")
        self.started = time.monotonic()
        self.calls: list[dict[str, str]] = []
        self.truncated_generations: list[dict[str, str]] = []

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.max_seconds - self.elapsed)

    def reserve(self, role: str) -> None:
        if self.remaining_seconds <= 0:
            raise BudgetExceededError("B04 runtime budget exhausted")
        if len(self.calls) >= self.max_calls:
            raise BudgetExceededError("B04 model-call budget exhausted")
        self.calls.append({"role": role, "reserved_at": _utcnow()})

    def check_time(self) -> None:
        if self.remaining_seconds <= 0:
            raise BudgetExceededError("B04 runtime budget exhausted")

    def record_truncation(self, role: str) -> None:
        self.truncated_generations.append({"role": role, "observed_at": _utcnow()})


class BudgetedEndpoint:
    """Meter the endpoint that ``RoleBackend.attempt_plan`` hands to the caller."""

    def __init__(self, inner: Any, budget: RunBudget, role: str):
        self._inner = inner
        self._budget = budget
        self._role = role

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def generate_single_attempt(
        self, prompt: str, system_prompt: str = ""
    ) -> tuple[str, str]:
        self._budget.reserve(self._role)
        timeout = self._budget.remaining_seconds
        if timeout <= 0:
            raise BudgetExceededError("B04 runtime budget exhausted")
        reply, finish = await asyncio.wait_for(
            self._inner.generate_single_attempt(prompt, system_prompt),
            timeout=timeout,
        )
        if finish == "length":
            self._budget.record_truncation(self._role)
        return reply, finish


class BudgetedBackend:
    """Count production consolidation/extraction generations before dispatch."""

    def __init__(self, inner: Any, budget: RunBudget, role: str):
        self._inner = inner
        self._budget = budget
        self._role = role

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def attempt_plan(self) -> tuple[Any, bool]:
        """Wrap the resolved endpoint so role-path calls stay inside the budget."""
        endpoint, degraded = self._inner.attempt_plan()
        return BudgetedEndpoint(endpoint, self._budget, self._role), degraded

    def record_attempt_result(self, endpoint: Any, error: BaseException) -> bool:
        """Unwrap before forwarding: the inner backend compares endpoint identity."""
        return self._inner.record_attempt_result(getattr(endpoint, "_inner", endpoint), error)

    async def generate_single_attempt(
        self, prompt: str, system_prompt: str = ""
    ) -> tuple[str, str]:
        return await BudgetedEndpoint(self._inner, self._budget, self._role).generate_single_attempt(
            prompt, system_prompt
        )

    async def generate_detailed(self, prompt: str, *args: Any, **kwargs: Any):
        self._budget.reserve(self._role)
        timeout = self._budget.remaining_seconds
        if timeout <= 0:
            raise BudgetExceededError("B04 runtime budget exhausted")
        result = await asyncio.wait_for(
            self._inner.generate_detailed(prompt, *args, **kwargs),
            timeout=timeout,
        )
        if isinstance(result, tuple) and len(result) > 1 and result[1] == "length":
            self._budget.record_truncation(self._role)
        return result

    async def generate(self, prompt: str, *args: Any, **kwargs: Any):
        self._budget.reserve(self._role)
        timeout = self._budget.remaining_seconds
        if timeout <= 0:
            raise BudgetExceededError("B04 runtime budget exhausted")
        return await asyncio.wait_for(
            self._inner.generate(prompt, *args, **kwargs),
            timeout=timeout,
        )


class BudgetedEvalLLM:
    def __init__(
        self,
        inner: Any,
        budget: RunBudget,
        role: str,
        max_tokens: int,
        reasoning_effort: str | None = None,
    ):
        self._inner = inner
        self._budget = budget
        self._role = role
        self._max_tokens = max(1, int(max_tokens))
        self._reasoning_effort = reasoning_effort

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def chat(self, *args: Any, **kwargs: Any):
        self._budget.reserve(self._role)
        timeout = self._budget.remaining_seconds
        if timeout <= 0:
            raise BudgetExceededError("B04 runtime budget exhausted")
        self._inner.timeout = timeout
        kwargs["max_tokens"] = min(
            int(kwargs.get("max_tokens", self._max_tokens)), self._max_tokens
        )
        if self._reasoning_effort:
            kwargs.setdefault("reasoning_effort", self._reasoning_effort)
        return self._inner.chat(*args, **kwargs)

    def cost_summary(self) -> dict[str, Any]:
        return self._inner.cost_summary()


class BudgetedEmbeddingService:
    """Meter embedding calls and disable EmbeddingService's auto-start fallback."""

    def __init__(self, base_url: str, model: str, budget: RunBudget):
        from mneme.embeddings import EmbeddingService

        self._budget = budget
        self._inner = EmbeddingService(
            base_url, model, timeout=budget.max_seconds, cache={}
        )
        self.similarity_requests = 0
        self.api_calls = 0
        self.api_failures = 0
        self.budget_exhausted = False
        original_request = self._inner._request_embedding

        async def budgeted_request(
            request_base_url: str, request_model: str, text: str
        ) -> list[float]:
            try:
                self._budget.reserve("embedding")
            except BudgetExceededError:
                self.budget_exhausted = True
                raise
            self.api_calls += 1
            timeout = self._budget.remaining_seconds
            if timeout <= 0:
                self.budget_exhausted = True
                raise BudgetExceededError("B04 runtime budget exhausted")
            return await asyncio.wait_for(
                original_request(request_base_url, request_model, text),
                timeout=timeout,
            )

        async def no_autostart_embed_uncached(text: str, key: str) -> list[float] | None:
            try:
                vector = await self._inner._request_embedding(
                    self._inner.base_url, self._inner.model, text
                )
            except BudgetExceededError:
                raise
            except Exception:
                self.api_failures += 1
                self._inner._cache[key] = None
                return None
            self._inner._cache[key] = vector
            return vector

        self._inner._request_embedding = budgeted_request
        # The production EmbeddingService starts a local fallback on endpoint errors.
        # B04 must keep every request explicit and inside its own budget.
        self._inner._embed_uncached = no_autostart_embed_uncached

    async def similarity(self, query: str, content: str) -> float | None:
        self.similarity_requests += 1
        return await self._inner.similarity(query, content)

    def summary(self) -> dict[str, Any]:
        return {
            "requested": True,
            "base_url": _safe_endpoint(self._inner.base_url),
            "model": self._inner.model,
            "similarity_requests": self.similarity_requests,
            "api_calls": self.api_calls,
            "api_failures": self.api_failures,
            "budget_exhausted": self.budget_exhausted,
            "cache_entries": len(self._inner._cache),
        }


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _code_fingerprint() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    names = (
        "b04.py",
        "b04_ingress.py",
        "b04_lineage.py",
        "answer.py",
        "judge.py",
        "scenarios.py",
    )
    return {name: _sha256(root / name) for name in names}


def _git_head() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            timeout=10, check=True,
        ).stdout.strip()
    except Exception:
        return None


def _safe_endpoint(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    parts = urlsplit(value)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    safe = urlunsplit((parts.scheme, host, parts.path.rstrip("/"), "", ""))
    return {"endpoint": safe, "endpoint_sha256": hashlib.sha256(value.encode()).hexdigest()}


def _memory_backend_base_url(value: str) -> str:
    """Return an OpenAI-compatible API root for production-role backends.

    ``EvalLLM`` takes a ``/v1`` URL, while ``OpenAICompatibleBackend`` appends
    ``/v1/chat/completions`` itself. Accept either spelling at the CLI and
    normalize it before wiring the isolated MEMORY endpoint.
    """
    parts = urlsplit(str(value or "").strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("memory-base-url must be an absolute http(s) URL")
    path = parts.path.rstrip("/")
    if path.casefold().endswith("/v1"):
        path = path[:-3]
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


def _memory_backend_overrides(args: argparse.Namespace) -> dict[str, str]:
    """Explicit, reproducible MEMORY-role configuration for the isolated run."""
    if args.max_consolidation_tokens < 1 or args.max_extract_tokens < 1:
        raise ValueError("memory role token caps must be at least 1")
    base_url = _memory_backend_base_url(args.memory_base_url)
    return {
        "LLM_ENDPOINT_MEMORY_BASE_URL": base_url,
        "LLM_ENDPOINT_MEMORY_API_KEY": str(args.memory_api_key or ""),
        "LLM_ENDPOINT_MEMORY_MODEL": str(args.memory_model),
        "LLM_ENDPOINT_MEMORY_KIND": str(args.memory_kind),
        "LLM_ENDPOINT_MEMORY_CONCURRENCY": "1",
        "LLM_ENDPOINT_MEMORY_TIMEOUT": "120",
        "LLM_ROLE_CONSOLIDATION_ENDPOINT": "MEMORY",
        "LLM_ROLE_CONSOLIDATION_MODEL": str(args.memory_model),
        "LLM_ROLE_CONSOLIDATION_TEMPERATURE": "0.3",
        "LLM_ROLE_CONSOLIDATION_MAX_TOKENS": str(args.max_consolidation_tokens),
        "LLM_ROLE_CONSOLIDATION_FALLBACK_ENDPOINT": "",
        "LLM_ROLE_EXTRACT_ENDPOINT": "MEMORY",
        "LLM_ROLE_EXTRACT_MODEL": str(args.memory_model),
        "LLM_ROLE_EXTRACT_TEMPERATURE": "0.2",
        "LLM_ROLE_EXTRACT_MAX_TOKENS": str(args.max_extract_tokens),
        "LLM_ROLE_EXTRACT_FALLBACK_ENDPOINT": "",
        "LLM_FALLBACK_ENABLED": "false",
    }


def _apply_memory_backend_overrides(overrides: dict[str, str]) -> None:
    """Apply isolated endpoint settings, including already-imported modules."""
    os.environ.update(overrides)
    settings = sys.modules.get("config.settings")
    if settings is not None:
        integer_keys = {
            "LLM_ENDPOINT_MEMORY_CONCURRENCY",
            "LLM_ROLE_CONSOLIDATION_MAX_TOKENS",
            "LLM_ROLE_EXTRACT_MAX_TOKENS",
        }
        float_keys = {
            "LLM_ENDPOINT_MEMORY_TIMEOUT",
            "LLM_ROLE_CONSOLIDATION_TEMPERATURE",
            "LLM_ROLE_EXTRACT_TEMPERATURE",
        }
        for key, value in overrides.items():
            if key == "LLM_FALLBACK_ENABLED":
                parsed: Any = value.casefold() == "true"
            elif key in integer_keys:
                parsed = int(value)
            elif key in float_keys:
                parsed = float(value)
            else:
                parsed = value
            setattr(settings, key, parsed)

    registry = sys.modules.get("core.llm.registry")
    if registry is not None:
        registry.reset_state()


def _memory_backend_identity(args: argparse.Namespace) -> dict[str, Any]:
    overrides = _memory_backend_overrides(args)
    return {
        "endpoint": "MEMORY",
        "base_url": _safe_endpoint(overrides["LLM_ENDPOINT_MEMORY_BASE_URL"]),
        "kind": overrides["LLM_ENDPOINT_MEMORY_KIND"],
        "model": overrides["LLM_ENDPOINT_MEMORY_MODEL"],
        "api_key_configured": bool(overrides["LLM_ENDPOINT_MEMORY_API_KEY"]),
        "fallback_enabled": False,
        "roles": {
            "consolidation": {
                "temperature": float(overrides["LLM_ROLE_CONSOLIDATION_TEMPERATURE"]),
                "max_tokens": int(overrides["LLM_ROLE_CONSOLIDATION_MAX_TOKENS"]),
            },
            "extract": {
                "temperature": float(overrides["LLM_ROLE_EXTRACT_TEMPERATURE"]),
                "max_tokens": int(overrides["LLM_ROLE_EXTRACT_MAX_TOKENS"]),
            },
        },
    }


def _backend_descriptor(backend: Any) -> dict[str, Any] | None:
    if backend is None:
        return None
    inner = getattr(backend, "_inner", backend)
    base_url = getattr(inner, "base_url", None) or getattr(inner, "endpoint", None)
    return {
        "class": type(inner).__name__,
        "name": str(getattr(inner, "name", "") or ""),
        "model": str(getattr(inner, "model", "") or getattr(inner, "model_name", "") or ""),
        "endpoint": _safe_endpoint(str(base_url)) if base_url else None,
    }


def _dataset_identity(data_dir: Path, scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    index = load_index(data_dir)
    source = index.get("source") or {}
    selected = []
    for scenario in scenarios:
        path = data_dir / f"{scenario['scenario_id'].replace('locomo-', '')}.json"
        if not path.exists():
            path = next(data_dir.glob(f"{scenario['scenario_id'].split('-')[-1]}*.json"), None)
        if path is None or not path.exists():
            raise FileNotFoundError(f"Cannot fingerprint scenario file for {scenario['scenario_id']}")
        selected.append({"scenario_id": scenario["scenario_id"], "sha256": _sha256(path)})
    return {
        "name": str(source.get("dataset") or "snap-research/locomo"),
        "revision": str(source.get("revision") or ""),
        "index_sha256": _sha256(data_dir / "index.json"),
        "source_sha256": str(source.get("sha256") or ""),
        "license": str(source.get("license") or "CC-BY-NC-4.0"),
        "scenarios": selected,
    }


def _personamem_identity(data_dir: Path) -> dict[str, Any]:
    files = sorted(data_dir.glob("*.json")) if data_dir.exists() else []
    return {
        "revision": "ed956dea41521fc4499acbc63f966e0fd3c053ba",
        "manifest_sha256": _sha256(data_dir.parent / "manifest.json")
        if (data_dir.parent / "manifest.json").exists() else None,
        "adapted_case_count": len(files),
        "adapted_cases_sha256": _json_digest(
            [(p.name, _sha256(p)) for p in files]
        ),
    }


def _effective_config(
    args: argparse.Namespace,
    dataset: dict[str, Any],
    personamem: dict[str, Any],
    qa_plan: dict[str, list[str]],
) -> dict[str, Any]:
    return {
        "fingerprint_schema": FINGERPRINT_SCHEMA,
        "dataset": dataset,
        "personamem": personamem,
        "tracks": args.tracks,
        "scenario_range": {
            "start_index": args.conversations_from,
            "count": args.conversations,
        },
        "retrieval_mode": args.mode,
        "pack_mode": args.pack_mode,
        "consolidation_mode": args.consolidation,
        "answer_model": {
            "base_url": _safe_endpoint(args.llm_base_url),
            "model": args.llm_model,
            "reasoning_effort": args.llm_reasoning_effort,
        },
        "judge_model": args.judge_model,
        "memory_backend": _memory_backend_identity(args),
        "embedding_model": {
            "base_url": _safe_endpoint(args.embedding_base_url),
            "model": args.embedding_model,
        },
        "qa_sample_per_category": args.qa_sample,
        "qa_sampling_scope": "per_category_across_selected_scenarios",
        "selected_qa_ids": qa_plan,
        "max_answer_tokens": args.max_answer_tokens,
        "max_judge_tokens": args.max_judge_tokens,
        "budget": {
            "max_model_calls": args.max_calls,
            "max_runtime_seconds": args.max_runtime_seconds,
        },
        "seed": args.seed,
        "prompt_versions": {"answer": ANSWER_PROMPT_VERSION, "judge": JUDGE_PROMPT_VERSION},
        "report_schema": REPORT_SCHEMA,
        "code_fingerprint": _code_fingerprint(),
    }


def _check_resume(workdir: Path, fingerprint: str, *, resume: bool) -> dict[str, Any]:
    path = workdir / "meta.json"
    if not path.exists():
        if resume:
            raise ValueError("--resume requires a B04 memory-eval-resume/2 meta.json")
        if workdir.exists() and any(workdir.iterdir()):
            raise ValueError("workdir is not empty; use --resume with a matching fingerprint or choose a new directory")
        return {
            "schema": FINGERPRINT_SCHEMA,
            "fingerprint": fingerprint,
            "created_at": _utcnow(),
            "inserted_sessions": {},
            "backend_roles": {},
            "capture_gates": {},
        }
    if not resume:
        raise ValueError("workdir already contains a run; pass --resume to validate its fingerprint")
    meta = json.loads(path.read_text(encoding="utf-8"))
    if meta.get("schema") != FINGERPRINT_SCHEMA:
        raise ValueError("legacy/unversioned memory_eval checkpoint is read-only; start a new workdir")
    if meta.get("fingerprint") != fingerprint:
        raise ValueError("resume fingerprint mismatch; start a new workdir")
    if not isinstance(meta.get("inserted_sessions"), dict):
        raise ValueError("resume checkpoint has invalid inserted_sessions")
    meta.setdefault("backend_roles", {})
    meta.setdefault("capture_gates", {})
    return meta


def _save_meta(workdir: Path, meta: dict[str, Any]) -> None:
    path = workdir / "meta.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_qa_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("qid"):
            out.append(row)
    return out


def _append_qa_result(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _batch_thresholds() -> dict[str, int]:
    import mneme.consolidator as module

    names = (
        "CONSOLIDATION_LOCAL_BATCH_SIZE",
        "CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE",
        "CONSOLIDATION_ONLINE_BATCH_SIZE",
        "CONSOLIDATION_ONLINE_FORCE_BATCH_SIZE",
    )
    return {name: int(getattr(module, name)) for name in names}


def _wrap_consolidator(cons: Any, budget: RunBudget) -> tuple[dict[str, Any], dict[str, Any]]:
    descriptors: dict[str, Any] = {}
    cons._backends = [
        (name, BudgetedBackend(backend, budget, f"consolidation:{name}"))
        for name, backend in cons._backends
    ]
    for name, backend in cons._backends:
        descriptors[name] = _backend_descriptor(backend)
    if cons._extract_backend is not None:
        name, backend = cons._extract_backend
        cons._extract_backend = (name, BudgetedBackend(backend, budget, f"extract:{name}"))
        descriptors[name] = _backend_descriptor(cons._extract_backend[1])
    return cons, descriptors


async def _ensure_capture_gate_open(
    env: Any,
    root: Path,
    key: str,
    meta: dict[str, Any],
    budget: RunBudget,
) -> dict[str, Any]:
    """Use the real default probe to renew the lease before fixture ingress."""
    while not env.capture_gate.capture_allowed():
        budget.reserve("capture_gate_probe")
        gate_open = await asyncio.wait_for(
            env.open_capture_gate(), timeout=max(0.1, budget.remaining_seconds)
        )
        snapshot = env.capture_gate.status_snapshot()
        snapshot["probe_source"] = "production CaptureGate default backend probe"
        snapshot["renewal_policy"] = "explicit_before_fixture_session_ingress"
        prior = meta.setdefault("capture_gates", {}).get(key) or {}
        history = list(prior.get("probe_history") or [])
        history.append({
            "state": snapshot.get("state"),
            "allowed": bool(gate_open),
            "last_probe_at": snapshot.get("last_probe_at"),
            "last_success_at": snapshot.get("last_success_at"),
            "error_category": snapshot.get("error_category"),
        })
        snapshot["probe_count"] = len(history)
        snapshot["probe_history"] = history
        meta.setdefault("capture_gates", {})[key] = snapshot
        _save_meta(root, meta)
        if gate_open:
            return snapshot

        retry_delay = max(0.0, float(snapshot.get("next_retry_in_seconds") or 0.0))
        if retry_delay >= budget.remaining_seconds and retry_delay > 0:
            raise BudgetExceededError("runtime budget cannot reach the next CaptureGate retry")
        if retry_delay > 0:
            await asyncio.sleep(retry_delay)
        budget.check_time()

    return env.capture_gate.status_snapshot()


async def _run_personamem(data_dir: Path, budget: RunBudget) -> dict[str, Any]:
    budget.check_time()
    from mneme.benchmark import run_benchmark

    metrics = run_benchmark(data_dir, retrieval_mode="rule")
    dimensions = metrics.get("dimensions") or {}
    return {
        "dataset": "bowen-upenn/PersonaMem-v2",
        "revision": "ed956dea41521fc4499acbc63f966e0fd3c053ba",
        "evaluation_contract": "Stella static memory retrieval adapter; not original task accuracy",
        "retrieval_mode": "rule",
        "cases_total": metrics.get("cases_total"),
        "cases_ok": metrics.get("cases_ok"),
        "cases_ok_rate": metrics.get("cases_ok_rate"),
        "forbidden_activation_rate": metrics.get("forbidden_activation_rate"),
        "cross_scope_leak_rate": (dimensions.get("scope_privacy") or {}).get("cross_scope_leak_rate"),
        "topic_metrics": metrics.get("topic_metrics"),
        "model_calls": 0,
    }


async def _run_track(
    args: argparse.Namespace,
    scenario: dict[str, Any],
    track: str,
    root: Path,
    meta: dict[str, Any],
    budget: RunBudget,
    qa_llm: BudgetedEvalLLM | None,
    judge_llm: BudgetedEvalLLM | None,
    selected_qa: list[dict[str, Any]],
) -> dict[str, Any]:
    from memory_eval.answer import answer_question
    from memory_eval.judge import build_judge_prompt, parse_verdict
    from memory_eval.metrics import aggregate_qa

    sid = str(scenario["scenario_id"])
    env_dir = root / track / sid
    env_dir.mkdir(parents=True, exist_ok=True)
    key = f"{track}/{sid}"
    inserted = int(meta["inserted_sessions"].get(key, 0))
    qa_path = env_dir / "qa_results.jsonl"
    mode = "controlled" if track == "controlled" else "production_equivalent"
    gate_result: dict[str, Any] | None = None
    backend_roles: dict[str, Any] = {}
    bypass_flags = (
        ["direct_group_messages_insert", "capture_gate_omitted", "batch_constants_overridden", "force_consolidation"]
        if track == "controlled" else []
    )

    env_context = ReplayEnv(env_dir, scenario) if track == "controlled" else ProductionReplayEnv(env_dir, scenario)
    with env_context.session():
        env = env_context
        expected_sessions = len(scenario.get("sessions") or [])
        if args.stage == "qa" and inserted < expected_sessions:
            raise RuntimeError(
                f"QA requires completed ingestion for {track}/{sid}: "
                f"{inserted}/{expected_sessions} sessions"
            )

        if track == "production" and (
            args.stage not in ("ingest", "all") or inserted >= expected_sessions
        ):
            gate_result = meta.get("capture_gates", {}).get(key) or {
                "state": "checkpointed", "allowed": True,
                "probe_source": "prior matching run",
            }

        if args.stage in ("ingest", "all") and inserted < len(scenario.get("sessions") or []):
            if track == "controlled" and args.consolidation == "oracle":
                from memory_eval.oracle import OracleConsolidationBackend

                cons = env.build_consolidator(fake_backend=OracleConsolidationBackend())
                backend_roles = {"consolidation": _backend_descriptor(cons._backends[0][1])}
            else:
                cons = env.build_consolidator(live=True)
                cons, backend_roles = _wrap_consolidator(cons, budget)
            meta["backend_roles"][key] = backend_roles
            _save_meta(root, meta)

            sessions = scenario["sessions"]
            for session in sessions[inserted:]:
                if track == "production":
                    gate_result = await _ensure_capture_gate_open(
                        env, root, key, meta, budget
                    )
                wall_before = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                if track == "controlled":
                    env.set_batch_size(len(session.get("messages") or []))
                    env.insert_sessions([session])
                    await cons.consolidate_group(int(scenario["group_id"]), force=True)
                    env.backdate_new_rows(str(session["ts"]), wall_before)
                else:
                    await env.record_fixture_session(session)
                    await cons.consolidate_group(int(scenario["group_id"]), force=False)
                inserted += 1
                meta["inserted_sessions"][key] = inserted
                _save_meta(root, meta)

        if args.stage in ("qa", "all") and inserted < expected_sessions:
            raise RuntimeError(
                f"QA requires completed ingestion for {track}/{sid}: "
                f"{inserted}/{expected_sessions} sessions"
            )

        if track == "production":
            thresholds = _batch_thresholds()
            bypass_flags = []
            counts = env.admission_capture_summary()
        else:
            thresholds = None
            counts = {"admission": None, "capture": None}
        funnel = env.funnel()
        lineage = build_lineage(env.db_path)

        qa_results = _load_qa_results(qa_path)
        embedding_service = None
        if args.mode in ("embedding", "hybrid"):
            embedding_service = BudgetedEmbeddingService(
                args.embedding_base_url, args.embedding_model, budget
            )
        if args.stage in ("qa", "all"):
            if qa_llm is None or judge_llm is None:
                raise RuntimeError("QA stage requires answer/judge clients")
            done = {str(row["qid"]) for row in qa_results}
            qa_items = selected_qa
            for qa in qa_items:
                if str(qa["qid"]) in done:
                    continue
                before_embedding = (
                    embedding_service.summary() if embedding_service is not None else None
                )
                record = await answer_question(
                    env, scenario, qa,
                    channel=args.mode,
                    llm=qa_llm,
                    service=embedding_service,
                    pack_mode=None if args.pack_mode == "auto" else args.pack_mode,
                )
                if embedding_service is not None and embedding_service.budget_exhausted:
                    raise BudgetExceededError("B04 embedding call budget exhausted")
                if embedding_service is not None:
                    after_embedding = embedding_service.summary()
                    record["embedding_api_calls"] = (
                        after_embedding["api_calls"] - before_embedding["api_calls"]
                    )
                    record["embedding_api_failures"] = (
                        after_embedding["api_failures"] - before_embedding["api_failures"]
                    )
                    record["embedding_similarity_requests"] = (
                        after_embedding["similarity_requests"]
                        - before_embedding["similarity_requests"]
                    )
                judge_raw = judge_llm.chat(
                    build_judge_prompt(
                        qa["question"], qa.get("gold_answer"), record["answer"],
                        adversarial_answer=qa.get("adversarial_answer"),
                    ),
                    max_tokens=2048,
                    temperature=0.0,
                )
                verdict = parse_verdict(judge_raw["text"])
                alignment = retrieval_source_alignment(
                    lineage,
                    [str(value) for value in record.get("retrieved_ids") or []],
                    [str(value) for value in qa.get("evidence_dia_ids") or []],
                )
                saved = {
                    "qid": str(qa["qid"]),
                    "category": qa.get("category"),
                    "category_name": qa.get("category_name"),
                    "gold_answer": qa.get("gold_answer"),
                    "evidence_dia_ids": qa.get("evidence_dia_ids") or [],
                    "verdict": verdict["verdict"],
                    "retrieved_ids": [str(value) for value in record.get("retrieved_ids") or []],
                    "pack_memory_count": record.get("pack_memory_count"),
                    "pack_chars": record.get("pack_chars"),
                    "retrieval_latency_seconds": record.get("retrieval_latency_seconds"),
                    "answer_latency_seconds": record.get("answer_latency_seconds"),
                    "answer_prompt_tokens": record.get("answer_prompt_tokens"),
                    "answer_completion_tokens": record.get("answer_completion_tokens"),
                    "source_alignment": alignment,
                    "embedding_api_calls": record.get("embedding_api_calls"),
                    "embedding_api_failures": record.get("embedding_api_failures"),
                    "embedding_similarity_requests": record.get(
                        "embedding_similarity_requests"
                    ),
                }
                _append_qa_result(qa_path, saved)
                qa_results.append(saved)
                done.add(str(qa["qid"]))

        return {
            "track": track,
            "mode": mode,
            "scenario_id": sid,
            "funnel": funnel,
            "capture_gate": gate_result,
            "admission_capture_counts": counts,
            "batch_thresholds": thresholds,
            "bypass_flags": bypass_flags,
            "backend_roles": backend_roles,
            "inserted_sessions": inserted,
            "expected_sessions": len(scenario.get("sessions") or []),
            "source_lineage": lineage,
            "embedding": (
                embedding_service.summary()
                if embedding_service is not None else {"requested": False}
            ),
            "qa_total": len(qa_results),
            "qa_aggregate": aggregate_qa(qa_results) if qa_results else {},
            "qa_results": qa_results,
        }


async def run(args: argparse.Namespace) -> int:
    workdir = args.workdir.resolve()
    if not workdir.is_absolute():
        raise ValueError("workdir must resolve to an absolute path")
    if workdir == Path.cwd().resolve():
        raise ValueError("workdir cannot be the repository root")
    if args.qa_sample < 0:
        raise ValueError("qa_sample must be zero (full QA) or a positive per-category sample")
    if args.max_answer_tokens < 1 or args.max_judge_tokens < 1:
        raise ValueError("answer and judge token caps must be at least 1")
    if args.max_calls < 1 or args.max_runtime_seconds < 1:
        raise ValueError("max_calls and max_runtime_seconds must be at least 1")
    if args.mode in ("embedding", "hybrid"):
        if not args.embedding_base_url or not args.embedding_model:
            raise ValueError(
                "embedding/hybrid requires explicit --embedding-base-url and --embedding-model"
            )
        if urlsplit(args.embedding_base_url).path.rstrip("/").endswith("/v1"):
            raise ValueError("embedding-base-url must omit the /v1 path suffix")
    data_dir = args.data_dir.resolve()
    scenarios = _select_scenarios(
        load_scenarios(data_dir), count=args.conversations, start=args.conversations_from
    )
    if not scenarios:
        raise ValueError("no LoCoMo scenarios selected")

    personamem_dir = args.personamem_dir.resolve()
    dataset = _dataset_identity(data_dir, scenarios)
    personamem_identity = _personamem_identity(personamem_dir)
    qa_plan = _select_qa_plan(scenarios, args.qa_sample, args.seed)
    qa_ids = {sid: [str(qa["qid"]) for qa in rows] for sid, rows in qa_plan.items()}
    effective = _effective_config(args, dataset, personamem_identity, qa_ids)
    fingerprint = _json_digest(effective)
    meta = _check_resume(workdir, fingerprint, resume=args.resume)
    workdir.mkdir(parents=True, exist_ok=True)

    ensure_eval_home(workdir)
    _apply_memory_backend_overrides(_memory_backend_overrides(args))

    budget = RunBudget(args.max_calls, args.max_runtime_seconds)
    qa_llm = judge_llm = None
    if args.stage in ("qa", "all"):
        from memory_eval.llm import EvalLLM

        inner = EvalLLM(args.llm_base_url, args.llm_model, args.llm_api_key,
                        timeout=float(args.max_runtime_seconds))
        if not args.llm_model:
            _ = inner.model
        qa_llm = BudgetedEvalLLM(inner, budget, "answer", args.max_answer_tokens,
                                 reasoning_effort=args.llm_reasoning_effort)
        if args.judge_model and args.judge_model != inner.model:
            judge_inner = EvalLLM(args.llm_base_url, args.judge_model, args.llm_api_key,
                                  timeout=float(args.max_runtime_seconds))
        else:
            judge_inner = inner
        judge_llm = BudgetedEvalLLM(judge_inner, budget, "judge", args.max_judge_tokens,
                                    reasoning_effort=args.llm_reasoning_effort)

    tracks = ["controlled", "production"] if args.tracks == "both" else [args.tracks]
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    try:
        for scenario in scenarios:
            for track in tracks:
                try:
                    budget.check_time()
                    result = await _run_track(
                        args,
                        scenario,
                        track,
                        workdir,
                        meta,
                        budget,
                        qa_llm,
                        judge_llm,
                        qa_plan[str(scenario["scenario_id"])],
                    )
                except Exception as exc:
                    errors.append({
                        "scenario_id": str(scenario["scenario_id"]),
                        "track": track,
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:300],
                    })
                    break
                results.append(result)
            if errors:
                break
    finally:
        _save_meta(workdir, meta)

    try:
        personamem = await _run_personamem(personamem_dir, budget) if personamem_dir.exists() else {
        "status": "skipped_data_missing", "model_calls": 0
        }
    except BudgetExceededError as exc:
        errors.append({
            "scenario_id": "personamem-static-adapter",
            "track": "dataset",
            "error_type": type(exc).__name__,
            "message": str(exc)[:300],
        })
        personamem = {"status": "skipped_budget_exhausted", "model_calls": 0}
    except Exception as exc:
        errors.append({
            "scenario_id": "personamem-static-adapter",
            "track": "dataset",
            "error_type": type(exc).__name__,
            "message": str(exc)[:300],
        })
        personamem = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "model_calls": 0,
        }
    report = {
        "report_schema": REPORT_SCHEMA,
        "generated_at": _utcnow(),
        "git_head": _git_head(),
        "run_fingerprint": fingerprint,
        "fingerprint_inputs": effective,
        "stage": args.stage,
        "status": "NOT_READY" if errors else "MEASURED_IN_SCOPE",
        "errors": errors,
        "budget": {
            "max_model_calls": budget.max_calls,
            "model_calls_reserved": len(budget.calls),
            "model_calls_by_role": _count_by_role(budget.calls),
            "truncated_generations": budget.truncated_generations,
            "truncated_generations_by_role": _count_by_role(budget.truncated_generations),
            "max_runtime_seconds": budget.max_seconds,
            "elapsed_seconds": round(budget.elapsed, 3),
        },
        "answer_model": qa_llm.cost_summary() if qa_llm is not None else None,
        "judge_model": judge_llm.cost_summary() if judge_llm is not None else None,
        "datasets": {
            "locomo": dataset,
            "personamem": {**personamem_identity, **personamem},
        },
        "tracks": results,
        "limitations": [
            "LoCoMo is English-domain external reference; it is not Stella Chinese-persona acceptance.",
            "Controlled track directly inserts rows, omits CaptureGate, overrides batch thresholds, and forces consolidation.",
            "Production-equivalent rows use the real admission policy, CaptureGate default probe, record_message writer, and unmodified batch thresholds.",
            "CaptureGate leases are renewed explicitly before each fixture-session ingress; the autonomous background probe worker is not run by this offline replay.",
            "Dataset timestamps are retained in transport events; production group_messages use wall-clock write time.",
            "Exact memory-to-source ancestry is reported; semantic answer support stays ALIGNMENT_UNRESOLVED without adjudication.",
            "PersonaMem score uses Stella's static retrieval adapter, not the original benchmark task accuracy.",
        ],
    }
    out_dir = (args.out or (workdir / "report")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "memory_eval_b04_report.json"
    md_path = out_dir / "memory_eval_b04_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_report(report), encoding="utf-8")
    print(f"B04 report: {json_path}")
    print(f"B04 summary: {md_path}")
    return 1 if errors else 0


def _count_by_role(calls: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for call in calls:
        counts[call["role"]] = counts.get(call["role"], 0) + 1
    return counts


def _select_qa_plan(
    scenarios: list[dict[str, Any]], sample_per_category: int, seed: int
) -> dict[str, list[dict[str, Any]]]:
    """Deterministically sample each category across all selected smoke scenes."""
    import random

    rows = [
        (scenario_index, str(scenario["scenario_id"]), qa)
        for scenario_index, scenario in enumerate(scenarios)
        for qa in scenario.get("qa") or []
    ]
    if sample_per_category == 0:
        picked = rows
    else:
        by_category: dict[int, list[tuple[int, str, dict[str, Any]]]] = {}
        for row in rows:
            by_category.setdefault(int(row[2].get("category") or 0), []).append(row)
        rng = random.Random(seed)
        picked = []
        for category in sorted(by_category):
            bucket = by_category[category]
            bucket.sort(key=lambda row: (row[0], str(row[2].get("qid") or "")))
            if len(bucket) <= sample_per_category:
                picked.extend(bucket)
            else:
                indices = sorted(rng.sample(range(len(bucket)), sample_per_category))
                picked.extend(bucket[index] for index in indices)
    plan: dict[str, list[dict[str, Any]]] = {
        str(scenario["scenario_id"]): [] for scenario in scenarios
    }
    for _, scenario_id, qa in sorted(
        picked, key=lambda row: (row[0], str(row[2].get("qid") or ""))
    ):
        plan[scenario_id].append(qa)
    return plan


def _select_scenarios(
    scenarios: list[dict[str, Any]], count: int, start: int
) -> list[dict[str, Any]]:
    if count < 1 or start < 1:
        raise ValueError("conversation count and start index must be at least 1")
    return scenarios[start - 1 : start - 1 + count]


def _render_report(report: dict[str, Any]) -> str:
    lines = [
        "# B04 双轨记忆评测摘要 / B04 Dual-Track Memory Evaluation",
        "",
        f"- Status: **{report['status']}**",
        f"- Run fingerprint: `{report['run_fingerprint']}`",
        f"- Model calls: {report['budget']['model_calls_reserved']} / {report['budget']['max_model_calls']}",
        f"- Calls by role: `{json.dumps(report['budget']['model_calls_by_role'], ensure_ascii=False)}`",
        f"- Runtime: {report['budget']['elapsed_seconds']} / {report['budget']['max_runtime_seconds']} s",
        "",
        "## LoCoMo tracks",
        "",
        "| Track | Scenario | Sessions | Sources | Candidates | Evidence | QA | Accuracy |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for track in report.get("tracks") or []:
        lineage = track.get("source_lineage") or {}
        counts = lineage.get("counts") or {}
        aggregate = track.get("qa_aggregate") or {}
        lines.append(
            f"| {track.get('mode')} | {track.get('scenario_id')} | "
            f"{track.get('inserted_sessions')}/{track.get('expected_sessions')} | "
            f"{counts.get('sources')} | {counts.get('candidates')} | "
            f"{counts.get('evidence_rows')} | {track.get('qa_total')} | {aggregate.get('accuracy')}% |"
        )
        lines.append(
            f"  - bypass flags: `{', '.join(track.get('bypass_flags') or []) or 'none'}`; "
            f"backend roles: `{json.dumps(track.get('backend_roles') or {}, ensure_ascii=False)}`"
        )
        lines.append(
            f"  - embedding: `{json.dumps(track.get('embedding') or {}, ensure_ascii=False)}`"
        )
    persona = report.get("datasets", {}).get("personamem", {})
    lines += [
        "",
        "## PersonaMem static retrieval adapter",
        "",
        f"- Cases: {persona.get('cases_total')} / `cases_ok_rate={persona.get('cases_ok_rate')}`",
        f"- Forbidden activation: {persona.get('forbidden_activation_rate')}; "
        f"cross-scope leak: {persona.get('cross_scope_leak_rate')}",
        "- This is Stella's retrieval adapter metric, not original PersonaMem task accuracy.",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in report.get("limitations") or [])
    if report.get("errors"):
        lines += ["", "## Errors", ""]
        lines.extend(
            f"- {row['scenario_id']} / {row['track']}: {row['error_type']}: {row['message']}"
            for row in report["errors"]
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="B04 dual-track memory benchmark")
    parser.add_argument("--data-dir", type=Path, default=Path("memory/benchmark/_public/locomo/adapted"))
    parser.add_argument("--personamem-dir", type=Path, default=Path("memory/benchmark/_public/personamem/adapted"))
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--stage", choices=("ingest", "qa", "all"), default="all")
    parser.add_argument("--tracks", choices=("controlled", "production", "both"), default="both")
    parser.add_argument("--conversations", type=int, default=2)
    parser.add_argument("--conversations-from", type=int, default=1)
    parser.add_argument(
        "--qa-sample", type=int, default=1,
        help="per category across all selected conversations; 0 means full QA",
    )
    parser.add_argument("--max-answer-tokens", type=int, default=512)
    parser.add_argument("--max-judge-tokens", type=int, default=128)
    parser.add_argument("--max-consolidation-tokens", type=int, default=1200)
    parser.add_argument("--max-extract-tokens", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261104)
    parser.add_argument("--mode", choices=("rule", "embedding", "fts", "hybrid"), default="rule")
    parser.add_argument("--embedding-base-url", default=None,
                        help="explicit base URL without /v1; required for embedding/hybrid")
    parser.add_argument("--embedding-model", default=None,
                        help="explicit embedding model ID; required for embedding/hybrid")
    parser.add_argument("--pack-mode", choices=("auto", "casual", "tech", "conflict"), default="auto")
    parser.add_argument("--consolidation", choices=("live", "oracle"), default="oracle",
                        help="controlled track backend; production track always uses backend_for")
    parser.add_argument("--llm-base-url", default="http://127.0.0.1:1234/v1")
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--llm-api-key", default="")
    parser.add_argument(
        "--llm-reasoning-effort", default="none",
        help="answer/judge request reasoning effort; 'none' keeps the eval protocol "
        "deterministic on thinking engines (Strata request field, ignored elsewhere)",
    )
    parser.add_argument("--memory-base-url", default="http://127.0.0.1:1234/v1")
    parser.add_argument("--memory-model", default="qwen/qwen3.8-27b")
    parser.add_argument("--memory-kind", choices=("local", "online"), default="local")
    parser.add_argument("--memory-api-key", default="")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_CALL_BUDGET)
    parser.add_argument("--max-runtime-seconds", type=int, default=DEFAULT_RUNTIME_SECONDS)
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(run(args))
    except Exception as exc:
        print(f"B04 failed closed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

