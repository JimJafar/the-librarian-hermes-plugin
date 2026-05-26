"""Provider mapping tests — off-record gating, fail-soft, hook→MCP mapping."""

from __future__ import annotations

import json
from pathlib import Path

from librarian.client import LibrarianClientError
from librarian.provider import (
    LibrarianConfig,
    LibrarianProvider,
    _extract_session_id,
    load_config,
    save_config,
)
from librarian.state import PluginState, StateError, StateStore

SESSION = "sess-1"


class FakeClient:
    def __init__(self, responses: dict[str, str] | None = None, fail: set[str] | None = None):
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._responses = responses or {}
        self._fail = fail or set()

    def call_tool(self, name: str, arguments: dict[str, object]) -> str:
        self.calls.append((name, dict(arguments)))
        if name in self._fail:
            raise LibrarianClientError("network", f"{name} down")
        return self._responses.get(name, "ok")

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]


def _provider(tmp_path: Path, client: FakeClient, *, config: LibrarianConfig | None = None):
    cfg = config or LibrarianConfig(
        endpoint="https://x/mcp", token="t", agent_id="hermes", project_key="proj"
    )
    p = LibrarianProvider(client=client, config=cfg)
    p.initialize(SESSION, hermes_home=str(tmp_path))
    return p


def _go_private(tmp_path: Path) -> None:
    StateStore(str(tmp_path)).save(PluginState(privacy="private"))


def test_initialize_makes_no_librarian_call(tmp_path: Path) -> None:
    client = FakeClient()
    _provider(tmp_path, client)
    assert client.calls == []


def test_prefetch_recalls_and_injects_agent_scope(tmp_path: Path) -> None:
    client = FakeClient({"recall": "recalled text"})
    p = _provider(tmp_path, client)
    assert p.prefetch("auth bug") == "recalled text"
    name, args = client.calls[0]
    assert name == "recall"
    assert args["query"] == "auth bug"
    assert args["agent_id"] == "hermes"
    assert args["project_key"] == "proj"


def test_system_prompt_block_uses_start_context(tmp_path: Path) -> None:
    client = FakeClient({"start_context": "frozen snapshot"})
    p = _provider(tmp_path, client)
    assert p.system_prompt_block() == "frozen snapshot"
    assert client.names() == ["start_context"]


def test_sync_turn_starts_session_then_records(tmp_path: Path) -> None:
    client = FakeClient({"start_session": "Session started: ses_abc"})
    p = _provider(tmp_path, client)
    p.sync_turn("hello", "hi there")
    assert client.names() == ["start_session", "record_session_event"]
    _, rec_args = client.calls[1]
    assert rec_args["session_id"] == "ses_abc"
    assert rec_args["type"] == "turn"


def test_session_is_started_once_then_reused(tmp_path: Path) -> None:
    client = FakeClient({"start_session": "ses_abc"})
    p = _provider(tmp_path, client)
    p.sync_turn("a", "b")
    p.sync_turn("c", "d")
    assert client.names().count("start_session") == 1
    assert client.names().count("record_session_event") == 2


def test_pre_compress_checkpoints_only_with_a_session(tmp_path: Path) -> None:
    client = FakeClient({"start_session": "ses_abc"})
    p = _provider(tmp_path, client)
    p.on_pre_compress([])  # no session yet → no call
    assert client.calls == []
    p.sync_turn("a", "b")  # establishes ses_abc
    p.on_pre_compress([])
    assert "checkpoint_session" in client.names()


def test_session_end_pauses_and_detaches(tmp_path: Path) -> None:
    client = FakeClient({"start_session": "ses_abc"})
    p = _provider(tmp_path, client)
    p.sync_turn("a", "b")
    p.on_session_end([])
    assert "pause_session" in client.names()
    # Detached locally: the stored session id is cleared.
    assert StateStore(str(tmp_path)).load().librarian_session_id is None


def test_handle_tool_call_forwards_with_agent_scope(tmp_path: Path) -> None:
    client = FakeClient({"remember": "stored"})
    p = _provider(tmp_path, client)
    out = p.handle_tool_call("remember", {"title": "t", "body": "b"})
    assert out == "stored"
    _, args = client.calls[0]
    assert args["agent_id"] == "hermes"


def test_handle_tool_call_unknown_tool(tmp_path: Path) -> None:
    client = FakeClient()
    p = _provider(tmp_path, client)
    assert "Unknown" in p.handle_tool_call("delete_everything", {})
    assert client.calls == []


def test_on_memory_write_mirrors_add_only(tmp_path: Path) -> None:
    client = FakeClient()
    p = _provider(tmp_path, client)
    p.on_memory_write("add", "note title", "note body")
    assert client.names() == ["remember"]
    client.calls.clear()
    p.on_memory_write("replace", "x", "y")
    p.on_memory_write("remove", "x", "")
    assert client.calls == []


# ---- off-record gating ----


def test_private_suppresses_reads_and_writes(tmp_path: Path) -> None:
    client = FakeClient({"recall": "should not happen"})
    p = _provider(tmp_path, client)
    _go_private(tmp_path)
    assert p.prefetch("q") == ""
    assert p.system_prompt_block() == ""
    p.sync_turn("a", "b")
    p.on_pre_compress([])
    p.on_session_end([])
    p.on_memory_write("add", "t", "b")
    assert client.calls == []


