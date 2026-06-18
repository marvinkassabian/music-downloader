#!/usr/bin/env python3
"""Simple configurable entrypoint for downloading YouTube Music playlists."""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import yt_dlp
from worker_pool import DownloadJob, run_download_jobs

# ---------------------------
# Manual configuration
# ---------------------------

# Add playlist links here.
PLAYLIST_URLS: list[str] = [
    "https://music.youtube.com/playlist?list=OLAK5uy_nWrBd-n_L0xHfL8lmH-qM9U2cTlKAOQYs&si=hN2DWt7sTW3zH4xv",
    "https://music.youtube.com/playlist?list=OLAK5uy_l38_t-faETNnZv7FZ_RjtYvl_hXVHPpX4&si=prC6pxFErvZ5nAAA",
    "https://music.youtube.com/playlist?list=OLAK5uy_ngnO6lTnpFPdCvgcTxnnC8fRdMmFn2jkA&si=ZuK4tY55eozWmLPM",
    "https://music.youtube.com/playlist?list=OLAK5uy_k-axKCdj15ZavMsthn-PVNfA3Qxw3FZgE&si=M8JIv_vIf_iUyoJ5",
    "https://music.youtube.com/playlist?list=OLAK5uy_kp9KxtkuU6hADyESsiqnQZEB264vvInPw",
]

# Optional: one URL per line. Lines starting with # are ignored.
PLAYLISTS_FILE: str | None = "playlists.txt"

AUDIO_FORMAT = "mp3"  # mp3, m4a, opus, wav, flac
AUDIO_QUALITY = "0"   # 0 is best for mp3
MAX_DOWNLOAD_WORKERS = 6  # Cap for auto workers; use 0 to disable cap.
CONCURRENT_FRAGMENT_DOWNLOADS = 4  # Per-track network fragment concurrency.

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
        "ignoreerrors": True,
        "nooverwrites": True,  # skip a track if the output file already exists
        "concurrent_fragment_downloads": CONCURRENT_FRAGMENT_DOWNLOADS,
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


def safe_name(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", value).strip().rstrip(".")
    return cleaned or "untitled"


def build_extract_options() -> dict:
    options: dict = {
        "extract_flat": "in_playlist",
        "skip_download": True,
        "ignoreerrors": True,
        "noplaylist": False,
        "quiet": True,
    }
    if COOKIES_FROM_BROWSER:
        options["cookiesfrombrowser"] = (COOKIES_FROM_BROWSER,)
    return options


def resolve_track_url(entry: dict) -> str | None:
    direct_url = entry.get("url")
    if isinstance(direct_url, str) and direct_url.startswith("http"):
        return direct_url

    webpage_url = entry.get("webpage_url")
    if isinstance(webpage_url, str) and webpage_url.startswith("http"):
        return webpage_url

    video_id = entry.get("id")
    if isinstance(video_id, str) and video_id:
        return f"https://music.youtube.com/watch?v={video_id}"

    return None


def build_jobs_for_playlist(playlist_url: str) -> list[DownloadJob]:
    try:
        with yt_dlp.YoutubeDL(build_extract_options()) as ydl:
            info = ydl.extract_info(playlist_url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        print(f"Failed to read playlist {playlist_url}: {exc}", file=sys.stderr)
        return []

    if not info:
        return []

    playlist_title = safe_name(str(info.get("title") or info.get("id") or "Unknown Playlist"))
    entries = info.get("entries") or []

    jobs: list[DownloadJob] = []
    seen_base_names: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue

        track_url = resolve_track_url(entry)
        if not track_url:
            continue

        track_title = safe_name(str(entry.get("title") or entry.get("id") or f"track-{index:03d}"))
        base_name = f"{index:03d} - {track_title}"

        # Dedupe only within the same playlist by final output basename.
        if base_name in seen_base_names:
            continue
        seen_base_names.add(base_name)

        output_path = Path("downloads") / playlist_title / f"{base_name}.{AUDIO_FORMAT}"
        jobs.append(DownloadJob(url=track_url, output_path=output_path, playlist_name=playlist_title))

    return jobs


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

    jobs: list[DownloadJob] = []
    for playlist_url in urls:
        jobs.extend(build_jobs_for_playlist(playlist_url))

    return run_download_jobs(jobs, build_ydl_options(), MAX_DOWNLOAD_WORKERS)


if __name__ == "__main__":
    raise SystemExit(main())
