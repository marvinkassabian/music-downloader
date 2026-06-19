"""Concurrent download helpers used by main.py."""

from __future__ import annotations

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yt_dlp
from yt_dlp.utils import DownloadError


@dataclass(frozen=True)
class DownloadJob:
    """Represents one track download target."""

    url: str
    output_path: Path
    playlist_name: str


TRANSIENT_ERROR_PATTERNS = (
    "connection reset by peer",
    "connection aborted",
    "timed out",
    "read timed out",
    "remote end closed connection",
    "temporarily unavailable",
)
AGE_RESTRICTION_PATTERNS = (
    "sign in to confirm your age",
    "this video may be inappropriate for some users",
)


def _auto_workers(total_jobs: int) -> int:
    # Downloads are mostly network-bound, but avoid spawning too many threads.
    cpu = os.cpu_count() or 1
    return max(1, min(total_jobs, max(4, cpu)))


def _resolve_workers(total_jobs: int, max_download_workers: int) -> int:
    workers = _auto_workers(total_jobs)
    if max_download_workers > 0:
        workers = min(workers, max_download_workers)
    return max(1, min(total_jobs, workers))


def _job_options(base_options: dict[str, Any], output_path: Path) -> dict[str, Any]:
    options = dict(base_options)
    options["noplaylist"] = True
    options["outtmpl"] = str(output_path.with_suffix(".%(ext)s"))
    return options


def _run_job(job: DownloadJob, base_options: dict[str, Any]) -> tuple[bool, str | None]:
    # Guard by final target file to avoid re-downloading when conversion already exists.
    if job.output_path.exists():
        return True, None

    job.output_path.parent.mkdir(parents=True, exist_ok=True)
    options = _job_options(base_options, job.output_path)

    max_attempts = max(1, int(options.get("retries", 0)) + 1)
    last_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            with yt_dlp.YoutubeDL(cast(Any, options)) as ydl:
                result = ydl.download([job.url])
            return result == 0, None
        except DownloadError as exc:
            last_error = str(exc)
            if not _is_transient_error(last_error):
                break
            if attempt < max_attempts:
                # Small bounded backoff for transient network failures.
                time.sleep(min(3.0, 0.5 * attempt))
        except Exception as exc:  # pragma: no cover - defensive catch for worker threads
            last_error = str(exc)
            if not _is_transient_error(last_error):
                break
            if attempt < max_attempts:
                time.sleep(min(3.0, 0.5 * attempt))

    return False, last_error


def _is_transient_error(error: str | None) -> bool:
    if not error:
        return False
    normalized = error.lower()
    return any(pattern in normalized for pattern in TRANSIENT_ERROR_PATTERNS)


def _is_age_restricted_error(error: str | None) -> bool:
    if not error:
        return False
    normalized = error.lower()
    return any(pattern in normalized for pattern in AGE_RESTRICTION_PATTERNS)


def _one_line_error(error: str | None) -> str | None:
    if not error:
        return None
    collapsed = re.sub(r"\s+", " ", error).strip()
    return collapsed[:280]


def run_download_jobs(jobs: list[DownloadJob], ydl_options: dict[str, Any], max_download_workers: int) -> int:
    """Run all download jobs with a bounded thread pool.

    Returns 0 when all jobs succeed, 1 otherwise.
    """

    if not jobs:
        print("No tracks found to download.")
        return 0

    existing_jobs = [job for job in jobs if job.output_path.exists()]
    pending_jobs = [job for job in jobs if not job.output_path.exists()]

    if existing_jobs:
        print(f"Skipping {len(existing_jobs)} existing track(s).")

    if not pending_jobs:
        print("All tracks already exist. Nothing to download.")
        return 0

    workers = _resolve_workers(len(pending_jobs), max_download_workers)
    print(f"Queued {len(pending_jobs)} track(s) across {workers} worker(s).")

    failures: list[tuple[DownloadJob, str | None]] = []
    lock = threading.Lock()

    def record_result(job: DownloadJob, ok: bool, error: str | None) -> None:
        if ok:
            return
        with lock:
            failures.append((job, error))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_job = {executor.submit(_run_job, job, ydl_options): job for job in pending_jobs}
        for future in as_completed(future_to_job):
            job = future_to_job[future]
            ok, error = future.result()
            record_result(job, ok, error)

    if failures:
        print(f"Failed downloads: {len(failures)}/{len(pending_jobs)}")
        age_restricted_count = 0
        transient_count = 0
        for job, error in failures:
            print(f" - {job.playlist_name}: {job.output_path.name}")
            one_line = _one_line_error(error)
            if one_line:
                print(f"   {one_line}")
            if _is_age_restricted_error(error):
                age_restricted_count += 1
            elif _is_transient_error(error):
                transient_count += 1

        if age_restricted_count:
            print(
                "Hint: some tracks are age-restricted. Set COOKIES_FROM_BROWSER in main.py "
                "or export cookies and set COOKIES_FILE to authenticate yt-dlp."
            )

        if transient_count:
            print(
                "Hint: transient network failures were detected. Retries are enabled; "
                "rerunning usually completes remaining tracks."
            )
        return 1

    print(f"Downloaded {len(pending_jobs)} new track(s) successfully.")
    return 0
