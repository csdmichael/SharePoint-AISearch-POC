"""Regenerate meeting MP4 files with human-like participants, speech audio, and transcripts."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from moviepy import AudioClip, VideoClip
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


def _speaker_voice(speaker: str) -> tuple[float, float]:
    presets = {
        "Alex": (145.0, 220.0),
        "Jordan": (132.0, 198.0),
        "Priya": (172.0, 258.0),
        "Casey": (158.0, 238.0),
    }
    return presets.get(speaker, (150.0, 225.0))


def site_topics(site_id: str, site_name: str) -> tuple[str, ...]:
    key = site_id.lower()
    if "hr" in key:
        return (
            "reviewed open hiring requisitions and interview loop progress",
            "discussed onboarding completion metrics and compliance training",
            "tracked employee relations cases and policy acknowledgement rates",
            "validated retention indicators and manager coaching action items",
            "aligned PTO coverage plans for upcoming release milestones",
            "confirmed owners for handbook and benefits documentation updates",
        )
    if "manufacturing" in key:
        return (
            "reviewed line throughput, cycle-time variance, and bottleneck stations",
            "walked through first-pass yield trends and defect Pareto updates",
            "covered preventive maintenance windows and downtime recovery tasks",
            "validated supplier quality alerts and containment actions",
            "confirmed safety observations, incident follow-ups, and training status",
            "aligned production schedule changes with inventory constraints",
        )
    if "sales" in key or "marketing" in key:
        return (
            "reviewed pipeline coverage by region and stage conversion trends",
            "discussed campaign performance, lead quality, and attribution signals",
            "covered forecast risks, renewal health, and upsell opportunities",
            "validated proposal turnaround metrics and deal desk blockers",
            "aligned account action plans for top strategic opportunities",
            "confirmed follow-up owners for customer feedback and references",
        )
    return (
        f"reviewed operational updates for {site_name}",
        "discussed compliance and governance checkpoints",
        "covered performance metrics and risk mitigation actions",
        "confirmed owners and target completion dates",
        "captured decisions and documented open follow-up tasks",
        "aligned next milestones and communication updates",
    )


def build_cues(site_id: str, site_name: str, meeting_number: int, seconds: int) -> list[dict[str, object]]:
    speakers = ("Alex", "Jordan", "Priya", "Casey")
    topics = site_topics(site_id, site_name)
    cue_count = max(8, min(14, seconds - 2))
    step = seconds / cue_count
    cues: list[dict[str, object]] = []
    for idx in range(cue_count):
        start = round(idx * step, 3)
        end = round(min(seconds, start + step - 0.25), 3)
        speaker = speakers[idx % len(speakers)]
        topic = topics[idx % len(topics)]
        cues.append(
            {
                "start": start,
                "end": end,
                "speaker": speaker,
                "text": f"{speaker}: {site_name} meeting {meeting_number:03d} {topic}.",
            }
        )
    return cues


def make_frame(
    site_name: str,
    meeting_number: int,
    timestamp: float,
    duration: float,
    active_speaker: str,
) -> np.ndarray:
    width, height = 1280, 720
    progress = timestamp / max(duration, 0.001)
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

    bar_width = int(width * 0.76)
    x_shift = int(math.sin(phase * 0.8) * 40)
    draw.rounded_rectangle(
        (120 + x_shift, 38, 120 + x_shift + bar_width, 98),
        radius=18,
        fill=(32, 92, 193),
        outline=(180, 210, 255),
        width=3,
    )

    font = ImageFont.load_default()
    draw.text((145 + x_shift, 59), f"{site_name} - Meeting Recording", fill=(245, 248, 255), font=font)
    draw.text((920, 59), f"Session {meeting_number:03d}", fill=(245, 248, 255), font=font)

    participant_boxes = [
        ("Alex", (80, 130, 600, 400), (65, 112, 201)),
        ("Jordan", (680, 130, 1200, 400), (79, 149, 116)),
        ("Priya", (80, 430, 600, 700), (150, 94, 201)),
        ("Casey", (680, 430, 1200, 700), (196, 124, 56)),
    ]
    mouth_open = 8 + int(6 * abs(math.sin(timestamp * 12)))
    for name, (x1, y1, x2, y2), accent in participant_boxes:
        active = name == active_speaker
        border_color = (248, 217, 93) if active else (178, 192, 221)
        draw.rounded_rectangle((x1, y1, x2, y2), radius=18, fill=(30, 44, 74), outline=border_color, width=4)
        draw.rectangle((x1 + 22, y1 + 22, x2 - 22, y2 - 82), fill=(46, 60, 94))
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2 - 28
        draw.ellipse((cx - 70, cy - 70, cx + 70, cy + 70), fill=(239, 196, 160), outline=(60, 60, 60))
        draw.ellipse((cx - 34, cy - 18, cx - 12, cy + 4), fill=(34, 34, 34))
        draw.ellipse((cx + 12, cy - 18, cx + 34, cy + 4), fill=(34, 34, 34))
        draw.arc((cx - 35, cy + 14, cx + 35, cy + 44), start=5, end=175, fill=(70, 30, 30), width=2)
        mouth_height = mouth_open if active else 3
        draw.ellipse((cx - 28, cy + 38, cx + 28, cy + 38 + mouth_height), fill=(120, 22, 22))
        draw.rectangle((cx - 90, cy + 72, cx + 90, cy + 170), fill=accent)
        draw.text((x1 + 20, y2 - 52), name, fill=(240, 244, 252), font=font)
        if active:
            draw.text((x2 - 135, y2 - 52), "Speaking", fill=(249, 224, 117), font=font)

    draw.text((96, 680), "Synthetic meeting demo with transcript-aligned speech audio", fill=(228, 235, 250), font=font)

    ring_center = (1180, 86)
    ring_radius = 40
    sweep = int(progress * 300)
    draw.ellipse(
        (
            ring_center[0] - ring_radius,
            ring_center[1] - ring_radius,
            ring_center[0] + ring_radius,
            ring_center[1] + ring_radius,
        ),
        outline=(120, 184, 255),
        width=6,
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
        width=8,
    )
    draw.text((1162, 80), f"{int(progress * 100):02d}%", fill=(255, 255, 255), font=font)

    return np.array(canvas, dtype=np.uint8)


def seconds_to_timestamp(total_seconds: int) -> str:
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"00:{minutes:02}:{seconds:02}.000"


def write_vtt(path: Path, cues: list[dict[str, object]]) -> None:
    lines = ["WEBVTT", ""]
    for cue in cues:
        start = int(float(cue["start"]))
        end = int(math.ceil(float(cue["end"])))
        lines.extend([f"{seconds_to_timestamp(start)} --> {seconds_to_timestamp(end)}", str(cue["text"]), ""])
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_txt(path: Path, site_name: str, meeting_number: int, cues: list[dict[str, object]]) -> None:
    lines = [f"{site_name} Meeting Transcript {meeting_number:03d}", ""]
    for cue in cues:
        lines.append(str(cue["text"]))
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def cue_at_time(cues: list[dict[str, object]], t: float) -> dict[str, object] | None:
    for cue in cues:
        if float(cue["start"]) <= t <= float(cue["end"]):
            return cue
    return None


def make_audio_sample(cues: list[dict[str, object]], t: float) -> float:
    cue = cue_at_time(cues, t)
    if cue is None:
        return 0.0
    speaker = str(cue["speaker"])
    base, harmonic = _speaker_voice(speaker)
    local_t = t - float(cue["start"])
    pulse = 0.55 + 0.45 * math.sin(local_t * 17.0)
    envelope = min(1.0, local_t * 4.0) * max(0.0, 1.0 - (t - float(cue["end"]) + 0.02) * 8.0)
    sample = (
        0.48 * math.sin(2.0 * math.pi * base * t)
        + 0.22 * math.sin(2.0 * math.pi * harmonic * t)
        + 0.09 * math.sin(2.0 * math.pi * (base * 0.5) * t)
    )
    return float(sample * pulse * envelope * 0.28)


def regenerate_site_media(site_id: str, site_root: Path, fps: int, seconds: int) -> dict[str, int]:
    manifest_path = site_root / "manifest.json"
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    video_entries = [entry for entry in entries if str(entry.get("filename", "")).lower().endswith(".mp4")]
    if not video_entries:
        return {"videos": 0, "vtt": 0, "txt": 0}

    stats = {"videos": 0, "vtt": 0, "txt": 0}
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_exe
    for entry in video_entries:
        relative_mp4 = Path(str(entry["relative_path"]).replace("\\", "/"))
        mp4_path = site_root / relative_mp4
        mp4_path.parent.mkdir(parents=True, exist_ok=True)
        meeting_number = parse_meeting_number(mp4_path.name)
        site_name = str(entry.get("title", site_id)).split(" MP4 ")[0].strip()
        cues = build_cues(site_id, site_name, meeting_number, seconds)
        duration = float(seconds)

        def frame_fn(t: float) -> np.ndarray:
            cue = cue_at_time(cues, t)
            speaker = str(cue["speaker"]) if cue else "Alex"
            return make_frame(site_name, meeting_number, t, duration, speaker)

        def audio_fn(t: float) -> np.ndarray | float:
            if np.isscalar(t):
                return make_audio_sample(cues, float(t))
            times = np.asarray(t, dtype=float)
            return np.array([make_audio_sample(cues, float(value)) for value in times], dtype=np.float32)

        clip = VideoClip(frame_fn, duration=duration).with_audio(AudioClip(audio_fn, duration=duration, fps=44100))
        clip.write_videofile(
            str(mp4_path),
            codec="libx264",
            audio_codec="aac",
            audio_bitrate="128k",
            fps=fps,
            bitrate="2200k",
            preset="medium",
            pixel_format="yuv420p",
            temp_audiofile=str(mp4_path.with_suffix(".tmp-audio.m4a")),
            remove_temp=True,
            logger=None,
        )
        clip.close()

        vtt_path = mp4_path.with_suffix(".vtt")
        txt_path = mp4_path.with_suffix(".txt")
        write_vtt(vtt_path, cues)
        write_txt(txt_path, site_name, meeting_number, cues)
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
