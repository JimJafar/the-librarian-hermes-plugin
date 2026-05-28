"""Slash-command tests — sessions-rethink PR 5 surface.

The seven ``/lib-session-*`` verbs and ``/lib-toggle-private`` are retired
and replaced by four user-facing verbs that surface prompts the LLM
follows (the actual MCP calls are agent operations).
"""

from __future__ import annotations

from typing import Any

from librarian.commands import register_commands
from librarian.provider import LibrarianProvider


class FakeCtx:
    def __init__(self) -> None:
        self.commands: dict[str, dict[str, Any]] = {}

    def register_command(
        self, name: str, handler: Any, *, description: str, args_hint: str
    ) -> None:
        self.commands[name] = {
            "handler": handler,
            "description": description,
            "args_hint": args_hint,
        }


def _registered() -> FakeCtx:
    ctx = FakeCtx()
    register_commands(ctx, LibrarianProvider())
    return ctx


def test_registers_exactly_four_verbs() -> None:
    ctx = _registered()
    assert set(ctx.commands.keys()) == {"handoff", "takeover", "learn", "toggle-private"}


def test_handoff_surfaces_the_five_section_template_prompt() -> None:
    ctx = _registered()
    out = ctx.commands["handoff"]["handler"]("")
    assert "Start & intent" in out
    assert "store_handoff" in out


def test_takeover_surfaces_the_list_then_claim_prompt() -> None:
    ctx = _registered()
    out = ctx.commands["takeover"]["handler"]("")
    assert "list_handoffs" in out
    assert "claim_handoff" in out


def test_learn_surfaces_the_propose_memory_prompt() -> None:
    ctx = _registered()
    out = ctx.commands["learn"]["handler"]("")
    assert "propose_memory" in out


def test_toggle_private_emits_marker_template_instruction() -> None:
    ctx = _registered()
    out = ctx.commands["toggle-private"]["handler"]("")
    assert "[librarian:private=on]" in out
    assert "[librarian:private=off]" in out


def test_register_is_a_no_op_when_ctx_lacks_register_command() -> None:
    class Bare:
        pass

    register_commands(Bare(), LibrarianProvider())  # must not raise
