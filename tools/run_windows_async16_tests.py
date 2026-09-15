#!/usr/bin/env python3
"""Run the repeatable native Windows polling/path evidence slice for ASYNC16."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import platform
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "src/test/unit/python/repomap_kg/coordinator/desired_state.unit.test.py",
    "src/test/unit/python/repomap_kg/coordinator/polling_operational.unit.test.py",
    "src/test/unit/python/repomap_kg/coordinator/service.unit.test.py",
    "src/test/unit/python/repomap_kg/ops/config.unit.test.py",
    "src/test/unit/python/repomap_kg/ops/source_generation.unit.test.py",
)


def main() -> int:
    if sys.platform == "win32":
        edition, version, _, architecture = platform.win32_ver()
        print(f"windows_edition={edition or 'unknown'}")
        print(f"windows_build={version or platform.version()}")
        print(f"python_version={platform.python_version()}")
        print(f"architecture={architecture or platform.machine()}")
        print(f"filesystem={_filesystem_name()}")
        print(f"runner_account={'administrator' if _is_admin() else 'current-user'}")
        print(f"interactive_session={bool(sys.stdin.isatty() or sys.stdout.isatty())}")
        print(f"psql_available={shutil.which('psql') is not None}")
        print("service_manager=not-mutated;polling-and-foreground-only")
        command = [sys.executable, "-m", "pytest", "--noconftest", "-q", *TESTS]
        completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
        return completed.returncode
    else:
        print("ASYNC16 native Windows tests require a Windows host", file=sys.stderr)
        return 2


def _is_admin() -> bool:
    if sys.platform == "win32":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False
    else:
        return False


def _filesystem_name() -> str:
    if sys.platform == "win32":
        root = Path.cwd().anchor
        if not root:
            return "unknown"
        volume_name = ctypes.create_unicode_buffer(261)
        filesystem_name = ctypes.create_unicode_buffer(261)
        serial = wintypes.DWORD()
        maximum_component = wintypes.DWORD()
        flags = wintypes.DWORD()
        try:
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
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
    else:
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
