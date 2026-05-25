# the-librarian-hermes-plugin

A [Hermes Agent](https://hermes-agent.nousresearch.com) **Memory Provider plugin** backed
by [The Librarian](https://github.com/JimJafar/the-librarian).

It makes The Librarian the agent's durable memory + session layer: recall is injected at
session start and on demand, the agent can `recall`/`remember`/`verify_memory` via tools,
each turn is recorded to a Librarian session, `/lib-session-*` slash commands drive the
session lifecycle, and an off-record privacy gate suppresses recording on request. It talks
to a Librarian **HTTP MCP server at a configurable endpoint**, so Hermes and the Librarian
can live on different servers.

## Install

Hermes discovers memory providers by **directory scan** (`~/.hermes/plugins/<name>/`), not
via pip — so this repo IS the plugin directory (modules at the repo root). Install it with
Hermes' git-based installer:

```sh
hermes plugins install JimJafar/the-librarian-hermes-plugin
```

This clones the repo into `~/.hermes/plugins/librarian/` (the dir name comes from `name:` in
`plugin.yaml`, not the repo name) and prompts for the `LIBRARIAN_AGENT_TOKEN` secret.

Then wire it up — there are **two activation steps**, because Hermes loads the plugin under
two loaders:

```sh
hermes memory setup            # select "librarian", enter the endpoint (provider half)
hermes plugins enable librarian  # privacy gate + /lib-session-* slash commands (general half)
```

`hermes memory setup` activates the **memory provider** (recall/remember/turn recording).
`hermes plugins enable librarian` registers the **`pre_gateway_dispatch` privacy gate** and
the **slash commands** — these don't load from `hermes memory setup` alone.

## Configure

`hermes memory setup` collects:

| Field | Required | Notes |
| --- | --- | --- |
| `endpoint` | yes | Librarian HTTP MCP URL, e.g. `https://librarian.example.com/mcp` |
| `token` | yes | Bearer token (the `LIBRARIAN_AGENT_TOKEN` secret → `<hermes_home>/.env`; never written to the config file) |
| `agent_id` | no | Canonical agent id; omit if the token is agent-bound server-side |
| `project_key` | no | Default project scope |
| `timeout_ms` | no | Per-call timeout (default 15000) |

Non-secret values are stored under `<hermes_home>/librarian-plugin/config.json` (0600); the
token comes only from the `LIBRARIAN_AGENT_TOKEN` environment variable (written to
`<hermes_home>/.env` by setup).

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

## Slash commands

Registered when the plugin is enabled as a general plugin (`hermes plugins enable librarian`):

| Command | The Librarian | Notes |
| --- | --- | --- |
| `/lib-session-start [title] [--private]` | `start_session` | `--private` goes off-record instead |
| `/lib-session-list [--include-ended]` | `list_sessions` | |
| `/lib-session-resume <session_id>` | `continue_session` (+ attach) | bare call lists sessions to pick from |
| `/lib-session-checkpoint [summary]` | `checkpoint_session` | needs an attached session |
| `/lib-session-pause` | `pause_session` | then detaches |
| `/lib-session-end [summary]` | `end_session` | then detaches |
| `/lib-session-search <query>` | `search_sessions` | |
| `/lib-toggle-private` | (local) | toggle off-record mode |

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
| `prefetch(query, *, session_id)` | `recall` | targeted recall before an API call |
| `sync_turn(user, asst, *, session_id)` | `start_session` (once) + `record_session_event` | non-blocking turn recording |
| `on_pre_compress` | `checkpoint_session` | checkpoint before compaction (returns `""`) |
| `on_session_switch` | (local) | re-points `source_ref`; detaches on `reset` |
| `on_session_end` | `pause_session` | pause (never auto-end); detach locally |
| `on_memory_write(add)` | `remember` | mirror built-in `add` writes |
| tools | `recall` / `remember` / `verify_memory` | agent-driven memory |
| `pre_gateway_dispatch` | (local) | the off-record privacy gate |

Two invariants:

- **Off-record** — say "off the record" / "don't remember this" (or `/lib-toggle-private`)
  and the `pre_gateway_dispatch` gate flips to private, ends the attached session with a
  neutral reason, and suppresses all Librarian calls until you go back on the record. The
  message still reaches the model — privacy means "don't record", not "don't answer".
- **Fail-soft** — if the Librarian is unreachable, a turn is never blocked: recall degrades
  to empty and writes are best-effort. (A remote store can be down; the built-in memory
  stays local.)

### Two loaders, one state file

Hermes loads the plugin twice — the **memory-provider loader** (`hermes memory setup`)
builds the provider it drives; the **general plugin loader** (`hermes plugins enable`) builds
a separate instance for the gate + slash commands and never calls `initialize()`. Those are
different objects in the same process, and Hermes exposes no way to share one. They
coordinate through a single per-profile state file (`<hermes_home>/librarian-plugin/
state.json`), and the gate/command instance lazily resolves `HERMES_HOME`. The trade-off:
**one active Librarian session per profile**, not per concurrent Hermes session.

## Status / compatibility

Method names/shapes are matched against `agent/memory_provider.py`, `hermes_cli/plugins.py`,
`gateway/run.py`, and `plugins/memory/__init__.py` in
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent); the
Librarian-facing mapping, privacy gating, slash commands, and fail-soft behaviour are
covered by the test suite. Live end-to-end behaviour (a real recall round-trip and that the
gate fires) is best confirmed on a running Hermes. Targets Python ≥ 3.10.

## Develop

```sh
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check . && bash scripts/typecheck.sh && .venv/bin/pytest
```

## License

Apache-2.0.
