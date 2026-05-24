"""Local plugin state — the attached Librarian session id + off-record flag.

Scoped under the Hermes profile (``hermes_home``) and keyed per Hermes session,
mirroring the TS lifecycle helper's local-state design but simpler (Hermes gives
explicit lifecycle hooks, and one provider instance runs per session/process, so
an in-process lock suffices — no cross-process lockfile).

Invariants:
- the file never holds prompt text or summaries (ids + flags only);
- absent state loads as the public default; a corrupt/unreadable file raises
  :class:`StateError` so the caller fails closed (no automatic Librarian call);
- writes are atomic (temp + ``os.replace``), dir ``0700`` / file ``0600``.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

STATE_VERSION = 1
_DIR_MODE = 0o700
_FILE_MODE = 0o600

Privacy = Literal["public", "private"]


class StateError(Exception):
    """Local state could not be read/parsed/written — the signal to fail closed."""


@dataclass(frozen=True)
class PluginState:
    privacy: Privacy = "public"
    librarian_session_id: str | None = None
    entered_private_at: str | None = None


def _state_dir(hermes_home: str) -> Path:
    return Path(hermes_home) / "librarian-plugin"


def _state_path(hermes_home: str, session_id: str) -> Path:
    # Hash the session id into the filename so an arbitrary id can't escape the
    # state dir or collide by concatenation.
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:40]
    return _state_dir(hermes_home) / f"{digest}.json"


def _to_dict(state: PluginState) -> dict[str, object]:
    return {
        "version": STATE_VERSION,
        "privacy": state.privacy,
        "librarian_session_id": state.librarian_session_id,
        "entered_private_at": state.entered_private_at,
    }


def _from_dict(raw: object, path: Path) -> PluginState:
    if not isinstance(raw, dict):
        raise StateError(f"harness state at {path} is not an object")
    privacy = raw.get("privacy")
    if privacy not in ("public", "private"):
        raise StateError(f"harness state at {path} has an invalid privacy value")
    session_id = raw.get("librarian_session_id")
    entered = raw.get("entered_private_at")
    if session_id is not None and not isinstance(session_id, str):
        raise StateError(f"harness state at {path} has a non-string session id")
    if entered is not None and not isinstance(entered, str):
        raise StateError(f"harness state at {path} has a non-string entered_private_at")
    return PluginState(privacy=privacy, librarian_session_id=session_id, entered_private_at=entered)


class StateStore:
    """Read/modify/write the per-session local state under ``hermes_home``."""

    def __init__(self, hermes_home: str, session_id: str) -> None:
        self.path = _state_path(hermes_home, session_id)
        self._lock = threading.Lock()

    def load(self) -> PluginState:
        """Return the stored state, the public default if absent, or raise
        :class:`StateError` if present-but-unreadable/invalid."""
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return PluginState()
        except OSError as err:
            raise StateError(f"cannot read harness state at {self.path}: {err}") from err
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as err:
            raise StateError(f"harness state at {self.path} is not valid JSON: {err}") from err
        return _from_dict(parsed, self.path)

    def save(self, state: PluginState) -> None:
        """Persist atomically with 0700/0600 permissions."""
        with self._lock:
            self._write(state)

    def update(self, mutate: Callable[[PluginState], PluginState]) -> PluginState:
        """Load + mutate + save under the lock; returns the saved state."""
        with self._lock:
            nxt = mutate(self.load())
            self._write(nxt)
            return nxt

    def _write(self, state: PluginState) -> None:
        directory = self.path.parent
        try:
            directory.mkdir(parents=True, exist_ok=True)
            # mkdir's mode is umask-masked; chmod the leaf to guarantee 0700.
            directory.chmod(_DIR_MODE)
            tmp = directory / f".{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
            # Exclusive create so a planted symlink isn't followed.
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
            try:
                os.write(fd, json.dumps(_to_dict(state)).encode("utf-8"))
            finally:
                os.close(fd)
            os.chmod(tmp, _FILE_MODE)
            os.replace(tmp, self.path)
        except OSError as err:
            raise StateError(f"cannot write harness state at {self.path}: {err}") from err
