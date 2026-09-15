"""Small platform boundary for Windows paths, ACLs, and reparse points."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path, PureWindowsPath
import stat


class WindowsPathError(ValueError):
    """A Windows path is outside the initial supported contract."""


class WindowsSecurityError(RuntimeError):
    """A native Windows security operation failed."""


_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4",
     "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3",
     "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}
)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def validate_supported_windows_path(value: str | os.PathLike[str]) -> PureWindowsPath:
    """Validate the conservative initial Windows path subset."""

    raw = os.fspath(value)
    if "\x00" in raw:
        raise WindowsPathError("path contains a NUL")
    path = PureWindowsPath(raw)
    text = str(path)
    if not path.is_absolute():
        raise WindowsPathError("path must be absolute")
    if text.startswith(("\\\\", "\\\\?\\", "\\\\.\\")):
        raise WindowsPathError("path form is unsupported")
    if ":" in text[2:]:
        raise WindowsPathError("path alternate data streams are unsupported")
    for part in path.parts[1:]:
        name = part.rstrip(" .").split(".", 1)[0].upper()
        if name in _RESERVED_NAMES:
            raise WindowsPathError("path reserved device name is unsupported")
    return path


def normalize_windows_path(value: str | os.PathLike[str]) -> str:
    """Return a deterministic case-insensitive comparison key."""

    return str(validate_supported_windows_path(value)).casefold()


def is_reparse_point(path: Path) -> bool:
    """Inspect a path without following its final component."""

    try:
        details = path.lstat()
    except OSError:
        return False
    return path.is_symlink() or bool(
        getattr(details, "st_file_attributes", 0) & _REPARSE_POINT
    )


def reject_reparse_path(path: Path) -> None:
    """Reject a final or existing parent reparse point."""

    if os.name != "nt":
        if is_reparse_point(Path(path)):
            raise WindowsSecurityError("reparse point is not allowed")
        return
    current = Path(path)
    while True:  # pragma: no cover - native Windows runner
        if (current.exists() or current.is_symlink()) and is_reparse_point(current):
            raise WindowsSecurityError("reparse point is not allowed")
        parent = current.parent
        if parent == current:
            return
        current = parent


def apply_owner_private_acl(path: Path) -> None:  # pragma: no cover - native Windows runner
    """Set a protected ACL containing only the current user on Windows."""

    if os.name != "nt":
        try:
            path.chmod(0o600 if path.is_file() else 0o700)
        except OSError as error:
            raise WindowsSecurityError("private permission update failed") from error
        return
    sid, token, _sid_buffer = _current_user_sid()
    api = _security_api()
    acl = ctypes.c_void_p()
    trustee = _TRUSTEE_W(
        None,
        0,
        0,
        1,
        sid,
    )
    entry = _EXPLICIT_ACCESS_W(
        0x10000000,
        2,
        0,
        trustee,
    )
    try:
        if api.SetEntriesInAclW(1, ctypes.byref(entry), None, ctypes.byref(acl)):
            raise WindowsSecurityError("private ACL construction failed")
        flags = 0x00000004 | 0x80000000
        result = api.SetNamedSecurityInfoW(
            str(path), 1, flags, None, None, acl, None
        )
        if result:
            raise WindowsSecurityError("private ACL update failed")
    finally:
        if acl:
            api.LocalFree(acl)
        api.CloseHandle(token)


def validate_owner_private_acl(path: Path) -> None:  # pragma: no cover - native Windows runner
    """Require a protected ACL with exactly one allow entry for the user."""

    if os.name != "nt":
        return
    sid, token, _sid_buffer = _current_user_sid()
    api = _security_api()
    security_descriptor = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    present = wintypes.BOOL()
    defaulted = wintypes.BOOL()
    try:
        result = api.GetNamedSecurityInfoW(
            str(path), 1, 0x00000004, None, None,
            ctypes.byref(dacl), None, ctypes.byref(security_descriptor)
        )
        if result:
            raise WindowsSecurityError("private ACL inspection failed")
        if not api.GetSecurityDescriptorDacl(
            security_descriptor, ctypes.byref(present), ctypes.byref(dacl),
            ctypes.byref(defaulted)
        ) or not present.value or not dacl:
            raise WindowsSecurityError("private ACL is not owner-only")
        acl_information = _ACL_SIZE_INFORMATION()
        if not api.GetAclInformation(
            dacl, ctypes.byref(acl_information), ctypes.sizeof(acl_information), 2
        ):
            raise WindowsSecurityError("private ACL inspection failed")
        if acl_information.AceCount != 1:
            raise WindowsSecurityError("private ACL is not owner-only")
        ace = ctypes.c_void_p()
        if not api.GetAce(dacl, 0, ctypes.byref(ace)):
            raise WindowsSecurityError("private ACL inspection failed")
        header = ctypes.cast(ace, ctypes.POINTER(_ACE_HEADER)).contents
        if header.AceType != 0:
            raise WindowsSecurityError("private ACL is not owner-only")
        allowed = ctypes.cast(ace, ctypes.POINTER(_ACCESS_ALLOWED_ACE)).contents
        sid_address = ctypes.addressof(allowed) + _ACCESS_ALLOWED_ACE.SidStart.offset
        if not api.EqualSid(
            ctypes.c_void_p(sid_address), sid
        ):
            raise WindowsSecurityError("private ACL is not owner-only")
    finally:
        if security_descriptor:
            api.LocalFree(security_descriptor)
        api.CloseHandle(token)


def _security_api():  # pragma: no cover - native Windows runner
    if os.name != "nt":
        raise WindowsSecurityError("Windows security APIs are unavailable")
    win_dll = getattr(ctypes, "WinDLL", None)
    if win_dll is None:
        raise WindowsSecurityError("Windows security APIs are unavailable")
    advapi = win_dll("advapi32", use_last_error=True)
    kernel = win_dll("kernel32", use_last_error=True)
    advapi.SetEntriesInAclW.argtypes = [
        wintypes.DWORD, ctypes.POINTER(_EXPLICIT_ACCESS_W), ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p)
    ]
    advapi.SetEntriesInAclW.restype = wintypes.DWORD
    advapi.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ]
    advapi.SetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL),
    ]
    advapi.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi.GetAclInformation.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.INT,
    ]
    advapi.GetAclInformation.restype = wintypes.BOOL
    advapi.GetAce.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi.GetAce.restype = wintypes.BOOL
    advapi.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi.EqualSid.restype = wintypes.BOOL
    advapi.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [
        wintypes.HANDLE, wintypes.INT, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    advapi.LocalFree = kernel.LocalFree
    advapi.CloseHandle = kernel.CloseHandle
    return advapi


def _current_user_sid():  # pragma: no cover - native Windows runner
    api = _security_api()
    token = wintypes.HANDLE()
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        raise WindowsSecurityError("Windows security APIs are unavailable")
    current_process = windll.kernel32.GetCurrentProcess
    current_process.restype = wintypes.HANDLE
    if not api.OpenProcessToken(
        current_process(), 0x0008, ctypes.byref(token)
    ):
        raise WindowsSecurityError("current user ACL lookup failed")
    size = wintypes.DWORD()
    api.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    if not api.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
        api.CloseHandle(token)
        raise WindowsSecurityError("current user ACL lookup failed")
    user = ctypes.cast(buffer, ctypes.POINTER(_TOKEN_USER)).contents
    return ctypes.c_void_p(user.User.Sid), token, buffer


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", _SID_AND_ATTRIBUTES)]


class _TRUSTEE_W(ctypes.Structure):
    _fields_ = [
        ("pMultipleTrustee", ctypes.c_void_p),
        ("MultipleTrusteeOperation", wintypes.DWORD),
        ("TrusteeForm", wintypes.DWORD),
        ("TrusteeType", wintypes.DWORD),
        ("ptstrName", ctypes.c_void_p),
    ]


class _EXPLICIT_ACCESS_W(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", wintypes.DWORD),
        ("grfAccessMode", wintypes.DWORD),
        ("grfInheritance", wintypes.DWORD),
        ("Trustee", _TRUSTEE_W),
    ]


class _ACE_HEADER(ctypes.Structure):
    _fields_ = [
        ("AceType", wintypes.BYTE),
        ("AceFlags", wintypes.BYTE),
        ("AceSize", wintypes.WORD),
    ]


class _ACCESS_ALLOWED_ACE(ctypes.Structure):
    _fields_ = [
        ("Header", _ACE_HEADER),
        ("Mask", wintypes.DWORD),
        ("SidStart", wintypes.DWORD),
    ]


class _ACL_SIZE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    ]


__all__ = [
    "WindowsPathError",
    "WindowsSecurityError",
    "apply_owner_private_acl",
    "is_reparse_point",
    "normalize_windows_path",
    "reject_reparse_path",
    "validate_owner_private_acl",
    "validate_supported_windows_path",
]
