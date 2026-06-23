import os

"""
fix_videos.py — auto-remove black bars and fix wrong SAR in video files.

Usage:
    python fix_videos.py                         # current folder
    python fix_videos.py "C:\\Users\\vlady\\Videos"

Output goes to a 'fixed/' subfolder. Originals are never touched.
All videos end up in fixed/ — processed or copied as-is.
Requires: ffmpeg + ffprobe in PATH.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".wmv"}
OUTPUT_FOLDER = "fixed"
CRF = 18  # video quality: 0 = lossless, 51 = worst. 18 is near-lossless.


# ── helpers ──────────────────────────────────────────────────────────────────


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def check_dependencies() -> None:
    """Verify ffmpeg and ffprobe are available before doing any work."""
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        print(f"Error: required tool(s) not found in PATH: {', '.join(missing)}")
        print("Install ffmpeg (includes ffprobe) and add it to PATH, then re-run.")
        sys.exit(1)


def get_video_stream(path: Path) -> dict | None:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-select_streams",
        "v:0",
        str(path),
    ]
    result = run(cmd)
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        return streams[0] if streams else None
    except json.JSONDecodeError:
        return None


def get_crop(path: Path, num_frames: int) -> str | None:
    """
    Run cropdetect and return the last detected crop string, e.g. '1080:960:0:28'.
    cropdetect is only reliable when SAR = 1:1 (square pixels).
    """
    cmd = [
        "ffmpeg",
        "-i",
        str(path),
        "-vf",
        "cropdetect=24:2:0",
        "-frames:v",
        str(num_frames),
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    crop = None
    for line in result.stderr.splitlines():
        if "crop=" in line:
            crop = line.split("crop=")[-1].strip()
    return crop


def sar_broken(stream: dict) -> bool:
    sar = stream.get("sample_aspect_ratio", "1:1")
    return sar not in ("1:1", "0:1", "", "N/A")


def crop_removes_pixels(stream: dict, crop_str: str) -> bool:
    try:
        cw = int(crop_str.split(":")[0])
        ch = int(crop_str.split(":")[1])
        return cw < stream["width"] or ch < stream["height"]
    except (ValueError, IndexError):
        return False


# ── core ─────────────────────────────────────────────────────────────────────


def process(path: Path, output_dir: Path) -> None:
    print(f"\n→ {path.name}")

    stream = get_video_stream(path)
    if not stream:
        print("  [!] Cannot read stream info — skipping")
        return

    w = stream["width"]
    h = stream["height"]
    sar = stream.get("sample_aspect_ratio", "1:1")
    duration = float(stream.get("duration", 60))
    num_frames = min(300, max(60, int(duration * 30)))

    print(f"  {w}x{h}  SAR: {sar}  duration: {duration:.1f}s")

    needs_sar = sar_broken(stream)

    # cropdetect is unreliable when SAR != 1:1 because pixels are not square.
    # In that case the display geometry is distorted, so detected crop coords
    # would map to wrong regions after SAR correction. Skip cropdetect entirely
    # when SAR is broken — fix SAR first, user can re-run if black bars remain.
    if needs_sar:
        crop_str = None
        needs_crop = False
    else:
        crop_str = get_crop(path, num_frames)
        needs_crop = crop_str is not None and crop_removes_pixels(stream, crop_str)

    output_path = output_dir / path.name

    if not needs_sar and not needs_crop:
        # No issues — copy as-is so fixed/ contains all videos
        print("  ✓ No issues — copying as-is")
        shutil.copy2(path, output_path)
        return

    if needs_sar:
        print("  [hint] SAR fixed first — black bars (if any) may remain.")
        print("         Re-run this script on 'fixed/' to crop them.")

    # Build filter chain.
    # Order: crop first (operates on original pixel dimensions),
    # then SAR scale (uses cropped iw × sar to get correct display width).
    # trunc(.../2)*2 forces even dimensions required by libx264.
    filters = []
    if needs_crop:
        print(f"  → Crop black bars: {crop_str}")
        filters.append(f"crop={crop_str}")
    if needs_sar:
        print(f"  → Fix SAR: {sar} → 1:1")
        filters.append("scale=trunc(iw*sar/2)*2:trunc(ih/2)*2,setsar=1")

    vf = ",".join(filters)

    cmd = [
        "ffmpeg",
        "-i",
        str(path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-crf",
        str(CRF),
        "-c:a",
        "copy",
        "-map_metadata",
        "0",  # preserve container metadata (title, date, etc.)
        "-y",  # overwrite output if exists
        str(output_path),
    ]

    print("  → Encoding…")
    result = run(cmd)

    if result.returncode == 0:
        orig_mb = path.stat().st_size / 1_048_576
        out_mb = output_path.stat().st_size / 1_048_576
        print(f"  ✓ Saved: {output_path.name}  ({orig_mb:.1f} MB → {out_mb:.1f} MB)")
        # restore original file timestamps
        stat = path.stat()
        os.utime(output_path, (stat.st_atime, stat.st_mtime))
    else:
        # Remove partially-written/broken output so 'fixed/' never holds
        # a corrupt file silently mistaken for a successful result.
        output_path.unlink(missing_ok=True)
        print("  ✗ Failed! (no output written)")
        lines = [l for l in result.stderr.splitlines() if l.strip()]
        for line in lines[-6:]:
            print(f"    {line}")


# ── entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    check_dependencies()

    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")

    if not folder.exists():
        print(f"Folder not found: {folder}")
        sys.exit(1)

    output_dir = folder / OUTPUT_FOLDER
    output_dir.mkdir(exist_ok=True)

    videos = sorted(
        f
        for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    )

    if not videos:
        print("No video files found.")
        sys.exit(0)

    print(f"Found {len(videos)} video(s)  →  output: '{output_dir}'")

    for video in videos:
        process(video, output_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
