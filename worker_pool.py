"""Concurrent download helpers used by main.py."""

from __future__ import annotations

import os
import threading
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
    try:
        # Guard by final target file to avoid re-downloading when conversion already exists.
        if job.output_path.exists():
            return True, None

        job.output_path.parent.mkdir(parents=True, exist_ok=True)
        options = _job_options(base_options, job.output_path)
        with yt_dlp.YoutubeDL(cast(Any, options)) as ydl:
            result = ydl.download([job.url])
        return result == 0, None
    except DownloadError as exc:
        return False, str(exc)
    except Exception as exc:  # pragma: no cover - defensive catch for worker threads
        return False, str(exc)


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
        for job, error in failures:
            print(f" - {job.playlist_name}: {job.output_path.name}")
            if error:
                print(f"   {error}")
        return 1

    print(f"Downloaded {len(pending_jobs)} new track(s) successfully.")
    return 0
