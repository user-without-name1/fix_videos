# fix_videos.py

Batch-fix black bars and wrong SAR (sample aspect ratio) in video files using `ffmpeg`/`ffprobe`.

## What it does

For every video in the target folder:

1. Reads stream info via `ffprobe` (resolution, SAR, duration).
2. If SAR is broken (not `1:1`) — fixes it via `scale` + `setsar=1`.
3. If SAR is fine — runs `cropdetect` to find black bars; crops them if found.
4. If neither issue is found — copies the file as-is into `fixed/`.
5. Otherwise — re-encodes with `libx264` (CRF 18, near-lossless) into `fixed/`.

**Originals are never modified or deleted.** All output goes into a `fixed/` subfolder of the target directory.

> Note: if a file has both broken SAR *and* black bars, only SAR is fixed on the first run (cropdetect is unreliable on non-square pixels). The script prints a hint to re-run on `fixed/` to remove remaining black bars.

## Requirements

- Python 3.10+ (uses `dict | None` syntax)
- `ffmpeg` and `ffprobe` available in `PATH`

### Installing ffmpeg

**Windows:**
1. Download a build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) (`ffmpeg-release-full.7z`)
2. Extract, e.g. to `C:\ffmpeg`
3. Add `C:\ffmpeg\bin` to your `PATH` environment variable
4. Verify: open a new terminal and run `ffmpeg -version` and `ffprobe -version`

**Linux (Debian/Ubuntu/WSL):**
```bash
sudo apt update && sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

The script checks for both tools on startup and exits with an instruction if either is missing — no need to verify manually before running.

## Usage

```bash
# Process current folder
python fix_videos.py

# Process a specific folder
python fix_videos.py "C:\Users\vlady\Videos"
```

Supported extensions: `.mp4`, `.mkv`, `.avi`, `.mov`, `.m4v`, `.wmv`

## Output

```
your_folder/
├── video1.mp4
├── video2.mkv
└── fixed/
    ├── video1.mp4   ← cropped/SAR-fixed or copied as-is
    └── video2.mkv
```

- File timestamps (atime/mtime) are restored to match the original after processing.
- Failed conversions do not leave a broken file behind in `fixed/` — the partial output is removed and the error (last 6 lines of `ffmpeg` stderr) is printed to console.

## Configuration

Edit constants at the top of the script:

| Constant | Default | Meaning |
|---|---|---|
| `CRF` | `18` | Encoding quality. `0` = lossless, `51` = worst. `18` ≈ visually lossless. |
| `OUTPUT_FOLDER` | `"fixed"` | Name of the output subfolder. |
| `VIDEO_EXTENSIONS` | see above | File extensions to process. |

## Known limitations

- `cropdetect` threshold is fixed at `24` — very dark scenes (e.g. night footage) can occasionally be misdetected as black bars. Check the printed crop value before trusting it on unusual content.
- Audio is always stream-copied (`-c:a copy`). If the source audio codec is incompatible with the target container, the run will fail (rare in practice with these container/extension combos).
- `duration` is read from the video stream; if a container reports duration only at the format level (rare), the script falls back to a 60s default for frame-count estimation.
