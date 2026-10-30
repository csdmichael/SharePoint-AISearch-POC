"""Structured, renderable previews of office documents for the in-page document viewer.

Unlike analytics/text.py (flat text for duplicate/conflict detection), these extractors keep enough
structure - paragraph style, table rows, worksheet grids, slide titles and bullets - for the UI to
render a readable approximation of the document without opening it in SharePoint or a desktop app.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

MAX_PARAGRAPHS = 400
MAX_TABLE_ROWS = 200
MAX_SHEET_ROWS = 300
MAX_SHEET_COLUMNS = 40
MAX_SHEETS = 10
MAX_SLIDES = 100


def preview_docx(content: bytes) -> dict[str, Any]:
    document = Document(BytesIO(content))
    blocks: list[dict[str, Any]] = []
    for paragraph in document.paragraphs:
        if len(blocks) >= MAX_PARAGRAPHS:
            break
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = (paragraph.style.name if paragraph.style else "") or ""
        kind = "heading" if style_name.lower().startswith("heading") or style_name.lower() == "title" else "paragraph"
        blocks.append({"kind": kind, "text": text, "style": style_name})
    tables: list[list[list[str]]] = []
    for table in document.tables:
        rows = [[cell.text for cell in row.cells] for row in table.rows[:MAX_TABLE_ROWS]]
        tables.append(rows)
    return {"kind": "docx", "blocks": blocks, "tables": tables}


def _shape_text_blocks(shapes, blocks: list[dict[str, Any]]) -> None:
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            _shape_text_blocks(shape.shapes, blocks)
            continue
        if shape.has_text_frame and shape.text_frame.text.strip():
            lines = [line.text for line in shape.text_frame.paragraphs if line.text.strip()]
            if lines:
                blocks.append({"lines": lines})
        if getattr(shape, "has_table", False) and shape.has_table:
            rows = [[cell.text for cell in row.cells] for row in shape.table.rows]
            blocks.append({"table": rows})


def preview_pptx(content: bytes) -> dict[str, Any]:
    presentation = Presentation(BytesIO(content))
    slides: list[dict[str, Any]] = []
    for index, slide in enumerate(presentation.slides, start=1):
        if index > MAX_SLIDES:
            break
        title = ""
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            title = slide.shapes.title.text_frame.text.strip()
        blocks: list[dict[str, Any]] = []
        for shape in slide.shapes:
            if shape == slide.shapes.title:
                continue
            _shape_text_blocks([shape], blocks)
        slides.append({"number": index, "title": title or f"Slide {index}", "blocks": blocks})
    return {"kind": "pptx", "slides": slides}


def preview_xlsx(content: bytes) -> dict[str, Any]:
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    try:
        sheets: list[dict[str, Any]] = []
        for sheet in workbook.worksheets[:MAX_SHEETS]:
            rows: list[list[str]] = []
            for row_index, row in enumerate(sheet.iter_rows(values_only=True)):
                if row_index >= MAX_SHEET_ROWS:
                    break
                values = ["" if value is None else str(value) for value in row[:MAX_SHEET_COLUMNS]]
                if any(value.strip() for value in values):
                    rows.append(values)
            sheets.append({"name": sheet.title, "rows": rows})
        return {"kind": "xlsx", "sheets": sheets}
    finally:
        workbook.close()


PREVIEW_EXTRACTORS = {
    ".docx": preview_docx,
    ".pptx": preview_pptx,
    ".xlsx": preview_xlsx,
}


def build_preview(extension: str, content: bytes) -> dict[str, Any]:
    extractor = PREVIEW_EXTRACTORS.get(extension.lower())
    if extractor is None:
        raise ValueError(f"no preview extractor for {extension}")
    return extractor(content)
