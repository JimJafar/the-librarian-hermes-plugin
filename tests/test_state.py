"""Local-state store tests."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from librarian.state import PluginState, StateError, StateStore


def _store(tmp_path: Path) -> StateStore:
    return StateStore(hermes_home=str(tmp_path))


def test_absent_state_loads_default_public(tmp_path: Path) -> None:
    state = _store(tmp_path).load()
    assert state == PluginState(privacy="public", librarian_session_id=None)


def test_round_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(
        PluginState(
            privacy="private",
            librarian_session_id="ses_abc",
            entered_private_at="2026-05-24T00:00:00Z",
        )
    )
    loaded = store.load()
    assert loaded.privacy == "private"
    assert loaded.librarian_session_id == "ses_abc"
    assert loaded.entered_private_at == "2026-05-24T00:00:00Z"


def test_corrupt_state_raises_state_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    path = store.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(StateError):
        store.load()


def test_invalid_utf8_raises_state_error(tmp_path: Path) -> None:
    # A torn/corrupt file with invalid UTF-8 must fail closed as StateError,
    # not escape as a raw UnicodeDecodeError (which would dodge the caller's
    # fail-closed handling and could drop the privacy flag).
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_bytes(b"\xff\xfe\x00 garbage")
    with pytest.raises(StateError):
        store.load()


def test_permissions_file_0600_dir_0700(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(PluginState())
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700


def test_atomic_no_temp_leftovers(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(PluginState(librarian_session_id="ses_1"))
    leftovers = [p.name for p in store.path.parent.iterdir() if ".tmp" in p.name]
    assert leftovers == []


def test_update_mutates_and_persists_under_lock(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(PluginState(privacy="public", librarian_session_id="ses_1"))

    def go_private(current: PluginState) -> PluginState:
        return PluginState(
            privacy="private",
            librarian_session_id=None,
            entered_private_at="2026-05-24T01:00:00Z",
        )

    result = store.update(go_private)
    assert result.privacy == "private"
    assert store.load().privacy == "private"
    assert store.load().librarian_session_id is None


def test_one_state_file_per_profile(tmp_path: Path) -> None:
    # State is now per-profile (not per Hermes session): two stores under the same
    # hermes_home share ONE file, so the memory-provider and general-plugin
    # instances coordinate through it. The path stays inside the profile dir.
    a = _store(tmp_path)
    b = _store(tmp_path)
    assert a.path == b.path
    assert tmp_path in a.path.parents
    assert a.path.suffix == ".json"


def test_state_serialises_compactly(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(PluginState(privacy="public"))
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["privacy"] == "public"
    assert raw["version"] == 1
