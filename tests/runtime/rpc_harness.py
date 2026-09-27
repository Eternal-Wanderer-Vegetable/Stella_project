# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""M3 RPC 测试基建：真实 Node host 子进程 + facade + 脚本化 Python LLM 后端。

链路完整性：测试经 facade.submit_turn →（stdio 协议）→ host → fork →
（provider.respond 回程）→ 脚本化后端 → finalize，无任何 Core mock。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from core.context import ChatContext
from core.llm.base import LLMBackend
from core.runtime.bridge import NodeBridge
from core.runtime.facade import RuntimeFacade, RuntimeStore
from core.runtime.turn_service import TurnService
from memory.post_processors import bad_phrase_filter, parse_output, split_lines

_PKG_DIR = Path(__file__).resolve().parent
# 单一来源：与 node_runtime/cortico 的测量/测试共用同一份冻结夹具配置
_FIXTURE_CONFIG = json.loads(
    (_PKG_DIR.parents[1] / "node_runtime" / "cortico" / "tests" / "fixtures" / "fixture-config.json")
    .read_text(encoding="utf-8")
)


class ScriptedBackend(LLMBackend):
    """脚本化后端：与 provider.respond 回程串联（记录每次收到的最终 prompt）。"""

    backend_name = "scripted-rpc"
    model = "scripted-model"

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.on_generate: Callable[[str], Awaitable[str]] | None = None

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self.prompts.append(prompt)
        if self.on_generate is not None:
            return await self.on_generate(prompt)
        return "<thought>好</thought><action>NONE</action><reply>脚本回复</reply>"


class RpcHarness:
    """一个 harness = 一个真实 Node host + facade + 脚本化后端。"""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.backend = ScriptedBackend()
        self.pipeline = TurnService(timeout=10.0)
        self.pipeline.set_llm_backend(self.backend)
        self.pipeline.register_post_hook(parse_output, priority=100)
        self.pipeline.register_post_hook(bad_phrase_filter, priority=80)
        self.pipeline.register_post_hook(split_lines, priority=60)
        self.store_path = tmp_path / "turns.jsonl"
        self.bridge = NodeBridge(
            host_config=_FIXTURE_CONFIG,
            data_root=tmp_path / "runtime-data",
            provider_handler=self._provider_respond,
        )
        self.facade = RuntimeFacade(self.bridge, store=RuntimeStore(self.store_path))
        self.provider_calls: list[str] = []
        self._provider_gate: dict[str, asyncio.Event] = {}
        self._provider_results: dict[str, str] = {}

    async def _provider_respond(self, params: dict[str, Any]) -> dict[str, Any]:
        from core.runtime.bridge import provider_prompt_text

        prompt = provider_prompt_text(params)
        self.provider_calls.append(prompt)
        key = str(params.get("key", ""))
        gate = self._provider_gate.get(key)
        if gate is not None:
            await asyncio.wait_for(gate.wait(), timeout=15.0)
        text = self._provider_results.get(key, "<thought>RPC</thought><action>NONE</action><reply>桥回复</reply>")
        return {"text": text}

    def hold_provider(self, key: str, *, result: str = "<reply>慢回复</reply>") -> asyncio.Event:
        """让指定 key 的下一次 provider.respond 挂起，直到测试放行。"""
        gate = asyncio.Event()
        self._provider_gate[key] = gate
        self._provider_results[key] = result
        return gate

    def release_provider(self, key: str) -> None:
        gate = self._provider_gate.pop(key, None)
        if gate is not None:
            gate.set()

    async def start(self) -> dict[str, Any]:
        return await self.facade.start()

    async def stop(self) -> None:
        for key in list(self._provider_gate):
            self.release_provider(key)
        await self.facade.stop()

    def ctx(self, message: str = "投影输入") -> ChatContext:
        return ChatContext(user_id=1001, group_id=1, msg_id=1, message=message)

    def store_lines(self) -> list[dict[str, Any]]:
        if not self.store_path.exists():
            return []
        return [json.loads(line) for line in self.store_path.read_text(encoding="utf-8").splitlines() if line.strip()]
