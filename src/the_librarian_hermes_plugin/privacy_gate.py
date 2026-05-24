"""The ``pre_gateway_dispatch`` privacy gate.

Hermes' ``pre_gateway_dispatch`` hook fires before auth and dispatch — the
synchronous, pre-agent point where off-record detection must happen so the
provider's later hooks (prefetch/sync_turn) see the right privacy state.

The gate detects a privacy marker / toggle in the incoming message and drives
the provider's privacy transition (which flips local state and ends the attached
session on going private). It does NOT block the message — privacy means "no
Librarian call", not "stop the model", and recording suppression is enforced by
the provider reading the off-record flag. So the gate returns ``None`` (allow).

The exact ``pre_gateway_dispatch`` payload shape is to be confirmed against a
real Hermes install; ``message_text`` extracts defensively from a str or the
common dict keys.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from .privacy import detect_privacy_signal


class PrivacyController(Protocol):
    def enter_private(self) -> str: ...
    def exit_private(self) -> str: ...
    def toggle_privacy(self) -> str: ...


def message_text(payload: Any) -> str:
    """Pull the user text from a pre_gateway_dispatch payload (str or dict)."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("content", "text", "message", "prompt"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    return ""


def make_privacy_gate(controller: PrivacyController) -> Callable[[Any], None]:
    """Build the ``pre_gateway_dispatch`` callback bound to a provider."""

    def gate(payload: Any) -> None:
        signal = detect_privacy_signal(message_text(payload)).signal
        if signal == "enter-private":
            controller.enter_private()
        elif signal == "exit-private":
            controller.exit_private()
        elif signal == "toggle":
            controller.toggle_privacy()
        # Always allow the message through (return None). The privacy effect is the
        # state flip + session end above; recording is suppressed by the provider.
        return None

    return gate
