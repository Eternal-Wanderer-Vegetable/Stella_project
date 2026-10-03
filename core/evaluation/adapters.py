# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""评测适配器（计划 §6.7.2/§6.7.3）：LLM 桩、embedding 查表、假发送器、路径沙箱。

纪律（计划 §6.7.2）：「生成器/插件/工具在评测中通过允许的 fake adapter；
生产 QQ sender 不可导入执行」——本模块所有适配器零网络、零真实副作用：

- :class:`FixtureModel`：按脚本次序返回预设回复的 LLM 桩，逐次记录调用；
- :class:`FixtureEmbedder`：查表向量桩，miss 返回零向量（embedding 离线）；
- :class:`FakeSender`：``send_one`` 恒返回 ``"simulated_ack"``，只记录不发送；
- :class:`ExperimentPaths`：实验目录合同，全部路径 resolve 后强制在 root 之下
  （防 ``..``/绝对路径逃逸，计划 §6.7.3「sandbox 绝对路径校验」）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ExperimentPaths",
    "FakeSender",
    "FixtureEmbedder",
    "FixtureModel",
    "PathEscapeError",
    "resolve_under",
]

SIMULATED_ACK = "simulated_ack"


class PathEscapeError(ValueError):
    """路径逃逸：解析结果不在实验 root 之下，一律拒绝。"""


def resolve_under(root: Path, candidate: Path | str) -> Path:
    """把 ``candidate`` 解析为绝对路径并强制约束在 ``root`` 之下。

    ``..`` 上跳、越界绝对路径都直接抛 :class:`PathEscapeError`——评测的
    每一个状态路径都必须留在沙箱内（计划 §6.7.2/§6.7.3）。
    """
    root_resolved = Path(root).resolve()
    candidate_path = Path(candidate)
    if not candidate_path.is_absolute():
        candidate_path = root_resolved / candidate_path
    resolved = candidate_path.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        msg = f"路径逃逸被拒绝: {resolved} 不在实验 root {root_resolved} 之下"
        raise PathEscapeError(msg) from None
    return resolved


@dataclass(frozen=True)
class ExperimentPaths:
    """一次实验的全部状态目录（计划 §6.7.2「每个实验一个工作目录」）。

    ``db/cache/logs/artifacts`` 在构造时全部 resolve 并校验在 ``root`` 之下；
    反序列化外部配置后调用 :meth:`validate` 重校验，防止伪造路径越界。
    """

    root: Path
    db: Path
    cache: Path
    logs: Path
    artifacts: Path

    @classmethod
    def create(cls, root: Path | str) -> "ExperimentPaths":
        """按 ``root`` 布局实验目录（缺目录就地创建）。"""
        root_resolved = Path(root).resolve()
        paths = cls(
            root=root_resolved,
            db=resolve_under(root_resolved, "db"),
            cache=resolve_under(root_resolved, "cache"),
            logs=resolve_under(root_resolved, "logs"),
            artifacts=resolve_under(root_resolved, "artifacts"),
        )
        for directory in (paths.root, paths.db, paths.cache, paths.logs, paths.artifacts):
            directory.mkdir(parents=True, exist_ok=True)
        return paths

    def child(self, name: Path | str) -> Path:
        """在 root 下解析子路径（任何逃逸抛 :class:`PathEscapeError`）。"""
        return resolve_under(self.root, name)

    def validate(self) -> None:
        """重校验全部路径仍在 root 之下（worker 从磁盘读回配置后必须调用）。"""
        for field_name in ("root", "db", "cache", "logs", "artifacts"):
            value = Path(getattr(self, field_name)).resolve()
            try:
                value.relative_to(self.root)
            except ValueError:
                msg = f"实验路径 {field_name}={value} 逃逸出 root {self.root}"
                raise PathEscapeError(msg) from None


class FixtureModel:
    """按脚本次序返回预设回复的 LLM 桩：零网络、零随机、逐次记录调用。

    脚本耗尽抛 :class:`FixtureExhaustedError`——静默循环复用会掩盖「回复
    条数与触发次数不匹配」这类真实缺陷，评测必须显式暴露。
    """

    def __init__(self, replies: Sequence[str]):
        self._replies = [str(r) for r in replies]
        self._cursor = 0
        self.calls: list[dict] = []

    @property
    def calls_made(self) -> int:
        """已消耗的模型调用数（预算账本直接读这里）。"""
        return len(self.calls)

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """返回脚本中的下一条预设回复；prompt 只记摘要（不落原文）。"""
        if self._cursor >= len(self._replies):
            msg = "FixtureModel 回复脚本已耗尽（触发次数超过预设脚本长度）"
            raise FixtureExhaustedError(msg)
        reply = self._replies[self._cursor]
        self.calls.append(
            {
                "index": self._cursor,
                "prompt_sha1": hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16],
                "system_sha1": hashlib.sha1(system.encode("utf-8")).hexdigest()[:16]
                if system
                else "",
                "reply": reply,
            }
        )
        self._cursor += 1
        return reply

    async def agenerate(self, prompt: str, *, system: str | None = None) -> str:
        """异步包装（与生产 async LLM 客户端调用形态一致）。"""
        return self.generate(prompt, system=system)


class FixtureExhaustedError(RuntimeError):
    """FixtureModel 脚本耗尽：评测样本与预设回复数不匹配。"""


class ModelEndpointError(RuntimeError):
    """真实模型端点调用失败（网络/超时/非 2xx/空回复）。"""


