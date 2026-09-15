from pathlib import PureWindowsPath

import pytest

from repomap_kg.coordinator.windows_security import (
    WindowsPathError,
    normalize_windows_path,
    validate_supported_windows_path,
)


@pytest.mark.parametrize(
    "value",
    [
        r"C:\Users\runner\repo-map",
        r"D:\work\repo-map\python.exe",
    ],
)
def test_supported_windows_paths_preserve_drive_and_casefold_key(value):
    normalized = validate_supported_windows_path(PureWindowsPath(value))

    assert normalized.drive
    assert normalize_windows_path(normalized) == str(normalized).casefold()


@pytest.mark.parametrize(
    "value",
    [
        r"relative\repo-map",
        r"\\server\share\repo-map",
        r"\\?\C:\repo-map",
        r"\\.\pipe\coordinator",
        r"C:\repo-map\config:secret",
        r"C:\repo-map\CON",
        r"C:\repo-map\NUL.txt",
    ],
)
def test_unsupported_windows_path_forms_are_rejected(value):
    with pytest.raises(WindowsPathError, match="path"):
        validate_supported_windows_path(PureWindowsPath(value))
