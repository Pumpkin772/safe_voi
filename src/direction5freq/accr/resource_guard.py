"""Fail-closed process and memory guard for Direction5 simulations.

The guard combines two independent protections on Windows:

* a Job Object hard-caps active processes and committed job memory; and
* a polling monitor records system commit, available RAM, and process-tree
  memory, then terminates the complete job when a registered limit is crossed.

No scientific simulation is permitted if either protection cannot be enabled.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Mapping, Sequence

import psutil


GIB = 1024 ** 3


class ResourceGuardError(RuntimeError):
    """Raised when a run cannot be guarded or exceeds a resource limit."""


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    max_system_commit_fraction: float
    max_system_commit_growth_bytes: int
    min_available_physical_bytes: int
    max_tree_private_bytes: int
    max_descendant_processes: int
    poll_interval_s: float
    timeout_s: float
    preflight_max_system_commit_fraction: float | None = None


@dataclass(frozen=True, slots=True)
class ResourceSample:
    elapsed_s: float
    system_commit_bytes: int
    system_commit_limit_bytes: int
    system_commit_fraction: float
    available_physical_bytes: int
    tree_rss_bytes: int
    tree_private_bytes: int
    descendant_processes: int


class _PerformanceInformation(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("CommitTotal", ctypes.c_size_t),
        ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t),
        ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t),
        ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t),
        ("PageSize", ctypes.c_size_t),
        ("HandleCount", wintypes.DWORD),
        ("ProcessCount", wintypes.DWORD),
        ("ThreadCount", wintypes.DWORD),
    ]


class _JobBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JobExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _windows_memory_status() -> tuple[int, int, int]:
    if os.name != "nt":
        virtual = psutil.virtual_memory()
        swap = psutil.swap_memory()
        commit = int(virtual.used + swap.used)
        limit = int(virtual.total + swap.total)
        return commit, max(limit, 1), int(virtual.available)
    information = _PerformanceInformation()
    information.cb = ctypes.sizeof(information)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetPerformanceInfo.argtypes = [
        ctypes.POINTER(_PerformanceInformation),
        wintypes.DWORD,
    ]
    psapi.GetPerformanceInfo.restype = wintypes.BOOL
    if not psapi.GetPerformanceInfo(ctypes.byref(information), information.cb):
        raise ResourceGuardError(
            f"GetPerformanceInfo failed with WinError {ctypes.get_last_error()}"
        )
    page = int(information.PageSize)
    return (
        int(information.CommitTotal) * page,
        max(int(information.CommitLimit) * page, 1),
        int(information.PhysicalAvailable) * page,
    )


def _tree_memory(root_pid: int) -> tuple[int, int, int]:
    try:
        root = psutil.Process(root_pid)
        descendants = root.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        raise ResourceGuardError(f"cannot inspect guarded process tree: {exc}") from exc
    rss = 0
    private = 0
    for process in [root, *descendants]:
        try:
            memory = process.memory_info()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        rss += int(memory.rss)
        private += int(getattr(memory, "private", memory.rss))
    return rss, private, len(descendants)


def _sample(root_pid: int, started: float) -> ResourceSample:
    commit, commit_limit, available = _windows_memory_status()
    rss, private, descendants = _tree_memory(root_pid)
    return ResourceSample(
        elapsed_s=time.monotonic() - started,
        system_commit_bytes=commit,
        system_commit_limit_bytes=commit_limit,
        system_commit_fraction=commit / commit_limit,
        available_physical_bytes=available,
        tree_rss_bytes=rss,
        tree_private_bytes=private,
        descendant_processes=descendants,
    )


def _terminate_tree(root_pid: int) -> None:
    try:
        root = psutil.Process(root_pid)
    except psutil.NoSuchProcess:
        return
    descendants = root.children(recursive=True)
    for process in reversed(descendants):
        try:
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, alive = psutil.wait_procs(descendants, timeout=2.0)
    for process in alive:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        root.terminate()
        root.wait(timeout=2.0)
    except psutil.TimeoutExpired:
        root.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def _assign_windows_job(
    process: subprocess.Popen,
    *,
    active_process_limit: int,
    job_memory_limit_bytes: int,
):
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ResourceGuardError(
            f"CreateJobObjectW failed with WinError {ctypes.get_last_error()}"
        )
    information = _JobExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = (
        0x00000008  # JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | 0x00000200  # JOB_OBJECT_LIMIT_JOB_MEMORY
        | 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    )
    information.BasicLimitInformation.ActiveProcessLimit = int(active_process_limit)
    information.JobMemoryLimit = int(job_memory_limit_bytes)
    ok = kernel32.SetInformationJobObject(
        job,
        9,  # JobObjectExtendedLimitInformation
        ctypes.byref(information),
        ctypes.sizeof(information),
    )
    if not ok:
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise ResourceGuardError(
            f"SetInformationJobObject failed with WinError {error}"
        )
    process_handle = wintypes.HANDLE(int(process._handle))
    if not kernel32.AssignProcessToJobObject(job, process_handle):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise ResourceGuardError(
            f"AssignProcessToJobObject failed with WinError {error}"
        )
    return job


def _close_windows_job(job) -> None:
    if job is not None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(job)


def _violation(
    sample: ResourceSample,
    limits: ResourceLimits,
    baseline_commit_bytes: int,
) -> str | None:
    checks = (
        (
            sample.system_commit_fraction > limits.max_system_commit_fraction,
            "SYSTEM_COMMIT_FRACTION",
        ),
        (
            sample.system_commit_bytes - baseline_commit_bytes
            > limits.max_system_commit_growth_bytes,
            "SYSTEM_COMMIT_GROWTH",
        ),
        (
            sample.available_physical_bytes < limits.min_available_physical_bytes,
            "AVAILABLE_PHYSICAL_MEMORY",
        ),
        (
            sample.tree_private_bytes > limits.max_tree_private_bytes,
            "PROCESS_TREE_PRIVATE_MEMORY",
        ),
        (
            sample.descendant_processes > limits.max_descendant_processes,
            "DESCENDANT_PROCESS_COUNT",
        ),
        (sample.elapsed_s > limits.timeout_s, "TIMEOUT"),
    )
    return next((name for failed, name in checks if failed), None)


def run_guarded(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    limits: ResourceLimits,
    monitor_log: Path,
    summary_path: Path,
) -> int:
    """Run one command under hard process limits and a recorded memory monitor."""

    monitor_log.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    commit, commit_limit, available = _windows_memory_status()
    preflight_fraction = commit / commit_limit
    preflight_limit = (
        limits.max_system_commit_fraction
        if limits.preflight_max_system_commit_fraction is None
        else limits.preflight_max_system_commit_fraction
    )
    if (
        preflight_fraction > preflight_limit
        or available < limits.min_available_physical_bytes
    ):
        summary = {
            "status": "REFUSED_BEFORE_START",
            "reason": "SYSTEM_MEMORY_PREFLIGHT",
            "system_commit_bytes": commit,
            "system_commit_limit_bytes": commit_limit,
            "system_commit_fraction": preflight_fraction,
            "available_physical_bytes": available,
            "limits": asdict(limits),
        }
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        raise ResourceGuardError("system memory preflight failed; child was not started")

    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=dict(environment),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    job = None
    started = time.monotonic()
    peak_commit_fraction = preflight_fraction
    peak_tree_private = 0
    peak_descendants = 0
    violation = None
    try:
        try:
            job = _assign_windows_job(
                process,
                active_process_limit=1 + limits.max_descendant_processes,
                job_memory_limit_bytes=limits.max_tree_private_bytes,
            )
        except Exception:
            _terminate_tree(process.pid)
            raise
        with monitor_log.open("w", encoding="utf-8") as stream:
            while process.poll() is None:
                sample = _sample(process.pid, started)
                peak_commit_fraction = max(peak_commit_fraction, sample.system_commit_fraction)
                peak_tree_private = max(peak_tree_private, sample.tree_private_bytes)
                peak_descendants = max(peak_descendants, sample.descendant_processes)
                stream.write(json.dumps(asdict(sample), sort_keys=True) + "\n")
                stream.flush()
                violation = _violation(sample, limits, commit)
                if violation is not None:
                    _terminate_tree(process.pid)
                    break
                time.sleep(limits.poll_interval_s)
        returncode = process.poll()
        if returncode is None:
            _terminate_tree(process.pid)
            returncode = process.wait(timeout=5.0)
        summary = {
            "status": "RESOURCE_LIMIT_EXCEEDED" if violation else (
                "COMPLETED" if returncode == 0 else "CHILD_FAILED"
            ),
            "violation": violation,
            "returncode": returncode,
            "elapsed_s": time.monotonic() - started,
            "baseline_system_commit_bytes": commit,
            "peak_system_commit_fraction": peak_commit_fraction,
            "peak_tree_private_bytes": peak_tree_private,
            "peak_descendant_processes": peak_descendants,
            "limits": asdict(limits),
        }
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        if violation:
            raise ResourceGuardError(f"guard terminated run: {violation}")
        return int(returncode)
    finally:
        _close_windows_job(job)


def wait_for_memory_preflight(
    limits: ResourceLimits,
    *,
    log_path: Path,
    timeout_s: float | None = None,
    poll_interval_s: float = 5.0,
) -> None:
    """Wait without a simulation child until the registered start buffer exists."""
    limit = (
        limits.max_system_commit_fraction
        if limits.preflight_max_system_commit_fraction is None
        else limits.preflight_max_system_commit_fraction
    )
    timeout = limits.timeout_s if timeout_s is None else float(timeout_s)
    started = time.monotonic()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as stream:
        while True:
            commit, commit_limit, available = _windows_memory_status()
            elapsed = time.monotonic() - started
            record = {
                "elapsed_s": elapsed,
                "system_commit_bytes": commit,
                "system_commit_limit_bytes": commit_limit,
                "system_commit_fraction": commit / commit_limit,
                "available_physical_bytes": available,
                "preflight_limit": limit,
            }
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
            if record["system_commit_fraction"] <= limit and available >= limits.min_available_physical_bytes:
                return
            if elapsed >= timeout:
                raise ResourceGuardError("timed out waiting for system memory preflight")
            time.sleep(float(poll_interval_s))


__all__ = [
    "GIB", "ResourceGuardError", "ResourceLimits", "run_guarded",
    "wait_for_memory_preflight",
]
