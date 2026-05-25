"""Slash-command tests — argument parsing, MCP mapping, attach/detach, privacy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from librarian.commands import register_commands
from librarian.provider import LibrarianConfig, LibrarianProvider
from librarian.state import StateStore

SESSION = "sess-1"


class FakeClient:
    def __init__(self, responses: dict[str, str] | None = None):
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._responses = responses or {}

    def call_tool(self, name: str, arguments: dict[str, object]) -> str:
        self.calls.append((name, dict(arguments)))
        return self._responses.get(name, "ok")

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]


class CommandCtx:
    def __init__(self) -> None:
        self.commands: dict[str, Any] = {}

    def register_command(self, name: str, handler: Any, **kwargs: Any) -> None:
        self.commands[name] = handler


def _provider(tmp_path: Path, client: FakeClient) -> LibrarianProvider:
    cfg = LibrarianConfig(endpoint="https://x/mcp", token="t", agent_id="h")
    p = LibrarianProvider(client=client, config=cfg)
    p.initialize(SESSION, hermes_home=str(tmp_path))
    return p


def _setup(tmp_path: Path, client: FakeClient) -> tuple[LibrarianProvider, dict[str, Any]]:
    p = _provider(tmp_path, client)
    ctx = CommandCtx()
    register_commands(ctx, p)
    return p, ctx.commands


def test_all_eight_commands_registered(tmp_path: Path) -> None:
    _, cmds = _setup(tmp_path, FakeClient())
    assert set(cmds) == {
        "lib-session-start",
        "lib-session-list",
        "lib-session-resume",
        "lib-session-checkpoint",
        "lib-session-pause",
        "lib-session-end",
        "lib-session-search",
        "lib-toggle-private",
    }


def test_start_creates_and_attaches(tmp_path: Path) -> None:
    client = FakeClient({"start_session": "ses_new"})
    _, cmds = _setup(tmp_path, client)
    out = cmds["lib-session-start"]("my title")
    assert "ses_new" in out
    assert client.names() == ["start_session"]
    assert StateStore(str(tmp_path)).load().librarian_session_id == "ses_new"


def test_start_private_goes_off_record_without_calling(tmp_path: Path) -> None:
    client = FakeClient()
    _, cmds = _setup(tmp_path, client)
    out = cmds["lib-session-start"]("--private")
    assert "Off the record" in out
    assert StateStore(str(tmp_path)).load().privacy == "private"
    assert client.calls == []


def test_list_passes_include_ended_flag(tmp_path: Path) -> None:
    client = FakeClient({"list_sessions": "the list"})
    _, cmds = _setup(tmp_path, client)
    assert cmds["lib-session-list"]("") == "the list"
    assert client.calls[0][1]["include_ended"] is False
    client.calls.clear()
    cmds["lib-session-list"]("--include-ended")
    assert client.calls[0][1]["include_ended"] is True


def test_resume_with_id_continues_and_attaches(tmp_path: Path) -> None:
    client = FakeClient({"continue_session": "handover text"})
    _, cmds = _setup(tmp_path, client)
    out = cmds["lib-session-resume"]("ses_xyz")
    assert out == "handover text"
    name, args = client.calls[0]
    assert name == "continue_session"
    assert args["session_id"] == "ses_xyz"
    assert args["attach"] is True
    assert StateStore(str(tmp_path)).load().librarian_session_id == "ses_xyz"


def test_resume_bare_lists_sessions(tmp_path: Path) -> None:
    client = FakeClient({"list_sessions": "session list"})
    _, cmds = _setup(tmp_path, client)
    out = cmds["lib-session-resume"]("")
    assert "session list" in out
    assert client.names() == ["list_sessions"]


def test_checkpoint_without_session_makes_no_call(tmp_path: Path) -> None:
    client = FakeClient()
    _, cmds = _setup(tmp_path, client)
    assert "No attached" in cmds["lib-session-checkpoint"]("")
    assert client.calls == []


def test_pause_detaches(tmp_path: Path) -> None:
    client = FakeClient()
    p, cmds = _setup(tmp_path, client)
    p.attach_session_id("ses_a")
    cmds["lib-session-pause"]("")
    assert "pause_session" in client.names()
    assert StateStore(str(tmp_path)).load().librarian_session_id is None


def test_end_with_summary_detaches(tmp_path: Path) -> None:
    client = FakeClient()
    p, cmds = _setup(tmp_path, client)
    p.attach_session_id("ses_a")
    cmds["lib-session-end"]("wrapped up")
    name, args = next(c for c in client.calls if c[0] == "end_session")
    assert args["session_id"] == "ses_a"
    assert args["summary"] == "wrapped up"
    assert StateStore(str(tmp_path)).load().librarian_session_id is None


def test_search_requires_a_query(tmp_path: Path) -> None:
    client = FakeClient()
    _, cmds = _setup(tmp_path, client)
    assert "Usage" in cmds["lib-session-search"]("")
    assert client.calls == []


def test_search_runs(tmp_path: Path) -> None:
    client = FakeClient({"search_sessions": "results"})
    _, cmds = _setup(tmp_path, client)
    assert cmds["lib-session-search"]("auth bug") == "results"
    name, args = client.calls[0]
    assert name == "search_sessions"
    assert args["query"] == "auth bug"


def test_toggle_private_flips_both_ways(tmp_path: Path) -> None:
    client = FakeClient()
    _, cmds = _setup(tmp_path, client)
    assert "Off the record" in cmds["lib-toggle-private"]("")
    assert StateStore(str(tmp_path)).load().privacy == "private"
    assert "On the record" in cmds["lib-toggle-private"]("")
    assert StateStore(str(tmp_path)).load().privacy == "public"


def test_commands_suppressed_while_private(tmp_path: Path) -> None:
    client = FakeClient({"list_sessions": "x"})
    p, cmds = _setup(tmp_path, client)
    p.enter_private()
    out = cmds["lib-session-list"]("")
    assert "Off the record" in out
    assert "list_sessions" not in client.names()
