"""Package + entry-point (register) tests.

Hermes calls register() under two loaders with disjoint context surfaces, so the
key property is that register() wires what each loader supports and never crashes
on the methods the other loader lacks.
"""

from __future__ import annotations

from typing import Any

import librarian as plugin
from librarian.provider import LibrarianProvider


class MemoryLoaderCtx:
    """Mirrors plugins/memory's _ProviderCollector: has register_memory_provider;
    register_hook/register_cli_command are no-ops; NO register_command."""

    def __init__(self) -> None:
        self.providers: list[Any] = []

    def register_memory_provider(self, provider: Any) -> None:
        self.providers.append(provider)

    def register_hook(self, *args: Any, **kwargs: Any) -> None:
        pass

    def register_cli_command(self, *args: Any, **kwargs: Any) -> None:
        pass


class GeneralLoaderCtx:
    """Mirrors hermes_cli PluginContext: has register_hook/register_command/
    register_cli_command but NO register_memory_provider."""

    def __init__(self) -> None:
        self.hooks: dict[str, Any] = {}
        self.commands: dict[str, Any] = {}

    def register_hook(self, event: str, callback: Any) -> None:
        self.hooks[event] = callback

    def register_command(self, name: str, handler: Any, **kwargs: Any) -> None:
        self.commands[name] = handler

    def register_cli_command(self, *args: Any, **kwargs: Any) -> None:
        pass


def test_version_is_a_string() -> None:
    assert isinstance(plugin.__version__, str)
    assert plugin.__version__


def test_register_is_exported() -> None:
    assert callable(plugin.register)


def test_memory_loader_gets_the_provider() -> None:
    ctx = MemoryLoaderCtx()
    plugin.register(ctx)  # must not raise despite no register_command
    assert len(ctx.providers) == 1
    assert isinstance(ctx.providers[0], LibrarianProvider)


def test_general_loader_gets_gate_and_commands() -> None:
    ctx = GeneralLoaderCtx()
    plugin.register(ctx)  # must not raise despite no register_memory_provider
    assert "pre_gateway_dispatch" in ctx.hooks
    assert callable(ctx.hooks["pre_gateway_dispatch"])
    assert "lib-toggle-private" in ctx.commands
    assert "lib-session-start" in ctx.commands
    assert len(ctx.commands) == 8


def test_gate_returns_allow_and_does_not_raise() -> None:
    ctx = GeneralLoaderCtx()
    plugin.register(ctx)
    # The gate drives privacy on its bound provider; assert it runs and returns
    # allow (None) on an ordinary message (no marker → no transition).
    assert ctx.hooks["pre_gateway_dispatch"](event="just a normal message") is None
