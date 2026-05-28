"""Hermes in-session slash commands for The Librarian.

Hermes slash commands are registered programmatically via
``ctx.register_command(name, handler, description, args_hint)``. Each handler
has the signature ``fn(raw_args: str) -> str | None``. They are only wired when
the plugin is loaded as a *general* plugin (``hermes plugins enable librarian``);
``hermes memory setup`` alone wires the provider but not these commands.

sessions-rethink PR 5 — the seven ``/lib-session-*`` verbs and
``/lib-toggle-private`` are retired and replaced by four user-facing verbs:

- ``/handoff`` — author a five-section narrative and persist via
  ``store_handoff`` for cross-harness pickup.
- ``/takeover`` — list candidate handoffs, atomically claim one,
  inject the document into the conversation.
- ``/learn`` — extract durable lessons from the conversation and feed
  them to ``propose_memory``.
- ``/toggle-private`` — flip the in-conversation
  ``[librarian:private=on|off]`` marker. Pure in-context — no server
  flag, no hook, no persisted state. The LLM honours the marker on its
  own.

A Hermes ``fn(raw_args)`` handler is non-interactive, so ``/handoff``
and ``/learn`` here surface the prompts that drive the LLM rather than
running the multi-step flow themselves. The LLM, having read the
``librarian`` skill block, then performs the actual MCP calls.
"""

from __future__ import annotations

from typing import Any

from .provider import LibrarianProvider

_HANDOFF_PROMPT = (
    "Author a five-section handoff document (Start & intent / Journey / "
    "Current state / What's left / Open questions), then call "
    "`store_handoff` with the document. See the librarian skill for the "
    "full template."
)

_TAKEOVER_PROMPT = (
    "Call `list_handoffs` with the current project_key + cwd, present "
    "candidates to the user, then `claim_handoff` on selection and inject "
    "the returned document_md as system context. See the librarian skill."
)

_LEARN_PROMPT = (
    "Extract durable lessons from this conversation and feed user-approved "
    "ones to `propose_memory`. See the librarian skill for the rejection "
    "criteria and confirmation contract."
)

_TOGGLE_ON = (
    "Private mode is ON. `[librarian:private=on]` — do not call `remember` "
    "or `propose_memory` until told otherwise. Recall is still allowed. "
    "/handoff and /learn require explicit user confirmation. Remain in this "
    "state until explicitly toggled off."
)

_TOGGLE_OFF = "Private mode is OFF. `[librarian:private=off]` — normal operation resumed."


def register_commands(ctx: Any, provider: LibrarianProvider) -> None:
    """Register the four user-facing slash commands.

    No-op if *ctx* has no ``register_command`` (e.g. the memory-provider
    loader's collector, which only keeps the provider).
    """
    del provider  # the four verbs are agent operations; no provider plumbing
    register = getattr(ctx, "register_command", None)
    if register is None:
        return

    def handoff(_raw_args: str = "") -> str:
        return _HANDOFF_PROMPT

    def takeover(_raw_args: str = "") -> str:
        return _TAKEOVER_PROMPT

    def learn(_raw_args: str = "") -> str:
        return _LEARN_PROMPT

    def toggle_private(_raw_args: str = "") -> str:
        # The toggle is pure in-conversation — we can't observe the prior
        # state from a non-interactive handler, so emit both markers in a
        # single message and rely on the LLM to read its own most-recent
        # state out of the transcript and pick the right one. This is
        # spec §6.5: the marker carries both the machine token and the
        # human-readable instruction, and the LLM owns the toggle.
        return (
            "Toggle in-conversation private mode. Inject the inverse of the "
            "most recent `[librarian:private=on|off]` marker. If ON: emit "
            f"`{_TOGGLE_ON}`. If OFF or no marker: emit `{_TOGGLE_OFF}`."
        )

    commands = (
        (
            "handoff",
            handoff,
            "Author and persist a cross-harness handoff document",
            "",
        ),
        (
            "takeover",
            takeover,
            "Pick up a handoff from another agent / harness",
            "",
        ),
        (
            "learn",
            learn,
            "Extract durable lessons from this conversation into memory proposals",
            "",
        ),
        (
            "toggle-private",
            toggle_private,
            "Toggle in-conversation private mode (no server state, no hook)",
            "",
        ),
    )
    for name, handler, description, args_hint in commands:
        register(name, handler, description=description, args_hint=args_hint)
