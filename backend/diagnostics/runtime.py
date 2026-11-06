"""Low-overhead, read-only runtime diagnostics for Render and other Linux hosts.

No environment values, credentials, database contents, or user data are exposed.
"""
from __future__ import annotations

import os
import platform
import time
from pathlib import Path
from typing import Any

_PROCESS_STARTED = time.monotonic()


def _read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _status_memory_bytes() -> tuple[int | None, int | None]:
    raw = _read_text("/proc/self/status")
    if not raw:
        return None, None

    values: dict[str, int] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition(":")
        if not separator or key not in {"VmRSS", "VmHWM"}:
            continue
        parts = value.strip().split()
        if not parts:
            continue
        try:
            amount = int(parts[0])
            unit = parts[1].lower() if len(parts) > 1 else "kb"
            values[key] = amount * (1024 if unit == "kb" else 1)
        except (ValueError, IndexError):
            continue
    return values.get("VmRSS"), values.get("VmHWM")


def _container_memory() -> tuple[int | None, int | None]:
    # cgroup v2
    current = _read_text("/sys/fs/cgroup/memory.current")
    limit = _read_text("/sys/fs/cgroup/memory.max")
    if current is not None and limit is not None:
        try:
            current_bytes = int(current)
            limit_bytes = None if limit == "max" else int(limit)
            if limit_bytes is not None and limit_bytes >= 2**60:
                limit_bytes = None
            return current_bytes, limit_bytes
        except ValueError:
            pass

    # cgroup v1 fallback
    current = _read_text("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    limit = _read_text("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    try:
        current_bytes = int(current) if current is not None else None
        limit_bytes = int(limit) if limit is not None else None
        if limit_bytes is not None and limit_bytes >= 2**60:
            limit_bytes = None
        return current_bytes, limit_bytes
    except ValueError:
        return None, None


def _cpu_quota_cores() -> float | None:
    # cgroup v2: "quota period", or "max period"
    raw = _read_text("/sys/fs/cgroup/cpu.max")
    if raw:
        parts = raw.split()
        if len(parts) == 2 and parts[0] != "max":
            try:
                return round(int(parts[0]) / int(parts[1]), 3)
            except (ValueError, ZeroDivisionError):
                pass

    # cgroup v1
    quota = _read_text("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    period = _read_text("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    try:
        if quota is not None and period is not None and int(quota) > 0:
            return round(int(quota) / int(period), 3)
    except (ValueError, ZeroDivisionError):
        pass
    return None


def collect_runtime_snapshot() -> dict[str, Any]:
    """Return safe process/container metrics without reading secrets or user data."""
    rss, peak_rss = _status_memory_bytes()
    memory_current, memory_limit = _container_memory()

    if peak_rss is None:
        try:
            import resource

            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            peak_rss = int(peak * (1024 if platform.system() == "Linux" else 1))
        except (ImportError, OSError, ValueError):
            peak_rss = None

    memory_percent = None
    if memory_current is not None and memory_limit:
        memory_percent = round(memory_current / memory_limit * 100, 1)

    return {
        "pid": os.getpid(),
        "python_version": platform.python_version(),
        "platform": platform.system().lower(),
        "uptime_seconds": round(time.monotonic() - _PROCESS_STARTED, 1),
        "port_configured": bool(os.getenv("PORT")),
        "process_rss_mb": round(rss / 1024 / 1024, 1) if rss is not None else None,
        "process_peak_rss_mb": (
            round(peak_rss / 1024 / 1024, 1) if peak_rss is not None else None
        ),
        "container_memory_current_mb": (
            round(memory_current / 1024 / 1024, 1)
            if memory_current is not None else None
        ),
        "container_memory_limit_mb": (
            round(memory_limit / 1024 / 1024, 1)
            if memory_limit is not None else None
        ),
        "container_memory_percent": memory_percent,
        "cpu_quota_cores": _cpu_quota_cores(),
    }


async def runtime_monitor_loop(logger: Any, interval_seconds: int = 60) -> None:
    """Log periodic CPU and memory samples; intended to run as a lifespan task."""
    previous_cpu = time.process_time()
    previous_wall = time.monotonic()

    while True:
        await __import__("asyncio").sleep(interval_seconds)
        current_cpu = time.process_time()
        current_wall = time.monotonic()
        elapsed = max(current_wall - previous_wall, 0.001)
        cpu_percent = round((current_cpu - previous_cpu) / elapsed * 100, 1)
        logger.info(
            "V36.2 runtime sample cpu_process_percent=%.1f %s",
            cpu_percent,
            collect_runtime_snapshot(),
        )
        previous_cpu = current_cpu
        previous_wall = current_wall
