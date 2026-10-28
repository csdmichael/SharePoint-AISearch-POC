"""Normalize site-corpus manifest artifact IDs by file extension and file number."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize artifact IDs in site manifests.")
    parser.add_argument("--plan", type=Path, default=Path(".state/site-content-plan.json"))
    parser.add_argument("--site-corpora-root", type=Path, default=Path(".state/site-corpora"))
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def file_number(filename: str) -> int:
    match = re.search(r"_(\d+)\.[^.]+$", filename)
    return int(match.group(1)) if match else 0


def normalize_site(site_id: str, root: Path) -> None:
    manifest_path = root / site_id / "manifest.json"
    entries: list[dict] = load_json(manifest_path)
    prefix = site_id.upper()
    extension_map = {
        ".docx": "DOCX",
        ".xlsx": "XLSX",
        ".pptx": "PPTX",
        ".pdf": "PDF",
        ".mp4": "MP4",
        ".vtt": "VTT",
        ".txt": "TXT",
    }
    for entry in entries:
        filename = str(entry.get("filename", ""))
        ext = Path(filename).suffix.lower()
        token = extension_map.get(ext)
        if not token:
            continue
        entry["artifact_id"] = f"{prefix}-{token}-{file_number(filename):03d}"
    manifest_path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    plan = load_json(args.plan)
    for site in plan["sites"]:
        normalize_site(str(site["siteId"]), args.site_corpora_root)
        print(f"[{site['siteId']}] manifest IDs normalized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
