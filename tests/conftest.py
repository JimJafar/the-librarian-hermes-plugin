"""Test bootstrap: load the flat plugin as the ``librarian`` package.

The repo root *is* the plugin directory (so ``hermes plugins install`` drops it
straight into ``~/.hermes/plugins/librarian/``), so there's an ``__init__.py`` at
the root. This conftest lives under ``tests/`` (which has no ``__init__.py``) on
purpose: a conftest beside the root ``__init__.py`` would make pytest treat the
repo dir as a package and try to import that ``__init__.py`` under the dir's
(hyphenated, invalid) name.

We load the package by path under the name ``librarian`` — pre-registering the
sibling modules in dependency order, exactly as Hermes'
``plugins/memory/_load_provider_from_dir`` does — so the package's relative
imports resolve from ``sys.modules`` and never hit pytest's meta-path hook (which
otherwise mis-resolves on-demand submodule imports). Tests then
``from librarian.X import Y`` without anything being installed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PKG = "librarian"

# Topological order: leaves first, then modules that import them, then __init__.
_SIBLINGS = ("client", "state", "privacy", "provider", "privacy_gate", "cli", "commands")


def _load_package() -> None:
    if _PKG in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(
        _PKG, _ROOT / "__init__.py", submodule_search_locations=[str(_ROOT)]
    )
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    sys.modules[_PKG] = package

    for stem in _SIBLINGS:
        sub_name = f"{_PKG}.{stem}"
        sub_spec = importlib.util.spec_from_file_location(sub_name, _ROOT / f"{stem}.py")
        assert sub_spec is not None and sub_spec.loader is not None
        sub_module = importlib.util.module_from_spec(sub_spec)
        sys.modules[sub_name] = sub_module
        sub_spec.loader.exec_module(sub_module)

    spec.loader.exec_module(package)


_load_package()
