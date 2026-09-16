from __future__ import annotations

import json
from pathlib import Path

import pytest
from mythings.engine import EngineRequest, EngineResult, NoopEngine
from mythings.github import GitHub
from mythings.ledger import Ledger, LedgerEntry
from mythings.policy import Action, Decision, PolicyResult
from mythings.testing import FakeGh, GitRepo, make_git_repo

from mytables.extract import Table
from mytables.tool import LEDGER_KIND, TOOL, Tool, _run_git


def gh_for(issues: list[dict] | None = None) -> FakeGh:
    return FakeGh(
        {
            ("issue", "list"): json.dumps(issues or []),
            ("pr", "create"): "https://github.com/o/r/pull/7\n",
        }
    )


def issue_obj(number: int = 1, body: str = "table-source:/tmp/does-not-exist.pdf") -> dict:
    return {
        "number": number,
        "title": "extract tables",
        "body": body,
        "url": f"https://github.com/o/r/issues/{number}",
        "labels": [{"name": "my-tables"}],
    }


@pytest.fixture()
def clone(tmp_path: Path) -> GitRepo:
    return make_git_repo(tmp_path, files={"README.md": "seed\n"})


def make_tool(
    clone: GitRepo,
    tmp_path: Path,
    runner: FakeGh,
    *,
    extractor,
    engine=None,
    real_git: bool = False,
    **kwargs,
):
    git_calls: list[tuple[Path, list[str]]] = []

    def git(tree: Path, argv: list[str]) -> None:
        git_calls.append((tree, argv))
        if real_git:
            _run_git(tree, argv)

    tool = Tool(
        repo=clone.path,
        ledger=Ledger(tmp_path / "ledger.jsonl"),
        github=GitHub("o/r", runner=runner),
        engine=engine or NoopEngine(),
        git=git,
        extractor=extractor,
        **kwargs,
    )
    return tool, git_calls


def ledger_entries(tmp_path: Path) -> list[LedgerEntry]:
    path = tmp_path / "ledger.jsonl"
    return [LedgerEntry.from_json(line) for line in path.read_text().splitlines()]


def test_no_labeled_issue_is_skipped(clone: GitRepo, tmp_path: Path) -> None:
    runner = gh_for(issues=[])
    tool, _ = make_tool(clone, tmp_path, runner, extractor=lambda p: [])
    result = tool.run()
    assert result.outcome == "skipped"
    (entry,) = ledger_entries(tmp_path)
    assert (entry.tool, entry.kind, entry.outcome) == (TOOL, LEDGER_KIND, "skipped")


def test_unknown_issue_number_is_skipped(clone: GitRepo, tmp_path: Path) -> None:
    runner = gh_for(issues=[issue_obj(number=4)])
    tool, _ = make_tool(clone, tmp_path, runner, extractor=lambda p: [])
    assert tool.run(issue_number=99).outcome == "skipped"


def test_missing_table_source_locator_is_a_noop(clone: GitRepo, tmp_path: Path) -> None:
    runner = gh_for(issues=[issue_obj(body="no locator here")])
    tool, git_calls = make_tool(clone, tmp_path, runner, extractor=lambda p: [])
    result = tool.run()
    assert result.outcome == "noop"
    assert not git_calls


class _FakeExtractor:
    def __init__(self, tables: list[Table]) -> None:
        self.tables = tables
        self.paths: list[Path] = []

    def __call__(self, path: Path) -> list[Table]:
        self.paths.append(path)
        return self.tables


