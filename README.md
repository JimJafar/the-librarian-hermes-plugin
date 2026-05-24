# the-librarian-hermes-plugin

A [Hermes Agent](https://hermes-agent.nousresearch.com) **Memory Provider plugin** backed
by [The Librarian](https://github.com/JimJafar/the-librarian).

It makes The Librarian the agent's durable memory + session layer: recall is injected at
session start, the agent can `remember`/`recall` via tools, turns are recorded to a
Librarian session, and an off-record privacy gate suppresses recording on demand. It talks
to a Librarian HTTP MCP server at a **configurable endpoint** (Hermes and the Librarian can
live on different servers), and coexists with Hermes' built-in memory while keeping it
minimal.

> Status: scaffolding. See the build for the full plugin (provider, privacy gate, client,
> migration CLI).
