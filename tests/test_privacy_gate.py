"""pre_gateway_dispatch privacy-gate tests + provider privacy transitions."""

from __future__ import annotations

from pathlib import Path

from the_librarian_hermes_plugin.privacy_gate import make_privacy_gate, message_text
from the_librarian_hermes_plugin.provider import LibrarianConfig, LibrarianProvider
from the_librarian_hermes_plugin.state import StateStore

SESSION = "sess-1"


class FakeController:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def enter_private(self) -> str:
        self.calls.append("enter")
        return "private"

    def exit_private(self) -> str:
        self.calls.append("exit")
        return "public"

    def toggle_privacy(self) -> str:
        self.calls.append("toggle")
        return "public"


def test_gate_routes_signals_to_controller() -> None:
    ctrl = FakeController()
    gate = make_privacy_gate(ctrl)
    assert gate("off the record, here's a secret") is None
    gate("you can remember again")
    gate("/lib-toggle-private")
    gate("just a normal message")
    assert ctrl.calls == ["enter", "exit", "toggle"]


def test_gate_accepts_dict_payloads() -> None:
    ctrl = FakeController()
    gate = make_privacy_gate(ctrl)
    gate({"content": "this is a private session"})
    gate({"text": "back on the record"})
    assert ctrl.calls == ["enter", "exit"]


def test_message_text_extraction() -> None:
    assert message_text("hi") == "hi"
    assert message_text({"content": "a"}) == "a"
    assert message_text({"prompt": "b"}) == "b"
    assert message_text({"unrelated": 1}) == ""
    assert message_text(123) == ""


# ---- provider privacy transitions (the controller the gate drives) ----


class FakeClient:
    def __init__(self, responses: dict[str, str] | None = None):
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._responses = responses or {}

    def call_tool(self, name: str, arguments: dict[str, object]) -> str:
        self.calls.append((name, dict(arguments)))
        return self._responses.get(name, "ok")

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]


def _provider(tmp_path: Path, client: FakeClient) -> LibrarianProvider:
    p = LibrarianProvider(
        client=client, config=LibrarianConfig(endpoint="https://x/mcp", token="t", agent_id="h")
    )
    p.initialize(SESSION, hermes_home=str(tmp_path))
    return p


def test_enter_private_ends_session_and_sets_state(tmp_path: Path) -> None:
    client = FakeClient({"start_session": "ses_abc"})
    p = _provider(tmp_path, client)
    p.sync_turn("a", "b")  # establishes ses_abc
    client.calls.clear()
    p.enter_private()
    # Ended the attached session with the neutral reason.
    assert client.names() == ["end_session"]
    _, args = client.calls[0]
    assert args["session_id"] == "ses_abc"
    assert args["summary"] == "switching to private mode"
    # Local state: private, detached, timestamped.
    state = StateStore(str(tmp_path), SESSION).load()
    assert state.privacy == "private"
    assert state.librarian_session_id is None
    assert state.entered_private_at is not None


def test_enter_private_with_no_session_makes_no_call(tmp_path: Path) -> None:
    client = FakeClient()
    p = _provider(tmp_path, client)
    p.enter_private()
    assert client.calls == []
    assert StateStore(str(tmp_path), SESSION).load().privacy == "private"


def test_exit_private_returns_public_and_clears_entered(tmp_path: Path) -> None:
    client = FakeClient()
    p = _provider(tmp_path, client)
    p.enter_private()
    p.exit_private()
    state = StateStore(str(tmp_path), SESSION).load()
    assert state.privacy == "public"
    assert state.entered_private_at is None


def test_toggle_flips_both_directions(tmp_path: Path) -> None:
    client = FakeClient()
    p = _provider(tmp_path, client)
    assert p.toggle_privacy() == "private"
    assert StateStore(str(tmp_path), SESSION).load().privacy == "private"
    assert p.toggle_privacy() == "public"
    assert StateStore(str(tmp_path), SESSION).load().privacy == "public"


def test_gate_drives_real_provider_end_to_end(tmp_path: Path) -> None:
    client = FakeClient({"start_session": "ses_abc"})
    p = _provider(tmp_path, client)
    p.sync_turn("a", "b")  # ses_abc attached
    gate = make_privacy_gate(p)
    gate("this is a private session")
    assert "end_session" in client.names()
    # A subsequent ordinary prompt records nothing while private.
    client.calls.clear()
    p.sync_turn("more", "secret")
    assert client.calls == []
    # Going public again, then a turn starts a fresh session.
    gate("you can remember again")
    p.sync_turn("back", "to work")
    assert "start_session" in client.names()
