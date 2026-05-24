"""Package + entry-point (register) tests."""

from __future__ import annotations

from typing import Any

import the_librarian_hermes_plugin as plugin
from the_librarian_hermes_plugin.provider import LibrarianProvider


class FakeCtx:
    def __init__(self) -> None:
        self.providers: list[Any] = []
        self.hooks: dict[str, Any] = {}

    def register_memory_provider(self, provider: Any) -> None:
        self.providers.append(provider)

    def register_hook(self, event: str, callback: Any) -> None:
        self.hooks[event] = callback


def test_version_is_a_string() -> None:
    assert isinstance(plugin.__version__, str)
    assert plugin.__version__


def test_register_is_exported() -> None:
    assert callable(plugin.register)


def test_register_wires_provider_and_gate() -> None:
    ctx = FakeCtx()
    plugin.register(ctx)
    assert len(ctx.providers) == 1
    assert isinstance(ctx.providers[0], LibrarianProvider)
    assert "pre_gateway_dispatch" in ctx.hooks
    assert callable(ctx.hooks["pre_gateway_dispatch"])


def test_gate_is_bound_to_the_registered_provider() -> None:
    ctx = FakeCtx()
    plugin.register(ctx)
    provider = ctx.providers[0]
    calls: list[str] = []
    provider.enter_private = lambda: calls.append("enter") or "private"  # type: ignore[method-assign]
    ctx.hooks["pre_gateway_dispatch"]("off the record")
    assert calls == ["enter"]
