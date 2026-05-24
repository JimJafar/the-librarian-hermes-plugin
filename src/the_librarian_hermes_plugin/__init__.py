"""Hermes Agent Memory Provider plugin backed by The Librarian.

The Hermes entry point is :func:`register`, discovered via the
``hermes_agent.plugins`` entry-point group. It registers a Librarian-backed
memory provider and the ``pre_gateway_dispatch`` privacy gate (bound to the same
provider instance, so the gate's privacy transitions act on the provider's state
and session).
"""

from __future__ import annotations

import logging
from typing import Any

from .privacy_gate import make_privacy_gate
from .provider import LibrarianProvider

__version__ = "0.0.1"

__all__ = ["__version__", "register"]

_logger = logging.getLogger("the_librarian_hermes_plugin")
_LEVELS = {"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}


def _log(level: str, message: str) -> None:
    _logger.log(_LEVELS.get(level, logging.INFO), message)


def register(ctx: Any) -> None:
    """Hermes plugin entry point. Registers the Librarian memory provider plus the
    privacy gate on the same provider instance."""
    provider = LibrarianProvider(logger=_log)
    ctx.register_memory_provider(provider)
    ctx.register_hook("pre_gateway_dispatch", make_privacy_gate(provider))
