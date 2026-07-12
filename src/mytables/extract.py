from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

# "Table N" at the start of a text line -- deterministic caption match, never
# an Engine judgment call. See my-things-core/docs/tools/my-tables.md.
_CAPTION_RE = re.compile(r"^\s*Table\s*\d+\b", re.IGNORECASE)

# Vertical search window (PDF points) to look for a caption immediately above
# (or, failing that, below) a table's bounding box. Table captions
# conventionally sit above, the mirror of MyFigure's below-first search.
_CAPTION_GAP = 40.0
_CAPTION_OVERLAP_SLACK = 15.0

# A single row or single column is usually a text-layout artifact (a bullet
# list, a two-column heading), not a table -- discard below this floor.
DEFAULT_MIN_ROWS = 2
DEFAULT_MIN_COLS = 2


@dataclass(frozen=True)
class Table:
    page: int  # 1-indexed, matching how a human would cite the page
    bbox: tuple[float, float, float, float]
    cells: tuple[tuple[str, ...], ...]  # rows of cells, "" for a blank cell
    caption: str  # "" when no deterministic match was found

    @property
    def rows(self) -> int:
        return len(self.cells)

    @property
    def cols(self) -> int:
        return len(self.cells[0]) if self.cells else 0

    def to_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in self.cells:
            writer.writerow(row)
        return buf.getvalue()


def _find_caption(words: list[dict], bbox: tuple[float, float, float, float]) -> str:
    x0, y0, x1, y1 = bbox
    lines: dict[int, list[dict]] = {}
    for word in words:
        lines.setdefault(round(word["top"]), []).append(word)

    below = ""
    for _top, line_words in sorted(lines.items()):
        line_words.sort(key=lambda w: w["x0"])
        line = " ".join(w["text"] for w in line_words).strip()
        if not line or not _CAPTION_RE.match(line):
            continue
        line_top = min(w["top"] for w in line_words)
        line_bottom = max(w["bottom"] for w in line_words)
        gap_above = y0 - line_bottom
        if -_CAPTION_OVERLAP_SLACK <= gap_above <= _CAPTION_GAP:
            return line  # above wins outright -- conventional table-caption position
        gap_below = line_top - y1
        if -_CAPTION_OVERLAP_SLACK <= gap_below <= _CAPTION_GAP and not below:
            below = line
    return below


def extract_tables(
    pdf_path: Path,
    *,
    min_rows: int = DEFAULT_MIN_ROWS,
    min_cols: int = DEFAULT_MIN_COLS,
) -> list[Table]:
    tables: list[Table] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            words = page.extract_words()
            for table in page.find_tables():
                grid = table.extract()
                cells = tuple(tuple(cell or "" for cell in row) for row in grid if any(row))
                if len(cells) < min_rows or (cells and len(cells[0]) < min_cols):
                    continue
                bbox = (table.bbox[0], table.bbox[1], table.bbox[2], table.bbox[3])
                tables.append(
                    Table(
                        page=page_index + 1,
                        bbox=bbox,
                        cells=cells,
                        caption=_find_caption(words, bbox),
                    )
                )
    return tables
