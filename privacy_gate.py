"""The ``pre_gateway_dispatch`` privacy gate.

Hermes' ``pre_gateway_dispatch`` hook fires before auth and dispatch — the
synchronous, pre-agent point where off-record detection must happen so the
provider's later hooks (prefetch/sync_turn) see the right privacy state.

The gate detects a privacy marker / toggle in the incoming message and drives
the provider's privacy transition (which flips local state and ends the attached
session on going private). It does NOT block the message — privacy means "no
Librarian call", not "stop the model", and recording suppression is enforced by
the provider reading the off-record flag. So the gate returns ``None`` (allow).

Hermes invokes the hook as
``invoke_hook("pre_gateway_dispatch", event=<MessageEvent>, gateway=..., session_store=...)``
and dispatches each callback as ``cb(**kwargs)`` — i.e. by **keyword**, with
``event`` a ``MessageEvent`` dataclass carrying ``.text`` (see ``gateway/run.py``
and ``hermes_cli/plugins.py:invoke_hook``). The callback may return an action
dict (``{"action": "skip"|"rewrite"|"allow"}``); ``None`` means allow. The gate
accepts keyword args (and ignores unknown ones via ``**_``) so it can never raise
on the calling convention. ``message_text`` reads ``event.text`` and still
tolerates a str / dict so the detector is unit-testable without a MessageEvent.
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
    """Pull the user text from a pre_gateway_dispatch payload.

    Hermes passes a ``MessageEvent`` (has ``.text``); the str / dict branches keep
    the detector unit-testable and tolerate adapters that pass a raw message.
    """
    text = getattr(payload, "text", None)
    if isinstance(text, str):
        return text
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("content", "text", "message", "prompt"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    return ""


def make_privacy_gate(controller: PrivacyController) -> Callable[..., None]:
    """Build the ``pre_gateway_dispatch`` callback bound to a provider.

    Hermes calls this by keyword (``event=...`` plus ``gateway``/``session_store``);
    the signature accepts those and swallows any other kwargs so a contract change
    never turns the gate into a per-turn ``TypeError``.
    """

    def gate(*, event: Any = None, **_: Any) -> None:
        signal = detect_privacy_signal(message_text(event)).signal
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
