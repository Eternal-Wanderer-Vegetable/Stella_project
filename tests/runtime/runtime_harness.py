# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""运行时测试基建：facade + 脚本化 provider + 阶段服务管线（计划修订 v2）。

执行器为进程内 asyncio（无 Node/桥），链路完整性 = facade.submit_turn →
prepare（阶段服务）→ provider（脚本化）→ finalize（标准后置钩子）。
行为基准另见冻结 oracle（test_legacy_reference_traces.py）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from core.context import ChatContext
from core.llm.base import LLMBackend
from core.runtime.facade import RuntimeFacade, RuntimeStore
from core.runtime.turn_service import TurnService
from memory.post_processors import bad_phrase_filter, parse_output, split_lines

_DEFAULT_REPLY = "<thought>RPC</thought><action>NONE</action><reply>桥回复</reply>"


class ScriptedBackend(LLMBackend):
    """脚本化后端：记录每次收到的最终 prompt（BC-6 断言用）。"""

    backend_name = "scripted-native"
    model = "scripted-model"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self.prompts.append(prompt)
        return "<thought>好</thought><action>NONE</action><reply>脚本回复</reply>"


class RuntimeHarness:
    """一个 harness = 一个 facade + 阶段服务管线 + 可门控的脚本化 provider。"""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.backend = ScriptedBackend()
        self.pipeline = TurnService(timeout=10.0)
        self.pipeline.set_llm_backend(self.backend)
        self.pipeline.register_post_hook(parse_output, priority=100)
        self.pipeline.register_post_hook(bad_phrase_filter, priority=80)
        self.pipeline.register_post_hook(split_lines, priority=60)
        self.store_path = tmp_path / "turns.jsonl"
        self.provider_calls: list[str] = []
        self._gates: dict[str, asyncio.Event] = {}
        self._results: dict[str, str] = {}
        self.facade = RuntimeFacade(
            provider=self._provider,
            store=RuntimeStore(self.store_path),
        )

    async def _provider(self, key: str, prompt: str) -> str:
        self.provider_calls.append(prompt)
        gate = self._gates.get(key)
        if gate is not None:
            await asyncio.wait_for(gate.wait(), timeout=15.0)
        return self._results.get(key, _DEFAULT_REPLY)

    def hold_provider(self, key: str, *, result: str = "<reply>慢回复</reply>") -> asyncio.Event:
        """让指定 key 的下一次 provider 调用挂起，直到测试放行。"""
        gate = asyncio.Event()
        self._gates[key] = gate
        self._results[key] = result
        return gate

    def release_provider(self, key: str) -> None:
        gate = self._gates.pop(key, None)
        if gate is not None:
            gate.set()

    async def start(self) -> dict:
        return await self.facade.start()

    async def stop(self) -> None:
        for key in list(self._gates):
            self.release_provider(key)
        await self.facade.stop()

    def ctx(self, message: str = "投影输入") -> ChatContext:
        return ChatContext(user_id=1001, group_id=1, msg_id=1, message=message)

    def store_lines(self) -> list[dict]:
        if not self.store_path.exists():
            return []
        return [json.loads(line) for line in self.store_path.read_text(encoding="utf-8").splitlines() if line.strip()]
