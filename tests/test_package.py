"""Scaffold-level package tests."""

from __future__ import annotations

import pytest

import the_librarian_hermes_plugin as plugin


def test_version_is_a_string() -> None:
    assert isinstance(plugin.__version__, str)
    assert plugin.__version__


def test_register_is_exported() -> None:
    assert callable(plugin.register)


def test_register_not_yet_wired() -> None:
    # The entry point resolves, but the wiring lands in a later increment.
    with pytest.raises(NotImplementedError):
        plugin.register(object())
