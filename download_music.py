#!/usr/bin/env python3
"""Download audio from YouTube Music playlists using yt-dlp."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yt_dlp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download songs from YouTube Music playlists using yt-dlp."
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="One or more playlist URLs.",
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        help="Path to a text file with one playlist URL per line.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="downloads/%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s",
        help="Output template for downloaded files.",
    )
    parser.add_argument(
        "--audio-format",
        choices=["mp3", "m4a", "opus", "wav", "flac"],
        default="mp3",
        help="Audio format to extract.",
    )
    parser.add_argument(
        "--audio-quality",
        default="0",
        help="Audio quality passed to FFmpegExtractAudio (0 is best for mp3).",
    )
    parser.add_argument(
        "--archive",
        default="downloaded.txt",
        help="Download archive file to avoid downloading duplicates.",
    )
    parser.add_argument(
        "--cookies-from-browser",
        choices=["chrome", "chromium", "firefox", "edge", "safari", "brave", "opera", "vivaldi"],
        help="Load cookies from a local browser profile for private/restricted content.",
    )
    parser.add_argument(
        "--cookie-file",
        type=Path,
        help="Path to an exported Netscape cookies.txt file (useful for age-restricted videos).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=8,
        help="Retry count for network errors.",
    )
    parser.add_argument(
        "--fragment-retries",
        type=int,
        default=8,
        help="Retry count for fragment download errors.",
    )
    parser.add_argument(
        "--extractor-retries",
        type=int,
        default=5,
        help="Retry count for extractor requests.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without downloading files.",
    )
    return parser.parse_args()


def read_urls_from_file(path: Path) -> list[str]:
    urls: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def read_urls_from_stdin() -> list[str]:
    if sys.stdin.isatty():
        return []

    urls: list[str] = []
    for line in sys.stdin:
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def build_ydl_options(args: argparse.Namespace) -> dict:
    options: dict = {
        "format": "bestaudio/best",
        "outtmpl": args.output,
        "ignoreerrors": True,
        "noplaylist": False,
        "download_archive": args.archive,
        "retries": max(0, args.retries),
        "fragment_retries": max(0, args.fragment_retries),
        "extractor_retries": max(0, args.extractor_retries),
        "file_access_retries": 3,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": args.audio_format,
                "preferredquality": args.audio_quality,
            }
        ],
    }

    if args.cookies_from_browser:
        options["cookiesfrombrowser"] = (args.cookies_from_browser,)

    if args.cookie_file:
        options["cookiefile"] = str(args.cookie_file)

    if args.dry_run:
        options["skip_download"] = True
        options["simulate"] = True

    return options


def main() -> int:
    args = parse_args()

    urls: list[str] = []
    urls.extend(args.urls)

    if args.input:
        if not args.input.exists():
            print(f"Input file not found: {args.input}", file=sys.stderr)
            return 2
        urls.extend(read_urls_from_file(args.input))

    urls.extend(read_urls_from_stdin())

    # Keep user-provided order but drop duplicates.
    unique_urls = list(dict.fromkeys(urls))

    if not unique_urls:
        print("No playlist URLs provided.", file=sys.stderr)
        print("Pass URLs as args, --input file, or pipe lines into stdin.", file=sys.stderr)
        return 2

    ydl_options = build_ydl_options(args)

    try:
        with yt_dlp.YoutubeDL(ydl_options) as ydl:
            result = ydl.download(unique_urls)
    except yt_dlp.utils.DownloadError as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1

    return 0 if result == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
