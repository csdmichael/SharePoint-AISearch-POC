"""Regenerate playable MP4 files and rich Teams-style transcripts for site corpora."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Regenerate corpus meeting media.")
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path(".state/site-content-plan.json"),
        help="Path to site-content-plan.json.",
    )
    parser.add_argument(
        "--site-corpora-root",
        type=Path,
        default=Path(".state/site-corpora"),
        help="Root folder for site corpora.",
    )
    parser.add_argument("--fps", type=int, default=12, help="Video frames per second.")
    parser.add_argument("--seconds", type=int, default=18, help="Duration per video in seconds.")
    return parser.parse_args()


def load_plan(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing plan file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_meeting_number(filename: str) -> int:
    match = re.search(r"meeting_(\d+)", filename, flags=re.IGNORECASE)
    return int(match.group(1)) if match else 1


def make_frame(site_name: str, meeting_number: int, frame_index: int, total_frames: int) -> np.ndarray:
    width, height = 1280, 720
    progress = frame_index / max(total_frames - 1, 1)
    phase = progress * 2 * math.pi

    canvas = Image.new("RGB", (width, height), color=(14, 26, 49))
    draw = ImageDraw.Draw(canvas)

    for row in range(height):
        blend = row / height
        color = (
            int(20 + 35 * blend),
            int(30 + 50 * blend),
            int(60 + 75 * blend),
        )
        draw.line((0, row, width, row), fill=color)

    bar_width = int(width * 0.68)
    x_shift = int(math.sin(phase) * 120)
    draw.rounded_rectangle(
        (180 + x_shift, 210, 180 + x_shift + bar_width, 290),
        radius=18,
        fill=(32, 92, 193),
        outline=(180, 210, 255),
        width=3,
    )

    font = ImageFont.load_default()
    draw.text((210 + x_shift, 235), f"{site_name} Meeting Recording", fill=(245, 248, 255), font=font)
    draw.text((210 + x_shift, 258), f"Session {meeting_number:03d}", fill=(235, 240, 252), font=font)
    draw.text((180, 350), "Agenda: metrics, blockers, owners, dates", fill=(228, 235, 250), font=font)
    draw.text((180, 376), "Transcript aligned in .vtt and .txt artifacts", fill=(228, 235, 250), font=font)

    ring_center = (1030, 260)
    ring_radius = 88
    sweep = int(progress * 300)
    draw.ellipse(
        (
            ring_center[0] - ring_radius,
            ring_center[1] - ring_radius,
            ring_center[0] + ring_radius,
            ring_center[1] + ring_radius,
        ),
        outline=(120, 184, 255),
        width=8,
    )
    draw.arc(
        (
            ring_center[0] - ring_radius,
            ring_center[1] - ring_radius,
            ring_center[0] + ring_radius,
            ring_center[1] + ring_radius,
        ),
        start=-90,
        end=-90 + sweep,
        fill=(253, 201, 92),
        width=10,
    )
    draw.text((980, 255), f"{int(progress * 100):02d}%", fill=(255, 255, 255), font=font)

    return np.array(canvas, dtype=np.uint8)


def seconds_to_timestamp(total_seconds: int) -> str:
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"00:{minutes:02}:{seconds:02}.000"


def write_vtt(path: Path, site_name: str, meeting_number: int, seconds: int) -> None:
    speakers = ("Alex", "Jordan", "Priya", "Casey")
    topics = (
        "reviewed action items from the prior session",
        "walked through quality and compliance checks",
        "covered operational throughput and blockers",
        "confirmed owners and target completion dates",
    )
    lines = ["WEBVTT", ""]
    window = max(3, seconds // 6)
    cue_count = max(6, seconds // window)
    for idx in range(cue_count):
        start = idx * window
        end = min(seconds, start + window - 1)
        speaker = speakers[idx % len(speakers)]
        topic = topics[idx % len(topics)]
        lines.extend(
            [
                f"{seconds_to_timestamp(start)} --> {seconds_to_timestamp(end)}",
                f"{speaker}: {site_name} meeting {meeting_number:03d} {topic}.",
                "",
            ]
        )
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_txt(path: Path, site_name: str, meeting_number: int) -> None:
    speakers = ("Alex", "Jordan", "Priya", "Casey")
    topics = (
        "reviewed action items from the prior session",
        "walked through quality and compliance checks",
        "covered operational throughput and blockers",
        "confirmed owners and target completion dates",
        "captured decisions and follow-up risks",
        "agreed on documentation updates",
    )
    lines = [f"{site_name} Meeting Transcript {meeting_number:03d}", ""]
    for idx, topic in enumerate(topics):
        speaker = speakers[idx % len(speakers)]
        lines.append(f"{speaker}: {site_name} meeting {meeting_number:03d} {topic}.")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def regenerate_site_media(site_id: str, site_root: Path, fps: int, seconds: int) -> dict[str, int]:
    manifest_path = site_root / "manifest.json"
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    video_entries = [entry for entry in entries if str(entry.get("filename", "")).lower().endswith(".mp4")]
    if not video_entries:
        return {"videos": 0, "vtt": 0, "txt": 0}

    total_frames = fps * seconds
    stats = {"videos": 0, "vtt": 0, "txt": 0}
    for entry in video_entries:
        relative_mp4 = Path(str(entry["relative_path"]).replace("\\", "/"))
        mp4_path = site_root / relative_mp4
        mp4_path.parent.mkdir(parents=True, exist_ok=True)
        meeting_number = parse_meeting_number(mp4_path.name)
        site_name = str(entry.get("title", site_id)).split(" MP4 ")[0].strip()

        with imageio.get_writer(str(mp4_path), fps=fps, codec="libx264", quality=7, macro_block_size=None) as writer:
            for frame_index in range(total_frames):
                writer.append_data(make_frame(site_name, meeting_number, frame_index, total_frames))

        vtt_path = mp4_path.with_suffix(".vtt")
        txt_path = mp4_path.with_suffix(".txt")
        write_vtt(vtt_path, site_name, meeting_number, seconds)
        write_txt(txt_path, site_name, meeting_number)
        stats["videos"] += 1
        stats["vtt"] += 1
        stats["txt"] += 1
    return stats


def main() -> int:
    args = parse_args()
    plan = load_plan(args.plan)
    for site in plan["sites"]:
        site_id = str(site["siteId"])
        site_root = args.site_corpora_root / site_id
        stats = regenerate_site_media(site_id, site_root, args.fps, args.seconds)
        print(
            f"[{site_id}] regenerated media: "
            f"mp4={stats['videos']}, vtt={stats['vtt']}, txt={stats['txt']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
