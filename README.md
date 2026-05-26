# the-librarian-hermes-plugin

[![CI](https://github.com/JimJafar/the-librarian-hermes-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/JimJafar/the-librarian-hermes-plugin/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

A [Hermes Agent](https://hermes-agent.nousresearch.com) **Memory Provider plugin**
backed by [The Librarian](https://github.com/JimJafar/the-librarian) — durable
memory, sessions, and an off-record privacy gate, against a Librarian HTTP MCP
server you point at (local or remote).

## Features

- **Memory tools** — `recall` / `remember` / `verify_memory`, auto-scoped to the
  calling agent, with memory ids surfaced so the verify-after-recall loop works.
- **Session lifecycle** — every turn is recorded, with checkpoints around
  compaction and pause on session end.
- **Slash commands** — the full `/lib-session-*` suite plus `/lib-toggle-private`.
- **Off-record privacy gate** — say "off the record" (or run
  `/lib-toggle-private`) and recording stops until you go back on.
- **Fail-soft** — if the Librarian is unreachable, recall degrades to empty and
  writes are best-effort; a turn is never blocked.
- **Dependency-light** — stdlib `urllib` for HTTP, no extra runtime deps.

## Install

```sh
hermes plugins install JimJafar/the-librarian-hermes-plugin
hermes memory setup            # pick "librarian", enter the endpoint
hermes plugins enable librarian
hermes gateway restart
```

The first three steps wire the memory provider, save the endpoint + token, and
enable the privacy gate + slash commands. Requires Python ≥ 3.10.

## Configure

`hermes memory setup` collects:

| Field | Required | Notes |
| --- | --- | --- |
| `endpoint` | yes | Librarian HTTP MCP URL, e.g. `https://librarian.example.com/mcp` |
| `token` | yes | Bearer token (stored as `LIBRARIAN_AGENT_TOKEN` in `<hermes_home>/.env`; never written to the config file) |
| `agent_id` | no | Canonical agent id (omit if the token is agent-bound server-side) |
| `project_key` | no | Default project scope |
| `timeout_ms` | no | Per-call timeout (default 15000) |

### Remote Librarian

The Librarian's no-auth mode is **localhost-only**, so a remote endpoint **must**
carry a token over **HTTPS**. On the Librarian host:

```sh
LIBRARIAN_HOST=0.0.0.0 LIBRARIAN_AGENT_TOKENS="hermes:<strong-token>" pnpm run serve
```

Then enter `endpoint` and `token` to match in `hermes memory setup`.

## Slash commands

| Command | Effect |
| --- | --- |
| `/lib-session-start [title] [--private]` | Start a new session (or go off-record with `--private`) |
| `/lib-session-list [--include-ended]` | List resumable sessions |
| `/lib-session-resume [<session_id>]` | Resume a session (bare call shows the picker) |
| `/lib-session-checkpoint [summary]` | Checkpoint the attached session |
| `/lib-session-pause` | Pause and detach |
| `/lib-session-end [summary]` | End and detach |
| `/lib-session-search <query>` | Search session content |
| `/lib-toggle-private` | Toggle off-record (private) mode |

## Migrate built-in memory

Import existing `MEMORY.md` / `USER.md` notes into The Librarian once:

```sh
hermes memory librarian-migrate
```

Each line becomes a memory (`MEMORY.md` → `lessons`, `USER.md` →
`relationship` — the latter routed through a proposal for human review). A
source file is emptied only if every entry imported, so a partial failure never
loses data.

## Develop

```sh
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check . \
  && bash scripts/typecheck.sh && .venv/bin/pytest
```

## License

Apache-2.0.
