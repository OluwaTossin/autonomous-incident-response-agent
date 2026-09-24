"""Minimal queue transport ports used by dispatch and worker orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class QueueMessage:
    body: str
    receipt_handle: str
    message_id: str | None = None
    receive_count: int | None = None


class QueuePublisher(Protocol):
    def send(self, message: str) -> str | None: ...

    def send_batch(self, messages: tuple[str, ...]) -> tuple[str | None, ...]: ...


class QueueConsumer(Protocol):
    def receive(
        self,
        *,
        max_messages: int,
        wait_time_seconds: int,
        visibility_timeout: int,
    ) -> tuple[QueueMessage, ...]: ...

    def delete(self, message: QueueMessage) -> None: ...

    def change_visibility(self, message: QueueMessage, timeout_seconds: int) -> None: ...
