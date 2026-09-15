"""Native Windows Job Object and process boundary implementation."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import subprocess
from typing import cast

from repomap_kg.coordinator._process_contracts import ProcessBoundaryError, WorkerProcess


def _kernel32():  # pragma: no cover - native Windows runner
    if (win_dll := getattr(ctypes, "WinDLL", None)) is None:
        raise OSError("windows_runtime_environment_unavailable")
    api = win_dll("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    api.CreateJobObjectW.restype = wintypes.HANDLE
    api.SetInformationJobObject.argtypes = [wintypes.HANDLE, wintypes.INT, wintypes.LPVOID, wintypes.DWORD]
    api.SetInformationJobObject.restype = wintypes.BOOL
    api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    api.AssignProcessToJobObject.restype = wintypes.BOOL
    api.ResumeThread.argtypes = [wintypes.HANDLE]
    api.ResumeThread.restype = wintypes.DWORD
    api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    api.TerminateJobObject.restype = wintypes.BOOL
    api.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, wintypes.INT, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
    ]
    api.QueryInformationJobObject.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    api.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
    api.Thread32First.restype = wintypes.BOOL
    api.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
    api.Thread32Next.restype = wintypes.BOOL
    api.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenThread.restype = wintypes.HANDLE
    return api


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [("value", ctypes.c_ulonglong)] * 6


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


class WindowsJobObject:  # pragma: no cover - native Windows runner
    """Native Job Object with kill-on-close and no breakaway allowance."""

    kind = "windows_job_object"

    def __init__(self) -> None:
        if os.name != "nt":
            raise ProcessBoundaryError("Windows Job Objects are unavailable")
        api = _kernel32()
        handle = api.CreateJobObjectW(None, None)
        if not handle:
            raise ProcessBoundaryError("job object creation failed")
        self._api = api
        self._handle = handle
        self._process: WorkerProcess | None = None
        self._closed = False
        limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = 0x00002000
        if not api.SetInformationJobObject(
            handle,
            9,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            api.CloseHandle(handle)
            raise ProcessBoundaryError("job object policy failed")

    def assign(self, process: object) -> None:
        handle = _popen_handle(process, "_handle")
        if not self._api.AssignProcessToJobObject(self._handle, handle):
            raise ProcessBoundaryError("job object assignment failed")
        self._process = cast(WorkerProcess, process)

    def resume(self, process: object) -> None:
        try:
            thread = _popen_handle(process, "_thread_handle")
            close_thread = False
        except ProcessBoundaryError:
            thread = _open_suspended_primary_thread(int(cast(WorkerProcess, process).pid))
            close_thread = True
        try:
            if self._api.ResumeThread(thread) == 0xFFFFFFFF:
                raise ProcessBoundaryError("suspended worker resume failed")
        finally:
            if close_thread:
                self._api.CloseHandle(thread)

    def terminate_tree(self) -> None:
        if not self._closed and not self._api.TerminateJobObject(self._handle, 1):
            raise ProcessBoundaryError("job object termination failed")

    def terminate_gracefully(self) -> None:
        return

    def kill_tree(self) -> None:
        self.terminate_tree()

    def tree_exists(self) -> bool:
        if self._closed:
            return False
        info = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        if self._api.QueryInformationJobObject(
            self._handle,
            1,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            return info.ActiveProcesses > 0
        process = self._process
        return process is not None and process.poll() is None

    def close(self) -> None:
        if not self._closed:
            self._api.CloseHandle(self._handle)
            self._closed = True


def _popen_handle(process: object, name: str):  # pragma: no cover - native Windows runner
    try:
        value = getattr(process, name)
        return wintypes.HANDLE(int(value))
    except (AttributeError, TypeError, ValueError):
        raise ProcessBoundaryError("required Windows process handle is unavailable") from None


def _open_suspended_primary_thread(pid: int):  # pragma: no cover - native Windows runner
    api = _kernel32()
    snapshot = api.CreateToolhelp32Snapshot(0x00000004, 0)
    invalid = ctypes.c_void_p(-1).value
    if not snapshot or snapshot == invalid:
        raise ProcessBoundaryError("suspended worker thread lookup failed")
    entry = _THREADENTRY32()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        found = api.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32OwnerProcessID == pid:
                thread = api.OpenThread(0x0002, False, entry.th32ThreadID)
                if thread:
                    return thread
                raise ProcessBoundaryError("suspended worker thread open failed")
            found = api.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        api.CloseHandle(snapshot)
    raise ProcessBoundaryError("suspended worker thread not found")


def _dispose_failed_process(process: object) -> None:
    try:
        cast(WorkerProcess, process).kill()
        cast(WorkerProcess, process).wait(timeout=5)
    except (AttributeError, OSError, subprocess.TimeoutExpired):
        return


