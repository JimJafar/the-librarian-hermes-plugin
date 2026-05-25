"""Parity tests for the ported privacy-marker detector.

Mirrors the canonical TypeScript cases in
the-librarian/integrations/shared/librarian-lifecycle/tests/privacy.test.ts so the
two implementations stay in lockstep.
"""

from __future__ import annotations

from librarian.privacy import (
    DEFAULT_PRIVATE_MARKERS,
    DEFAULT_PUBLIC_MARKERS,
    detect_privacy_signal,
)


def test_each_private_marker_alone() -> None:
    for marker in DEFAULT_PRIVATE_MARKERS:
        d = detect_privacy_signal(marker)
        assert d.signal == "enter-private", marker
        assert d.matched == marker


def test_private_marker_with_substantive_content() -> None:
    d = detect_privacy_signal("off the record, my api key is abc123 — what do you think?")
    assert d.signal == "enter-private"
    assert d.has_substantive_content is True


def test_bare_private_marker_has_no_substantive_content() -> None:
    d = detect_privacy_signal("  Off The Record.  ")
    assert d.signal == "enter-private"
    assert d.has_substantive_content is False


def test_curly_apostrophe_matches() -> None:
    d = detect_privacy_signal("don’t remember this")
    assert d.signal == "enter-private"


def test_each_public_marker_alone() -> None:
    for marker in DEFAULT_PUBLIC_MARKERS:
        d = detect_privacy_signal(marker)
        assert d.signal == "exit-private", marker


def test_exit_marker_with_trailing_content() -> None:
    d = detect_privacy_signal("you can remember again — let's get back to the refactor")
    assert d.signal == "exit-private"
    assert d.has_substantive_content is True


def test_bare_exit_marker_sub_threshold_punctuation() -> None:
    d = detect_privacy_signal("end private mode!")
    assert d.signal == "exit-private"
    assert d.has_substantive_content is False


def test_toggle_hyphen_and_colon_forms() -> None:
    assert detect_privacy_signal("/lib-toggle-private").signal == "toggle"
    assert detect_privacy_signal("  /lib:toggle-private  ").signal == "toggle"


def test_toggle_embedded_in_prose_is_not_a_toggle() -> None:
    assert detect_privacy_signal("run /lib-toggle-private to flip mode").signal == "none"


def test_no_false_positive_on_unrelated_prose() -> None:
    d = detect_privacy_signal("Please refactor the private fields in this class to be readonly.")
    assert d.signal == "none"


def test_empty_prompt_is_none() -> None:
    assert detect_privacy_signal("").signal == "none"


def test_private_takes_precedence_over_exit() -> None:
    d = detect_privacy_signal("you can remember again but actually keep this between us")
    assert d.signal == "enter-private"


def test_custom_markers_are_honoured() -> None:
    d = detect_privacy_signal("zip it", private_markers=["zip it"], public_markers=["unzip"])
    assert d.signal == "enter-private"