class RealEndpointModel:
    """真实模型端点适配器（计划 §6.7.2 ``model_validation`` 模式）。

    OpenAI 兼容 ``/v1/chat/completions``；endpoint 只来自显式配置
    （``STELLA_EVAL_MODEL_ENDPOINT``），绝无生产默认回退。零重试——
    评测要如实暴露失败，静默重试会污染分布；失败由 runner 按样本丢弃
    并计入 ``model_execution`` 维度。预算账本与 :class:`FixtureModel`
    同形（``calls_made``）。
    """

    def __init__(
        self,
        endpoint: str,
        *,
        timeout: float = 120.0,
        max_tokens: int = 512,  # 思考型模型的 reasoning 也计入 token 预算
        model: str | None = None,
    ):
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout
        self._max_tokens = max_tokens
        self._model = model
        self.calls: list[dict] = []

    @property
    def calls_made(self) -> int:
        return len(self.calls)

    def _resolve_model(self) -> str:
        if self._model:
            return self._model
        import json as _json
        import urllib.request

        with urllib.request.urlopen(
            f"{self._endpoint}/v1/models", timeout=self._timeout
        ) as resp:
            payload = _json.loads(resp.read().decode("utf-8"))
        models = payload.get("data") or []
        if not models:
            raise ModelEndpointError("endpoint /v1/models 返回空模型列表")
        self._model = str(models[0]["id"])
        return self._model

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        import json as _json
        import time as _time
        import urllib.request

        model = self._resolve_model()
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = _json.dumps(
            {
                "model": model,
                "messages": messages,
                "max_tokens": self._max_tokens,
                "temperature": 0.0,  # 评测口径：贪心解码；重复分布另行多轮
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self._endpoint}/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = _time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = _json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            self.calls.append(
                {
                    "index": len(self.calls),
                    "prompt_sha1": hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16],
                    "reply": "",
                    "error": f"{type(exc).__name__}: {exc}"[:200],
                    "latency_ms": round((_time.monotonic() - started) * 1000, 1),
                }
            )
            raise ModelEndpointError(f"{type(exc).__name__}: {exc}") from exc
        reply = str(
            ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")
            or ""
        ).strip()
        self.calls.append(
            {
                "index": len(self.calls),
                "prompt_sha1": hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16],
                "reply": reply,
                "latency_ms": round((_time.monotonic() - started) * 1000, 1),
            }
        )
        if not reply:
            raise ModelEndpointError("端点返回空回复")
        return reply


class FixtureEmbedder:
    """查表向量桩：命中原样返回表内向量，miss 返回零向量；零网络。

    维度取表内首条向量长度（构造时显式给定则强制一致）；零向量与任何向量
    的余弦恒为 0（memory.embeddings.cosine_similarity 已兜底除零），语义
    通道在评测里退化为「无信息但不报错」。
    """

    def __init__(
        self,
        table: Mapping[str, Sequence[float]] | None = None,
        *,
        dimension: int | None = None,
    ):
        self._table: dict[str, list[float]] = {k: [float(x) for x in v] for k, v in (table or {}).items()}
        first = next(iter(self._table.values()), None)
        resolved = dimension if dimension is not None else (len(first) if first else 8)
        if resolved <= 0:
            raise ValueError("FixtureEmbedder 维度必须为正数")
        for key, vec in self._table.items():
            if len(vec) != resolved:
                msg = f"FixtureEmbedder 向量维度不一致: {key} 有 {len(vec)} 维，期望 {resolved}"
                raise ValueError(msg)
        self._dimension: int = resolved
        self.lookups = 0
        self.hits = 0

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        """查表返回向量；miss 返回零向量。"""
        self.lookups += 1
        vec = self._table.get(text)
        if vec is None:
            return [0.0] * self._dimension
        self.hits += 1
        return list(vec)

    async def aembed(self, text: str) -> list[float]:
        """异步包装（与 memory.embeddings.EmbeddingService.embed 同形）。"""
        return self.embed(text)

    def as_embedding_service(self) -> "_FixtureEmbeddingService":
        """包装成 ``EmbeddingService`` 形状（``await svc.embed(text)``），
        供 ParticipationManager 的注入点直接使用。"""
        return _FixtureEmbeddingService(self)


class _FixtureEmbeddingService:
    """``memory.embeddings.EmbeddingService`` 的查表替身（duck typing）。"""

    def __init__(self, embedder: FixtureEmbedder):
        self._embedder = embedder

    async def embed(self, text: str) -> list[float] | None:
        return self._embedder.embed(text)


class FakeSender:
    """假发送器：``send_one(line, i)`` 恒返回 ``"simulated_ack"``。

    只把调用追加进 ``sent`` 记录，绝不触网、绝不 import 任何真实 QQ sender
    （计划 §6.7.2：isolated_pipeline 结果合同「simulated_ack 明确」）。
    """

    def __init__(self):
        self.sent: list[dict] = []

    @property
    def ack(self) -> str:
        return SIMULATED_ACK

    @property
    def sends_made(self) -> int:
        return len(self.sent)

    def send_one(self, line: str, i: int) -> str:
        """记录一次发送并返回固定回执 ``"simulated_ack"``。"""
        self.sent.append({"line": line, "i": i, "seq": len(self.sent)})
        return SIMULATED_ACK

    async def asend_one(self, line: str, i: int) -> str:
        """异步包装（与生产 sender 的 async 形态一致）。"""
        return self.send_one(line, i)
