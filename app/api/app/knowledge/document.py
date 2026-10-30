"""Renders the knowledge artifact as the SharePoint document (DOCX, which the Search indexer reads) and as Markdown.

The document holds the summarized business knowledge and enough provenance to understand where it came from. It
never contains the original conversation.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

EMPTY_SECTION = "Not stated in the source."
FORBIDDEN_FILE_CHARS = re.compile(r'[\\/:*?"<>|#%~&{}\x00-\x1f]')


@dataclass(frozen=True)
class ArtifactContent:
    artifact_id: str
    title: str
    summary: str
    context: str
    root_cause: str
    decision: str
    recommended_action: str
    key_facts: tuple[str, ...]
    source_type: str
    source_description: str
    extraction_method: str
    governance: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def sections(self) -> list[tuple[str, list[str], bool]]:
        """(heading, paragraphs or bullets, is_bullets). Empty sections say so instead of disappearing."""

        def text(value: str) -> list[str]:
            return [value] if value.strip() else [EMPTY_SECTION]

        source_lines = [
            f"Source type: {self.source_type}",
            f"Source description: {self.source_description or EMPTY_SECTION}",
            f"Captured by: {self.extraction_method}",
            "The original conversation is not stored in this document.",
        ]
        return [
            ("Summary", text(self.summary), False),
            ("Context", text(self.context), False),
            ("Root Cause", text(self.root_cause), False),
            ("Decision", text(self.decision), False),
            ("Recommended Action", text(self.recommended_action), False),
            ("Key Facts", list(self.key_facts) or [EMPTY_SECTION], bool(self.key_facts)),
            ("Source", source_lines, False),
        ]


def safe_file_stem(title: str, limit: int = 120) -> str:
    cleaned = FORBIDDEN_FILE_CHARS.sub(" ", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned[:limit].strip(" .")) or "Knowledge"


def render_markdown(content: ArtifactContent) -> str:
    lines = [f"# {content.title}", ""]
    for heading, items, bullets in content.sections():
        lines += [f"## {heading}", ""]
        lines += [f"- {item}" for item in items] if bullets else items
        lines.append("")
    lines += ["## Governance Information", ""]
    lines += [f"- **{label}:** {value}" for label, value in content.governance]
    return "\n".join(lines).strip() + "\n"


def plain_text(content: ArtifactContent) -> str:
    """Text the indexer will extract; also the input of the content hash."""

    parts = [content.title]
    for heading, items, _ in content.sections():
        parts += [heading, *items]
    parts += ["Governance Information", *[f"{label}: {value}" for label, value in content.governance]]
    return "\n".join(parts)


def render_docx(content: ArtifactContent, *, author: str) -> bytes:
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    document.core_properties.title = content.title
    document.core_properties.author = author
    document.core_properties.subject = f"Knowledge artifact {content.artifact_id}"
    document.core_properties.comments = "Created with Save to Knowledge. Reviewed and published by the knowledge owner."

    document.add_heading(content.title, level=0)
    for heading, items, bullets in content.sections():
        document.add_heading(heading, level=1)
        for item in items:
            document.add_paragraph(item, style="List Bullet" if bullets else None)

    document.add_heading("Governance Information", level=1)
    table = document.add_table(rows=0, cols=2)
    table.style = "Light Grid Accent 1"
    for label, value in content.governance:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = value
        cells[0].paragraphs[0].runs[0].bold = True
    footer = document.add_paragraph("Durable knowledge promoted from collaboration. SharePoint is the system of record.")
    footer.alignment = WD_ALIGN_PARAGRAPH.LEFT
    footer.runs[0].italic = True

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