def test_happy_path_deterministic_caption_no_engine_call(
    clone: GitRepo, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    # A table with a deterministic caption never needs the Engine.
    source = tmp_path_factory.mktemp("src") / "book.pdf"
    source.write_bytes(b"%PDF fake")
    tables = [
        Table(
            page=1,
            bbox=(0, 0, 10, 10),
            cells=(("Name", "Score"), ("Alice", "90")),
            caption="Table 1: scores",
        )
    ]
    extractor = _FakeExtractor(tables)

    runner = gh_for(issues=[issue_obj(body=f"table-source:{source}")])
    tool, git_calls = make_tool(
        clone, tmp_path, runner, extractor=extractor, engine=NoopEngine(), real_git=True
    )
    result = tool.run()

    assert result.outcome == "success"
    assert extractor.paths == [source]
    ops = [argv[0] for _, argv in git_calls]
    assert ops == ["checkout", "add", "commit", "push"]
    add_path = git_calls[1][1][1]
    assert add_path == "tables/book"

    index = json.loads(clone.read_committed("my-tables/1", "tables/book/index.json"))
    assert index["tables"][0]["caption"] == "Table 1: scores"
    assert index["tables"][0]["rows"] == 2
    assert index["tables"][0]["cols"] == 2


def test_missing_caption_triggers_one_engine_call_with_cells(
    clone: GitRepo, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    source = tmp_path_factory.mktemp("src") / "book.pdf"
    source.write_bytes(b"%PDF fake")
    tables = [
        Table(page=1, bbox=(0, 0, 10, 10), cells=(("a", "b"), ("1", "2")), caption=""),
        Table(page=2, bbox=(0, 0, 10, 10), cells=(("c", "d"), ("3", "4")), caption="Table 2: ok"),
        Table(page=3, bbox=(0, 0, 10, 10), cells=(("e", "f"), ("5", "6")), caption=""),
    ]
    extractor = _FakeExtractor(tables)

    class ScriptedEngine:
        def __init__(self) -> None:
            self.calls = 0
            self.seen: EngineRequest | None = None

        def run(self, request: EngineRequest) -> EngineResult:
            self.calls += 1
            self.seen = request
            return EngineResult(text=json.dumps({"summaries": ["first table", "third table"]}))

    engine = ScriptedEngine()
    runner = gh_for(issues=[issue_obj(body=f"table-source:{source}")])
    tool, git_calls = make_tool(
        clone, tmp_path, runner, extractor=extractor, engine=engine, real_git=True
    )
    result = tool.run()

    assert result.outcome == "success"
    assert engine.calls == 1  # exactly one Engine call per run
    assert engine.seen is not None
    assert "2 table(s)" in engine.seen.prompt

    index = json.loads(clone.read_committed("my-tables/1", "tables/book/index.json"))
    rows = {row["csv"]: row for row in index["tables"]}
    assert rows["p1-1.csv"]["summary"] == "first table"
    assert rows["p1-1.csv"]["caption"] == "first table"  # no deterministic caption -> falls back
    assert rows["p2-2.csv"]["caption"] == "Table 2: ok"
    assert rows["p2-2.csv"]["summary"] == ""  # had a caption -> never asked
    assert rows["p3-3.csv"]["summary"] == "third table"


def test_no_tables_found_is_a_noop(
    clone: GitRepo, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    source = tmp_path_factory.mktemp("src") / "book.pdf"
    source.write_bytes(b"%PDF fake")
    runner = gh_for(issues=[issue_obj(body=f"table-source:{source}")])
    tool, git_calls = make_tool(clone, tmp_path, runner, extractor=lambda p: [])
    result = tool.run()
    assert result.outcome == "noop"
    assert not git_calls
    (entry,) = [e for e in ledger_entries(tmp_path) if e.outcome == "noop"]
    assert entry.detail == "nothing to change for #1"


def test_nonexistent_source_path_is_a_noop(clone: GitRepo, tmp_path: Path) -> None:
    runner = gh_for(issues=[issue_obj(body="table-source:/nowhere/nothing.pdf")])
    tool, git_calls = make_tool(clone, tmp_path, runner, extractor=lambda p: [])
    result = tool.run()
    assert result.outcome == "noop"
    assert not git_calls


def test_noop_engine_still_indexes_tables_with_empty_summaries(
    clone: GitRepo, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    source = tmp_path_factory.mktemp("src") / "book.pdf"
    source.write_bytes(b"%PDF fake")
    tables = [Table(page=1, bbox=(0, 0, 10, 10), cells=(("a",), ("1",)), caption="")]
    extractor = _FakeExtractor(tables)
    runner = gh_for(issues=[issue_obj(body=f"table-source:{source}")])
    tool, _ = make_tool(
        clone, tmp_path, runner, extractor=extractor, engine=NoopEngine(), real_git=True
    )
    result = tool.run()

    assert result.outcome == "success"
    index = json.loads(clone.read_committed("my-tables/1", "tables/book/index.json"))
    assert index["tables"][0]["summary"] == ""
    assert index["tables"][0]["caption"] == ""


class AskPolicy:
    def evaluate(self, action: Action) -> PolicyResult:
        return PolicyResult(Decision.ASK, reason="needs a human")


def test_ask_fails_closed_unattended(
    clone: GitRepo,
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    source = tmp_path_factory.mktemp("src") / "book.pdf"
    source.write_bytes(b"%PDF fake")
    tables = [Table(page=1, bbox=(0, 0, 10, 10), cells=(("a", "b"), ("1", "2")), caption="ok")]
    runner = gh_for(issues=[issue_obj(body=f"table-source:{source}")])
    tool, git_calls = make_tool(
        clone,
        tmp_path,
        runner,
        extractor=_FakeExtractor(tables),
        engine=NoopEngine(),
        policy=AskPolicy(),
    )
    result = tool.run()
    assert result.outcome == "denied"
    assert not git_calls
    assert not runner.saw("pr", "create")
