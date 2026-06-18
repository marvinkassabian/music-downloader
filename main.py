#!/usr/bin/env python3
"""Simple configurable entrypoint for downloading YouTube Music playlists."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yt_dlp

# ---------------------------
# Manual configuration
# ---------------------------

# Add playlist links here.
PLAYLIST_URLS: list[str] = [
    "https://music.youtube.com/playlist?list=PLRZ3iHgMV7KaQTS_faNh21PEs2IRbNPE5&si=nd2LgUejIEkSq_YR",
    "https://music.youtube.com/playlist?list=PLRZ3iHgMV7KZNG0Ia7GYJ-FiaPrDX7All&si=vKHOFY21Daz6GY-E",
    "https://music.youtube.com/playlist?list=PLRZ3iHgMV7Kavdyws4mqjr8h2ZeXXP3p-&si=w7DUYvqX9XnQgNWS",
    "https://music.youtube.com/playlist?list=PLRZ3iHgMV7KZpRvzTltw9RupIKjUBX9hR&si=aZdYQPyv6reAhZY8",
    "https://music.youtube.com/playlist?list=PLRZ3iHgMV7KYQR6PomU8P26NYCQl6IJoL&si=JxtNNAzJZ5QUHMvD",
    "https://music.youtube.com/playlist?list=PLRZ3iHgMV7Ka6WzZhXGPtPq1dqS5TO95p&si=QZXQZ_-jnqTRQChv",
    "https://music.youtube.com/playlist?list=PLRZ3iHgMV7KY9RQFEgTSFPeuvLsnNhPfX&si=aptcjgaMNGtZV1yw",
]

# Optional: one URL per line. Lines starting with # are ignored.
PLAYLISTS_FILE: str | None = "playlists.txt"

OUTPUT_TEMPLATE = "downloads/%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s"
AUDIO_FORMAT = "mp3"  # mp3, m4a, opus, wav, flac
AUDIO_QUALITY = "0"   # 0 is best for mp3

# Optional: chrome, chromium, firefox, edge, safari, brave, opera, vivaldi
COOKIES_FROM_BROWSER: str | None = None

DRY_RUN = False


def read_urls_from_file(path: Path) -> list[str]:
    urls: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def collect_urls() -> list[str]:
    urls: list[str] = []
    urls.extend(PLAYLIST_URLS)

    if PLAYLISTS_FILE:
        file_path = Path(PLAYLISTS_FILE)
        if file_path.exists():
            urls.extend(read_urls_from_file(file_path))
        else:
            print(f"Warning: playlists file not found: {file_path}", file=sys.stderr)

    # Keep order while removing duplicates.
    return list(dict.fromkeys(urls))


def build_ydl_options() -> dict:
    options: dict = {
        "format": "bestaudio/best",
        "outtmpl": OUTPUT_TEMPLATE,
        "ignoreerrors": True,
        "noplaylist": False,
        "nooverwrites": True,  # skip a track if the output file already exists
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": AUDIO_FORMAT,
                "preferredquality": AUDIO_QUALITY,
            }
        ],
    }

    if COOKIES_FROM_BROWSER:
        options["cookiesfrombrowser"] = (COOKIES_FROM_BROWSER,)

    if DRY_RUN:
        options["skip_download"] = True
        options["simulate"] = True

    return options


def main() -> int:
    urls = collect_urls()

    if not urls:
        print("No playlist URLs configured.", file=sys.stderr)
        print("Add URLs to PLAYLIST_URLS or set PLAYLISTS_FILE.", file=sys.stderr)
        return 2

    has_ffmpeg = shutil.which("ffmpeg") is not None
    has_ffprobe = shutil.which("ffprobe") is not None
    if not (has_ffmpeg and has_ffprobe):
        print("Error: ffmpeg/ffprobe not found.", file=sys.stderr)
        print("Install with: sudo apt update && sudo apt install -y ffmpeg", file=sys.stderr)
        print("This script requires ffmpeg for audio conversion.", file=sys.stderr)
        return 2

    if shutil.which("node") is None and shutil.which("deno") is None:
        print("Tip: install a JS runtime to reduce yt-dlp YouTube warnings.", file=sys.stderr)
        print("Example: sudo apt install -y nodejs", file=sys.stderr)

    try:
        with yt_dlp.YoutubeDL(build_ydl_options()) as ydl:
            result = ydl.download(urls)
    except yt_dlp.utils.DownloadError as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1

    return 0 if result == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
