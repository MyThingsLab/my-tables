# my-tables

[![CI](https://github.com/MyThingsLab/my-tables/actions/workflows/ci.yml/badge.svg)](https://github.com/MyThingsLab/my-tables/actions/workflows/ci.yml) [![codecov](https://codecov.io/gh/MyThingsLab/my-tables/branch/main/graph/badge.svg)](https://codecov.io/gh/MyThingsLab/my-tables) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A [MyThingsLab](../my-things-core) `My[X]` tool: extracts every table from a
PDF into structured form — page number, cells (CSV + rendered Markdown), its
deterministically-located caption, and (only when the caption is missing or
unhelpful) a one-line Engine-written summary of what the table reports.

Design doc: [`my-things-core/docs/tools/my-tables.md`](../my-things-core/docs/tools/my-tables.md).
See [`CLAUDE.md`](CLAUDE.md) for the tool's Engine call, invariants, and
backlog label.

```bash
mytables run --engine noop   # or: python -m mytables run
```

is a safe end-to-end dry run: zero tokens, no branch, no PR, one honest
ledger entry.

## Install (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ../my-things-core -e ".[dev]"
pytest
```

## License

MIT — see [`LICENSE`](LICENSE).
