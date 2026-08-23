# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""PersonaManager（`context.persona_manager`）。

**只读，且只暴露插件专属的那一个人格。**

刻意不暴露 Stella 的空间人格（`system_prompts/*.md`）：那是 Stella 的身份，
泄漏进插件就等于让插件用 Stella 的语气说话，用户会分不清谁在说话。那些文件也由
安装器 GUI 拥有，不该让插件读写。
"""

from __future__ import annotations

from typing import Any

from .exceptions import StellaCompatNotSupported
from .po import Personality

PLUGIN_PERSONA_ID = "plugin_default"


def _plugin_prompt() -> str:
    # 读 config.settings 的属性而不是 `from config import X`——后者在 import 时绑死，
    # 运行期改配置（含测试 monkeypatch）不生效。
    try:
        from config import settings

        return settings.ASTRBOT_LLM_SYSTEM_PROMPT
    except Exception:
        return ""


def _build_persona() -> Personality:
    return Personality(
        name=PLUGIN_PERSONA_ID,
        prompt=_plugin_prompt(),
        begin_dialogs=[],
        mood_imitation_dialogs=[],
        tools=None,
        skills=None,
        custom_error_message=None,
        _begin_dialogs_processed=[],
        _mood_imitation_dialogs_processed="",
    )


class PersonaManager:
    """只读人格管理器。写操作一律抛 NotSupported。"""

    def __init__(self) -> None:
        self.default_persona = PLUGIN_PERSONA_ID

    @property
    def personas_v3(self) -> list[Personality]:
        return [_build_persona()]

    @property
    def selected_default_persona_v3(self) -> Personality:
        return _build_persona()

    @property
    def persona_v3_config(self) -> list[dict]:
        return [dict(_build_persona())]

    async def initialize(self) -> None:
        """无需初始化，保留形状。"""

    def get_persona_v3_by_id(self, persona_id: str | None) -> Personality | None:
        if persona_id in (None, "", PLUGIN_PERSONA_ID):
            return _build_persona()
        return None

    async def get_default_persona_v3(self, umo: Any = None) -> Personality:
        _ = umo
        return _build_persona()

    async def get_persona(self, persona_id: str) -> Personality:
        persona = self.get_persona_v3_by_id(persona_id)
        if persona is None:
            raise ValueError(f"Persona {persona_id} not found")
        return persona

    async def get_all_personas(self) -> list[Personality]:
        return [_build_persona()]

    def get_v3_persona_data(self) -> tuple[list[dict], list[Personality], Personality]:
        persona = _build_persona()
        return [dict(persona)], [persona], persona

    async def resolve_selected_persona(
        self,
        *,
        umo: Any,
        conversation_persona_id: str | None = None,
        platform_name: str = "",
        provider_settings: dict | None = None,
    ) -> tuple[str | None, Personality | None, str | None, bool]:
        _ = (umo, conversation_persona_id, platform_name, provider_settings)
        return PLUGIN_PERSONA_ID, _build_persona(), None, False

    # ---------- 写操作：不开放 ----------

    async def create_persona(self, *args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        raise StellaCompatNotSupported("PersonaManager.create_persona（人格由 Stella 管理，插件只读）")

    async def update_persona(self, *args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        raise StellaCompatNotSupported("PersonaManager.update_persona（人格由 Stella 管理，插件只读）")

    async def delete_persona(self, *args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        raise StellaCompatNotSupported("PersonaManager.delete_persona（人格由 Stella 管理，插件只读）")


_manager: PersonaManager | None = None


def get_persona_manager() -> PersonaManager:
    global _manager
    if _manager is None:
        _manager = PersonaManager()
    return _manager


__all__ = ["PLUGIN_PERSONA_ID", "PersonaManager", "get_persona_manager"]
