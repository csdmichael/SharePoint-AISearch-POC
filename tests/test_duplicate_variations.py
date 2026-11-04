"""Unit tests for scripts/duplicate_variations.py, using the stdlib unittest module only.

Run from the repository root: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import random
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from docx import Document  # noqa: E402
from openpyxl import Workbook, load_workbook  # noqa: E402
from pptx import Presentation  # noqa: E402

from scripts.duplicate_variations import (  # noqa: E402
    EDITED_COPY_PAGES,
    EXTENDED_COPY_EDITED_PAGES,
    edit_pages,
    revise_text,
    write_variant,
)

INTRO = "Escalations are routed within 8 business hours to the accountable lead for every open finding."
REQUIREMENT = "Operational requirement {n}: Ensure each control owner signs the checklist before release, with 3 reviewers."
BULLET_ONE = "Reviewers identify several exceptions and track each one to closure in the register."
BULLET_TWO = "Managers keep the approval log current for all employees across 2 business units."


def _write_docx(path: Path, pages: int) -> None:
    document = Document()
    for number in range(1, pages + 1):
        document.add_heading(f"Section {number}", level=1)
        document.add_paragraph(INTRO)
        document.add_paragraph(REQUIREMENT.format(n=number))
        document.add_paragraph(BULLET_ONE, style="List Bullet")
        document.add_paragraph(BULLET_TWO, style="List Bullet")
        if number < pages:
            document.add_page_break()
    document.save(str(path))


def _write_pptx(path: Path, slides: int) -> None:
    presentation = Presentation()
    for number in range(1, slides + 1):
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = f"Slide {number}"
        body = slide.placeholders[1].text_frame
        body.text = INTRO
        for text in (REQUIREMENT.format(n=number), BULLET_ONE, BULLET_TWO):
            paragraph = body.add_paragraph()
            paragraph.text = text
            paragraph.level = 1
    presentation.save(str(path))


def _write_xlsx(path: Path, sheets: int) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for number in range(1, sheets + 1):
        sheet = workbook.create_sheet(title=f"Sheet {number}")
        sheet.merge_cells("A1:D1")
        sheet["A1"] = f"Workbook title {number}"
        sheet.merge_cells("A3:D3")
        sheet["A3"] = INTRO
        sheet.merge_cells("A4:D4")
        sheet["A4"] = REQUIREMENT.format(n=number)
        sheet["A6"] = "Governance Checkpoints"
        sheet["A7"] = f"• {BULLET_ONE}"
        sheet["A8"] = f"• {BULLET_TWO}"
    workbook.save(str(path))


def _docx_pages(path: Path) -> list[str]:
    pages: list[list[str]] = [[]]
    for paragraph in Document(str(path)).paragraphs:
        pages[-1].append(paragraph.text)
        if paragraph._p.xpath('.//w:br[@w:type="page"]'):
            pages.append([])
    return ["\n".join(lines) for lines in pages]


def _pptx_pages(path: Path) -> list[str]:
    return [
        "\n".join(paragraph.text for shape in slide.shapes if shape.has_text_frame for paragraph in shape.text_frame.paragraphs)
        for slide in Presentation(str(path)).slides
    ]


def _xlsx_pages(path: Path) -> list[str]:
    return [
        "\n".join(str(cell.value) for row in sheet.iter_rows() for cell in row if cell.value is not None)
        for sheet in load_workbook(str(path)).worksheets
    ]


def _changed_pages(before: list[str], after: list[str]) -> list[int]:
    return [number for number, (old, new) in enumerate(zip(before, after), start=1) if old != new]


def _digits(pages: list[str]) -> list[str]:
    return re.findall(r"\d+", "\n".join(pages))


class PageEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)

    def tearDown(self) -> None:
        self._directory.cleanup()

    def test_docx_edited_copy_changes_exactly_the_edited_pages(self) -> None:
        source = self.root / "policy.docx"
        target = self.root / "policy (edited copy).docx"
        _write_docx(source, pages=5)

        edits = write_variant(source, target, pages=EDITED_COPY_PAGES, kind="edited")

        before, after = _docx_pages(source), _docx_pages(target)
        self.assertEqual(len(before), len(after))
        self.assertEqual(len(edits), EDITED_COPY_PAGES)
        self.assertEqual(_changed_pages(before, after), sorted(edit.page for edit in edits))
        self.assertEqual(_digits(before), _digits(after))

    def test_docx_extended_variant_edits_three_pages_and_keeps_page_count(self) -> None:
        source = self.root / "handbook.docx"
        target = self.root / "handbook (extended copy).docx"
        _write_docx(source, pages=6)

        edits = write_variant(source, target, pages=EXTENDED_COPY_EDITED_PAGES, kind="extended")

        before, after = _docx_pages(source), _docx_pages(target)
        self.assertEqual(len(before), len(after))
        self.assertEqual(len(_changed_pages(before, after)), EXTENDED_COPY_EDITED_PAGES)
        self.assertEqual(sorted(edit.page for edit in edits), _changed_pages(before, after))

    def test_pptx_variant_changes_only_the_chosen_slides(self) -> None:
        source = self.root / "deck.pptx"
        target = self.root / "deck (edited copy).pptx"
        _write_pptx(source, slides=4)

        edits = write_variant(source, target, pages=EDITED_COPY_PAGES, kind="edited")

        before, after = _pptx_pages(source), _pptx_pages(target)
        self.assertEqual(len(before), len(after))
        self.assertEqual(_changed_pages(before, after), sorted(edit.page for edit in edits))
        self.assertEqual(len(edits), EDITED_COPY_PAGES)
        self.assertEqual(_digits(before), _digits(after))

    def test_xlsx_variant_changes_only_the_chosen_sheets(self) -> None:
        source = self.root / "workbook.xlsx"
        target = self.root / "workbook (edited copy).xlsx"
        _write_xlsx(source, sheets=4)

        edits = write_variant(source, target, pages=EDITED_COPY_PAGES, kind="edited")

        before, after = _xlsx_pages(source), _xlsx_pages(target)
        self.assertEqual(len(before), len(after))
        self.assertEqual(_changed_pages(before, after), sorted(edit.page for edit in edits))
        self.assertEqual(len(edits), EDITED_COPY_PAGES)
        self.assertEqual(_digits(before), _digits(after))

    def test_same_source_and_kind_reproduce_the_same_copy(self) -> None:
        source = self.root / "policy.docx"
        _write_docx(source, pages=5)
        first, second = self.root / "first.docx", self.root / "second.docx"

        write_variant(source, first, pages=EDITED_COPY_PAGES, kind="edited")
        write_variant(source, second, pages=EDITED_COPY_PAGES, kind="edited")

        self.assertEqual(_docx_pages(first), _docx_pages(second))

    def test_different_documents_do_not_share_one_pattern(self) -> None:
        patterns = set()
        for name in ("policy-a", "policy-b", "policy-c", "policy-d", "policy-e", "policy-f"):
            source = self.root / f"{name}.docx"
            _write_docx(source, pages=5)
            edits = write_variant(source, self.root / f"{name} (edited copy).docx", pages=EDITED_COPY_PAGES, kind="edited")
            patterns.add(tuple(edit.page for edit in edits))

        self.assertGreater(len(patterns), 1)

    def test_requesting_more_pages_than_the_document_has_is_rejected(self) -> None:
        source = self.root / "short.docx"
        _write_docx(source, pages=2)

        with self.assertRaises(ValueError):
            edit_pages(source, pages=3, rng=random.Random(1))


class ReviseTextTests(unittest.TestCase):
    SAMPLES = (
        "Escalations are routed within 8 business hours to the accountable lead.",
        "Ensure 3 reviewers sign off; managers keep 2 logs.",
        "Annual recertification for all personnel.",
    )

    def test_revision_changes_wording_and_keeps_every_digit(self) -> None:
        for seed in range(50):
            for sample in self.SAMPLES:
                revised = revise_text(sample, random.Random(seed))
                self.assertNotEqual(revised, sample)
                self.assertEqual(re.findall(r"\d+", revised), re.findall(r"\d+", sample))


if __name__ == "__main__":
    unittest.main()
