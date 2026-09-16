from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from mytables.extract import DEFAULT_MIN_COLS, DEFAULT_MIN_ROWS, extract_tables


def _make_pdf(
    path: Path,
    *,
    table_bbox: tuple[float, float, float, float] = (50, 100, 350, 200),
    rows: int = 3,
    cols: int = 2,
    caption: str | None = "Table 1: sample data",
    caption_pos: tuple[float, float] = (50, 90),
) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    if caption is not None:
        page.insert_text(caption_pos, caption, fontsize=11)

    x0, y0, x1, y1 = table_bbox
    for r in range(rows + 1):
        y = y0 + r * (y1 - y0) / rows
        page.draw_line((x0, y), (x1, y))
    for c in range(cols + 1):
        x = x0 + c * (x1 - x0) / cols
        page.draw_line((x, y0), (x, y1))
    for r in range(rows):
        for c in range(cols):
            cx = x0 + c * (x1 - x0) / cols + 5
            cy = y0 + r * (y1 - y0) / rows + (y1 - y0) / rows - 5
            page.insert_text((cx, cy), f"r{r}c{c}", fontsize=9)

    doc.save(path)
    doc.close()


@pytest.fixture()
def pdf_with_caption(tmp_path: Path) -> Path:
    path = tmp_path / "doc.pdf"
    _make_pdf(path)
    return path


def test_extracts_one_table_with_deterministic_caption_above(pdf_with_caption: Path) -> None:
    tables = extract_tables(pdf_with_caption)
    assert len(tables) == 1
    table = tables[0]
    assert table.page == 1
    assert table.caption == "Table 1: sample data"
    assert table.rows == 3
    assert table.cols == 2


def test_caption_below_used_when_nothing_found_above(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    _make_pdf(
        path,
        table_bbox=(50, 100, 350, 200),
        caption="Table 2: caption sits below",
        caption_pos=(50, 210),
    )
    (table,) = extract_tables(path)
    assert table.caption == "Table 2: caption sits below"


def test_missing_caption_yields_empty_string(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    _make_pdf(path, caption=None)
    (table,) = extract_tables(path)
    assert table.caption == ""


def test_single_column_is_filtered_by_the_col_floor(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    _make_pdf(path, cols=1, rows=3)
    assert extract_tables(path) == []


def test_single_row_is_filtered_by_the_row_floor(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    _make_pdf(path, rows=1, cols=2)
    assert extract_tables(path) == []


def test_min_rows_cols_are_configurable(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    _make_pdf(path, cols=1, rows=3)
    tables = extract_tables(path, min_cols=1)
    assert len(tables) == 1


def test_text_only_pdf_has_no_tables(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "just some prose, no tables here")
    doc.save(path)
    doc.close()
    assert extract_tables(path) == []


def test_to_csv_round_trips_cells(pdf_with_caption: Path) -> None:
    (table,) = extract_tables(pdf_with_caption)
    csv_text = table.to_csv()
    assert csv_text.count("\n") == table.rows


def test_default_floors_are_positive() -> None:
    assert DEFAULT_MIN_ROWS > 0
    assert DEFAULT_MIN_COLS > 0
