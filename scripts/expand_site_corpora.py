"""Expand per-site corpora with additional files and deeper folder paths."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


FILE_TYPES = ("docx", "xlsx", "pptx", "pdf")
MEETING_TYPES = ("mp4", "vtt", "txt")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Expand site corpora in .state/site-corpora.")
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path(".state/site-content-plan.json"),
        help="Path to site content plan JSON.",
    )
    parser.add_argument(
        "--expansion",
        type=Path,
        default=Path("config/site-content-expansion.json"),
        help="Path to expansion config JSON.",
    )
    parser.add_argument(
        "--site-corpora-root",
        type=Path,
        default=Path(".state/site-corpora"),
        help="Root folder containing site corpora and manifests.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(path: str) -> str:
    return re.sub(r"/+", "/", path.replace("\\", "/")).lstrip("./")


def parse_index(value: str, prefix: str, kind: str) -> int:
    match = re.match(rf"^{re.escape(prefix)}-{kind.upper()}-(\d+)$", value or "")
    return int(match.group(1)) if match else 0


def pick_template(entries: list[dict], extension: str) -> dict:
    suffix = f".{extension}"
    candidates = [row for row in entries if str(row.get("filename", "")).lower().endswith(suffix)]
    if not candidates:
        raise ValueError(f"No template file found for extension {suffix}.")
    non_draft = [row for row in candidates if not str(row.get("filename", "")).upper().startswith("DRAFT_")]
    return non_draft[0] if non_draft else candidates[0]


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_vtt(site_name: str, meeting_number: int, speakers: list[str], agenda: list[str]) -> str:
    cue_lines = ["WEBVTT", ""]
    for offset in range(4):
        start = offset * 15
        end = start + 14
        speaker = speakers[offset % len(speakers)]
        agenda_line = agenda[offset % len(agenda)]
        cue_lines.extend(
            [
                f"{start // 60:02}:{start % 60:02}.000 --> {end // 60:02}:{end % 60:02}.000",
                f"{speaker}: {site_name} meeting {meeting_number:03d} {agenda_line}.",
                "",
            ]
        )
    return "\n".join(cue_lines).strip() + "\n"


def build_txt(site_name: str, meeting_number: int, speakers: list[str], agenda: list[str]) -> str:
    lines = [f"{site_name} Meeting Transcript {meeting_number:03d}", ""]
    for idx in range(4):
        speaker = speakers[idx % len(speakers)]
        agenda_line = agenda[idx % len(agenda)]
        lines.append(f"{speaker}: {site_name} meeting {meeting_number:03d} {agenda_line}.")
    lines.append("")
    return "\n".join(lines)


def add_file_entry(
    *,
    entries: list[dict],
    path_set: set[str],
    artifact_prefix: str,
    site_label: str,
    category: str,
    relative_path: str,
    source_table: str,
    source_system: str,
    generated_at: str,
    kind: str,
    index: int,
    title_prefix: str,
) -> None:
    relative_path = normalize(relative_path)
    filename = Path(relative_path).name
    entry = {
        "artifact_id": f"{artifact_prefix}-{kind.upper()}-{index:03d}",
        "filename": filename,
        "title": f"{title_prefix} {site_label} {kind.upper()} Document {index:02d}",
        "category": category,
        "source_table": source_table,
        "source_system": source_system,
        "profile_generated_at": generated_at,
        "relative_path": relative_path,
    }
    if relative_path in path_set:
        raise ValueError(f"Duplicate manifest path generated: {relative_path}")
    path_set.add(relative_path)
    entries.append(entry)


def expand_site(
    *,
    site_id: str,
    site_corpora_root: Path,
    expansion: dict,
    categories: list[str],
) -> dict[str, int]:
    site_root = site_corpora_root / site_id
    manifest_path = site_root / "manifest.json"
    entries: list[dict] = json.loads(manifest_path.read_text(encoding="utf-8"))
    existing_paths = {normalize(str(row["relative_path"])) for row in entries}

    if not entries:
        raise ValueError(f"Manifest is empty: {manifest_path}")

    source_table = str(entries[0].get("source_table", f"corp.{site_id}.knowledge_assets"))
    source_system = str(entries[0].get("source_system", "SharePoint Synthetic Generator"))
    site_label = str(entries[0].get("title", site_id)).replace("DRAFT ", "").split(" DOCX ")[0].strip()
    artifact_prefix = site_id.upper()
    generated_at = datetime.now(timezone.utc).isoformat()

    counters: dict[str, int] = defaultdict(int)
    for row in entries:
        artifact_id = str(row.get("artifact_id", ""))
        for token in (*FILE_TYPES, "mp4", "vtt", "txt"):
            counters[token] = max(counters[token], parse_index(artifact_id, artifact_prefix, token))

    additional = expansion["additionalPerSite"]
    subfolders = expansion["subfolders"]
    transcript_template = expansion["transcriptTemplate"]
    docx_every = int(expansion.get("draftRules", {}).get("docxEvery", 0))

    by_extension_template = {ext: pick_template(entries, ext) for ext in (*FILE_TYPES, "mp4")}

    for ext in FILE_TYPES:
        amount = int(additional.get(ext, 0))
        for iteration in range(amount):
            counters[ext] += 1
            index = counters[ext]
            category = categories[iteration % len(categories)]
            folder_choices = subfolders.get(category) or ["General"]
            folder_name = folder_choices[iteration % len(folder_choices)]
            is_draft = ext == "docx" and docx_every > 0 and index % docx_every == 0
            base_name = f"{site_id}_{ext}_{index:02d}.{ext}"
            filename = f"DRAFT_{base_name}" if is_draft else base_name
            relative_path = f"{category}/{folder_name}/{filename}"
            destination = site_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            source_file = site_root / normalize(str(by_extension_template[ext]["relative_path"]))
            shutil.copy2(source_file, destination)
            add_file_entry(
                entries=entries,
                path_set=existing_paths,
                artifact_prefix=artifact_prefix,
                site_label=site_label,
                category=category,
                relative_path=relative_path,
                source_table=source_table,
                source_system=source_system,
                generated_at=generated_at,
                kind=ext,
                index=index,
                title_prefix="DRAFT" if is_draft else "",
            )

    meeting_amount = int(additional.get("meetings", 0))
    speakers = [str(value) for value in transcript_template["speakers"]]
    agenda = [str(value) for value in transcript_template["agenda"]]
    for iteration in range(meeting_amount):
        counters["mp4"] += 1
        counters["vtt"] += 1
        counters["txt"] += 1
        meeting_index = counters["mp4"]
        category = categories[iteration % len(categories)]
        folder_choices = subfolders.get(category) or ["Meetings"]
        folder_name = folder_choices[iteration % len(folder_choices)]
        meeting_stem = f"{site_id}_meeting_{meeting_index:02d}"
        relative_base = f"{category}/{folder_name}/{meeting_stem}"

        source_mp4 = site_root / normalize(str(by_extension_template["mp4"]["relative_path"]))
        target_mp4 = site_root / f"{relative_base}.mp4"
        target_mp4.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_mp4, target_mp4)

        write_text(site_root / f"{relative_base}.vtt", build_vtt(site_label, meeting_index, speakers, agenda))
        write_text(site_root / f"{relative_base}.txt", build_txt(site_label, meeting_index, speakers, agenda))

        add_file_entry(
            entries=entries,
            path_set=existing_paths,
            artifact_prefix=artifact_prefix,
            site_label=site_label,
            category=category,
            relative_path=f"{relative_base}.mp4",
            source_table=source_table,
            source_system=source_system,
            generated_at=generated_at,
            kind="mp4",
            index=meeting_index,
            title_prefix="",
        )
        add_file_entry(
            entries=entries,
            path_set=existing_paths,
            artifact_prefix=artifact_prefix,
            site_label=site_label,
            category=category,
            relative_path=f"{relative_base}.vtt",
            source_table=source_table,
            source_system=source_system,
            generated_at=generated_at,
            kind="vtt",
            index=meeting_index,
            title_prefix="",
        )
        add_file_entry(
            entries=entries,
            path_set=existing_paths,
            artifact_prefix=artifact_prefix,
            site_label=site_label,
            category=category,
            relative_path=f"{relative_base}.txt",
            source_table=source_table,
            source_system=source_system,
            generated_at=generated_at,
            kind="txt",
            index=meeting_index,
            title_prefix="",
        )

    manifest_path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")

    totals: dict[str, int] = defaultdict(int)
    for row in entries:
        ext = Path(str(row["filename"])).suffix.lower().lstrip(".")
        totals[ext] += 1
    return dict(totals)


def main() -> int:
    args = parse_args()
    plan = load_json(args.plan)
    expansion = load_json(args.expansion)
    categories = [str(value) for value in plan["categories"]]
    for site in plan["sites"]:
        site_id = str(site["siteId"])
        totals = expand_site(
            site_id=site_id,
            site_corpora_root=args.site_corpora_root,
            expansion=expansion,
            categories=categories,
        )
        formatted = ", ".join(f"{key}={totals[key]}" for key in sorted(totals))
        print(f"[{site_id}] manifest expanded: {formatted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
