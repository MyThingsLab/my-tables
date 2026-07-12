from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from mythings.engine import Engine, EngineRequest, EngineResult
from mythings.github import GitHub, Issue
from mythings.ledger import Ledger
from mythings.policy import Policy
from mythings.tool import BaseToolRunner
from mythings.tool import ToolRunResult as Result

from mytables.extract import Table, extract_tables

TOOL = "mytables"
LEDGER_KIND = "table_extract"
BACKLOG_LABEL = "my-tables"

SYSTEM = (
    "You are given one or more tables extracted from a document page, each as "
    "CSV cells preceded by nearby page text for context. For each table, in "
    "the order given, write ONE line summarizing only what the table reports "
    "-- never invent values beyond the cells shown. Reply with strict JSON: "
    '{"summaries": ["...", ...]}, one entry per table, same order.'
)

_SOURCE_RE = re.compile(r"^\s*table-source:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(stem: str) -> str:
    return _SLUG_RE.sub("-", stem.lower()).strip("-") or "doc"


def _parse_source(body: str) -> str | None:
    match = _SOURCE_RE.search(body)
    return match.group(1) if match else None


def _render_index(doc_id: str, tables: list[Table], summaries: list[str]) -> str:
    rows = []
    for n, (table, summary) in enumerate(zip(tables, summaries, strict=True), start=1):
        caption = table.caption or summary
        rows.append(
            {
                "page": table.page,
                "bbox": list(table.bbox),
                "caption": caption,
                "summary": summary,
                "rows": table.rows,
                "cols": table.cols,
                "csv": f"p{table.page}-{n}.csv",
            }
        )
    return json.dumps({"doc_id": doc_id, "tables": rows}, indent=2, sort_keys=True) + "\n"


def _render_markdown(table: Table) -> str:
    if not table.cells:
        return ""
    header, *body = table.cells
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _render_readme(doc_id: str, tables: list[Table], summaries: list[str]) -> str:
    lines = [f"# Tables — {doc_id}", ""]
    for n, (table, summary) in enumerate(zip(tables, summaries, strict=True), start=1):
        caption = table.caption or summary or "(no caption or summary)"
        lines.append(f"## p{table.page}-{n}.csv (page {table.page})")
        lines.append("")
        lines.append(caption)
        lines.append("")
        lines.append(_render_markdown(table))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class Tool(BaseToolRunner):
    def __init__(
        self,
        *,
        repo: str | Path = ".",
        ledger: Ledger | None = None,
        github: GitHub | None = None,
        engine: Engine | None = None,
        policy: Policy | None = None,
        base: str = "main",
        label: str = BACKLOG_LABEL,
        git: Callable[[Path, list[str]], None] | None = None,
        extractor: Callable[[Path], list[Table]] = extract_tables,
    ) -> None:
        super().__init__(
            repo=repo,
            ledger=ledger,
            github=github,
            engine=engine,
            policy=policy,
            base=base,
            label=label,
            git=git,
        )
        self._extractor = extractor
        self._doc_id = ""
        self._tables: list[Table] = []
        self._gaps: list[Table] = []

    def prework(self, issue: Issue) -> str:
        source = _parse_source(issue.body)
        if source is None:
            return "no table-source: locator in issue body"

        path = Path(source)
        if not path.is_file():
            return f"table-source path does not exist: {source}"

        self._doc_id = _slug(path.stem)
        self._tables = self._extractor(path)
        self._gaps = [t for t in self._tables if not t.caption]
        return f"{len(self._tables)} table(s), {len(self._gaps)} needing a summary"

    def request(self, issue: Issue, context: str) -> EngineRequest:
        if not self._gaps:
            return EngineRequest(prompt="nothing to summarize", system=SYSTEM)

        lines = [f"{len(self._gaps)} table(s), in order:"]
        for n, table in enumerate(self._gaps, start=1):
            lines.append(f"{n}. page {table.page}, no caption found nearby.")
            lines.append(table.to_csv())
        return EngineRequest(prompt="\n".join(lines), system=SYSTEM)

    def apply(self, tree: Path, issue: Issue, result: EngineResult) -> str | None:
        if not self._tables:
            return None

        summaries_by_gap = self._parse_summaries(result.text)
        summaries: list[str] = []
        gap_iter = iter(summaries_by_gap)
        for table in self._tables:
            summaries.append("" if table.caption else next(gap_iter, ""))

        out_dir = tree / "tables" / self._doc_id
        out_dir.mkdir(parents=True, exist_ok=True)
        for n, table in enumerate(self._tables, start=1):
            (out_dir / f"p{table.page}-{n}.csv").write_text(table.to_csv(), encoding="utf-8")
        (out_dir / "index.json").write_text(
            _render_index(self._doc_id, self._tables, summaries), encoding="utf-8"
        )
        (out_dir / "README.md").write_text(
            _render_readme(self._doc_id, self._tables, summaries), encoding="utf-8"
        )
        return f"tables/{self._doc_id}"

    @staticmethod
    def _parse_summaries(text: str) -> list[str]:
        if not text:
            return []
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return []
        summaries = obj.get("summaries")
        if not isinstance(summaries, list):
            return []
        return [str(s) for s in summaries]

    def run(self, issue_number: int | None = None) -> Result:
        return self.run_issue_workflow(TOOL, LEDGER_KIND, issue_number)
