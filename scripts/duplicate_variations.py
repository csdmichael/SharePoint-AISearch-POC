"""Randomized, wording-only page edits for generated duplicate documents.

A realistic duplicate differs from its source in a few places: one sentence reworded on one page, one bullet
updated on another. This module makes such copies of .docx, .pptx and .xlsx files. Every chosen page (a DOCX page,
a PPTX slide or an XLSX sheet) receives one edit at a randomly chosen body-text position, so the copy differs from
its source on exactly the chosen pages.

Edits never add, remove or change a digit. An edited copy keeps the numeric fingerprint of its source and stays a
near duplicate under the governance rules (cosine threshold plus identical numeric fingerprint).

Choices are seeded from the source file name and the copy kind, so regenerating a corpus reproduces the same copies.
"""

from __future__ import annotations

import random
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from docx import Document
from openpyxl import load_workbook
from pptx import Presentation

EDITED_COPY_PAGES = 2
EXTENDED_COPY_EDITED_PAGES = 3

MIN_EDITABLE_LENGTH = 40
BULLET_PREFIX = "• "

WORD_SWAPS = (
    ("ensure", "confirm"),
    ("provide", "supply"),
    ("maintain", "keep"),
    ("identify", "determine"),
    ("typically", "usually"),
    ("approximately", "about"),
    ("important", "critical"),
    ("several", "multiple"),
    ("defines", "establishes"),
    ("describes", "outlines"),
    ("tracks", "monitors"),
    ("compares", "evaluates"),
    ("employees", "staff members"),
    ("managers", "team leads"),
)

REVISION_SENTENCES = (
    "Escalation contacts were confirmed with the accountable lead for this revision.",
    "Reference links were refreshed against the current controlled-document index.",
    "Review ownership was confirmed with the process owner for the latest cycle.",
    "Scope wording was clarified after the most recent operations governance review.",
    "Responsibilities for this step were confirmed with the accountable team lead.",
    "Evidence retention was aligned with the current quarterly audit checkpoint.",
)

_DOCX_BODY_STYLES = ("Normal", "List Bullet")
_DOCX_FOOTER = re.compile(r"Page \d+ of \d+ \|")


@dataclass(frozen=True)
class PageEdit:
    page: int
    before: str
    after: str


@dataclass(frozen=True)
class _Unit:
    text: str
    write: Callable[[str], None]


def write_variant(source: Path, target: Path, *, pages: int, kind: str) -> list[PageEdit]:
    """Copy source to target, then edit `pages` randomly chosen pages of the copy."""
    shutil.copy2(source, target)
    return edit_pages(target, pages, random.Random(f"{source.name}|{kind}"))


def edit_pages(path: Path, pages: int, rng: random.Random) -> list[PageEdit]:
    """Apply one wording edit to each of `pages` randomly chosen pages of a .docx, .pptx or .xlsx file, in place."""
    loader = _LOADERS.get(path.suffix.lower())
    if loader is None:
        raise ValueError(f"Unsupported duplicate source: {path.name}")
    document, page_units = loader(path)
    editable = [index for index, units in enumerate(page_units) if units]
    if pages > len(editable):
        raise ValueError(f"{path.name} has {len(editable)} editable pages, {pages} requested.")
    edits = []
    for index in sorted(rng.sample(editable, pages)):
        unit = rng.choice(page_units[index])
        revised = revise_text(unit.text, rng)
        unit.write(revised)
        edits.append(PageEdit(page=index + 1, before=unit.text, after=revised))
    document.save(str(path))
    return edits


def revise_text(text: str, rng: random.Random) -> str:
    """Reword text without changing its digits. Appends a sentence when no word swap applies."""
    swaps = [(old, new) for old, new in WORD_SWAPS if re.search(rf"\b{old}\b", text, re.IGNORECASE)]
    if swaps and rng.random() < 0.5:
        old, new = rng.choice(swaps)
        return re.sub(
            rf"\b{old}\b",
            lambda match: _match_case(match.group(0), new),
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    return f"{text.rstrip()} {rng.choice(REVISION_SENTENCES)}"


def _match_case(original: str, replacement: str) -> str:
    return replacement.capitalize() if original[:1].isupper() else replacement


def _writer(target: Any, attribute: str, prefix: str = "") -> Callable[[str], None]:
    def write(new_text: str) -> None:
        setattr(target, attribute, f"{prefix}{new_text}")

    return write


def _load_docx(path: Path) -> tuple[Any, list[list[_Unit]]]:
    document = Document(str(path))
    pages: list[list[_Unit]] = [[]]
    for paragraph in document.paragraphs:
        unit = _docx_unit(paragraph)
        if unit is not None:
            pages[-1].append(unit)
        if paragraph._p.xpath('.//w:br[@w:type="page"]'):
            pages.append([])
    return document, pages


def _docx_unit(paragraph: Any) -> _Unit | None:
    text = paragraph.text.strip()
    style = paragraph.style.name if paragraph.style is not None else ""
    if style not in _DOCX_BODY_STYLES or len(text) < MIN_EDITABLE_LENGTH or _DOCX_FOOTER.match(text):
        return None
    if any(run.italic for run in paragraph.runs):
        return None
    return _Unit(text=text, write=_writer(paragraph, "text"))


def _load_pptx(path: Path) -> tuple[Any, list[list[_Unit]]]:
    presentation = Presentation(str(path))
    pages: list[list[_Unit]] = []
    for slide in presentation.slides:
        units: list[_Unit] = []
        for shape in slide.placeholders:
            if shape.placeholder_format.idx != 1 or not shape.has_text_frame:
                continue
            for paragraph in shape.text_frame.paragraphs:
                text = paragraph.text.strip()
                if len(text) >= MIN_EDITABLE_LENGTH:
                    units.append(_Unit(text=text, write=_writer(paragraph, "text")))
        pages.append(units)
    return presentation, pages


def _load_xlsx(path: Path) -> tuple[Any, list[list[_Unit]]]:
    workbook = load_workbook(str(path))
    pages: list[list[_Unit]] = []
    for sheet in workbook.worksheets:
        merged_rows = {
            merged.min_row
            for merged in sheet.merged_cells.ranges
            if merged.min_col == 1 and merged.max_col > 1 and merged.min_row >= 3
        }
        units: list[_Unit] = []
        for row in range(3, sheet.max_row + 1):
            cell = sheet.cell(row=row, column=1)
            value = cell.value
            if not isinstance(value, str):
                continue
            if row in merged_rows and len(value.strip()) >= MIN_EDITABLE_LENGTH:
                units.append(_Unit(text=value.strip(), write=_writer(cell, "value")))
            elif value.startswith(BULLET_PREFIX):
                text = value[len(BULLET_PREFIX):].strip()
                units.append(_Unit(text=text, write=_writer(cell, "value", BULLET_PREFIX)))
        pages.append(units)
    return workbook, pages


_LOADERS = {".docx": _load_docx, ".pptx": _load_pptx, ".xlsx": _load_xlsx}
