"""Platform probes and bounded diagnostics for the ASYNC15 tool facade."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import ctypes
from ctypes import wintypes
import re
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


def guid(value: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.c_void_p),
        ("Attributes", wintypes.DWORD),
    ]


class _TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", _SID_AND_ATTRIBUTES)]


def _windows_dll(name: str) -> ctypes.CDLL:
    loader = getattr(ctypes, "WinDLL", None)
    if not callable(loader):
        raise RuntimeError("native_windows_required")
    return loader(name, use_last_error=True)


def _last_error() -> int:
    getter = getattr(ctypes, "get_last_error", None)
    return int(getter()) if callable(getter) else 0


def current_user_sid(*, platform_name: str) -> str:
    """Return the current Windows token SID without localized command output."""

    if platform_name == "win32":
        advapi = _windows_dll("advapi32")
        kernel = _windows_dll("kernel32")
        advapi.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        advapi.OpenProcessToken.restype = wintypes.BOOL
        advapi.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            wintypes.INT,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi.GetTokenInformation.restype = wintypes.BOOL
        advapi.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.LPWSTR),
        ]
        advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel.LocalFree.restype = wintypes.HLOCAL
        token = wintypes.HANDLE()
        if not advapi.OpenProcessToken(
            kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)
        ):
            raise OSError(_last_error(), "OpenProcessToken failed")
        try:
            size = wintypes.DWORD()
            advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            buffer = ctypes.create_string_buffer(size.value)
            if not advapi.GetTokenInformation(
                token, 1, buffer, size, ctypes.byref(size)
            ):
                raise OSError(_last_error(), "GetTokenInformation failed")
            sid = ctypes.cast(buffer, ctypes.POINTER(_TOKEN_USER)).contents.User.Sid
            sid_text = wintypes.LPWSTR()
            if not advapi.ConvertSidToStringSidW(
                sid, ctypes.byref(sid_text)
            ):
                raise OSError(_last_error(), "ConvertSidToStringSid failed")
            try:
                value = sid_text.value
                if not isinstance(value, str):
                    raise OSError("ConvertSidToStringSid returned no SID")
                return value
            finally:
                kernel.LocalFree(sid_text)
        finally:
            kernel.CloseHandle(token)
    raise RuntimeError("native_windows_required")


def task_scheduler_com_probe(
    *,
    platform_name: str,
    scheduler_clsid: str,
    service_iid: str,
) -> dict[str, object]:
    """Check Task Scheduler 2.0 COM without changing scheduler state."""

    if platform_name != "win32":
        return {
            "available": False,
            "hresult": None,
            "error": "native_windows_required",
        }
    ole32 = _windows_dll("ole32")
    winfunctype = getattr(ctypes, "WINFUNCTYPE", None)
    if not callable(winfunctype):
        return {
            "available": False,
            "hresult": None,
            "error": "native_windows_required",
        }
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long
    initialization = ole32.CoInitializeEx(None, 0x2)
    changed_mode = ctypes.c_ulong(initialization).value == 0x80010106
    initialized_here = initialization in (0, 1)
    if initialization not in (0, 1) and not changed_mode:
        return {
            "available": False,
            "hresult": f"0x{ctypes.c_ulong(initialization).value:08x}",
            "error": "com_initialize_failed",
        }
    instance = ctypes.c_void_p()
    try:
        hresult = ole32.CoCreateInstance(
            ctypes.byref(guid(scheduler_clsid)),
            None,
            0x1,
            ctypes.byref(guid(service_iid)),
            ctypes.byref(instance),
        )
        if instance.value:
            vtable = ctypes.cast(
                instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
            ).contents
            release = winfunctype(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
            release(instance)
        return {
            "available": hresult >= 0 and bool(instance.value),
            "hresult": f"0x{ctypes.c_ulong(hresult).value:08x}",
            "error": None if hresult >= 0 else "com_create_failed",
        }
    finally:
        if initialized_here:
            ole32.CoUninitialize()


def run_command(
    argv: tuple[str, ...],
    *,
    repo_root: Path,
    environ: Mapping[str, str],
    runner: Callable[..., subprocess.CompletedProcess[bytes]],
    timeout: int = 30,
) -> subprocess.CompletedProcess[bytes]:
    return runner(
        argv,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=False,
        timeout=timeout,
        shell=False,
        env={
            "SystemRoot": environ.get("SystemRoot", ""),
            "PATH": environ.get("PATH", ""),
        },
    )


def manager_output(result: subprocess.CompletedProcess[object] | None) -> str:
    if result is None:
        return ""
    values: list[str] = []
    for value in (result.stdout, result.stderr):
        if isinstance(value, bytes):
            values.append(value.decode("utf-8", errors="replace"))
        elif isinstance(value, str):
            values.append(value)
    return "\n".join(values)


def manager_category(
    result: subprocess.CompletedProcess[object] | None,
    *,
    output: Callable[[subprocess.CompletedProcess[object] | None], str] = manager_output,
) -> str | None:
    if result is None or result.returncode == 0:
        return None
    text = output(result).casefold()
    categories = (
        ("access is denied", "access_denied"),
        ("logon failure", "logon_failure"),
        ("password", "credential_required"),
        ("missing a required", "invalid_task_xml"),
        ("invalid", "invalid_task_definition"),
        ("already exists", "task_collision"),
    )
    for marker, category in categories:
        if marker in text:
            return category
    return "manager_command_failed"


def manager_diagnostic(
    result: subprocess.CompletedProcess[object] | None,
    *,
    output: Callable[[subprocess.CompletedProcess[object] | None], str] = manager_output,
) -> str | None:
    if result is None or result.returncode == 0:
        return None
    text = " ".join(output(result).split())
    text = re.sub(r"[A-Za-z]:\\[^ ]*", "<private-path>", text)
    text = re.sub(r"\\RepoMap\\ASYNC15-Probe-[0-9a-f-]+", "<test-task>", text)
    return text[:240]


def cleanup_temp_directory(
    path: Path,
    *,
    remove_tree: Callable[[Path], None] = shutil.rmtree,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    for _attempt in range(20):
        try:
            remove_tree(path)
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            sleep(0.25)
    return False


def native_probe(
    logon_type: str,
    *,
    platform_name: str,
    current_sid: Callable[[], str],
    build_xml: Callable[..., bytes],
    parse_xml: Callable[[bytes], dict[str, object]],
    xml_shape: Callable[[bytes], dict[str, object] | None],
    run: Callable[[tuple[str, ...]], subprocess.CompletedProcess[bytes]],
    category: Callable[..., str | None],
    diagnostic: Callable[..., str | None],
    cleanup: Callable[[Path], bool],
    executable: str,
    make_temp_directory: Callable[..., str] = tempfile.mkdtemp,
    which: Callable[[str], str | None] = shutil.which,
    token_hex: Callable[[int], str] = secrets.token_hex,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Probe registration/query/run/cleanup without touching a production task."""

    if platform_name != "win32":
        raise RuntimeError("native Windows startup probe requires Windows")
    schtasks = which("schtasks.exe")
    sc = which("sc.exe")
    if schtasks is None or sc is None:
        return {
            "schtasks_available": bool(schtasks),
            "sc_available": bool(sc),
            "sc_query_exit": None,
            "logon_type": logon_type,
        }
    task_name = rf"\RepoMap\ASYNC15-Probe-{token_hex(6)}"
    temporary = Path(make_temp_directory(prefix="repomap-async15-"))
    result: dict[str, object] = {}
    try:
        marker = temporary / "started.marker"
        xml_path = temporary / "task.xml"
        user_id = current_sid()
        arguments = ("-c", f"open({str(marker)!r}, 'w').close()")
        xml = build_xml(
            task_name=task_name,
            user_id=user_id,
            command=executable,
            arguments=arguments,
            working_directory=str(temporary),
            stdout_path=str(temporary / "stdout.log"),
            stderr_path=str(temporary / "stderr.log"),
            logon_type=logon_type,
        )
        xml_path.write_bytes(xml)
        create = run(
            (schtasks, "/Create", "/TN", task_name, "/XML", str(xml_path), "/F")
        )
        query = run_task = end = delete = delete_repeat = None
        absent = None
        error_category = None
        try:
            if create.returncode == 0:
                query = run((schtasks, "/Query", "/TN", task_name, "/XML"))
                run_task = run((schtasks, "/Run", "/TN", task_name))
                sleep(2)
                end = run((schtasks, "/End", "/TN", task_name))
        except (OSError, subprocess.SubprocessError) as error:
            error_category = type(error).__name__
        finally:
            if create.returncode == 0:
                try:
                    delete = run((schtasks, "/Delete", "/TN", task_name, "/F"))
                    delete_repeat = run(
                        (schtasks, "/Delete", "/TN", task_name, "/F")
                    )
                except (OSError, subprocess.SubprocessError) as error:
                    error_category = type(error).__name__
            try:
                absent = run((schtasks, "/Query", "/TN", task_name, "/XML"))
            except (OSError, subprocess.SubprocessError) as error:
                error_category = type(error).__name__
        sc_query = run((sc, "query"))
        try:
            semantics = (
                None
                if query is None or query.returncode
                else parse_xml(query.stdout)
            )
        except ValueError:
            semantics = None
            error_category = error_category or "task_xml_invalid"
        query_shape = None if query is None else xml_shape(query.stdout)
        result = {
            "schtasks_available": True,
            "sc_available": True,
            "sc_query_exit": sc_query.returncode,
            "logon_type": logon_type,
            "task_create_exit": create.returncode,
            "task_create_category": category(create),
            "task_create_diagnostic": diagnostic(create),
            "task_query_exit": None if query is None else query.returncode,
            "task_query_category": category(query),
            "task_query_diagnostic": diagnostic(query),
            "task_query_bytes": None if query is None else len(query.stdout),
            "task_query_shape": query_shape,
            "task_run_exit": None if run_task is None else run_task.returncode,
            "task_run_category": category(run_task),
            "task_end_exit": None if end is None else end.returncode,
            "task_end_category": category(end),
            "task_delete_exit": None if delete is None else delete.returncode,
            "task_delete_category": category(delete),
            "task_delete_repeat_exit": None
            if delete_repeat is None
            else delete_repeat.returncode,
            "task_delete_repeat_category": category(delete_repeat),
            "task_absent_exit": None if absent is None else absent.returncode,
            "task_absent_category": category(absent),
            "marker_created": marker.exists(),
            "probe_error": error_category,
            "task_xml_valid": semantics is not None,
            "task_xml_current_user": semantics is not None
            and semantics["user_id"] == user_id,
            "task_xml_least_privilege": semantics is not None
            and semantics["run_level"] in (None, "LeastPrivilege"),
            "task_xml_exact_argv": semantics is not None
            and semantics["command"] == executable
            and semantics["arguments"] == arguments,
        }
    finally:
        result["temporary_cleanup"] = cleanup(temporary)
    return result
