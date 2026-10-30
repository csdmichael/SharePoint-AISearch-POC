"""Generate a realistic per-site knowledge corpus (documents + meeting recordings).

Replaces the old generic duplicate-template corpus for the hr, manufacturing, and sales sites with:

  - a department-based folder structure that mirrors how the business actually organizes
    its SharePoint knowledge hub (see ``scripts/site_corpus_data.py``);
  - real, distinct DOCX/PDF/XLSX/PPTX content per document (no copied templates);
  - a "Meeting Recordings and Transcripts" folder with unique meeting titles, each with its
    own agenda, transcript (VTT + TXT), and rendered MP4 recording (no repeated dialogue and
    no bare numeric meeting names).

Output lands in ``.state/site-corpora/<site>/`` with a manifest.json, ready for
``scripts/sync_site_corpora_to_data.py`` to copy into ``data/sites/<site>/`` and for the
SharePoint uploader to publish.

Usage:
    python scripts/generate_realistic_site_corpus.py --site hr
    python scripts/generate_realistic_site_corpus.py --all
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import math
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches as DocxInches, Pt, RGBColor
from imageio_ffmpeg import get_ffmpeg_exe
from moviepy import AudioClip, VideoClip
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XlsxImage
from openpyxl.styles import Alignment, Font, PatternFill
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Inches, Pt as PptxPt
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as PdfImage, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer
from reportlab.platypus import Table as PdfTable
from reportlab.platypus import TableStyle

try:
    from .site_corpus_data import PARTICIPANTS, SITE_DATA, SITE_LABELS
except ImportError:
    from site_corpus_data import PARTICIPANTS, SITE_DATA, SITE_LABELS

EXTENSION_FOR_DOC_TYPE = {
    "policy": "docx",
    "procedure": "docx",
    "report": "pdf",
    "tracker": "xlsx",
    "deck": "pptx",
}
SOURCE_SYSTEM = "SharePoint Online"
ACCENT = RGBColor(0x1F, 0x4E, 0x79)


def slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a realistic per-site corpus.")
    parser.add_argument("--site", choices=sorted(SITE_DATA), help="Generate a single site.")
    parser.add_argument("--all", action="store_true", help="Generate every configured site.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(".state/site-corpora"),
        help="Root folder to write <site>/manifest.json and files into.",
    )
    parser.add_argument("--seconds", type=int, default=22, help="Duration per meeting video.")
    parser.add_argument("--fps", type=int, default=12, help="Meeting video frame rate.")
    parser.add_argument("--skip-video", action="store_true", help="Skip MP4 rendering (fast content-only run).")
    args = parser.parse_args()
    if not args.site and not args.all:
        parser.error("Pass --site <id> or --all.")
    return args


# ---------------------------------------------------------------------------
# Document renderers (12 pages / 12 slides / 12 sheets with tables & diagrams)
# ---------------------------------------------------------------------------

SECTION_BLUEPRINTS = [
    ("Executive Summary & Scope", "Overview", "Defines the operational charter, scope boundaries, and executive accountability."),
    ("Architecture & Process Flow", "Architecture", "Maps end-to-end process stages, handoff gates, and system-of-record integrations."),
    ("Governance Standards & Controls", "Controls", "Establishes mandatory compliance controls, approval thresholds, and audit evidence."),
    ("Operational KPIs & Benchmarks", "KPIs", "Tracks baseline performance, target SLAs, and quarterly benchmark progression."),
    ("Roles, Responsibilities & RACI", "RACI Matrix", "Clarifies ownership across accountable executives, operational leads, and reviewers."),
    ("Standard Operating Procedures", "Procedures", "Provides step-by-step execution checklists, intake criteria, and verification gates."),
    ("Risk Register & Mitigations", "Risk Register", "Catalogs operational, compliance, and delivery risks alongside preventive mitigations."),
    ("Quality Assurance & Audits", "Quality Audit", "Specifies sampling frequencies, inspection tolerances, and nonconformance workflows."),
    ("Exception Handling & Escalations", "Escalations", "Outlines severity tiers, response SLAs, and cross-functional escalation paths."),
    ("Cross-Functional Dependencies", "SLAs", "Documents upstream and downstream team dependencies and service-level commitments."),
    ("Continuous Improvement Roadmap", "Roadmap", "Schedules quarterly optimization milestones, automation targets, and capability reviews."),
    ("Appendix, Lineage & Sign-off", "Sign-off", "Records document lineage, governance metadata, version history, and owner sign-off."),
]


def _create_architecture_diagram_png(title: str, site_label: str, department: str) -> bytes:
    width, height = 760, 250
    image = Image.new("RGB", (width, height), color=(248, 250, 252))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    draw.rectangle((0, 0, width, 42), fill=(31, 78, 121))
    draw.text((16, 14), f"{site_label} | {department} - Process & Governance Flow", fill=(255, 255, 255), font=font)

    stages = [
        ("1. Intake & Scope", "Owner validation\n& classification", (43, 87, 154)),
        ("2. Policy Controls", "Compliance gate\n& peer review", (33, 115, 70)),
        ("3. Execution & SLA", "Operational run\n& telemetry log", (180, 95, 6)),
        ("4. Audit & Index", "SharePoint + AI\nSearch governance", (92, 45, 145)),
    ]
    box_w, box_h = 155, 125
    top_y = 68
    for idx, (heading, sub, color) in enumerate(stages):
        left_x = 24 + idx * 182
        draw.rounded_rectangle(
            (left_x, top_y, left_x + box_w, top_y + box_h),
            radius=10,
            fill=(255, 255, 255),
            outline=color,
            width=3,
        )
        draw.rectangle((left_x, top_y, left_x + box_w, top_y + 32), fill=color)
        draw.text((left_x + 10, top_y + 10), heading, fill=(255, 255, 255), font=font)
        draw.text((left_x + 12, top_y + 52), sub, fill=(40, 50, 65), font=font)
        if idx < len(stages) - 1:
            ax = left_x + box_w + 4
            ay = top_y + box_h // 2
            draw.line((ax, ay, ax + 18, ay), fill=(31, 78, 121), width=3)
            draw.polygon([(ax + 18, ay - 6), (ax + 25, ay), (ax + 18, ay + 6)], fill=(31, 78, 121))

    draw.text((16, 215), f"Artifact Workflow Diagram: {title[:75]}", fill=(90, 102, 115), font=font)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _create_kpi_chart_png(title: str, department: str) -> bytes:
    width, height = 760, 250
    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    draw.rectangle((0, 0, width, 38), fill=(21, 101, 192))
    draw.text((16, 12), f"{department} - Operational KPI & Compliance Benchmark Chart", fill=(255, 255, 255), font=font)

    bars = [
        ("Q1 Baseline", 78, (100, 149, 237)),
        ("Q2 Actual", 86, (65, 105, 225)),
        ("Q3 Current", 93, (33, 150, 83)),
        ("SLA Target", 95, (242, 153, 74)),
        ("Audit Score", 98, (45, 156, 219)),
    ]
    chart_left, chart_bottom, chart_top = 70, 205, 58
    chart_height = chart_bottom - chart_top
    for pct in (25, 50, 75, 100):
        y = chart_bottom - int(chart_height * (pct / 100.0))
        draw.line((chart_left, y, width - 30, y), fill=(225, 230, 238), width=1)
        draw.text((25, y - 6), f"{pct}%", fill=(100, 110, 125), font=font)

    for idx, (label, val, color) in enumerate(bars):
        bx = chart_left + 30 + idx * 125
        bh = int(chart_height * (val / 100.0))
        by = chart_bottom - bh
        draw.rectangle((bx, by, bx + 72, chart_bottom), fill=color, outline=(30, 40, 60), width=1)
        draw.text((bx + 18, by - 16), f"{val}%", fill=(20, 30, 45), font=font)
        draw.text((bx + 4, chart_bottom + 8), label, fill=(40, 50, 65), font=font)

    draw.line((chart_left, chart_top, chart_left, chart_bottom), fill=(80, 90, 105), width=2)
    draw.line((chart_left, chart_bottom, width - 30, chart_bottom), fill=(80, 90, 105), width=2)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _owner_line(owner: str, generated_at: datetime) -> str:
    return f"Owner: {owner}  |  Last updated: {generated_at.strftime('%B %d, %Y')}"


def _build_sections(doc: dict, site_label: str, department: str, generated_at: datetime) -> list[dict]:
    base_table = doc["table"] or [
        ("Control Area", "Owner", "Target SLA", "Verification Status"),
        (department, doc["owner"], "5 business days", "Verified"),
        (f"{doc['title'][:28]} Gate 1", doc["owner"], "3 business days", "Active"),
        (f"{doc['title'][:28]} Gate 2", doc["owner"], "10 business days", "Monitored"),
    ]
    points = list(doc["points"])
    sections: list[dict] = []
    for idx, (sec_title, short_sheet, sec_desc) in enumerate(SECTION_BLUEPRINTS, start=1):
        p1 = (
            f"{doc['summary']} Section {idx} ({sec_title}) applies to {department} within {site_label} "
            f"and is maintained by {doc['owner']}. {sec_desc}"
        )
        p2 = (
            f"Operational requirement {idx}.1: {points[(idx - 1) % len(points)]} "
            f"Secondary control {idx}.2: {points[idx % len(points)]}"
        )
        sec_bullets = [
            points[(idx - 1) % len(points)],
            points[idx % len(points)],
            f"Section {idx} review cadence is tracked by {doc['owner']} under {department} governance.",
        ]
        if idx == 1:
            sec_table = base_table
        else:
            header, *rows = base_table
            sec_table = [
                header,
                *rows,
                tuple(
                    f"Sec-{idx}" if col == 0 else (f"Stage {idx} Verified" if col == len(header) - 1 else str(val))
                    for col, val in enumerate(rows[(idx - 1) % len(rows)])
                ),
            ]
        image_kind = None
        if idx in (2, 6, 9):
            image_kind = "architecture"
        elif idx in (4, 8, 11):
            image_kind = "chart"
        sections.append(
            {
                "number": idx,
                "heading": f"Section {idx}: {sec_title}",
                "sheet_name": f"{idx:02d} {short_sheet}"[:31],
                "paragraphs": [p1, p2],
                "bullets": sec_bullets,
                "table": sec_table,
                "image_kind": image_kind,
            }
        )
    return sections


def render_docx(path: Path, doc: dict, site_label: str, department: str, generated_at: datetime) -> None:
    document = Document()
    arch_png = _create_architecture_diagram_png(doc["title"], site_label, department)
    chart_png = _create_kpi_chart_png(doc["title"], department)
    sections = _build_sections(doc, site_label, department, generated_at)

    for sec in sections:
        if sec["number"] == 1:
            title = document.add_heading(doc["title"], level=0)
            title.alignment = WD_ALIGN_PARAGRAPH.LEFT
            meta = document.add_paragraph(f"{site_label} | {department} | {_owner_line(doc['owner'], generated_at)}")
            meta.runs[0].italic = True

        document.add_heading(sec["heading"], level=1)
        for para in sec["paragraphs"]:
            document.add_paragraph(para)
        for point in sec["bullets"]:
            document.add_paragraph(point, style="List Bullet")

        header, *rows = sec["table"]
        table = document.add_table(rows=1, cols=len(header))
        table.style = "Light Grid Accent 1"
        for cell, value in zip(table.rows[0].cells, header):
            cell.text = str(value)
            if cell.paragraphs and cell.paragraphs[0].runs:
                cell.paragraphs[0].runs[0].bold = True
        for row in rows:
            cells = table.add_row().cells
            for cell, value in zip(cells, row):
                cell.text = str(value)

        if sec["image_kind"] == "architecture":
            document.add_picture(io.BytesIO(arch_png), width=DocxInches(5.8))
        elif sec["image_kind"] == "chart":
            document.add_picture(io.BytesIO(chart_png), width=DocxInches(5.8))

        footer = document.add_paragraph(
            f"Page {sec['number']} of {len(sections)} | {site_label} | {department} | {SOURCE_SYSTEM}"
        )
        footer.runs[0].font.size = Pt(8)
        footer.runs[0].font.color.rgb = RGBColor(0x80, 0x80, 0x80)

        if sec["number"] < len(sections):
            document.add_page_break()

    document.save(path)


def render_pdf(path: Path, doc: dict, site_label: str, department: str, generated_at: datetime) -> None:
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle("Body", parent=styles["BodyText"], spaceAfter=8, leading=13)
    meta_style = ParagraphStyle("Meta", parent=styles["Normal"], textColor=colors.HexColor("#555555"), spaceAfter=10)
    arch_png = _create_architecture_diagram_png(doc["title"], site_label, department)
    chart_png = _create_kpi_chart_png(doc["title"], department)
    sections = _build_sections(doc, site_label, department, generated_at)

    story = []
    for sec in sections:
        story.append(Paragraph(f"{doc['title']} - {sec['heading']}", styles["Title"] if sec["number"] == 1 else styles["Heading1"]))
        story.append(Paragraph(f"{site_label} | {department} | {_owner_line(doc['owner'], generated_at)} | Page {sec['number']} of {len(sections)}", meta_style))
        for para in sec["paragraphs"]:
            story.append(Paragraph(para, body_style))
        story.append(
            ListFlowable(
                [ListItem(Paragraph(point, body_style)) for point in sec["bullets"]],
                bulletType="bullet",
            )
        )
        story.append(Spacer(1, 8))

        header, *rows = sec["table"]
        pdf_table = PdfTable([header, *rows], hAlign="LEFT")
        pdf_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBBBBB")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F8")]),
                ]
            )
        )
        story.append(pdf_table)
        story.append(Spacer(1, 10))

        img_bytes = arch_png if sec["image_kind"] == "architecture" else (chart_png if sec["image_kind"] == "chart" else None)
        if img_bytes:
            story.append(PdfImage(io.BytesIO(img_bytes), width=430, height=142))
            story.append(Spacer(1, 8))

        story.append(Paragraph(f"Source: {site_label} knowledge base | {SOURCE_SYSTEM}", meta_style))
        if sec["number"] < len(sections):
            story.append(PageBreak())

    SimpleDocTemplate(str(path), pagesize=letter, topMargin=0.6 * inch, bottomMargin=0.6 * inch).build(story)


def render_xlsx(path: Path, doc: dict, site_label: str, department: str, generated_at: datetime) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    arch_png = _create_architecture_diagram_png(doc["title"], site_label, department)
    chart_png = _create_kpi_chart_png(doc["title"], department)
    sections = _build_sections(doc, site_label, department, generated_at)

    for sec in sections:
        sheet = workbook.create_sheet(title=sec["sheet_name"])
        sheet.merge_cells("A1:D1")
        sheet["A1"] = f"{doc['title']} - {sec['heading']}"
        sheet["A1"].font = Font(bold=True, size=13, color="1F4E79")
        sheet.merge_cells("A2:D2")
        sheet["A2"] = f"{site_label} | {department} | {_owner_line(doc['owner'], generated_at)}"
        sheet.merge_cells("A3:D3")
        sheet["A3"] = sec["paragraphs"][0]
        sheet["A3"].alignment = Alignment(wrap_text=True)
        sheet.row_dimensions[3].height = 42
        sheet.merge_cells("A4:D4")
        sheet["A4"] = sec["paragraphs"][1]
        sheet["A4"].alignment = Alignment(wrap_text=True)
        sheet.row_dimensions[4].height = 36

        row_start = 6
        header, *rows = sec["table"]
        for col_index, value in enumerate(header, start=1):
            cell = sheet.cell(row=row_start, column=col_index, value=str(value))
            cell.font = header_font
            cell.fill = header_fill
        for row_offset, data_row in enumerate(rows, start=1):
            for col_index, value in enumerate(data_row, start=1):
                sheet.cell(row=row_start + row_offset, column=col_index, value=str(value))

        bullet_start = row_start + len(rows) + 2
        sheet.cell(row=bullet_start, column=1, value="Governance Checkpoints").font = Font(bold=True)
        for b_idx, bullet in enumerate(sec["bullets"], start=1):
            sheet.cell(row=bullet_start + b_idx, column=1, value=f"• {bullet}")

        img_bytes = arch_png if sec["image_kind"] == "architecture" else (chart_png if sec["image_kind"] == "chart" else None)
        if img_bytes:
            xl_img = XlsxImage(io.BytesIO(img_bytes))
            xl_img.width = 480
            xl_img.height = 160
            sheet.add_image(xl_img, f"A{bullet_start + len(sec['bullets']) + 2}")

        for col_index in range(1, max(len(header), 4) + 1):
            sheet.column_dimensions[chr(64 + col_index)].width = 30

    workbook.save(path)


def render_pptx(path: Path, doc: dict, site_label: str, department: str, generated_at: datetime) -> None:
    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    arch_png = _create_architecture_diagram_png(doc["title"], site_label, department)
    chart_png = _create_kpi_chart_png(doc["title"], department)
    sections = _build_sections(doc, site_label, department, generated_at)

    for sec in sections:
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = f"{sec['number']}. {sec['heading'].split(': ', 1)[-1]} - {doc['title'][:36]}"
        body = slide.placeholders[1].text_frame
        body.text = sec["paragraphs"][0]
        for bullet in sec["bullets"]:
            paragraph = body.add_paragraph()
            paragraph.text = bullet
            paragraph.level = 1

        header, *rows = sec["table"]
        rows_total = len(rows) + 1
        cols_total = len(header)
        graphic_frame = slide.shapes.add_table(
            rows_total, cols_total, Inches(0.6), Inches(4.1), Inches(6.2), Inches(0.38 * rows_total)
        )
        table_shape = graphic_frame.table
        for col_index, value in enumerate(header):
            cell = table_shape.cell(0, col_index)
            cell.text = str(value)
            cell.text_frame.paragraphs[0].font.bold = True
            cell.text_frame.paragraphs[0].font.size = PptxPt(11)
        for row_index, data_row in enumerate(rows, start=1):
            for col_index, value in enumerate(data_row):
                cell = table_shape.cell(row_index, col_index)
                cell.text = str(value)
                cell.text_frame.paragraphs[0].font.size = PptxPt(10)

        img_bytes = arch_png if sec["image_kind"] in ("architecture", None) else chart_png
        slide.shapes.add_picture(io.BytesIO(img_bytes), Inches(7.1), Inches(4.05), Inches(5.6), Inches(2.0))

    presentation.save(path)


RENDERERS = {"docx": render_docx, "pdf": render_pdf, "xlsx": render_xlsx, "pptx": render_pptx}


def _make_near_duplicate_doc(doc: dict) -> dict:
    edited = copy.deepcopy(doc)
    swaps = [
        ("standards", "guidelines"),
        ("Defines", "Establishes"),
        ("Describes", "Outlines"),
        ("Walks", "Guides"),
        ("Tracks", "Monitors"),
        ("Compares", "Evaluates"),
        ("Summarizes", "Reviews"),
        ("Overview", "Summary"),
        ("Twelve-slide", "Multi-slide"),
        ("Multi-sheet", "Comprehensive"),
        ("employees", "staff members"),
        ("managers", "team leads"),
    ]
    summary = edited["summary"]
    changed = 0
    for old, new in swaps:
        if old in summary:
            summary = summary.replace(old, new, 1)
            changed += 1
    if changed == 0:
        summary = summary + " Reviewed for current governance cycle."
    edited["summary"] = summary
    return edited


# ---------------------------------------------------------------------------
# Meeting recordings (video + transcript)
# ---------------------------------------------------------------------------

def _speaker_voice(index: int) -> tuple[float, float]:
    presets = [(145.0, 220.0), (132.0, 198.0), (172.0, 258.0), (158.0, 238.0), (150.0, 226.0), (165.0, 248.0)]
    return presets[index % len(presets)]


def build_cues(agenda: list[tuple[int, str]], names: list[str], seconds: int) -> list[dict]:
    step = seconds / len(agenda)
    cues = []
    for index, (speaker_index, line) in enumerate(agenda):
        start = round(index * step, 3)
        end = round(min(seconds, start + step - 0.3), 3)
        cues.append(
            {
                "start": start,
                "end": end,
                "speaker": names[speaker_index % len(names)],
                "speaker_index": speaker_index % len(names),
                "text": f"{names[speaker_index % len(names)]}: {line}",
            }
        )
    return cues


def cue_at_time(cues: list[dict], t: float) -> dict | None:
    for cue in cues:
        if cue["start"] <= t <= cue["end"]:
            return cue
    return None


def seconds_to_timestamp(total_seconds: int) -> str:
    minutes, seconds = divmod(total_seconds, 60)
    return f"00:{minutes:02}:{seconds:02}.000"


def write_vtt(path: Path, cues: list[dict]) -> None:
    lines = ["WEBVTT", ""]
    for cue in cues:
        start, end = int(cue["start"]), int(math.ceil(cue["end"]))
        lines.extend([f"{seconds_to_timestamp(start)} --> {seconds_to_timestamp(end)}", cue["text"], ""])
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_txt(path: Path, meeting_title: str, cues: list[dict]) -> None:
    lines = [f"Meeting Transcript: {meeting_title}", ""]
    lines.extend(cue["text"] for cue in cues)
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def make_frame(meeting_title: str, names: list[str], t: float, duration: float, active_speaker: str) -> np.ndarray:
    width, height = 1280, 720
    progress = t / max(duration, 0.001)
    canvas = Image.new("RGB", (width, height), color=(14, 26, 49))
    draw = ImageDraw.Draw(canvas)
    for row in range(height):
        blend = row / height
        draw.line((0, row, width, row), fill=(int(20 + 35 * blend), int(30 + 50 * blend), int(60 + 75 * blend)))

    bar_width = int(width * 0.86)
    draw.rounded_rectangle((70, 30, 70 + bar_width, 92), radius=16, fill=(32, 92, 193), outline=(180, 210, 255), width=3)
    font = ImageFont.load_default()
    draw.text((92, 52), meeting_title, fill=(245, 248, 255), font=font)

    visible = names[:4]
    positions = [(80, 130, 600, 400), (680, 130, 1200, 400), (80, 430, 600, 700), (680, 430, 1200, 700)]
    accents = [(65, 112, 201), (79, 149, 116), (150, 94, 201), (196, 124, 56)]
    mouth_open = 8 + int(6 * abs(math.sin(t * 12)))
    for name, box, accent in zip(visible, positions, accents):
        x1, y1, x2, y2 = box
        active = name == active_speaker
        border_color = (248, 217, 93) if active else (178, 192, 221)
        draw.rounded_rectangle((x1, y1, x2, y2), radius=18, fill=(30, 44, 74), outline=border_color, width=4)
        draw.rectangle((x1 + 22, y1 + 22, x2 - 22, y2 - 82), fill=(46, 60, 94))
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2 - 28
        draw.ellipse((cx - 70, cy - 70, cx + 70, cy + 70), fill=(239, 196, 160), outline=(60, 60, 60))
        draw.ellipse((cx - 34, cy - 18, cx - 12, cy + 4), fill=(34, 34, 34))
        draw.ellipse((cx + 12, cy - 18, cx + 34, cy + 4), fill=(34, 34, 34))
        draw.arc((cx - 35, cy + 14, cx + 35, cy + 44), start=5, end=175, fill=(70, 30, 30), width=2)
        draw.ellipse((cx - 28, cy + 38, cx + 28, cy + 38 + (mouth_open if active else 3)), fill=(120, 22, 22))
        draw.rectangle((cx - 90, cy + 72, cx + 90, cy + 170), fill=accent)
        draw.text((x1 + 20, y2 - 52), name, fill=(240, 244, 252), font=font)
        if active:
            draw.text((x2 - 135, y2 - 52), "Speaking", fill=(249, 224, 117), font=font)

    draw.text((70, 680), "Recorded meeting with transcript-aligned speech audio", fill=(228, 235, 250), font=font)
    ring_center, ring_radius = (1180, 61), 30
    sweep = int(progress * 300)
    draw.ellipse(
        (ring_center[0] - ring_radius, ring_center[1] - ring_radius, ring_center[0] + ring_radius, ring_center[1] + ring_radius),
        outline=(120, 184, 255), width=5,
    )
    draw.arc(
        (ring_center[0] - ring_radius, ring_center[1] - ring_radius, ring_center[0] + ring_radius, ring_center[1] + ring_radius),
        start=-90, end=-90 + sweep, fill=(253, 201, 92), width=7,
    )
    return np.array(canvas, dtype=np.uint8)


def make_audio_sample(cues: list[dict], t: float) -> float:
    cue = cue_at_time(cues, t)
    if cue is None:
        return 0.0
    base, harmonic = _speaker_voice(cue["speaker_index"])
    local_t = t - cue["start"]
    pulse = 0.55 + 0.45 * math.sin(local_t * 17.0)
    envelope = min(1.0, local_t * 4.0) * max(0.0, 1.0 - (t - cue["end"] + 0.02) * 8.0)
    sample = (
        0.48 * math.sin(2.0 * math.pi * base * t)
        + 0.22 * math.sin(2.0 * math.pi * harmonic * t)
        + 0.09 * math.sin(2.0 * math.pi * (base * 0.5) * t)
    )
    return float(sample * pulse * envelope * 0.28)


def render_meeting_video(path: Path, meeting_title: str, names: list[str], cues: list[dict], seconds: int, fps: int) -> None:
    duration = float(seconds)

    def frame_fn(t: float) -> np.ndarray:
        cue = cue_at_time(cues, t)
        return make_frame(meeting_title, names, t, duration, cue["speaker"] if cue else names[0])

    def audio_fn(t):
        if np.isscalar(t):
            return make_audio_sample(cues, float(t))
        return np.array([make_audio_sample(cues, float(value)) for value in np.asarray(t, dtype=float)], dtype=np.float32)

    clip = VideoClip(frame_fn, duration=duration).with_audio(AudioClip(audio_fn, duration=duration, fps=44100))
    clip.write_videofile(
        str(path),
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="128k",
        fps=fps,
        bitrate="2200k",
        preset="medium",
        pixel_format="yuv420p",
        temp_audiofile=str(path.with_suffix(".tmp-audio.m4a")),
        remove_temp=True,
        logger=None,
    )
    clip.close()


# ---------------------------------------------------------------------------
# Corpus assembly
# ---------------------------------------------------------------------------

def generate_site(site_id: str, output_root: Path, seconds: int, fps: int, skip_video: bool) -> dict[str, int]:
    site = SITE_DATA[site_id]
    site_label = SITE_LABELS[site_id]
    names = [name for name, _role in PARTICIPANTS[site_id]]
    site_root = output_root / site_id
    if site_root.exists():
        shutil.rmtree(site_root)
    site_root.mkdir(parents=True)

    os.environ.setdefault("IMAGEIO_FFMPEG_EXE", get_ffmpeg_exe())
    generated_at = datetime.now(timezone.utc)
    manifest: list[dict] = []
    counter = 0
    dup_counts_by_ext: dict[str, int] = {"docx": 0, "pptx": 0, "xlsx": 0}

    for department in site["departments"]:
        folder = department["folder"]
        for doc in department["documents"]:
            counter += 1
            extension = EXTENSION_FOR_DOC_TYPE[doc["doc_type"]]
            base_slug = slug(doc["title"])
            filename = f"{base_slug}.{extension}"
            relative_path = f"{folder}/{filename}"
            destination = site_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            RENDERERS[extension](destination, doc, site_label, folder, generated_at)
            manifest.append(
                {
                    "artifact_id": f"{site_id.upper()}-DOC-{counter:03d}",
                    "filename": filename,
                    "title": doc["title"],
                    "category": folder,
                    "source_table": f"corp.{site_id}.knowledge_assets",
                    "source_system": SOURCE_SYSTEM,
                    "profile_generated_at": generated_at.isoformat(),
                    "relative_path": relative_path,
                }
            )

            # Generate multi-page exact and near-duplicate pairs for docx, pptx, and xlsx
            if extension in dup_counts_by_ext and dup_counts_by_ext[extension] < 1:
                dup_counts_by_ext[extension] += 1
                counter += 1
                exact_filename = f"{base_slug} (copy).{extension}"
                exact_rel = f"{folder}/{exact_filename}"
                shutil.copy2(destination, site_root / exact_rel)
                manifest.append(
                    {
                        "artifact_id": f"{site_id.upper()}-DOC-{counter:03d}",
                        "filename": exact_filename,
                        "title": f"{doc['title']} (Copy)",
                        "category": folder,
                        "source_table": f"corp.{site_id}.knowledge_assets",
                        "source_system": SOURCE_SYSTEM,
                        "profile_generated_at": generated_at.isoformat(),
                        "relative_path": exact_rel,
                    }
                )
                counter += 1
                near_filename = f"{base_slug} (edited copy).{extension}"
                near_rel = f"{folder}/{near_filename}"
                near_doc = _make_near_duplicate_doc(doc)
                RENDERERS[extension](site_root / near_rel, near_doc, site_label, folder, generated_at)
                manifest.append(
                    {
                        "artifact_id": f"{site_id.upper()}-DOC-{counter:03d}",
                        "filename": near_filename,
                        "title": f"{doc['title']} (Edited Copy)",
                        "category": folder,
                        "source_table": f"corp.{site_id}.knowledge_assets",
                        "source_system": SOURCE_SYSTEM,
                        "profile_generated_at": generated_at.isoformat(),
                        "relative_path": near_rel,
                    }
                )

    meetings_folder = site["meetings_folder"]
    cached_site_root = Path("data/sites") / site_id
    for meeting_index, meeting in enumerate(site["meetings"], start=1):
        meeting_slug = slug(meeting["title"])
        relative_base = f"{meetings_folder}/{meeting_slug}"
        cues = build_cues(meeting["agenda"], names, seconds)

        vtt_path = site_root / f"{relative_base}.vtt"
        txt_path = site_root / f"{relative_base}.txt"
        vtt_path.parent.mkdir(parents=True, exist_ok=True)
        write_vtt(vtt_path, cues)
        write_txt(txt_path, meeting["title"], cues)

        mp4_path = site_root / f"{relative_base}.mp4"
        cached_mp4 = cached_site_root / f"{relative_base}.mp4"
        if not skip_video:
            if cached_mp4.exists() and cached_mp4.stat().st_size > 10000:
                shutil.copy2(cached_mp4, mp4_path)
            else:
                render_meeting_video(mp4_path, meeting["title"], names, cues, seconds, fps)

        for suffix, kind in ((".mp4", "mp4"), (".vtt", "vtt"), (".txt", "txt")):
            if suffix == ".mp4" and skip_video:
                continue
            manifest.append(
                {
                    "artifact_id": f"{site_id.upper()}-MTG-{meeting_index:03d}-{kind.upper()}",
                    "filename": f"{meeting_slug}{suffix}",
                    "title": f"{meeting['title']} - {('Recording' if kind == 'mp4' else 'Transcript')}",
                    "category": meetings_folder,
                    "source_table": f"corp.{site_id}.meeting_recordings",
                    "source_system": SOURCE_SYSTEM,
                    "profile_generated_at": generated_at.isoformat(),
                    "relative_path": f"{relative_base}{suffix}",
                }
            )

    manifest_path = site_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    stats = {
        "documents": sum(1 for m in manifest if "-DOC-" in m["artifact_id"]),
        "meetings": len(site["meetings"]),
        "files": len(manifest),
    }
    return stats


def main() -> None:
    args = parse_args()
    site_ids = sorted(SITE_DATA) if args.all else [args.site]
    for site_id in site_ids:
        stats = generate_site(site_id, args.output_root, args.seconds, args.fps, args.skip_video)
        print(json.dumps({"site": site_id, **stats}))


if __name__ == "__main__":
    main()
