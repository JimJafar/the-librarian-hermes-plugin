"""Hermes Agent Memory Provider plugin backed by The Librarian.

The Hermes entry point is :func:`register`, discovered via the
``hermes_agent.plugins`` entry-point group. It wires a Librarian-backed memory
provider plus a privacy gate. The wiring is filled in over later build
increments; this scaffold establishes the package + entry point.
"""

from __future__ import annotations

__version__ = "0.0.1"

__all__ = ["__version__", "register"]


def register(ctx: object) -> None:
    """Hermes plugin entry point.

    Will register the Librarian memory provider (``ctx.register_memory_provider``)
    and the ``pre_gateway_dispatch`` privacy gate. Implemented in a later
    increment; raising keeps a half-wired plugin from silently doing nothing.
    """
    raise NotImplementedError("register() is wired in a later build increment")
