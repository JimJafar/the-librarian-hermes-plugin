"""The Librarian-backed Hermes Memory Provider.

Maps the Hermes ``MemoryProvider`` hooks onto Librarian MCP tools (via
:class:`client.LibrarianClient`). Two invariants dominate:

- **Memory-only after sessions-rethink PR 5.** The session subsystem
  (start/checkpoint/pause/end/resume, the natural-language privacy gate,
  the local state-store) is retired. The provider's surface is now:
  recall + remember + verify_memory MCP tools, plus per-turn
  conv-state injection into the system prompt (spec §4.9). The four
  user-facing verbs (/handoff, /takeover, /learn, /toggle-private) are
  exposed through ``commands.py`` and call the MCP layer directly.
- **Fail-soft:** a Librarian / client failure is logged and swallowed —
  a turn is never blocked; recall just degrades to empty.

The Hermes ``MemoryProvider`` ABC lives in the Hermes codebase (provided
at runtime), not installed here, so we subclass it when importable and
``object`` otherwise. Method names/shapes match
``agent/memory_provider.py`` in NousResearch/hermes-agent (e.g.
``prefetch``/``sync_turn`` take a keyword ``session_id``;
``handle_tool_call(tool_name, args, **kwargs)``).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .client import LibrarianClient, LibrarianClientError

if TYPE_CHECKING:
    _Base = object
else:
    try:  # pragma: no cover - exercised only inside a real Hermes runtime
        from agent.memory_provider import MemoryProvider as _Base
    except ImportError:
        _Base = object

LogFn = Callable[[str, str], None]

_CONFIG_FILENAME = "config.json"
_PROVIDER_NAME = "librarian"


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
    not fully configured."""
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
    """Hermes Memory Provider backed by The Librarian (memory-only)."""

    def __init__(
        self,
        *,
        client: LibrarianClient | None = None,
        config: LibrarianConfig | None = None,
        logger: LogFn | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._log: LogFn = logger or (lambda _level, _msg: None)
        self._env = env if env is not None else dict(os.environ)
        self._session_id: str | None = None

    # ---- identity / availability / config (the ABC surface) ----

    @property
    def name(self) -> str:
        return _PROVIDER_NAME

    def is_available(self) -> bool:
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
        """Agent startup: cache the session id and wire the MCP client.

        sessions-rethink PR 5 — no Librarian session is created here or
        elsewhere; the four user-facing verbs are now pure agent
        operations.
        """
        self._session_id = session_id
        hermes_home = kwargs.get("hermes_home")
        if not isinstance(hermes_home, str):
            self._log("error", "librarian: no hermes_home supplied; provider inert this session")
            return
        if self._config is None:
            self._config = load_config(hermes_home, self._env)
        if self._client is None and self._config is not None:
            self._client = LibrarianClient(
                self._config.endpoint, self._config.token, timeout_ms=self._config.timeout_ms
            )

    def _resolve_hermes_home(self) -> str | None:
        home = self._env.get("HERMES_HOME")
        if home:
            return home
        user_home = self._env.get("HOME")
        return str(Path(user_home) / ".hermes") if user_home else None

    def shutdown(self) -> None:
        self._client = None

    # ---- read (prefetch + system-prompt block) ----

    def system_prompt_block(self) -> str:
        """Frozen recall snapshot injected once at session start (cache-friendly,
        matching the built-in). The conv-state block is prepended on every call
        so the LLM sees the current `domain` / `session_id` / `off_record`."""
        recall_text = self._call_text("start_context", self._agent_args({}))
        return _prefix_with_conv_state(self._fetch_conv_state(), recall_text)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Targeted recall before an API call. Prepended with the canonical
        `<conversation-state>` block from spec §4.9 so the LLM sees the current
        `domain` / `session_id` / `off_record` on every turn — defeating
        context-compaction-driven state loss."""
        del session_id  # the ABC's hint; one Librarian endpoint per profile
        recall_text = self._call_text("recall", self._agent_args({"query": query}))
        return _prefix_with_conv_state(self._fetch_conv_state(), recall_text)

    def _fetch_conv_state(self) -> dict[str, Any] | None:
        """Look up the conv_state row for this Hermes session, or None.

        conv-id convention: `hermes:<session_id>`.
        Fail-soft: any error returns None, the block is omitted, and the prompt
        reaches the model unchanged.
        """
        if not self._session_id or self._client is None:
            return None
        conv_id = f"hermes:{self._session_id}"
        try:
            text = self._client.call_tool("conv_state_get", {"conv_id": conv_id})
        except LibrarianClientError as err:
            self._log("warn", f"librarian: conv_state_get failed: {err}")
            return None
        if not text or text.startswith("No conversation state"):
            return None
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) and "conv_id" in parsed else None

    # ---- write (turn persistence — now no-ops; sessions are retired) ----

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        del user_content, assistant_content, session_id  # no-op post-rethink

    def on_pre_compress(self, messages: Sequence[object]) -> str:
        del messages  # no checkpoint surface — provider contributes no text
        return ""

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        **kwargs: Any,
    ) -> None:
        """Hermes rotated the agent's session id; track it so the next
        conv-state lookup uses the right conv_id."""
        del parent_session_id, reset, kwargs
        self._session_id = new_session_id

    def on_session_end(self, messages: Sequence[object]) -> None:
        del messages  # no-op post-rethink

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Mirror a built-in memory write into the Librarian (safety net). Only
        `add` maps cleanly to `remember`."""
        del metadata
        if action != "add":
            self._log("info", f"librarian: not mirroring built-in '{action}' write")
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
                        "result": {
                            "type": "string",
                            "enum": ["useful", "not_useful", "outdated"],
                        },
                    },
                    "required": ["memory_id", "result"],
                },
            },
        ]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        if tool_name not in {"recall", "remember", "verify_memory"}:
            return f"Unknown Librarian tool: {tool_name}"
        if not isinstance(args, dict):
            return f"The Librarian tool {tool_name} expects an object of arguments."
        scoped = self._agent_args(dict(args)) if tool_name != "verify_memory" else dict(args)
        # Agent-driven recall always asks for ids so the next-turn
        # verify_memory has something to target.
        if tool_name == "recall":
            scoped.setdefault("include_ids", True)
        return self._call_text(tool_name, scoped)

    # ---- helpers shared with commands.py ----

    def run_tool(self, name: str, args: dict[str, Any], *, scope: bool = True) -> str:
        """Public entry point used by the slash commands in commands.py."""
        scoped = self._agent_args(dict(args)) if scope else dict(args)
        return self._call_text(name, scoped)

    def _agent_args(self, args: dict[str, Any]) -> dict[str, Any]:
        out = dict(args)
        if self._config is None:
            return out
        if self._config.agent_id and "agent_id" not in out:
            out["agent_id"] = self._config.agent_id
        if self._config.project_key and "project_key" not in out:
            out["project_key"] = self._config.project_key
        return out

    def _call_text(self, tool: str, args: dict[str, Any]) -> str:
        if self._client is None:
            return ""
        try:
            return self._client.call_tool(tool, args)
        except LibrarianClientError as err:
            self._log("warn", f"librarian: {tool} failed: {err}")
            return ""

    def _call_soft(self, tool: str, args: dict[str, Any]) -> None:
        self._call_text(tool, args)


def _render_conv_state_block(state: dict[str, Any] | None) -> str:
    if not state or "conv_id" not in state:
        return ""
    domain = state.get("domain") or "unknown"
    session_id = state.get("session_id") or "none"
    off_record = "true" if state.get("off_record") else "false"
    return "\n".join(
        [
            "<conversation-state>",
            f"  conv_id: {state['conv_id']}",
            f"  domain: {domain}",
            f"  session_id: {session_id}",
            f"  off_record: {off_record}",
            "</conversation-state>",
        ]
    )


def _prefix_with_conv_state(state: dict[str, Any] | None, recall_text: str) -> str:
    block = _render_conv_state_block(state)
    if not block:
        return recall_text or ""
    if not recall_text:
        return block
    return f"{block}\n\n{recall_text}"
