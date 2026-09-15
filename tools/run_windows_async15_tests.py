#!/usr/bin/env python3
"""Run ASYNC15 native Windows startup-authority evidence."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

import windows_async15_reporting as _reporting


REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"
TASK_NS = f"{{{TASK_NAMESPACE}}}"
TASK_IDENTITY = r"\RepoMap\Coordinator"
TASK_AUTHOR = "RepoMap ASYNC15"
TASK_TRIGGER_DELAY = "PT30S"
TASK_RESTART_INTERVAL = "PT1M"
TASK_RESTART_COUNT = "3"
TASK_EXECUTION_LIMIT = "PT1H"
TASK_LOGON_TYPES = frozenset({"InteractiveToken", "S4U"})
TASK_SCHEDULER_CLSID = "0f87369f-a4e5-4cfc-bd3e-73e6154572dd"
TASK_SERVICE_IID = "2faba4c7-4da9-4013-9697-20cc3fd40f85"


_GUID = _reporting._GUID
_guid = _reporting.guid
_SID_AND_ATTRIBUTES = _reporting._SID_AND_ATTRIBUTES
_TOKEN_USER = _reporting._TOKEN_USER


def build_task_xml(
    *,
    task_name: str,
    user_id: str,
    command: str,
    arguments: tuple[str, ...],
    working_directory: str,
    stdout_path: str,
    stderr_path: str,
    logon_type: str,
) -> bytes:
    """Render the bounded, credential-free XML used by the native probe."""

    _validate_task_inputs(
        task_name=task_name,
        user_id=user_id,
        command=command,
        arguments=arguments,
        working_directory=working_directory,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        logon_type=logon_type,
    )
    ET.register_namespace("", TASK_NAMESPACE)
    root = ET.Element(f"{TASK_NS}Task", {"version": "1.3"})
    registration = ET.SubElement(root, f"{TASK_NS}RegistrationInfo")
    ET.SubElement(registration, f"{TASK_NS}Author").text = TASK_AUTHOR
    ET.SubElement(registration, f"{TASK_NS}URI").text = task_name
    triggers = ET.SubElement(root, f"{TASK_NS}Triggers")
    trigger = ET.SubElement(triggers, f"{TASK_NS}LogonTrigger")
    ET.SubElement(trigger, f"{TASK_NS}Enabled").text = "true"
    ET.SubElement(trigger, f"{TASK_NS}Delay").text = TASK_TRIGGER_DELAY
    principals = ET.SubElement(root, f"{TASK_NS}Principals")
    principal = ET.SubElement(principals, f"{TASK_NS}Principal", {"id": "Author"})
    ET.SubElement(principal, f"{TASK_NS}UserId").text = user_id
    ET.SubElement(principal, f"{TASK_NS}LogonType").text = logon_type
    ET.SubElement(principal, f"{TASK_NS}RunLevel").text = "LeastPrivilege"
    settings = ET.SubElement(root, f"{TASK_NS}Settings")
    settings_values = (
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("DisallowStartIfOnBatteries", "true"),
        ("StopIfGoingOnBatteries", "false"),
        ("AllowHardTerminate", "true"),
        ("StartWhenAvailable", "true"),
        ("ExecutionTimeLimit", TASK_EXECUTION_LIMIT),
        ("AllowStartOnDemand", "true"),
        ("Enabled", "true"),
        ("Hidden", "false"),
    )
    for name, value in settings_values:
        ET.SubElement(settings, f"{TASK_NS}{name}").text = value
    restart = ET.SubElement(settings, f"{TASK_NS}RestartOnFailure")
    ET.SubElement(restart, f"{TASK_NS}Interval").text = TASK_RESTART_INTERVAL
    ET.SubElement(restart, f"{TASK_NS}Count").text = TASK_RESTART_COUNT
    actions = ET.SubElement(root, f"{TASK_NS}Actions", {"Context": "Author"})
    action = ET.SubElement(actions, f"{TASK_NS}Exec")
    ET.SubElement(action, f"{TASK_NS}Command").text = command
    ET.SubElement(action, f"{TASK_NS}Arguments").text = subprocess.list2cmdline(
        arguments
    )
    ET.SubElement(action, f"{TASK_NS}WorkingDirectory").text = working_directory
    return ET.tostring(root, encoding="utf-16", xml_declaration=True)


def parse_task_xml(content: bytes) -> dict[str, object]:
    """Extract only the structured fields used by the authority probe."""

    if not isinstance(content, bytes) or len(content) > 64 * 1024:
        raise ValueError("task_definition_invalid")
    try:
        root = _parse_task_root(content)
        if root.tag != f"{TASK_NS}Task":
            raise ValueError
        registration = root.find(f"{TASK_NS}RegistrationInfo")
        principal = root.find(f"{TASK_NS}Principals/{TASK_NS}Principal")
        action = root.find(f"{TASK_NS}Actions/{TASK_NS}Exec")
        if registration is None or principal is None or action is None:
            raise ValueError
        task_identity = _required_text(registration, "URI")
        user_id = _required_text(principal, "UserId")
        logon_type = _required_text(principal, "LogonType")
        run_level = _optional_text(principal, "RunLevel")
        command = _required_text(action, "Command")
        argument_text = _required_text(action, "Arguments")
        working_directory = _required_text(action, "WorkingDirectory")
        arguments = tuple(_strip_quotes(value) for value in shlex.split(argument_text, posix=False))
    except (ET.ParseError, TypeError, ValueError, UnicodeError):
        raise ValueError("task_definition_invalid") from None
    return {
        "task_identity": task_identity,
        "user_id": user_id,
        "logon_type": logon_type,
        "run_level": run_level,
        "command": command,
        "arguments": arguments,
        "working_directory": working_directory,
    }


def _parse_task_root(content: bytes) -> ET.Element:
    """Parse scheduler output across its documented and observed encodings."""

    candidates: list[bytes | str] = [content]
    for encoding in ("utf-8", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            candidates.append(content.decode(encoding))
        except UnicodeDecodeError:
            continue
    for candidate in candidates:
        try:
            return ET.fromstring(candidate)
        except (ET.ParseError, TypeError, UnicodeError):
            continue
    raise ValueError("task_definition_invalid")


def _task_xml_shape(content: bytes) -> dict[str, object] | None:
    """Return a public-safe XML shape for bounded native diagnostics."""

    try:
        root = _parse_task_root(content)
    except ValueError:
        return None
    return {
        "root": root.tag,
        "children": tuple(child.tag for child in root),
        "fields": {
            "uri": root.find(f"{TASK_NS}RegistrationInfo/{TASK_NS}URI") is not None,
            "user_id": root.find(
                f"{TASK_NS}Principals/{TASK_NS}Principal/{TASK_NS}UserId"
            )
            is not None,
            "logon_type": root.find(
                f"{TASK_NS}Principals/{TASK_NS}Principal/{TASK_NS}LogonType"
            )
            is not None,
            "run_level": root.find(
                f"{TASK_NS}Principals/{TASK_NS}Principal/{TASK_NS}RunLevel"
            )
            is not None,
            "command": root.find(
                f"{TASK_NS}Actions/{TASK_NS}Exec/{TASK_NS}Command"
            )
            is not None,
            "arguments": root.find(
                f"{TASK_NS}Actions/{TASK_NS}Exec/{TASK_NS}Arguments"
            )
            is not None,
            "working_directory": root.find(
                f"{TASK_NS}Actions/{TASK_NS}Exec/{TASK_NS}WorkingDirectory"
            )
            is not None,
        },
    }


def _validate_task_inputs(**values: object) -> None:
    task_name = values["task_name"]
    user_id = values["user_id"]
    command = values["command"]
    arguments = values["arguments"]
    working_directory = values["working_directory"]
    stdout_path = values["stdout_path"]
    stderr_path = values["stderr_path"]
    logon_type = values["logon_type"]
    if (
        not isinstance(task_name, str)
        or not task_name.startswith("\\RepoMap\\")
        or ".." in task_name
        or "\x00" in task_name
        or "\n" in task_name
        or not isinstance(user_id, str)
        or not user_id
        or "\x00" in user_id
        or not isinstance(command, str)
        or not _is_absolute_windows_path(command)
        or not isinstance(arguments, tuple)
        or not all(isinstance(value, str) and "\x00" not in value for value in arguments)
        or not isinstance(working_directory, str)
        or not _is_absolute_windows_path(working_directory)
        or not isinstance(stdout_path, str)
        or not _is_absolute_windows_path(stdout_path)
        or not isinstance(stderr_path, str)
        or not _is_absolute_windows_path(stderr_path)
        or logon_type not in TASK_LOGON_TYPES
    ):
        raise ValueError("task_definition_invalid")


def _required_text(parent: ET.Element, name: str) -> str:
    value = parent.findtext(f"{TASK_NS}{name}")
    if not isinstance(value, str) or not value:
        raise ValueError("task_definition_invalid")
    return value


def _optional_text(parent: ET.Element, name: str) -> str | None:
    value = parent.findtext(f"{TASK_NS}{name}")
    if value is not None and not value:
        raise ValueError("task_definition_invalid")
    return value


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def _is_absolute_windows_path(value: str) -> bool:
    path = PureWindowsPath(value)
    return path.is_absolute() and not value.startswith(("\\\\", "\\\\?\\", "\\\\.\\"))


def current_user_sid() -> str:
    """Return the current Windows token SID without localized command output."""

    return _reporting.current_user_sid(platform_name=sys.platform)


def _task_scheduler_com_probe() -> dict[str, object]:
    """Check the Task Scheduler 2.0 COM class without changing scheduler state."""

    return _reporting.task_scheduler_com_probe(
        platform_name=sys.platform,
        scheduler_clsid=TASK_SCHEDULER_CLSID,
        service_iid=TASK_SERVICE_IID,
    )


def _run(argv: tuple[str, ...], *, timeout: int = 30) -> subprocess.CompletedProcess[bytes]:
    return _reporting.run_command(
        argv,
        repo_root=REPO_ROOT,
        environ=os.environ,
        runner=subprocess.run,
        timeout=timeout,
    )


def _manager_output(result: subprocess.CompletedProcess[object] | None) -> str:
    return _reporting.manager_output(result)


def _manager_category(result: subprocess.CompletedProcess[object] | None) -> str | None:
    return _reporting.manager_category(result, output=_manager_output)


def _manager_diagnostic(result: subprocess.CompletedProcess[object] | None) -> str | None:
    """Return one bounded, path-redacted manager diagnostic for evidence."""

    return _reporting.manager_diagnostic(result, output=_manager_output)


def _cleanup_temp_directory(path: Path) -> bool:
    return _reporting.cleanup_temp_directory(
        path,
        remove_tree=shutil.rmtree,
        sleep=time.sleep,
    )


def _native_probe(logon_type: str = "InteractiveToken") -> dict[str, object]:
    """Probe registration/query/run/cleanup without touching a production task."""

    return _reporting.native_probe(
        logon_type,
        platform_name=sys.platform,
        current_sid=current_user_sid,
        build_xml=build_task_xml,
        parse_xml=parse_task_xml,
        xml_shape=_task_xml_shape,
        run=_run,
        category=_manager_category,
        diagnostic=_manager_diagnostic,
        cleanup=_cleanup_temp_directory,
        executable=str(Path(sys.executable).resolve()),
        make_temp_directory=tempfile.mkdtemp,
        which=shutil.which,
        token_hex=secrets.token_hex,
        sleep=time.sleep,
    )


def main() -> int:
    if sys.platform == "win32":
        edition, version, _, architecture = platform.win32_ver()
        facts = {
            "windows_edition": edition or "unknown",
            "windows_build": version or platform.version(),
            "python_version": platform.python_version(),
            "architecture": architecture or platform.machine(),
            "filesystem": _filesystem_name(),
            "runner_account": "administrator" if _is_admin() else "current-user",
            "interactive_session": bool(sys.stdin.isatty() or sys.stdout.isatty()),
            "service_manager_mutated": False,
            "task_scheduler_com": _task_scheduler_com_probe(),
        }
        print(
            json.dumps(
                {
                    "facts": facts,
                    "probe": _native_probe("InteractiveToken"),
                    "s4u_probe": _native_probe("S4U"),
                },
                sort_keys=True,
            )
        )
        return 0
    else:
        print(
            "ASYNC15 native Windows startup tests require a Windows host",
            file=sys.stderr,
        )
        return 2


def _is_admin() -> bool:
    try:
        windll = getattr(ctypes, "windll")
        return bool(windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _filesystem_name() -> str:
    root = Path.cwd().anchor
    if not root:
        return "unknown"
    windll = getattr(ctypes, "windll", None)
    kernel32 = getattr(windll, "kernel32", None)
    if kernel32 is None:
        return "unknown"
    volume_name = ctypes.create_unicode_buffer(261)
    filesystem_name = ctypes.create_unicode_buffer(261)
    serial = wintypes.DWORD()
    maximum_component = wintypes.DWORD()
    flags = wintypes.DWORD()
    try:
        ok = kernel32.GetVolumeInformationW(
            root,
            volume_name,
            len(volume_name),
            ctypes.byref(serial),
            ctypes.byref(maximum_component),
            ctypes.byref(flags),
            filesystem_name,
            len(filesystem_name),
        )
    except (AttributeError, OSError):
        return "unknown"
    return filesystem_name.value if ok and filesystem_name.value else "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
