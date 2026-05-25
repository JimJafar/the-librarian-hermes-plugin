#!/usr/bin/env bash
# Type-check the flat plugin modules as the `librarian` package.
#
# The repo root *is* the plugin dir (so `hermes plugins install` drops it into
# ~/.hermes/plugins/librarian/), but the repo dir name is hyphenated and can't be
# a Python package name. The modules use package-relative imports, so mypy needs
# to see them under a valid package name: stage them into librarian/ and run
# `mypy -p librarian`. Config comes from [tool.mypy] in pyproject.toml.
set -euo pipefail
cd "$(dirname "$0")/.."

STAGE=".mypy-stage"
MODULES=(__init__.py cli.py client.py commands.py privacy.py privacy_gate.py provider.py state.py py.typed)

rm -rf "$STAGE"
mkdir -p "$STAGE/librarian"
cp "${MODULES[@]}" "$STAGE/librarian/"

MYPYPATH="$STAGE" mypy -p librarian "$@"
