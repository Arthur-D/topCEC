# SPDX-License-Identifier: GPL-3.0-or-later
"""Structural interfaces for the monitor's Linux activity, media, and CEC providers."""
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ActivityProvider(Protocol):
    def seed(self, device: Any) -> dict[int, Any]: ...

    def event_activity(self, state: dict[str, Any], event: Any,
                       focused: bool) -> str | None: ...


@runtime_checkable
class MediaProvider(Protocol):
    def decode_scan(self, output: str, errors: str, returncode: int) -> list[dict[str, Any]]: ...

    def audio_state(self, frames: list[dict[str, Any]], mapping: Any,
                    now: float, target_output: str) -> tuple[bool, bool]: ...


@runtime_checkable
class CecBackend(Protocol):
    @property
    def fault(self) -> str | None: ...

    @property
    def pending(self) -> str | None: ...

    @property
    def process(self) -> Any | None: ...

    def request(self, action: str) -> None: ...

    def activity(self, wake_requested: bool = False) -> None: ...

    def poll(self) -> None: ...

    def close(self) -> None: ...
