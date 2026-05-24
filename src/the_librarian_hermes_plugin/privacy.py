"""Privacy-marker detection — a faithful Python port of the canonical TypeScript
source at ``the-librarian/integrations/shared/librarian-lifecycle/src/privacy.ts``.

Pure, dependency-free phrase matching. The plugin runs this *before* any Librarian
call to decide whether the current prompt is off-record. Exact / near-exact phrase
matching only (never a semantic classifier): a missed marker leaks nothing on its
own, but a false positive on ordinary prose would silently stop recording.

The marker lists here MUST stay in sync with the TS source (there is no shared
runtime). The parity tests mirror ``privacy.test.ts`` to catch drift.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

# Default enter-private phrases (§3.3).
DEFAULT_PRIVATE_MARKERS: tuple[str, ...] = (
    "this is a private session",
    "don't remember this",
    "do not remember this",
    "don't save this",
    "do not save this",
    "don't store this",
    "off the record",
    "keep this between us",
    "private from here",
)

# Default exit-private phrases (§3.3).
DEFAULT_PUBLIC_MARKERS: tuple[str, ...] = (
    "you can remember again",
    "end private mode",
    "back on the record",
    "this can be remembered",
)

# The pure toggle command, in both the colon and hyphen renderings (§3.1).
TOGGLE_COMMANDS: tuple[str, ...] = ("/lib-toggle-private", "/lib:toggle-private")

PrivacySignal = Literal["enter-private", "exit-private", "toggle", "none"]

# Trailing punctuation ("off the record.") is not substantive; real content is.
# The 3-char floor lets short filler read as a bare marker while any genuine
# instruction trips it. Both directions of error fail safe: over-reporting means
# we decline to record the current turn (the private-biased choice for §3.3).
_SUBSTANTIVE_MIN_CHARS = 3
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class PrivacyDetection:
    signal: PrivacySignal
    matched: str | None = None
    has_substantive_content: bool = False


def _normalise(text: str) -> str:
    """Lowercase and fold smart apostrophes to ASCII so smart-quoted contractions
    match the straight-quoted marker list."""
    folded = unicodedata.normalize("NFKC", text).replace("‘", "'").replace("’", "'")
    return folded.lower()


def _has_substantive_remainder(normalised_prompt: str, normalised_marker: str) -> bool:
    # Removing only the first occurrence is deliberate: if a marker repeats, the
    # leftover copies inflate the count toward "substantive" — i.e. toward not
    # recording the turn, the safe direction.
    idx = normalised_prompt.find(normalised_marker)
    if idx == -1:
        without = normalised_prompt
    else:
        without = f"{normalised_prompt[:idx]} {normalised_prompt[idx + len(normalised_marker) :]}"
    return len(_NON_ALNUM.sub("", without)) >= _SUBSTANTIVE_MIN_CHARS


def _first_match(normalised_prompt: str, markers: tuple[str, ...] | list[str]) -> str | None:
    # Returns a matching marker (first in list order, not necessarily first by
    # position). Only `signal` drives behaviour; `matched` is for neutral logging.
    for marker in markers:
        if _normalise(marker) in normalised_prompt:
            return marker
    return None


def detect_privacy_signal(
    prompt: str,
    *,
    private_markers: tuple[str, ...] | list[str] | None = None,
    public_markers: tuple[str, ...] | list[str] | None = None,
) -> PrivacyDetection:
    """Classify a prompt's privacy intent. Private markers take precedence over exit
    markers in the same prompt (fail toward privacy, §3.3). A pure
    ``/lib-toggle-private`` command is ``toggle``; the same string embedded in prose
    is not."""
    normalised = _normalise(prompt)
    trimmed = normalised.strip()

    if trimmed in TOGGLE_COMMANDS:
        return PrivacyDetection("toggle", trimmed, False)

    privates = private_markers if private_markers is not None else DEFAULT_PRIVATE_MARKERS
    enter = _first_match(normalised, privates)
    if enter is not None:
        return PrivacyDetection(
            "enter-private", enter, _has_substantive_remainder(normalised, _normalise(enter))
        )

    publics = public_markers if public_markers is not None else DEFAULT_PUBLIC_MARKERS
    exit_ = _first_match(normalised, publics)
    if exit_ is not None:
        return PrivacyDetection(
            "exit-private", exit_, _has_substantive_remainder(normalised, _normalise(exit_))
        )

    return PrivacyDetection("none", None, False)
