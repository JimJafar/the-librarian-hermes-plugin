# Changelog

All notable changes to **the-librarian-hermes-plugin** are documented in
this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This changelog starts at v0.0.1 — the first version likely to see public
adoption. The pre-v0.0.1 development history lives in the git log; only
changes from this point forward are catalogued here.

## [Unreleased]

### Added

- `AGENTS.md` with the family-wide house rules (privacy, fail-soft,
  cross-repo contracts, CHANGELOG discipline, etc.) and the
  Hermes-plugin-specific build / test / gotcha notes. Sibling
  AGENTS.md files in the four other Librarian repos share the same
  baseline.

### Changed

- **AGENTS.md §2 and §4** updated: the canonical TS privacy-detector
  source in `the-librarian/integrations/shared/librarian-lifecycle/`
  was deleted when the family went fully standalone. `privacy.py`
  here is now one of five peer implementations across the family
  (Claude Code, Codex, this repo, OpenCode, Pi). Coordinate any
  marker-list change across all five repos.

## [0.0.1] — 2026-05-26

Public baseline. A [Hermes](https://github.com/NousResearch/hermes-agent)
memory-provider plugin for
[The Librarian](https://github.com/JimJafar/the-librarian) — durable memory
+ cross-harness session lifecycle, backed by a remote Librarian MCP server.

### Shipped in this baseline

- **Hermes `MemoryProvider`** subclass mapping `prefetch`, `sync_turn`,
  `on_pre_compress`, `handle_tool_call`, and the lifecycle verbs onto
  Librarian MCP tools (via `LibrarianClient`). Both invariants honoured:
  off-record means no Librarian call at all; a Librarian/network failure
  is logged and swallowed — a turn is never blocked, recall just degrades
  to empty.
- **`/lib-session-*` slash commands** registered programmatically via
  `ctx.register_command` (Hermes' native command interface). Each handler
  routes through the privacy-gated, fail-soft provider.
- **`pre_gateway_dispatch` privacy gate** — natural-language privacy
  markers detected synchronously before auth/dispatch; going private ends
  any attached session with a neutral reason and suppresses further
  recording until the user comes back on the record.
- **`hermes memory setup` integration** via `get_config_schema` — install-
  time secret prompt for `LIBRARIAN_AGENT_TOKEN`, endpoint collected
  through the setup flow.
- **Distribution** — `hermes plugins install` installs from this repo to
  `~/.hermes/plugins/librarian/`; `kind: standalone` is set explicitly so
  both the memory-provider loader AND the general plugin loader run
  `register()` (gate + slash commands).

[Unreleased]: https://github.com/JimJafar/the-librarian-hermes-plugin/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/JimJafar/the-librarian-hermes-plugin/releases/tag/v0.0.1
