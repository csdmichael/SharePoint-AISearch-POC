"""Generate a realistic per-site knowledge corpus (documents + meeting recordings).

Replaces the old generic duplicate-template corpus (``expand_site_corpora.py`` /
``regenerate_site_media.py``) for the hr, manufacturing, and sales sites with:

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
from docx.shared import Pt, RGBColor
from imageio_ffmpeg import get_ffmpeg_exe
from moviepy import AudioClip, VideoClip
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Inches, Pt as PptxPt
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer
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
# Document renderers
# ---------------------------------------------------------------------------

def _owner_line(owner: str, generated_at: datetime) -> str:
    return f"Owner: {owner}  |  Last updated: {generated_at.strftime('%B %d, %Y')}"


def render_docx(path: Path, doc: dict, site_label: str, department: str, generated_at: datetime) -> None:
    document = Document()
    title = document.add_heading(doc["title"], level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    meta = document.add_paragraph(f"{site_label} | {department}")
    meta.runs[0].italic = True
    document.add_paragraph(_owner_line(doc["owner"], generated_at))
    document.add_paragraph(doc["summary"])
    document.add_heading("Key Points", level=1)
    for point in doc["points"]:
        document.add_paragraph(point, style="List Bullet")
    if doc["table"]:
        header, *rows = doc["table"]
        table = document.add_table(rows=1, cols=len(header))
        table.style = "Light Grid Accent 1"
        for cell, value in zip(table.rows[0].cells, header):
            cell.text = str(value)
            cell.paragraphs[0].runs[0].bold = True
        for row in rows:
            cells = table.add_row().cells
            for cell, value in zip(cells, row):
                cell.text = str(value)
    footer = document.add_paragraph(f"Source: {site_label} knowledge base | {SOURCE_SYSTEM}")
    footer.runs[0].font.size = Pt(8)
    footer.runs[0].font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    document.save(path)


def render_pdf(path: Path, doc: dict, site_label: str, department: str, generated_at: datetime) -> None:
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle("Body", parent=styles["BodyText"], spaceAfter=10)
    meta_style = ParagraphStyle("Meta", parent=styles["Normal"], textColor=colors.HexColor("#555555"), spaceAfter=12)
    story = [
        Paragraph(doc["title"], styles["Title"]),
        Paragraph(f"{site_label} | {department}", meta_style),
        Paragraph(_owner_line(doc["owner"], generated_at), meta_style),
        Paragraph(doc["summary"], body_style),
        Paragraph("Key Points", styles["Heading2"]),
        ListFlowable(
            [ListItem(Paragraph(point, body_style)) for point in doc["points"]],
            bulletType="bullet",
        ),
        Spacer(1, 12),
    ]
    if doc["table"]:
        header, *rows = doc["table"]
        pdf_table = PdfTable([header, *rows], hAlign="LEFT")
        pdf_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBBBBB")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
                ]
            )
        )
        story.append(pdf_table)
    story.append(Spacer(1, 18))
    story.append(Paragraph(f"Source: {site_label} knowledge base | {SOURCE_SYSTEM}", meta_style))
    SimpleDocTemplate(str(path), pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch).build(story)


def render_xlsx(path: Path, doc: dict, site_label: str, department: str, generated_at: datetime) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Overview"
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")

    sheet.merge_cells("A1:D1")
    sheet["A1"] = doc["title"]
    sheet["A1"].font = Font(bold=True, size=14)
    sheet.merge_cells("A2:D2")
    sheet["A2"] = f"{site_label} | {department} | {_owner_line(doc['owner'], generated_at)}"
    sheet.merge_cells("A3:D3")
    sheet["A3"] = doc["summary"]
    sheet["A3"].alignment = Alignment(wrap_text=True)
    sheet.row_dimensions[3].height = 45

    row = 5
    table = doc["table"] or [("Key Point",), *[(point,) for point in doc["points"]]]
    header, *rows = table
    for col_index, value in enumerate(header, start=1):
        cell = sheet.cell(row=row, column=col_index, value=str(value))
        cell.font = header_font
        cell.fill = header_fill
    for row_offset, data_row in enumerate(rows, start=1):
        for col_index, value in enumerate(data_row, start=1):
            sheet.cell(row=row + row_offset, column=col_index, value=str(value))
    for col_index in range(1, max(len(header), 4) + 1):
        sheet.column_dimensions[chr(64 + col_index)].width = 32
    workbook.save(path)


def render_pptx(path: Path, doc: dict, site_label: str, department: str, generated_at: datetime) -> None:
    presentation = Presentation()
    title_slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    title_slide.shapes.title.text = doc["title"]
    title_slide.placeholders[1].text = f"{site_label} | {department}\n{_owner_line(doc['owner'], generated_at)}"

    content_slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    content_slide.shapes.title.text = "Overview"
    body = content_slide.placeholders[1].text_frame
    body.text = doc["summary"]
    for point in doc["points"]:
        paragraph = body.add_paragraph()
        paragraph.text = point
        paragraph.level = 1

    if doc["metrics"]:
        metrics_slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        metrics_slide.shapes.title.text = "Key Metrics"
        metrics_body = metrics_slide.placeholders[1].text_frame
        first = True
        for name, value in doc["metrics"].items():
            if first:
                metrics_body.text = f"{name}: {value}"
                first = False
            else:
                paragraph = metrics_body.add_paragraph()
                paragraph.text = f"{name}: {value}"

    if doc["table"]:
        header, *rows = doc["table"]
        table_slide = presentation.slides.add_slide(presentation.slide_layouts[5])
        table_slide.shapes.title.text = "Details"
        rows_total = len(rows) + 1
        cols_total = len(header)
        graphic_frame = table_slide.shapes.add_table(
            rows_total, cols_total, Inches(0.5), Inches(1.5), Inches(9), Inches(0.4 * rows_total)
        )
        table_shape = graphic_frame.table
        for col_index, value in enumerate(header):
            cell = table_shape.cell(0, col_index)
            cell.text = str(value)
            cell.text_frame.paragraphs[0].font.bold = True
            cell.text_frame.paragraphs[0].font.size = PptxPt(14)
        for row_index, data_row in enumerate(rows, start=1):
            for col_index, value in enumerate(data_row):
                table_shape.cell(row_index, col_index).text = str(value)

    presentation.save(path)


RENDERERS = {"docx": render_docx, "pdf": render_pdf, "xlsx": render_xlsx, "pptx": render_pptx}


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

    for department in site["departments"]:
        folder = department["folder"]
        for doc in department["documents"]:
            counter += 1
            extension = EXTENSION_FOR_DOC_TYPE[doc["doc_type"]]
            filename = f"{slug(doc['title'])}.{extension}"
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

    meetings_folder = site["meetings_folder"]
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
        if not skip_video:
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
