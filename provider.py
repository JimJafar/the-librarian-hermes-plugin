"""The Librarian-backed Hermes Memory Provider.

Maps the Hermes ``MemoryProvider`` hooks onto Librarian MCP tools (via
:class:`client.LibrarianClient`), gated by the local off-record flag
(:mod:`state`) and the ported privacy detector. Two invariants dominate:

- **Off-record:** while private, no Librarian call is made (prefetch/system block
  return empty; sync/checkpoint/pause/tool-calls are suppressed).
- **Fail-soft:** a Librarian/client failure is logged and swallowed — a turn is
  never blocked, recall just degrades to empty (the remote store can be down).

The Hermes ``MemoryProvider`` ABC lives in the Hermes codebase (provided at
runtime), not installed here, so we subclass it when importable and ``object``
otherwise. Method names/shapes match ``agent/memory_provider.py`` in
NousResearch/hermes-agent (e.g. ``prefetch``/``sync_turn`` take a keyword
``session_id``; ``handle_tool_call(tool_name, args, **kwargs)``;
``on_pre_compress`` returns ``str``).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .client import LibrarianClient, LibrarianClientError
from .state import PluginState, StateError, StateStore

if TYPE_CHECKING:
    _Base = object
else:
    try:  # pragma: no cover - exercised only inside a real Hermes runtime
        from agent.memory_provider import MemoryProvider as _Base
    except ImportError:
        _Base = object

LogFn = Callable[[str, str], None]
StateStoreFactory = Callable[[str], StateStore]

_CONFIG_FILENAME = "config.json"
_PROVIDER_NAME = "librarian"
_PRIVATE_END_REASON = "switching to private mode"


@dataclass(frozen=True)
class LibrarianConfig:
    endpoint: str
    token: str
    agent_id: str | None = None
    project_key: str | None = None
    timeout_ms: int = 15000


def config_schema() -> list[dict[str, Any]]:
    """Field descriptors for ``hermes memory setup`` (the get_config_schema body)."""
    return [
        {
            "key": "endpoint",
            "description": "Librarian HTTP MCP endpoint URL",
            "url": True,
            "required": True,
            "secret": False,
        },
        {
            "key": "token",
            "description": "Librarian agent bearer token",
            "secret": True,
            "required": True,
            "env_var": "LIBRARIAN_AGENT_TOKEN",
        },
        {
            "key": "agent_id",
            "description": "Canonical agent id (optional if the token is agent-bound)",
            "required": False,
            "secret": False,
        },
        {
            "key": "project_key",
            "description": "Default project scope (optional)",
            "required": False,
            "secret": False,
        },
        {
            "key": "timeout_ms",
            "description": "Per-call timeout in ms",
            "required": False,
            "secret": False,
            "default": 15000,
        },
    ]


def _config_path(hermes_home: str) -> Path:
    return Path(hermes_home) / "librarian-plugin" / _CONFIG_FILENAME


def save_config(values: dict[str, Any], hermes_home: str) -> None:
    """Persist non-secret config under hermes_home. The token is never written —
    it comes from the LIBRARIAN_AGENT_TOKEN env var at load time."""
    path = _config_path(hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    non_secret = {k: v for k, v in values.items() if k != "token"}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(non_secret).encode("utf-8"))
    finally:
        os.close(fd)
    path.chmod(0o600)


def load_config(hermes_home: str, env: dict[str, str]) -> LibrarianConfig | None:
    """Load config (non-secret from hermes_home, token from env). Returns None if
    not fully configured (no endpoint or no token) — the provider is then inert."""
    path = _config_path(hermes_home)
    values: dict[str, Any] = {}
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        values = {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(values, dict):
        return None
    endpoint = values.get("endpoint")
    token = env.get("LIBRARIAN_AGENT_TOKEN")
    if not isinstance(endpoint, str) or not endpoint or not token:
        return None
    timeout = values.get("timeout_ms")
    return LibrarianConfig(
        endpoint=endpoint,
        token=token,
        agent_id=values.get("agent_id") or None,
        project_key=values.get("project_key") or None,
        timeout_ms=int(timeout) if isinstance(timeout, int) else 15000,
    )


class LibrarianProvider(_Base):
    """Hermes Memory Provider backed by The Librarian."""

    def __init__(
        self,
        *,
        client: LibrarianClient | None = None,
        config: LibrarianConfig | None = None,
        state_store_factory: StateStoreFactory | None = None,
        logger: LogFn | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._make_state = state_store_factory or StateStore
        self._log: LogFn = logger or (lambda _level, _msg: None)
        self._env = env if env is not None else dict(os.environ)
        self._state: StateStore | None = None
        self._session_id: str | None = None

    # ---- identity / availability / config (the ABC surface) ----

    @property
    def name(self) -> str:
        return _PROVIDER_NAME

    def is_available(self) -> bool:
        # Per the ABC, no network — just check whether config resolves. Lazy-load
        # config (file + env only) on first call so a freshly-constructed instance
        # reports availability correctly BEFORE Hermes' MemoryManager calls
        # ``initialize()`` (``hermes memory status`` calls is_available first).
        if self._config is None:
            hermes_home = self._resolve_hermes_home()
            if hermes_home is not None:
                self._config = load_config(hermes_home, self._env)
        return self._config is not None

    def get_config_schema(self) -> list[dict[str, Any]]:
        return config_schema()

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        save_config(values, hermes_home)

    # ---- lifecycle ----

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        """Agent startup: set up local state + client. Does NOT create a Librarian
        session — that happens lazily on the first recorded turn (§5.1)."""
        self._session_id = session_id
        hermes_home = kwargs.get("hermes_home")
        if not isinstance(hermes_home, str):
            self._log("error", "librarian: no hermes_home supplied; provider inert this session")
            self._state = None
            return
        self._wire(hermes_home)

    def _wire(self, hermes_home: str) -> None:
        """Set up per-profile state + (if configured) the client for *hermes_home*."""
        self._state = self._make_state(hermes_home)
        if self._config is None:
            self._config = load_config(hermes_home, self._env)
        if self._client is None and self._config is not None:
            self._client = LibrarianClient(
                self._config.endpoint, self._config.token, timeout_ms=self._config.timeout_ms
            )

    def _resolve_hermes_home(self) -> str | None:
        """Best-effort hermes_home from the captured env (no os.environ peek so
        tests can isolate by passing ``env=``). HERMES_HOME wins; HOME/.hermes is
        the documented Hermes default; nothing → None (caller skips lazy work)."""
        home = self._env.get("HERMES_HOME")
        if home:
            return home
        user_home = self._env.get("HOME")
        return str(Path(user_home) / ".hermes") if user_home else None

    def _ensure_runtime(self) -> None:
        """Lazily wire an instance that was never ``initialize()``-d.

        The general-plugin loader (privacy gate + slash commands) builds a provider
        via ``register()`` but never calls ``initialize()`` — only the
        ``MemoryManager`` does, on its own instance. Resolve ``HERMES_HOME`` from
        the captured env so the gate/command paths attach to the SAME per-profile
        state + config the live memory provider uses (see ``state`` module)."""
        if self._state is not None:
            return
        hermes_home = self._resolve_hermes_home()
        if hermes_home is not None:
            self._wire(hermes_home)

    def shutdown(self) -> None:
        self._state = None
        self._client = None
        self._session_id = None

    # ---- privacy transitions (driven by the pre_gateway_dispatch gate) ----

    def enter_private(self) -> str:
        """Go off-record. Writes private state FIRST (so future calls are
        suppressed even if the end fails), then ends the attached session with a
        neutral reason (§4.3). Idempotent."""
        self._ensure_runtime()
        session = self._current_session()
        self._set_privacy("private", clear_session=True, stamp_entered=True)
        if session is not None:
            self._call_soft(
                "end_session",
                self._agent_args({"session_id": session, "summary": _PRIVATE_END_REASON}),
            )
        return "private"

    def exit_private(self) -> str:
        """Go back on-record. The next turn starts a fresh session (the prior one
        was ended on entering private); this turn is not recorded."""
        self._ensure_runtime()
        self._set_privacy("public", clear_session=True, stamp_entered=False)
        return "public"

    def toggle_privacy(self) -> str:
        self._ensure_runtime()
        return self.exit_private() if self._read_privacy() == "private" else self.enter_private()

    def _read_privacy(self) -> str:
        # Actual current privacy for the toggle decision; fail closed to private.
        if self._state is None:
            return "private"
        try:
            return self._state.load().privacy
        except StateError:
            return "private"

    def _set_privacy(self, privacy: str, *, clear_session: bool, stamp_entered: bool) -> None:
        state = self._state
        if state is None:
            return
        # timezone.utc (not datetime.UTC, which is 3.11+) — the package targets 3.10.
        entered = datetime.now(timezone.utc).isoformat() if stamp_entered else None

        def mutate(cur: PluginState) -> PluginState:
            return PluginState(
                privacy="private" if privacy == "private" else "public",
                librarian_session_id=None if clear_session else cur.librarian_session_id,
                entered_private_at=entered if privacy == "private" else None,
            )

        try:
            state.update(mutate)
        except StateError as err:
            self._log("error", f"librarian: could not set privacy={privacy}: {err}")

    # ---- recall (read) ----

    def system_prompt_block(self) -> str:
        """Frozen recall snapshot injected once at session start (cache-friendly,
        matching the built-in). Empty while private or on any failure."""
        if self._is_private():
            return ""
        return self._call_text("start_context", self._agent_args({}))

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Targeted recall before an API call. Empty while private or on failure.

        ``session_id`` (the ABC's per-concurrent-session hint) is accepted but not
        used for scoping: this provider keeps one active session per profile."""
        if self._is_private():
            return ""
        return self._call_text("recall", self._agent_args({"query": query}))

    # ---- write (turn persistence) ----

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """Record the completed turn to the Librarian session (must be non-blocking;
        Hermes runs this in a daemon thread). Skipped while private. ``session_id``
        is accepted per the ABC but not used (one active session per profile)."""
        if self._is_private():
            return
        session = self._ensure_session()
        if session is None:
            return
        summary = _turn_summary(user_content, assistant_content)
        # `type` must be one of the Librarian's SessionPayloadType values
        # (message/command/file/error/decision/question/checkpoint/handover/note).
        # "turn" is not in that enum, so the server's Zod validator rejects it
        # and `_call_soft` silently swallows the error — leaving the session with
        # zero events. A completed user↔assistant exchange is a `message`.
        self._call_soft(
            "record_session_event",
            self._agent_args({"session_id": session, "type": "message", "summary": summary}),
        )

    def on_pre_compress(self, messages: Sequence[object]) -> str:
        """Checkpoint the session before compaction. Returns "" — this provider
        contributes no text to the compression summary (the ABC allows that)."""
        if self._is_private():
            return ""
        session = self._current_session()
        if session is None:
            return ""
        self._call_soft(
            "checkpoint_session",
            self._agent_args({"session_id": session, "summary": "Context compaction checkpoint."}),
        )
        return ""

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        **kwargs: Any,
    ) -> None:
        """Hermes rotated the agent's session id (/resume, /branch, /reset, /new,
        compression). Update the cached id used for ``source_ref``; on a genuine
        reset (new conversation) detach so the next turn opens a fresh Librarian
        session rather than appending to the previous one."""
        self._session_id = new_session_id
        if reset:
            self._detach()

    def on_session_end(self, messages: Sequence[object]) -> None:
        # Pause (never end — §5.4); detach locally so a later turn resumes by match.
        if self._is_private():
            return
        session = self._current_session()
        if session is None:
            return
        self._call_soft(
            "pause_session",
            self._agent_args({"session_id": session, "summary": "Session paused (agent end)."}),
        )
        self._detach()

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Mirror a built-in memory write into the Librarian (safety net). Only
        `add` maps cleanly to `remember`; replace/remove key off MEMORY.md substring
        matching with no Librarian-id correspondence, so they're not mirrored (v1).
        ``metadata`` (write provenance) is accepted per the ABC but unused in v1."""
        if self._is_private():
            return
        if action != "add":
            self._log("info", f"librarian: not mirroring built-in '{action}' write (v1)")
            return
        title = (target or content).strip()[:120] or "Imported note"
        self._call_soft(
            "remember",
            self._agent_args({"title": title, "body": content, "category": "lessons"}),
        )

    # ---- agent-facing tools ----

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "recall",
                "description": (
                    "Recall durable memories from The Librarian. Each line is "
                    "prefixed with the memory's id in brackets (e.g. `[mem_...]`) "
                    "— pass that id to `verify_memory` after using a result so "
                    "the store learns which recalls were load-bearing."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {
                "name": "remember",
                "description": "Store a durable memory in The Librarian.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "category": {"type": "string"},
                    },
                    "required": ["title", "body"],
                },
            },
            {
                "name": "verify_memory",
                "description": (
                    "Record a verdict against a memory after recalling it. "
                    "`useful` raises its recall rank, `not_useful` lowers it, "
                    "`outdated` archives it. The `memory_id` is the id in "
                    "brackets from the preceding `recall` line."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string"},
                        "result": {"type": "string", "enum": ["useful", "not_useful", "outdated"]},
                    },
                    "required": ["memory_id", "result"],
                },
            },
        ]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        if tool_name not in {"recall", "remember", "verify_memory"}:
            return f"Unknown Librarian tool: {tool_name}"
        if not isinstance(args, dict):
            return f"The Librarian tool {tool_name} expects an object of arguments."
        if self._is_private():
            return "Off the record — The Librarian is paused; nothing was recalled or stored."
        scoped = self._agent_args(dict(args)) if tool_name != "verify_memory" else dict(args)
        # Agent-driven recall always asks for ids so the next-turn verify_memory
        # has something to target. Background prefetch (system-prompt block) does
        # NOT set this — that's cache-friendly prose, never verified.
        if tool_name == "recall":
            scoped.setdefault("include_ids", True)
        try:
            return self._require_client().call_tool(tool_name, scoped)
        except (LibrarianClientError, _Inert) as err:
            self._log("warn", f"librarian: tool {tool_name} failed: {err}")
            return f"The Librarian is unavailable right now ({tool_name} could not complete)."

    # ---- slash-command helpers (driven by commands.py) ----

    def is_private(self) -> bool:
        """Public off-record check for slash-command handlers."""
        self._ensure_runtime()
        return self._is_private()

    def current_session_id(self) -> str | None:
        """The attached Librarian session id, or None."""
        self._ensure_runtime()
        return self._current_session()

    def detach(self) -> None:
        """Forget the attached session locally (no Librarian call)."""
        self._ensure_runtime()
        self._detach()

    def run_tool(self, name: str, args: dict[str, Any], *, scope: bool = True) -> str:
        """Privacy-gated, fail-soft text call for slash commands. Returns the
        tool's text, or a short human message while private / unavailable."""
        self._ensure_runtime()
        if self._is_private():
            return "Off the record — The Librarian is paused; nothing was sent."
        scoped = self._agent_args(dict(args)) if scope else dict(args)
        try:
            return self._require_client().call_tool(name, scoped)
        except (LibrarianClientError, _Inert) as err:
            self._log("warn", f"librarian: {name} failed: {err}")
            return f"The Librarian is unavailable right now ({name} could not complete)."

    def attach_session_id(self, session_id: str) -> None:
        """Attach *session_id* locally so subsequent turns record to it."""
        self._ensure_runtime()
        state = self._state
        if state is None:
            return
        try:
            state.update(
                lambda cur: PluginState(
                    privacy=cur.privacy,
                    librarian_session_id=session_id,
                    entered_private_at=cur.entered_private_at,
                )
            )
        except StateError as err:
            self._log("warn", f"librarian: could not attach session {session_id}: {err}")

    def start_new_session(self, title: str | None = None) -> str | None:
        """Start a fresh Librarian session and attach it (for /lib-session-start).
        No-op while private. Returns the new session id, or None on failure."""
        self._ensure_runtime()
        if self._is_private():
            return None
        try:
            client = self._require_client()
        except _Inert:
            return None
        args = self._agent_args({"harness": "hermes", "start_summary": title or "Hermes session."})
        if title:
            args["title"] = title
        if self._session_id is not None:
            args["source_ref"] = f"hermes:session:{self._session_id}"
        try:
            text = client.call_tool("start_session", args)
        except LibrarianClientError as err:
            self._log("warn", f"librarian: start_session failed: {err}")
            return None
        session_id = _extract_session_id(text)
        if session_id is not None:
            self.attach_session_id(session_id)
        return session_id

    # ---- internals ----

    def _is_private(self) -> bool:
        if self._state is None:
            return True  # no state → fail closed (suppress)
        try:
            return self._state.load().privacy == "private"
        except StateError as err:
            self._log("error", f"librarian: state unreadable, suppressing: {err}")
            return True

    def _current_session(self) -> str | None:
        if self._state is None:
            return None
        try:
            return self._state.load().librarian_session_id
        except StateError:
            return None

    def _ensure_session(self) -> str | None:
        existing = self._current_session()
        if existing is not None:
            return existing
        state = self._state
        if state is None:
            return None
        # Create-or-get atomically under the state lock so two racing first turns
        # (e.g. the daemon sync_turn vs another caller) converge on ONE session:
        # the loser's mutate sees the id the winner just wrote and reuses it. The
        # start_session network call runs inside the lock — brief, and the price of
        # never orphaning a session.
        captured: dict[str, str | None] = {"id": None}

        def mutate(cur: PluginState) -> PluginState:
            if cur.librarian_session_id is not None:
                captured["id"] = cur.librarian_session_id
                return cur
            session_id = self._start_session_call()
            captured["id"] = session_id
            if session_id is None:
                return cur
            return PluginState(
                privacy=cur.privacy,
                librarian_session_id=session_id,
                entered_private_at=cur.entered_private_at,
            )

        try:
            state.update(mutate)
        except StateError as err:
            self._log("error", f"librarian: could not persist session id: {err}")
            return None
        return captured["id"]

    def _start_session_call(self) -> str | None:
        try:
            client = self._require_client()
        except _Inert:
            return None
        args = self._agent_args({"harness": "hermes", "start_summary": "Hermes session."})
        if self._session_id is not None:
            args["source_ref"] = f"hermes:session:{self._session_id}"
        try:
            text = client.call_tool("start_session", args)
        except LibrarianClientError as err:
            self._log("warn", f"librarian: start_session failed: {err}")
            return None
        session_id = _extract_session_id(text)
        if session_id is None:
            self._log("warn", "librarian: start_session returned no id")
        return session_id

    def _detach(self) -> None:
        if self._state is None:
            return
        try:
            self._state.update(
                lambda cur: PluginState(
                    privacy=cur.privacy,
                    librarian_session_id=None,
                    entered_private_at=cur.entered_private_at,
                )
            )
        except StateError as err:
            self._log("warn", f"librarian: could not detach session: {err}")

    def _agent_args(self, args: dict[str, Any]) -> dict[str, Any]:
        if self._config and self._config.agent_id and "agent_id" not in args:
            args["agent_id"] = self._config.agent_id
        if self._config and self._config.project_key and "project_key" not in args:
            args["project_key"] = self._config.project_key
        return args

    def _call_text(self, tool: str, args: dict[str, Any]) -> str:
        try:
            return self._require_client().call_tool(tool, args)
        except (LibrarianClientError, _Inert) as err:
            self._log("warn", f"librarian: {tool} failed (degraded to empty): {err}")
            return ""

    def _call_soft(self, tool: str, args: dict[str, Any]) -> None:
        try:
            self._require_client().call_tool(tool, args)
        except (LibrarianClientError, _Inert) as err:
            self._log("warn", f"librarian: {tool} failed: {err}")

    def _require_client(self) -> LibrarianClient:
        if self._client is None:
            raise _Inert("librarian provider is not configured")
        return self._client


class _Inert(Exception):
    """The provider has no client (unconfigured) — treated as a soft failure."""


def _turn_summary(user_content: str, assistant_content: str) -> str:
    user = user_content.strip().splitlines()[0][:200] if user_content.strip() else ""
    assistant = assistant_content.strip().splitlines()[0][:200] if assistant_content.strip() else ""
    return f"User: {user}\nAssistant: {assistant}".strip()


_SESSION_ID_RE = re.compile(r"\bses_[A-Za-z0-9]+\b")


def _extract_session_id(text: str) -> str | None:
    # start_session returns formatted text; pull the first ses_… token. The word
    # boundary stops at adjacent punctuation so we never capture trailing junk.
    match = _SESSION_ID_RE.search(text)
    return match.group(0) if match else None
