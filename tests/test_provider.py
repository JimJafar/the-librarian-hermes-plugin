"""Provider mapping tests — sessions-rethink PR 5 (memory-only surface).

Covers:
- recall / remember / verify_memory MCP tool mapping
- on_memory_write("add") mirrors to `remember`; other actions are no-ops
- prefetch + system_prompt_block prepend the canonical
  <conversation-state> block on conv_state_get hits
- prefetch + system_prompt_block stay silent on conv_state_get misses
- sync_turn, on_pre_compress, on_session_end are no-ops (no session
  surface anymore — they accept the ABC's call shape but contribute
  nothing)
"""

from __future__ import annotations

import json

from librarian.client import LibrarianClientError
from librarian.provider import LibrarianConfig, LibrarianProvider, load_config, save_config


class FakeClient:
    def __init__(
        self,
        responses: dict[str, str] | None = None,
        fail: set[str] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._responses = responses or {}
        self._fail = fail or set()

    def call_tool(self, name: str, arguments: dict[str, object]) -> str:
        self.calls.append((name, dict(arguments)))
        if name in self._fail:
            raise LibrarianClientError("network", f"{name} failed")
        return self._responses.get(name, "")


def _provider(client: FakeClient | None = None) -> LibrarianProvider:
    config = LibrarianConfig(
        endpoint="https://example/mcp", token="t", agent_id="agent-a"
    )
    p = LibrarianProvider(client=client or FakeClient(), config=config)
    p._session_id = "sess-1"  # the conv-state lookup uses this
    return p


def test_handle_tool_call_routes_recall_remember_verify() -> None:
    client = FakeClient({"recall": "results", "remember": "ok", "verify_memory": "noted"})
    p = _provider(client)

    assert p.handle_tool_call("recall", {"query": "x"}) == "results"
    assert p.handle_tool_call("remember", {"title": "t", "body": "b"}) == "ok"
    assert p.handle_tool_call("verify_memory", {"memory_id": "mem_1", "result": "useful"}) == "noted"

    # recall must auto-include ids so verify_memory has something to target.
    recall_call = next(c for c in client.calls if c[0] == "recall")
    assert recall_call[1].get("include_ids") is True
    # remember + recall carry the agent_id; verify_memory does not (it is keyed by memory_id).
    assert recall_call[1].get("agent_id") == "agent-a"
    remember_call = next(c for c in client.calls if c[0] == "remember")
    assert remember_call[1].get("agent_id") == "agent-a"
    verify_call = next(c for c in client.calls if c[0] == "verify_memory")
    assert "agent_id" not in verify_call[1]


def test_handle_tool_call_rejects_unknown_tools() -> None:
    p = _provider()
    assert "Unknown" in p.handle_tool_call("delete_everything", {})


def test_on_memory_write_mirrors_add_calls_only() -> None:
    client = FakeClient({"remember": "ok"})
    p = _provider(client)

    p.on_memory_write("add", "note title", "the body")
    assert client.calls[-1][0] == "remember"

    # Non-add actions are no-ops.
    client.calls.clear()
    p.on_memory_write("replace", "t", "b")
    p.on_memory_write("remove", "t", "")
    assert client.calls == []


def test_prefetch_prepends_conv_state_block_on_a_hit() -> None:
    row = json.dumps(
        {
            "conv_id": "hermes:sess-1",
            "domain": "coding",
            "session_id": "ses_1",
            "off_record": False,
        }
    )
    client = FakeClient({"conv_state_get": row, "recall": "recall body"})
    p = _provider(client)

    out = p.prefetch("how do I X")
    assert out.startswith("<conversation-state>")
    assert "domain: coding" in out
    assert "recall body" in out


def test_prefetch_returns_recall_only_when_conv_state_misses() -> None:
    client = FakeClient(
        {"conv_state_get": "No conversation state for conv_id hermes:sess-1.", "recall": "hits"}
    )
    p = _provider(client)
    assert p.prefetch("q") == "hits"


def test_prefetch_returns_empty_string_when_conv_state_throws() -> None:
    client = FakeClient({"recall": ""}, fail={"conv_state_get"})
    p = _provider(client)
    out = p.prefetch("q")
    assert out == ""


def test_system_prompt_block_prepends_conv_state_block_on_a_hit() -> None:
    row = json.dumps(
        {
            "conv_id": "hermes:sess-1",
            "domain": "general",
            "session_id": None,
            "off_record": False,
        }
    )
    client = FakeClient({"conv_state_get": row, "start_context": "context"})
    p = _provider(client)
    out = p.system_prompt_block()
    assert out.startswith("<conversation-state>")
    assert "session_id: none" in out
    assert "context" in out


def test_retired_lifecycle_methods_are_silent_no_ops() -> None:
    client = FakeClient()
    p = _provider(client)
    p.sync_turn("user", "assistant")
    assert p.on_pre_compress([]) == ""
    p.on_session_end([])
    p.on_session_switch("new-sess", reset=True)
    assert client.calls == []
    # The new session id is tracked so subsequent conv-state lookups
    # use the right conv_id even though no Librarian call fires here.
    assert p._session_id == "new-sess"


def test_load_and_save_config_round_trip(tmp_path: object) -> None:
    hermes_home = str(tmp_path)
    save_config({"endpoint": "https://e/mcp", "agent_id": "a1"}, hermes_home)
    cfg = load_config(hermes_home, {"LIBRARIAN_AGENT_TOKEN": "tok"})
    assert cfg is not None
    assert cfg.endpoint == "https://e/mcp"
    assert cfg.token == "tok"
    assert cfg.agent_id == "a1"


def test_load_config_returns_none_when_token_missing(tmp_path: object) -> None:
    save_config({"endpoint": "https://e/mcp"}, str(tmp_path))
    assert load_config(str(tmp_path), {}) is None