def test_private_handle_tool_call_returns_off_record_message(tmp_path: Path) -> None:
    client = FakeClient()
    p = _provider(tmp_path, client)
    _go_private(tmp_path)
    out = p.handle_tool_call("remember", {"title": "t", "body": "b"})
    assert "Off the record" in out
    assert client.calls == []


# ---- fail-soft ----


def test_client_failure_degrades_recall_to_empty(tmp_path: Path) -> None:
    client = FakeClient(fail={"recall"})
    p = _provider(tmp_path, client)
    assert p.prefetch("q") == ""  # no raise


def test_sync_turn_swallows_client_failure(tmp_path: Path) -> None:
    client = FakeClient(fail={"start_session"})
    p = _provider(tmp_path, client)
    p.sync_turn("a", "b")  # must not raise
    assert client.names() == ["start_session"]  # never reached record


def test_unconfigured_provider_is_inert(tmp_path: Path) -> None:
    # env={} keeps is_available()'s lazy load from finding a real ~/.hermes on a
    # dev machine — we want to assert behaviour with NO config anywhere.
    p = LibrarianProvider(client=None, config=None, env={})
    p.initialize(SESSION, hermes_home=str(tmp_path))
    assert p.is_available() is False
    assert p.prefetch("q") == ""
    p.sync_turn("a", "b")  # no raise
    assert "unavailable" in p.handle_tool_call("recall", {"query": "q"}).lower()


def test_no_hermes_home_is_inert_and_private(tmp_path: Path) -> None:
    client = FakeClient()
    p = LibrarianProvider(client=client, config=LibrarianConfig(endpoint="https://x", token="t"))
    p.initialize(SESSION)  # no hermes_home
    assert p.prefetch("q") == ""
    assert client.calls == []


# ---- config ----


def test_save_config_omits_token_and_load_reads_from_env(tmp_path: Path) -> None:
    save_config(
        {"endpoint": "https://x/mcp", "token": "should-not-persist", "agent_id": "hermes"},
        str(tmp_path),
    )
    written = json.loads((tmp_path / "librarian-plugin" / "config.json").read_text())
    assert "token" not in written
    assert written["endpoint"] == "https://x/mcp"

    cfg = load_config(str(tmp_path), {"LIBRARIAN_AGENT_TOKEN": "from-env"})
    assert cfg is not None
    assert cfg.token == "from-env"
    assert cfg.endpoint == "https://x/mcp"
    assert cfg.agent_id == "hermes"


def test_load_config_none_when_unconfigured(tmp_path: Path) -> None:
    assert load_config(str(tmp_path), {}) is None  # no config file, no token
    save_config({"endpoint": "https://x"}, str(tmp_path))
    assert load_config(str(tmp_path), {}) is None  # endpoint but no token
    assert load_config(str(tmp_path), {"LIBRARIAN_AGENT_TOKEN": "t"}) is not None


def test_is_available_reflects_config(tmp_path: Path) -> None:
    assert LibrarianProvider(config=LibrarianConfig(endpoint="x", token="t")).is_available() is True
    # Lazy load points at an empty profile dir → no config.json, no token → not
    # available. (env={...HERMES_HOME...} keeps the test off any real ~/.hermes.)
    p = LibrarianProvider(config=None, env={"HERMES_HOME": str(tmp_path)})
    assert p.is_available() is False


def test_is_available_lazy_loads_from_hermes_home(tmp_path: Path) -> None:
    # The real fix for `hermes memory status` showing "not available": is_available
    # must resolve config from disk + env without requiring initialize() first.
    save_config({"endpoint": "https://x/mcp"}, str(tmp_path))
    p = LibrarianProvider(
        config=None,
        env={"HERMES_HOME": str(tmp_path), "LIBRARIAN_AGENT_TOKEN": "t"},
    )
    assert p.is_available() is True


def test_provider_name(tmp_path: Path) -> None:
    assert LibrarianProvider().name == "librarian"


# ---- fail-closed on unreadable state (must not raise out of any hook) ----


class _BrokenStore:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def load(self) -> PluginState:
        raise StateError("corrupt")

    def update(self, _mutate: object) -> PluginState:
        raise StateError("corrupt")

    def save(self, _state: object) -> None:
        raise StateError("corrupt")


def test_state_error_is_swallowed_by_every_hook(tmp_path: Path) -> None:
    client = FakeClient()
    cfg = LibrarianConfig(endpoint="https://x/mcp", token="t")
    p = LibrarianProvider(client=client, config=cfg, state_store_factory=_BrokenStore)
    p.initialize(SESSION, hermes_home=str(tmp_path))
    # Unreadable state → treated as private → no call, and nothing raises.
    assert p.prefetch("q") == ""
    assert p.system_prompt_block() == ""
    p.sync_turn("a", "b")
    p.on_pre_compress([])
    p.on_session_end([])
    p.on_memory_write("add", "t", "b")
    assert "Off the record" in p.handle_tool_call("recall", {"query": "q"})
    assert client.calls == []


def test_extract_session_id_boundaries() -> None:
    assert _extract_session_id("Session started: ses_abc123.") == "ses_abc123"
    assert _extract_session_id("created ses_abc.def now") == "ses_abc"
    assert _extract_session_id("nothing here") is None
    assert _extract_session_id("preses_abc") is None
