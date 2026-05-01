"""
Parallel PDF downloader with per-domain rate limiting and 429 auto-backoff.

Usage:
    from resophy.tools.basic_tools.parallel_downloader import (
        parallel_download, DownloadTask, DownloadResult, DomainLimit, RateLimitError,
    )

    tasks = [DownloadTask(task_id="1234.5678", fn=lambda: download_func(...), domain="export.arxiv.org")]
    results = parallel_download(tasks, max_workers=3)
    for r in results:
        if r.success:
            print(f"Downloaded: {r.result}")
        else:
            print(f"Failed: {r.error}")
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import requests


class RateLimitError(Exception):
    """Raised when a 429 Too Many Requests response is received."""
    pass


@dataclass
class DomainLimit:
    max_concurrent: int = 5
    min_interval: float = 1.0  # seconds between requests to same domain


@dataclass
class DownloadTask:
    task_id: str  # unique identifier (e.g., arxiv_id)
    fn: Callable[[], Any]  # the download function to call
    domain: str = ""  # for rate limiting, e.g. "export.arxiv.org"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DownloadResult:
    task_id: str
    success: bool
    result: Any = None  # return value of fn on success
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


DEFAULT_DOMAIN_LIMITS: Dict[str, DomainLimit] = {
    "arxiv.org": DomainLimit(max_concurrent=2, min_interval=3.0),
    "export.arxiv.org": DomainLimit(max_concurrent=2, min_interval=3.0),
    "api.openalex.org": DomainLimit(max_concurrent=5, min_interval=0.5),
    "api.semanticscholar.org": DomainLimit(max_concurrent=2, min_interval=1.1),
}

MAX_RETRIES = 3
BACKOFF_BASE = 2.0  # seconds


def _extract_domain(url: str) -> str:
    """Extract domain from a URL, e.g. 'export.arxiv.org' from 'https://export.arxiv.org/pdf/1234'."""
    try:
        parsed = urlparse(url)
        return parsed.hostname or ""
    except Exception:
        return ""


class _DomainRateLimiter:
    """Per-domain concurrency cap + minimum interval enforcement."""

    def __init__(self, domain_limits: Dict[str, DomainLimit]):
        self._domain_limits = domain_limits
        self._semaphores: Dict[str, threading.Semaphore] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._last_request_time: Dict[str, float] = {}
        self._global_lock = threading.Lock()

    def _ensure_domain(self, domain: str):
        """Lazily create per-domain primitives."""
        if domain not in self._semaphores:
            limit = self._domain_limits.get(domain, DomainLimit())
            self._semaphores[domain] = threading.Semaphore(limit.max_concurrent)
            self._locks[domain] = threading.Lock()
            self._last_request_time[domain] = 0.0

    def acquire(self, domain: str):
        """Block until a slot is available and min_interval has elapsed."""
        with self._global_lock:
            self._ensure_domain(domain)

        sem = self._semaphores[domain]
        sem.acquire()

        # Enforce minimum interval between requests
        limit = self._domain_limits.get(domain, DomainLimit())
        if limit.min_interval > 0:
            lock = self._locks[domain]
            with lock:
                now = time.monotonic()
                elapsed = now - self._last_request_time[domain]
                if elapsed < limit.min_interval:
                    time.sleep(limit.min_interval - elapsed)
                self._last_request_time[domain] = time.monotonic()

    def release(self, domain: str):
        """Release a concurrency slot."""
        with self._global_lock:
            self._ensure_domain(domain)
        self._semaphores[domain].release()


def _execute_with_backoff(
    task: DownloadTask,
    rate_limiter: _DomainRateLimiter,
    stop_event: Optional[threading.Event],
) -> DownloadResult:
    """Execute a single download task with rate limiting and 429 backoff."""
    domain = task.domain or "default"

    for attempt in range(MAX_RETRIES + 1):
        if stop_event and stop_event.is_set():
            return DownloadResult(task_id=task.task_id, success=False, error="Cancelled")

        rate_limiter.acquire(domain)
        try:
            result = task.fn()
            return DownloadResult(
                task_id=task.task_id, success=True, result=result, metadata=task.metadata
            )
        except (RateLimitError, requests.exceptions.HTTPError) as e:
            is_429 = isinstance(e, RateLimitError) or (
                isinstance(e, requests.exceptions.HTTPError)
                and hasattr(e, 'response') and e.response is not None
                and e.response.status_code == 429
            )
            if is_429 and attempt < MAX_RETRIES:
                rate_limiter.release(domain)
                backoff = BACKOFF_BASE ** (attempt + 1)
                print(f"[ParallelDownload] 429 on {task.task_id}, "
                      f"retrying in {backoff:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(backoff)
                continue
            return DownloadResult(
                task_id=task.task_id, success=False,
                error=str(e), metadata=task.metadata,
            )
        except Exception as e:
            return DownloadResult(
                task_id=task.task_id, success=False, error=str(e), metadata=task.metadata
            )
        finally:
            rate_limiter.release(domain)

    return DownloadResult(task_id=task.task_id, success=False, error="Max retries exceeded")


def parallel_download(
    tasks: List[DownloadTask],
    max_workers: int = 3,
    domain_limits: Optional[Dict[str, DomainLimit]] = None,
    stop_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> List[DownloadResult]:
    """Execute download tasks in parallel with per-domain rate limiting.

    Args:
        tasks: ordered list of download tasks
        max_workers: max concurrent threads
        domain_limits: overrides for DEFAULT_DOMAIN_LIMITS
        stop_event: signal cancellation
        on_progress: callback(completed, total, task_id) after each task finishes

    Returns:
        List of DownloadResult in the same order as input tasks.
    """
    if not tasks:
        return []

    # Merge domain limits
    effective_limits = dict(DEFAULT_DOMAIN_LIMITS)
    if domain_limits:
        effective_limits.update(domain_limits)

    rate_limiter = _DomainRateLimiter(effective_limits)

    # Track results by task index to preserve order
    results: Dict[int, DownloadResult] = {}
    completed_count = 0
    completed_lock = threading.Lock()
    total = len(tasks)

    def _run_task(index: int, task: DownloadTask) -> tuple[int, DownloadResult]:
        return index, _execute_with_backoff(task, rate_limiter, stop_event)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_run_task, i, task): i
            for i, task in enumerate(tasks)
        }

        for future in as_completed(futures):
            if stop_event and stop_event.is_set():
                executor.shutdown(wait=False, cancel_futures=True)
                break

            index, result = future.result()
            results[index] = result

            with completed_lock:
                completed_count += 1
                if on_progress:
                    on_progress(completed_count, total, result.task_id)

    # Return results in original order
    return [results.get(i, DownloadResult(task_id=tasks[i].task_id, success=False, error="Not executed"))
            for i in range(len(tasks))]
