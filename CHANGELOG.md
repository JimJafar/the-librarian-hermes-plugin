# Changelog

All notable changes to **the-librarian-hermes-plugin** are documented in
this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This changelog starts at v0.0.1 — the first version likely to see public
adoption. The pre-v0.0.1 development history lives in the git log; only
changes from this point forward are catalogued here.

## [Unreleased]

## [0.3.1] — 2026-06-07

### Fixed

- **`plugin.yaml` `version` now matches the release tag.** The 0.3.0 release
  left `plugin.yaml` at `0.2.0` — the release docs wrongly stated Hermes had
  "no embedded version file." Bumped to `0.3.1`, and corrected `AGENTS.md` +
  `docs/release.md` so bumping `plugin.yaml`'s `version` is a required release
  step going forward.

## [0.3.0] — 2026-06-07

### Added

- **Awareness primer injected every turn (spec 041).** `prefetch()` now emits
  the operator-authored awareness primer as a `<librarian>` block on every turn,
  reminding the agent it has durable memory and which verbs to use. The primer
  is read from the same `conv_state_get` response (no extra call) and rendered
  byte-identically to the other Librarian plugins. It is emitted **independently
  of the conv-state row gate** — so the primer appears even on a brand-new
  conversation that has no conv-state row yet. An empty primer (operator opted
  out) renders nothing, and any Librarian/parse failure stays fail-soft (no
  block, the turn proceeds).

### Changed

- **Conv-state block trimmed to `conv_id` + `off_record` (lockstep).** The
  injected `<conversation-state>` block drops the retired `domain` and
  `session_id` lines, leaving only `conv_id` and `off_record`. This is a
  lockstep change with the Librarian server's conv-state shape. The conv-id
  lookup key (`hermes:<session_id>`) is unchanged.
- **Doc residue cleanup.** `AGENTS.md` and `README.md` drop the retired
  `/lib-session-*` slash-command tables/contract and the stale conv-state
  `domain` field; the cross-repo contract now lists the four handoff verbs
  (`/handoff`, `/takeover`, `/learn`, `/toggle-private`) and the
  `active | proposed | archived` memory state model. `commands.py` docstring
  reworded to reflect the retired session verbs.

## [0.2.0] — 2026-05-28

### Added

- **Release runbook + per-repo release doc.** A new
  [`docs/release.md`](docs/release.md) captures the per-repo release
  steps (no embedded version file — release is purely a git tag +
  GitHub release for traceability, since Hermes installs by
  directory clone). AGENTS.md is thinned and points at it; the
  cross-family runbook lives in the monorepo at
  [`the-librarian/docs/release-runbook.md`](https://github.com/JimJafar/the-librarian/blob/main/docs/release-runbook.md).

### Changed

- **Sessions rethink — breaking change (sessions-rethink PR 5).** The
  entire session subsystem retires. The Hermes plugin becomes a
  memory-only provider with four user-facing slash commands.
  - **Removed slash commands**: `/lib-session-start`, `/lib-session-list`,
    `/lib-session-resume`, `/lib-session-checkpoint`,
    `/lib-session-pause`, `/lib-session-end`, `/lib-session-search`,
    `/lib-toggle-private`.
  - **Added slash commands**: `/handoff`, `/takeover`, `/learn`,
    `/toggle-private`. Each surfaces a prompt that drives the LLM
    through the agent-side flow (Hermes' non-interactive command
    handlers can't run multi-step pickers directly).
  - **Removed hooks**: `pre_gateway_dispatch` (the natural-language
    privacy detector) is no longer registered. Private mode is now an
    in-conversation `[librarian:private=on|off]` marker the LLM
    handles via `/toggle-private`.
  - **Removed source**: `state.py` (per-profile local state file with
    its session attachment + privacy flag), `privacy.py` (marker
    detector), `privacy_gate.py` (gateway middleware). Their tests
    too.
  - **Provider rewritten**: ~750 → ~370 lines. Kept: config + client
    setup, recall / remember / verify_memory tool calls, conv-state
    injection in `prefetch` + `system_prompt_block`,
    `on_memory_write("add")` mirror. Dropped: every method that
    started/checkpointed/paused/ended a Librarian session, the
    privacy flag plumbing, `start_new_session` / `current_session_id`
    / `attach_session_id` / `detach`. ABC methods (`sync_turn`,
    `on_pre_compress`, `on_session_end`) become typed no-ops so
    Hermes' MemoryManager still has the interface it expects.
  - **Server compatibility**: requires a Librarian server running the
    sessions-rethink PR 1 build (the `store_handoff` / `list_handoffs`
    / `claim_handoff` and `conv_state_*` MCP tools must exist).
  - **Migration**: existing operators should restart Hermes after
    updating the plugin. The local `<hermes_home>/librarian-plugin/
    state.json` file the old plugin maintained becomes inert — safe to
    delete by hand.

### Added

- **Conv-state injection on every prefetch + system prompt.** Implements
  spec §4.9 of the upstream memory-domain-isolation rollout. The
  provider now calls `conv_state_get` on every `prefetch(query)` and
  `system_prompt_block()` (using `hermes:<session_id>` as the conv-id
  per spec §4.8) and prepends the canonical `<conversation-state>`
  block to the recall text when a row exists. The LLM sees the current
  `domain` / `session_id` / `off_record` on every turn, which defeats
  context-compaction-driven state loss. When no row exists or the
  Librarian fails, the block is omitted and the prefetch text reaches
  the model unchanged (AGENTS.md §2 fail-soft contract preserved).
  The privacy gate continues to suppress every Librarian call while
  off-record — the conv-state block is no exception.

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

[Unreleased]: https://github.com/JimJafar/the-librarian-hermes-plugin/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/JimJafar/the-librarian-hermes-plugin/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/JimJafar/the-librarian-hermes-plugin/compare/v0.0.1...v0.2.0
[0.0.1]: https://github.com/JimJafar/the-librarian-hermes-plugin/releases/tag/v0.0.1
