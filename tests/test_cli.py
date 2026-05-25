"""Migration CLI tests (built-in MEMORY.md/USER.md → Librarian)."""

from __future__ import annotations

from pathlib import Path

from librarian.cli import migrate, register_cli
from librarian.client import LibrarianClientError


class FakeClient:
    def __init__(self, fail_bodies: set[str] | None = None):
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._fail = fail_bodies or set()

    def call_tool(self, name: str, arguments: dict[str, object]) -> str:
        self.calls.append((name, dict(arguments)))
        if arguments.get("body") in self._fail:
            raise LibrarianClientError("network", "down")
        return "ok"


def _write(tmp_path: Path, memory: str | None = None, user: str | None = None) -> None:
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir(parents=True, exist_ok=True)
    if memory is not None:
        (mem_dir / "MEMORY.md").write_text(memory, encoding="utf-8")
    if user is not None:
        (mem_dir / "USER.md").write_text(user, encoding="utf-8")


def test_imports_entries_with_categories_and_empties_files(tmp_path: Path) -> None:
    _write(
        tmp_path,
        memory="# Agent notes\n- Uses pnpm not npm\n- CI runs on push\n",
        user="# User\n- Prefers concise answers\n",
    )
    client = FakeClient()
    result = migrate(str(tmp_path), client)

    assert result.imported == 3
    bodies = {args["body"]: args["category"] for _, args in client.calls}
    assert bodies["Uses pnpm not npm"] == "lessons"
    assert bodies["CI runs on push"] == "lessons"
    assert bodies["Prefers concise answers"] == "relationship"
    # Files emptied after a clean import.
    assert (tmp_path / "memories" / "MEMORY.md").read_text() == ""
    assert (tmp_path / "memories" / "USER.md").read_text() == ""
    assert set(result.emptied) == {"MEMORY.md", "USER.md"}


def test_strips_bullets_skips_headings_and_short_lines(tmp_path: Path) -> None:
    _write(tmp_path, memory="# Heading\n\n* a bullet fact\n- second fact\nx\n")
    client = FakeClient()
    migrate(str(tmp_path), client)
    bodies = [args["body"] for _, args in client.calls]
    assert "a bullet fact" in bodies  # "* " stripped
    assert "second fact" in bodies  # "- " stripped
    assert "x" not in bodies  # below the 3-char floor


def test_dry_run_counts_without_writing(tmp_path: Path) -> None:
    _write(tmp_path, memory="- one\n- two\n")
    client = FakeClient()
    result = migrate(str(tmp_path), client, dry_run=True)
    assert result.imported == 2
    assert client.calls == []
    assert (tmp_path / "memories" / "MEMORY.md").read_text() != ""  # untouched


def test_missing_files_is_noop(tmp_path: Path) -> None:
    (tmp_path / "memories").mkdir()
    client = FakeClient()
    result = migrate(str(tmp_path), client)
    assert result.imported == 0
    assert client.calls == []


def test_partial_failure_leaves_that_file_intact(tmp_path: Path) -> None:
    _write(tmp_path, memory="- good fact\n", user="- doomed fact\n")
    client = FakeClient(fail_bodies={"doomed fact"})
    result = migrate(str(tmp_path), client)

    assert result.imported == 1
    assert result.failed == 1
    # MEMORY.md imported cleanly → emptied; USER.md had a failure → left intact.
    assert (tmp_path / "memories" / "MEMORY.md").read_text() == ""
    assert (tmp_path / "memories" / "USER.md").read_text() != ""
    assert result.emptied == ["MEMORY.md"]
    assert result.skipped_files == ["USER.md"]


def test_agent_id_injected_when_provided(tmp_path: Path) -> None:
    _write(tmp_path, memory="- a fact\n")
    client = FakeClient()
    migrate(str(tmp_path), client, agent_id="hermes")
    _, args = client.calls[0]
    assert args["agent_id"] == "hermes"


def test_summary_text(tmp_path: Path) -> None:
    _write(tmp_path, memory="- a fact\n")
    result = migrate(str(tmp_path), FakeClient())
    assert "imported 1" in result.summary()
    assert "MEMORY.md" in result.summary()


def test_register_cli_is_a_noop_without_register_cli_command() -> None:
    class BareCtx:
        pass

    register_cli(BareCtx())  # must not raise


def test_register_cli_registers_when_supported() -> None:
    registered: list[str] = []

    class Ctx:
        def register_cli_command(self, *, name: str, **_kwargs: object) -> None:
            registered.append(name)

    register_cli(Ctx())
    assert registered == ["librarian-migrate"]
