# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Transport-neutral media references for outbound messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

MediaKind = Literal["image", "file"]


@dataclass(frozen=True, slots=True)
class MediaSource:
    """A media location understood by the selected adapter.

    ``uri`` can be an HTTPS URL, a local path, or an adapter-supported data URI.
    It stays process-local when used by a send; callers must not put credentials
    or short-lived signed URLs into durable delivery targets.
    """

    kind: MediaKind
    uri: str = field(repr=False)
    name: str = ""
    mime_type: str = ""
    fallback_text: str = ""

    def __post_init__(self) -> None:
        if self.kind not in {"image", "file"}:
            raise ValueError("media kind must be image or file")
        if not isinstance(self.uri, str) or not self.uri:
            raise ValueError("media uri must be a non-empty string")
        for name in ("name", "mime_type", "fallback_text"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be a string")
