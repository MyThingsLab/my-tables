# my-tables — agent instructions

You are developing **my-tables**, a MyThingsLab My[X] tool.

**Inherited rules:** obey [`./HARNESS.md`](./HARNESS.md) in full — the vendored
MyThingsLab build-harness rules. Do not restate or override them. Anything not
covered here defers to `HARNESS.md`, then `my-things-core/docs/CONVENTIONS.md`.

## This tool

- **Purpose:** extracts every table from a PDF into structured form —
  page number, cells (CSV + rendered Markdown), its deterministically-located
  caption, and (only when the caption is missing or unhelpful) a one-line
  Engine-written summary of what the table reports — see the design doc:
  [`my-things-core/docs/tools/my-tables.md`](../my-things-core/docs/tools/my-tables.md).
- **The single Engine call:** optional, only for tables whose
  deterministically-located caption is missing or generic — "given this
  table's cells and the surrounding page text, write a one-line summary of
  what the table reports." Against `NoopEngine`, the table is still indexed
  with its cells and caption; `summary=""`.
- **Invariants / rules:** deterministic pre-work only (open the PDF with
  `pdfplumber`, run per-page table detection, discard degenerate
  single-row/column results below a fixed floor, regex-match a nearby
  "Table N" caption above the region) — the Engine call never gates whether
  a table gets indexed nor invents cell values, it only fills a caption gap.
  `pdfplumber` is this tool's own runtime dependency, not core's (core stays
  dependency-free). Triggered by an open `my-tables`-labeled issue
  (`table-source:<path>`), the same handoff shape MyArchivist already uses
  for MyBibliography — never a direct call into or import of MyArchivist.
  Writes `tables/<doc-id>/` (CSVs + `index.json` + a rendered README) inside
  a `Workspace` and opens exactly one PR per run, routed through `Policy`
  (`Guard` default). **Never merges.** Ledger `kind`: `table_extract`.
- **Backlog label:** `my-tables`

## Testing

Fakes come from `mythings.testing` (opt-in via `pytest_plugins` in
`tests/conftest.py`; see `my-things-core/docs/CONVENTIONS.md`, "Shared test
fixtures"). Never copy fixture code into a conftest — only domain-specific
helpers live there.
