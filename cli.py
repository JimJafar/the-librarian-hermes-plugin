"""One-time migration of Hermes' built-in memory into The Librarian.

Hermes' built-in memory lives in two markdown files under
``<hermes_home>/memories/``: ``MEMORY.md`` (agent notes) and ``USER.md`` (user
profile). Since the Librarian coexists with — but supersedes — the built-in, this
imports those facts into the Librarian and then empties the files so the built-in
stays minimal and the two don't drift.

Each non-empty, non-heading line becomes one memory (bullet markers stripped) —
MEMORY.md → ``lessons``, USER.md → ``relationship`` (the latter is a protected
category, so the Librarian routes it to a proposal for review, which is the right
default for user-profile facts). A file is emptied ONLY if every one of its
entries imported, so a partial failure never loses data.

``register_cli`` wires a ``hermes <name>`` subcommand via
``ctx.register_cli_command`` (a no-op if the loader's context lacks it, e.g. the
memory-provider collector); ``migrate`` (the testable core) is format-tolerant of
the built-in ``MEMORY.md``/``USER.md`` layout.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .client import LibrarianClient, LibrarianClientError
from .provider import load_config

_FILES = (("MEMORY.md", "lessons"), ("USER.md", "relationship"))
_MIN_ENTRY_CHARS = 3


class _ToolClient(Protocol):
    def call_tool(self, name: str, arguments: dict[str, Any]) -> str: ...


@dataclass
class MigrationResult:
    imported: int = 0
    failed: int = 0
    emptied: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"imported {self.imported}"]
        if self.failed:
            parts.append(f"{self.failed} failed")
        if self.emptied:
            parts.append(f"emptied {', '.join(self.emptied)}")
        if self.skipped_files:
            parts.append(f"left intact (errors): {', '.join(self.skipped_files)}")
        return "Librarian migration: " + "; ".join(parts) + "."


def _memories_dir(hermes_home: str) -> Path:
    return Path(hermes_home) / "memories"


def _parse_entries(path: Path) -> list[str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return []
    entries: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Strip a leading markdown bullet/numbered marker.
        for marker in ("- ", "* ", "+ "):
            if stripped.startswith(marker):
                stripped = stripped[len(marker) :].strip()
                break
        if len(stripped) >= _MIN_ENTRY_CHARS:
            entries.append(stripped)
    return entries


def _empty_file(path: Path) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_TRUNC)
    os.close(fd)


def migrate(
    hermes_home: str,
    client: _ToolClient,
    *,
    dry_run: bool = False,
    agent_id: str | None = None,
) -> MigrationResult:
    """Import built-in memory into the Librarian and empty the source files.

    A file is emptied only if all its entries imported (partial failure → file
    left intact so nothing is lost). ``dry_run`` counts without writing."""
    result = MigrationResult()
    for filename, category in _FILES:
        path = _memories_dir(hermes_home) / filename
        entries = _parse_entries(path)
        if not entries:
            continue
        file_failed = False
        for entry in entries:
            if dry_run:
                result.imported += 1
                continue
            args: dict[str, Any] = {"title": entry[:120], "body": entry, "category": category}
            if agent_id:
                args["agent_id"] = agent_id
            try:
                client.call_tool("remember", args)
                result.imported += 1
            except LibrarianClientError:
                result.failed += 1
                file_failed = True
        if dry_run:
            continue
        if file_failed:
            result.skipped_files.append(filename)
        else:
            _empty_file(path)
            result.emptied.append(filename)
    return result


def register_cli(ctx: Any) -> None:
    """Wire the ``hermes memory librarian-migrate`` subcommand (shape to-verify)."""

    def handler(_args: Any = None) -> str:
        hermes_home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
        config = load_config(hermes_home, dict(os.environ))
        if config is None:
            return "Librarian is not configured — run `hermes memory setup` first."
        client = LibrarianClient(config.endpoint, config.token, timeout_ms=config.timeout_ms)
        return migrate(hermes_home, client, agent_id=config.agent_id).summary()

    _register_command(ctx, handler)


def _register_command(ctx: Any, handler: Callable[..., str]) -> None:
    register = getattr(ctx, "register_cli_command", None)
    if register is None:
        return
    register(
        name="librarian-migrate",
        help="Import Hermes built-in memory (MEMORY.md/USER.md) into The Librarian.",
        setup_fn=lambda _parser: None,
        handler_fn=handler,
    )
