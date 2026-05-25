"""Hermes in-session slash commands for The Librarian.

Hermes slash commands are registered programmatically via
``ctx.register_command(name, handler, description, args_hint)`` (NOT markdown
files like Claude Code). Each handler has the signature ``fn(raw_args: str) ->
str | None`` and runs in both CLI and gateway sessions. They are only wired when
the plugin is loaded as a *general* plugin (``hermes plugins enable librarian``);
``hermes memory setup`` alone wires the provider but not these commands.

Every handler routes through the provider, which is privacy-gated (no Librarian
call while off-record) and fail-soft (a store outage degrades to a short message,
never an exception). The ``resume`` command can't run the interactive pick that
Claude Code offers — a ``fn(raw_args)`` handler is non-interactive — so it lists
sessions when called bare and resumes a specific id when given one.
"""

from __future__ import annotations

from typing import Any

from .provider import LibrarianProvider

_PRIVATE_MSG = "🔒 Off the record — Librarian recording is paused."
_PUBLIC_MSG = "🟢 On the record — Librarian recording resumed."


def _pop_flag(raw: str, flag: str) -> tuple[bool, str]:
    """Remove *flag* from *raw* if present; return ``(was_present, remainder)``."""
    tokens = (raw or "").split()
    if flag in tokens:
        tokens = [t for t in tokens if t != flag]
        return True, " ".join(tokens).strip()
    return False, (raw or "").strip()


def register_commands(ctx: Any, provider: LibrarianProvider) -> None:
    """Register the ``/lib-session-*`` + ``/lib-toggle-private`` slash commands.

    No-op if *ctx* has no ``register_command`` (e.g. the memory-provider loader's
    collector, which only keeps the provider), so this is safe on every loader.
    """
    register = getattr(ctx, "register_command", None)
    if register is None:
        return

    def start(raw_args: str = "") -> str:
        private, title = _pop_flag(raw_args, "--private")
        if private:
            provider.enter_private()
            return _PRIVATE_MSG
        session_id = provider.start_new_session(title or None)
        if session_id is None:
            return "Could not start a Librarian session (off the record or unavailable)."
        return f"Started Librarian session {session_id}" + (f" — {title}" if title else "") + "."

    def list_sessions(raw_args: str = "") -> str:
        include_ended, _ = _pop_flag(raw_args, "--include-ended")
        return provider.run_tool("list_sessions", {"include_ended": include_ended})

    def resume(raw_args: str = "") -> str:
        ident = (raw_args or "").strip()
        if not ident:
            listing = provider.run_tool("list_sessions", {"include_ended": True})
            return f"{listing}\n\nResume one with: /lib-session-resume <session_id>"
        text = provider.run_tool("continue_session", {"session_id": ident, "attach": True})
        provider.attach_session_id(ident)
        return text

    def checkpoint(raw_args: str = "") -> str:
        session_id = provider.current_session_id()
        if session_id is None:
            return "No attached Librarian session to checkpoint."
        args: dict[str, Any] = {"session_id": session_id}
        if raw_args.strip():
            args["summary"] = raw_args.strip()
        return provider.run_tool("checkpoint_session", args)

    def pause(raw_args: str = "") -> str:
        session_id = provider.current_session_id()
        if session_id is None:
            return "No attached Librarian session to pause."
        text = provider.run_tool("pause_session", {"session_id": session_id})
        provider.detach()
        return text

    def end(raw_args: str = "") -> str:
        session_id = provider.current_session_id()
        if session_id is None:
            return "No attached Librarian session to end."
        args: dict[str, Any] = {"session_id": session_id}
        if raw_args.strip():
            args["summary"] = raw_args.strip()
        text = provider.run_tool("end_session", args)
        provider.detach()
        return text

    def search(raw_args: str = "") -> str:
        query = (raw_args or "").strip()
        if not query:
            return "Usage: /lib-session-search <query>"
        return provider.run_tool("search_sessions", {"query": query})

    def toggle_private(raw_args: str = "") -> str:
        return _PRIVATE_MSG if provider.toggle_privacy() == "private" else _PUBLIC_MSG

    commands = (
        ("lib-session-start", start, "Start a new Librarian session", "[title] [--private]"),
        (
            "lib-session-list",
            list_sessions,
            "List resumable Librarian sessions",
            "[--include-ended]",
        ),
        (
            "lib-session-resume",
            resume,
            "Resume a Librarian session (fetch handover + attach)",
            "<session_id>",
        ),
        ("lib-session-checkpoint", checkpoint, "Checkpoint the attached session", "[summary]"),
        ("lib-session-pause", pause, "Pause the attached session", ""),
        ("lib-session-end", end, "End the attached session", "[summary]"),
        ("lib-session-search", search, "Search Librarian sessions by content", "<query>"),
        ("lib-toggle-private", toggle_private, "Toggle off-record (private) mode", ""),
    )
    for name, handler, description, args_hint in commands:
        register(name, handler, description=description, args_hint=args_hint)
