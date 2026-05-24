# the-librarian-hermes-plugin

A [Hermes Agent](https://hermes-agent.nousresearch.com) **Memory Provider plugin** backed
by [The Librarian](https://github.com/JimJafar/the-librarian).

It makes The Librarian the agent's durable memory + session layer: recall is injected at
session start and on demand, the agent can `recall`/`remember`/`verify_memory` via tools,
each turn is recorded to a Librarian session, and an off-record privacy gate suppresses
recording on request. It talks to a Librarian **HTTP MCP server at a configurable
endpoint**, so Hermes and the Librarian can live on different servers.

## Install

```sh
pip install the-librarian-hermes-plugin     # PyPI (or: pip install -e . from a checkout)
hermes plugins enable librarian
hermes memory setup                         # prompts for endpoint + token (below)
```

Hermes discovers the plugin via the `hermes_agent.plugins` entry point — no manual copy
into `~/.hermes/plugins/` needed.

## Configure

`hermes memory setup` collects:

| Field | Required | Notes |
| --- | --- | --- |
| `endpoint` | yes | Librarian HTTP MCP URL, e.g. `https://librarian.example.com/mcp` |
| `token` | yes | Bearer token (stored as the `LIBRARIAN_AGENT_TOKEN` secret — never written to disk) |
| `agent_id` | no | Canonical agent id; omit if the token is agent-bound server-side |
| `project_key` | no | Default project scope |
| `timeout_ms` | no | Per-call timeout (default 15000) |

Non-secret values are stored under `<hermes_home>/librarian-plugin/config.json` (0600);
the token comes only from the `LIBRARIAN_AGENT_TOKEN` environment variable.

### Remote deployment (Hermes and the Librarian on different servers)

Serve the Librarian's HTTP MCP and point `endpoint` at it:

```sh
# on the Librarian host
LIBRARIAN_HOST=0.0.0.0 LIBRARIAN_AGENT_TOKENS="hermes:<strong-token>" pnpm run serve
```

Then set `endpoint` to your public URL (behind TLS) and `token` to `<strong-token>`. The
Librarian's no-auth mode is **localhost-only**, so a remote endpoint **must** carry a token
over **HTTPS**. (`LIBRARIAN_AGENT_TOKENS` binds the token to an `agent_id` server-side, so
attribution is correct without setting `agent_id` here.)

## Migrate built-in memory (one-time)

The Librarian coexists with Hermes' built-in memory (Hermes keeps the built-in active);
this plugin treats the Librarian as the source of truth and keeps the built-in minimal.
Import existing `MEMORY.md`/`USER.md` facts once:

```sh
hermes memory librarian-migrate
```

Each note becomes a memory (`MEMORY.md` → `lessons`, `USER.md` → `relationship`, the latter
routed to a proposal for review); a source file is emptied only if every entry imported, so
a partial failure never loses data.

## How it works

| Hermes hook | The Librarian | Notes |
| --- | --- | --- |
| `initialize` | — | local setup; session created lazily on the first recorded turn |
| `system_prompt_block` | `start_context` | frozen recall snapshot at session start (prefix-cache-friendly) |
| `prefetch` | `recall` | targeted recall before an API call |
| `sync_turn` | `start_session` (once) + `record_session_event` | non-blocking turn recording |
| `on_pre_compress` | `checkpoint_session` | checkpoint before compaction |
| `on_session_end` | `pause_session` | pause (never auto-end); detach locally |
| tools | `recall` / `remember` / `verify_memory` | agent-driven memory |

Two invariants:

- **Off-record** — say "off the record" / "don't remember this" (or `/lib-toggle-private`)
  and the `pre_gateway_dispatch` gate flips to private, ends the attached session with a
  neutral reason, and suppresses all Librarian calls until you go back on the record. The
  message still reaches the model — privacy means "don't record", not "don't answer".
- **Fail-soft** — if the Librarian is unreachable, a turn is never blocked: recall degrades
  to empty and writes are best-effort. (A remote store can be down; the built-in memory
  stays local.)

## Status / compatibility

Built and unit-tested against the Hermes plugin docs (`MemoryProvider` ABC,
`pre_gateway_dispatch`, `register`/`register_cli`, config schema). The exact ABC method
names/shapes, the `pre_gateway_dispatch` payload, and the CLI registration are **to be
confirmed against a real Hermes install** — the Librarian-facing mapping, privacy gating,
and fail-soft behaviour are fully covered by the test suite. Targets Python ≥ 3.10.

## Develop

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy && .venv/bin/pytest
```

## License

Apache-2.0.
