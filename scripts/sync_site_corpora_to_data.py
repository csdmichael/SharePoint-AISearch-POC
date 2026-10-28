"""Copy generated multi-site corpora from .state into data/sites/<siteId>."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


REQUIRED_EXTENSIONS = {".docx", ".xlsx", ".pptx", ".pdf", ".mp4", ".vtt", ".txt"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync site corpora to the repository data folder."
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path(".state/site-content-plan.json"),
        help="Path to site-content-plan.json",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(".state/site-corpora"),
        help="Root folder containing generated per-site corpus files.",
    )
    parser.add_argument(
        "--destination-root",
        type=Path,
        default=Path("data/sites"),
        help="Destination root where data/<siteId> folders are created.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing destination site folders before copy.",
    )
    return parser.parse_args()


def load_plan(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Plan file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_transcript_pairing(site_root: Path) -> None:
    video_files = sorted(site_root.rglob("*.mp4"))
    for video_file in video_files:
        stem = video_file.with_suffix("")
        vtt = stem.with_suffix(".vtt")
        txt = stem.with_suffix(".txt")
        if not vtt.exists():
            raise FileNotFoundError(f"Missing Teams-style VTT transcript: {vtt}")
        if not txt.exists():
            raise FileNotFoundError(f"Missing plain transcript text file: {txt}")


def extension_counts(site_root: Path) -> dict[str, int]:
    counts: dict[str, int] = {ext: 0 for ext in REQUIRED_EXTENSIONS}
    for file_path in site_root.rglob("*"):
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        if ext in counts:
            counts[ext] += 1
    return counts


def sync_site(site_id: str, source_root: Path, destination_root: Path, clean: bool) -> None:
    source_site_root = source_root / site_id
    destination_site_root = destination_root / site_id
    if not source_site_root.exists():
        raise FileNotFoundError(f"Source site folder not found: {source_site_root}")

    if clean and destination_site_root.exists():
        shutil.rmtree(destination_site_root)
    destination_site_root.mkdir(parents=True, exist_ok=True)

    for source_file in source_site_root.rglob("*"):
        if not source_file.is_file():
            continue
        relative_path = source_file.relative_to(source_site_root)
        destination_file = destination_site_root / relative_path
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file)

    validate_transcript_pairing(destination_site_root)

    counts = extension_counts(destination_site_root)
    missing = [ext for ext, count in counts.items() if count == 0]
    if missing:
        raise ValueError(
            f"Missing generated file types for site '{site_id}' in {destination_site_root}: "
            + ", ".join(missing)
        )

    print(f"[{site_id}] synced to {destination_site_root}")
    print("  " + ", ".join(f"{ext}={counts[ext]}" for ext in sorted(counts)))


def main() -> int:
    args = parse_args()
    plan = load_plan(args.plan)
    sites = plan.get("sites", [])
    if not sites:
        raise ValueError("No sites defined in plan.")

    for site in sites:
        site_id = site.get("siteId")
        if not site_id:
            raise ValueError("Each site entry must include siteId.")
        sync_site(
            site_id=site_id,
            source_root=args.source_root,
            destination_root=args.destination_root,
            clean=args.clean,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
