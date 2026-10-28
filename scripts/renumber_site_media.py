"""Renumber site meeting media files so filenames and artifact IDs are unique per site."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


MEDIA_EXTS = (".mp4", ".vtt", ".txt")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Renumber meeting media in site corpora.")
    parser.add_argument("--plan", type=Path, default=Path(".state/site-content-plan.json"))
    parser.add_argument("--site-corpora-root", type=Path, default=Path(".state/site-corpora"))
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def meeting_stem(relative_path: str) -> str | None:
    posix_path = relative_path.replace("\\", "/")
    if "_meeting_" not in posix_path:
        return None
    stem = str(Path(posix_path).with_suffix("")).replace("\\", "/")
    return stem


def normalize_media_for_site(site_id: str, root: Path) -> None:
    site_root = root / site_id
    manifest_path = site_root / "manifest.json"
    entries: list[dict] = load_json(manifest_path)

    groups: dict[str, list[dict]] = {}
    for entry in entries:
        rel = str(entry.get("relative_path", ""))
        stem = meeting_stem(rel)
        if not stem:
            continue
        groups.setdefault(stem, []).append(entry)

    ordered_stems = sorted(
        groups.keys(),
        key=lambda stem: (
            int(re.search(r"_meeting_(\d+)$", stem).group(1)) if re.search(r"_meeting_(\d+)$", stem) else 0,
            stem,
        ),
    )

    prefix = site_id.upper()
    temp_renames: list[tuple[Path, Path]] = []
    final_renames: list[tuple[Path, Path]] = []
    for sequence, old_stem in enumerate(ordered_stems, start=1):
        old_stem_path = Path(old_stem)
        new_stem = f"{site_id}_meeting_{sequence:02d}"
        for ext in MEDIA_EXTS:
            old_relative = f"{old_stem_path.as_posix()}{ext}"
            old_file = site_root / old_relative
            if old_file.exists():
                temp_file = old_file.with_name(f"__tmp__{old_file.name}")
                temp_renames.append((old_file, temp_file))
                final_file = old_file.with_name(f"{new_stem}{ext}")
                final_renames.append((temp_file, final_file))
        for entry in groups[old_stem]:
            ext = Path(str(entry["filename"])).suffix.lower()
            token = ext.lstrip(".").upper()
            folder = Path(str(entry["relative_path"]).replace("\\", "/")).parent.as_posix()
            entry["filename"] = f"{new_stem}{ext}"
            entry["relative_path"] = f"{folder}/{new_stem}{ext}"
            entry["artifact_id"] = f"{prefix}-{token}-{sequence:03d}"

    for source, target in temp_renames:
        source.rename(target)
    for source, target in final_renames:
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)

    manifest_path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    plan = load_json(args.plan)
    for site in plan["sites"]:
        normalize_media_for_site(str(site["siteId"]), args.site_corpora_root)
        print(f"[{site['siteId']}] media renumbered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
