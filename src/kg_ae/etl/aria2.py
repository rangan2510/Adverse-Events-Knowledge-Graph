"""
aria2c-based batch download manager.

We hand a flat list of :class:`DownloadSpec` (url + destination) to a single
``aria2c`` process via an input file. aria2c then handles, natively and in one
pass:

- inter-file parallelism (``-j``: download several files at once),
- per-file multi-connection splits (``-x``/``-s``: one big file over N sockets),
- resume of partial files (``--continue``),
- retries with backoff (``--max-tries`` / ``--retry-wait``),
- live console progress.

This replaces the old per-file httpx loop + tenacity + ThreadPoolExecutor for
all "simple file URL" datasets. Sources that need pre-resolution (paginated
APIs, directory listings) resolve their URLs first, then can still hand the
resulting specs here.

If aria2c is not installed (e.g. a minimal box), we transparently fall back to
a per-spec httpx download with retries.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from kg_ae.config import settings
from kg_ae.etl.logging import get_logger

log = get_logger("kg_ae.etl.aria2")

ARIA2C = shutil.which("aria2c")


@dataclass(frozen=True)
class DownloadSpec:
    """A single file to download."""

    url: str
    dest: Path  # absolute destination file path
    source: str = ""  # owning dataset key (for logging)


def aria2_available() -> bool:
    """True if aria2c is on PATH and enabled in settings."""
    return bool(ARIA2C) and settings.use_aria2


def _build_input_file(specs: list[DownloadSpec], tmp: Path) -> None:
    """Write specs in aria2c input-file format.

    Format per entry::

        <url>
          dir=<absolute dir>
          out=<filename>
    """
    lines: list[str] = []
    for spec in specs:
        spec.dest.parent.mkdir(parents=True, exist_ok=True)
        lines.append(spec.url)
        lines.append(f"  dir={spec.dest.parent}")
        lines.append(f"  out={spec.dest.name}")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_aria2(input_file: Path, concurrency: int, timeout: float | None = None) -> int:
    """Run a single aria2c process over the input file (progress to console).

    Returns the process exit code (0 = all ok). Does not raise on partial
    failure; the caller reconciles by checking which files landed on disk.

    Slow/stuck connections are bounded so one pathological server (e.g. a
    throttled mirror) cannot hang the whole batch:
    - ``--lowest-speed-limit`` aborts a transfer that stalls below a floor,
    - ``--timeout`` / ``--connect-timeout`` bound individual sockets,
    - the ``timeout`` arg is a hard wall-clock ceiling on the whole process.
    """
    cmd = [
        ARIA2C,
        f"--input-file={input_file}",
        f"-j{concurrency}",          # parallel downloads (files at once)
        "-x", "8",                   # max connections per server (per file)
        "-s", "8",                   # split each file into 8 segments
        "-k", "1M",                  # min split size
        "--continue=true",           # resume partial files
        "--max-tries=5",             # retry flaky servers
        "--retry-wait=5",            # seconds between tries
        "--lowest-speed-limit=1K",   # only abort a truly dead (near-zero) transfer
        "--timeout=120",             # per-connection read timeout
        "--connect-timeout=30",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        "--console-log-level=warn",
        "--summary-interval=0",
        "--check-certificate=true",
    ]
    # No capture_output: let aria2c render its own progress to the console.
    try:
        return subprocess.run(cmd, check=False, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        log.error("etl.aria2.timeout", seconds=timeout)
        return 1



@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
def _httpx_fetch(spec: DownloadSpec, timeout: float = 600.0) -> None:
    """Fallback / mop-up: download a single spec with httpx (retried)."""
    spec.dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", spec.url, timeout=timeout, follow_redirects=True) as response:
        response.raise_for_status()
        with open(spec.dest, "wb") as f:
            for chunk in response.iter_bytes(chunk_size=65536):
                f.write(chunk)


def _complete(spec: DownloadSpec) -> bool:
    """True if the file fully downloaded (exists and no aria2 control sidecar).

    aria2c leaves a ``<file>.aria2`` control file next to a partial download and
    removes it on success. Its presence (or a missing target) means the file is
    incomplete and must not be treated as a successful download.
    """
    control = spec.dest.with_name(spec.dest.name + ".aria2")
    return spec.dest.exists() and not control.exists()


def _discard_partial(spec: DownloadSpec) -> None:
    """Remove a partial download and its aria2 control sidecar, if present."""
    control = spec.dest.with_name(spec.dest.name + ".aria2")
    spec.dest.unlink(missing_ok=True)
    control.unlink(missing_ok=True)


def fetch_specs(
    specs: list[DownloadSpec], concurrency: int | None = None
) -> tuple[list[DownloadSpec], list[DownloadSpec]]:
    """Download all specs. Returns ``(downloaded, failed)``.

    Strategy:
    1. One aria2c process downloads everything in parallel (fast, resumable).
    2. Any spec whose file is missing afterwards (e.g. a transient network
       abort that exhausted aria2c's tries) is retried once with httpx, which
       uses a single connection and tolerates servers that reject multi-segment
       range requests.

    aria2c partial failures never abort the batch; the caller inspects the
    ``failed`` list and decides whether the run can proceed.
    """
    if not specs:
        return [], []

    concurrency = concurrency or settings.download_concurrency

    if aria2_available():
        with tempfile.TemporaryDirectory() as td:
            input_file = Path(td) / "aria2-input.txt"
            _build_input_file(specs, input_file)
            log.info(
                "etl.aria2.batch",
                files=len(specs),
                concurrency=concurrency,
                sources=",".join(sorted({s.source for s in specs if s.source})),
            )
            _run_aria2(input_file, concurrency, timeout=settings.download_timeout)

        # Mop up anything aria2c couldn't complete, via httpx. A file is only
        # complete if it exists AND has no ``.aria2`` control sidecar (which
        # marks an aborted/partial transfer). Partial files are removed so the
        # httpx fetch starts clean.
        for spec in specs:
            if _complete(spec):
                continue
            _discard_partial(spec)
            log.info("etl.aria2.mopup_httpx", source=spec.source, file=spec.dest.name)
            try:
                _httpx_fetch(spec)
            except Exception as e:  # noqa: BLE001 - reported via failed list
                log.error("etl.download.failed", source=spec.source, file=spec.dest.name, detail=str(e))
    else:
        log.info("etl.aria2.fallback_httpx", files=len(specs))
        for spec in specs:
            try:
                _httpx_fetch(spec)
            except Exception as e:  # noqa: BLE001
                log.error("etl.download.failed", source=spec.source, file=spec.dest.name, detail=str(e))

    downloaded = [s for s in specs if _complete(s)]
    failed = [s for s in specs if not _complete(s)]
    return downloaded, failed
