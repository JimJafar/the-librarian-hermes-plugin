"""Hermes Agent Memory Provider plugin backed by The Librarian.

The Hermes entry point is :func:`register`. Hermes calls it under TWO loaders,
each with a different context surface (see ``hermes_cli/plugins.py`` and
``plugins/memory/__init__.py``):

- the **memory-provider loader** (``hermes memory setup``) — its context has
  ``register_memory_provider`` but no-ops hooks/commands;
- the **general plugin loader** (``hermes plugins enable librarian``) — its
  ``PluginContext`` has ``register_hook``/``register_command``/
  ``register_cli_command`` but NO ``register_memory_provider``.

So ``register`` guards every call: each loader wires the parts it supports. The
two loaders build *separate* provider instances; they coordinate through the
shared per-profile state file (see the ``state`` module), and the gate/command
instance lazily resolves ``HERMES_HOME`` since only the memory loader calls
``initialize()``.
"""

from __future__ import annotations

import logging
from typing import Any

# NOTE: the submodule imports live inside register() (local imports), not at module
# scope. The repo root IS the plugin package, so generic Python tooling (pytest's
# collector, linters) may import this __init__ *without* a package context, where
# top-level ``from .x import`` would raise. Deferring them keeps a bare import of
# this file clean; at runtime register() always runs inside the package, so the
# relative imports resolve normally.

__version__ = "0.0.1"

__all__ = ["__version__", "register"]

_logger = logging.getLogger("the_librarian_hermes_plugin")
_LEVELS = {"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}


def _log(level: str, message: str) -> None:
    _logger.log(_LEVELS.get(level, logging.INFO), message)


def register(ctx: Any) -> None:
    """Hermes plugin entry point — wires whatever the calling loader supports.

    Every registration is guarded because the memory-provider loader and the
    general plugin loader expose disjoint context methods (see the module
    docstring); calling an absent one would abort the whole ``register``."""
    from .cli import register_cli
    from .commands import register_commands
    from .privacy_gate import make_privacy_gate
    from .provider import LibrarianProvider

    provider = LibrarianProvider(logger=_log)
    if hasattr(ctx, "register_memory_provider"):
        ctx.register_memory_provider(provider)
    if hasattr(ctx, "register_hook"):
        ctx.register_hook("pre_gateway_dispatch", make_privacy_gate(provider))
    register_commands(ctx, provider)  # no-op if ctx has no register_command
    register_cli(ctx)  # no-op if ctx has no register_cli_command
