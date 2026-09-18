"""Runtime capability guard for the database-independent portable worker."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import sysconfig
from typing import Iterable

try:
    import fcntl
except ImportError:  # pragma: no cover - native Windows
    fcntl = None  # type: ignore[assignment]

_DENIED_IMPORT_PREFIXES = (
    "psycopg",
    "psycopg2",
    "sqlite3",
    "repomap_kg.coordinator._control_",
    "repomap_kg.storage.staged_ingestion",
    "repomap_kg.storage.staging_copy",
    "repomap_kg.storage.staged_publication",
    "repomap_kg.coordinator.local_lifecycle",
    "repomap_kg.coordinator.startup_recovery",
    "repomap_kg.registry",
)
_DENIED_EVENTS = (
    "socket.",
    "os.exec",
    "os.posix_spawn",
    "os.spawn",
    "os.system",
    "os.fork",
    "os.forkpty",
)
_ENUMERATION_EVENTS = {"os.listdir", "os.scandir"}
_SINGLE_PATH_MUTATIONS: dict[str, tuple[int, int | None]] = {
    "os.mkdir": (0, 2),
    "os.remove": (0, 1),
    "os.rmdir": (0, 1),
    "os.chmod": (0, 2),
}
_TWO_PATH_MUTATIONS: dict[str, tuple[int, int, int | None, int | None]] = {
    "os.rename": (0, 1, 2, 3),
    "os.link": (0, 1, 2, 3),
}


def install_portable_authority_guard(
    *,
    store_root: Path,
    workspace_root: Path,
    code_roots: Iterable[Path],
) -> None:
    """Deny database, network, command, and unattributed filesystem authority."""

    runtime_paths = sysconfig.get_paths()
    trusted_runtime_roots = tuple(
        Path(value)
        for key, value in runtime_paths.items()
        if key in {"stdlib", "platstdlib", "purelib", "platlib"} and value
    )
    read_roots = tuple(
        dict.fromkeys(
            path.resolve()
            for path in (
                store_root,
                workspace_root,
                *code_roots,
                *trusted_runtime_roots,
            )
        )
    )
    resolved_code_roots = tuple(dict.fromkeys(path.resolve() for path in code_roots))
    store_root = store_root.resolve()
    write_roots = (
        store_root / "objects",
        store_root / "temporary",
        workspace_root.resolve(),
    )
    exact_mkdir_roots = (store_root, *write_roots)

    def guard(event: str, args: tuple[object, ...]) -> None:
        _validate_audit_event(
            event, args, read_roots, write_roots, exact_mkdir_roots, resolved_code_roots
        )

    sys.addaudithook(guard)


def _is_approved_go_helper(
    args: tuple[object, ...], code_roots: tuple[Path, ...]
) -> bool:
    if not args:
        return False
    raw_exe = args[0]
    if raw_exe is None and len(args) > 1:
        argv = args[1]
        raw_exe = argv[0] if isinstance(argv, (list, tuple)) and argv else None
    if not isinstance(raw_exe, (str, bytes, os.PathLike)):
        return False
    try:
        candidate = Path(os.fsdecode(raw_exe)).resolve()
    except (TypeError, ValueError):
        return False
    if candidate.name not in {"repomap-go-extract", "repomap-go-extract.exe"}:
        return False
    if any(candidate == root or candidate.is_relative_to(root) for root in code_roots):
        return True
    helper_env = os.environ.get("REPOMAP_GO_HELPER")
    if helper_env:
        try:
            return candidate == Path(helper_env).resolve()
        except (TypeError, ValueError):
            pass
    return False


def _validate_audit_event(
    event: str,
    args: tuple[object, ...],
    read_roots: tuple[Path, ...],
    write_roots: tuple[Path, ...],
    exact_mkdir_roots: tuple[Path, ...] = (),
    code_roots: tuple[Path, ...] = (),
) -> None:
    if event == "import" and args and isinstance(args[0], str):
        if args[0].startswith(_DENIED_IMPORT_PREFIXES):
            raise PermissionError("portable worker import authority denied")
    if (
        event in {"os.posix_spawn", "os.posix_spawnp", "subprocess.Popen"}
        and _is_approved_go_helper(args, code_roots)
    ):
        return
    if event.startswith(_DENIED_EVENTS):
        raise PermissionError("portable worker runtime authority denied")
    if event.startswith("subprocess."):
        raise PermissionError("portable worker runtime authority denied")
    if event == "open":
        _validate_open(args, read_roots, write_roots)
        return
    if event in _ENUMERATION_EVENTS:
        if len(args) != 1:
            raise PermissionError("portable worker filesystem authority denied")
        path = (
            _descriptor_path(args[0])
            if isinstance(args[0], int) and not isinstance(args[0], bool)
            else _normalized_path(args[0], None)
        )
        _require_allowed(path, read_roots)
        return
    single = _SINGLE_PATH_MUTATIONS.get(event)
    if single is not None:
        path_index, dir_fd_index = single
        raw_path = _argument(args, path_index)
        dir_fd = _optional_dir_fd(args, dir_fd_index)
        if dir_fd not in {None, -1}:
            raise PermissionError("portable worker filesystem authority denied")
        path = (
            _descriptor_path(raw_path)
            if isinstance(raw_path, int) and not isinstance(raw_path, bool)
            else _normalized_path(raw_path, None)
        )
        if event == "os.mkdir" and path in exact_mkdir_roots:
            return
        _require_allowed(path, write_roots)
        return
    two = _TWO_PATH_MUTATIONS.get(event)
    if two is not None:
        source_index, destination_index, source_fd_index, destination_fd_index = two
        _require_allowed(
            _normalized_path(
                _argument(args, source_index),
                _optional_dir_fd(args, source_fd_index),
            ),
            write_roots,
        )
        _require_allowed(
            _normalized_path(
                _argument(args, destination_index),
                _optional_dir_fd(args, destination_fd_index),
            ),
            write_roots,
        )
        return
    if event == "os.symlink":
        if len(args) < 2:
            raise PermissionError("portable worker filesystem authority denied")
        destination = _normalized_path(
            args[1], _optional_dir_fd(args, 2)
        )
        source = _normalized_symlink_target(args[0], destination.parent)
        _require_allowed(source, write_roots)
        _require_allowed(destination, write_roots)


def _validate_open(
    args: tuple[object, ...],
    read_roots: tuple[Path, ...],
    write_roots: tuple[Path, ...],
) -> None:
    if not args:
        raise PermissionError("portable worker filesystem authority denied")
    target = args[0]
    if isinstance(target, int) and not isinstance(target, bool):
        if target < 0:
            raise PermissionError("portable worker filesystem authority denied")
        try:
            st = os.fstat(target)
        except OSError:
            raise PermissionError("portable worker filesystem authority denied") from None
        if stat.S_ISFIFO(st.st_mode):
            try:
                path = _descriptor_path(target)
            except PermissionError:
                return
        else:
            path = _descriptor_path(target)
    else:
        path = _normalized_path(target, None)
    mode = args[1] if len(args) > 1 else "r"
    flags = args[2] if len(args) > 2 else 0
    writing = (
        isinstance(mode, str) and any(marker in mode for marker in ("w", "a", "+", "x"))
    ) or (
        isinstance(flags, int)
        and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
    )
    allowed = write_roots if writing else read_roots
    _require_allowed(path, allowed)


def _argument(args: tuple[object, ...], index: int) -> object:
    if index >= len(args):
        raise PermissionError("portable worker filesystem authority denied")
    return args[index]


def _optional_dir_fd(args: tuple[object, ...], index: int | None) -> object | None:
    if index is None or index >= len(args):
        return None
    return args[index]


def _normalized_path(raw: object, dir_fd: object | None) -> Path:
    if dir_fd not in {None, -1}:
        raise PermissionError("portable worker filesystem authority denied")
    if not isinstance(raw, (str, bytes, os.PathLike)):
        raise PermissionError("portable worker filesystem authority denied")
    try:
        decoded = os.fsdecode(raw)
    except (TypeError, UnicodeError):
        raise PermissionError("portable worker filesystem authority denied") from None
    if not decoded or "\x00" in decoded or any("\udc80" <= char <= "\udcff" for char in decoded):
        raise PermissionError("portable worker filesystem authority denied")
    path = Path(os.path.abspath(decoded))
    _reject_symlink_components(path)
    return path


def _descriptor_path(raw: object) -> Path:
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise PermissionError("portable worker filesystem authority denied")
    if fcntl is not None and hasattr(fcntl, "F_GETPATH"):
        try:
            encoded = fcntl.fcntl(raw, fcntl.F_GETPATH, b"\0" * 1024)
            decoded = os.fsdecode(encoded.split(b"\0", 1)[0])
            if decoded:
                return Path(decoded)
        except (OSError, TypeError, UnicodeError, ValueError):
            pass
    for prefix in ("/proc/self/fd", "/dev/fd"):
        candidate = Path(prefix) / str(raw)
        try:
            resolved = Path(os.path.realpath(candidate))
        except OSError:
            continue
        if resolved != candidate and resolved.is_absolute():
            return resolved
    raise PermissionError("portable worker filesystem authority denied")


def _normalized_symlink_target(raw: object, destination_parent: Path) -> Path:
    if not isinstance(raw, (str, bytes, os.PathLike)):
        raise PermissionError("portable worker filesystem authority denied")
    try:
        decoded = os.fsdecode(raw)
    except (TypeError, UnicodeError):
        raise PermissionError("portable worker filesystem authority denied") from None
    if not decoded or "\x00" in decoded or any("\udc80" <= char <= "\udcff" for char in decoded):
        raise PermissionError("portable worker filesystem authority denied")
    candidate = Path(decoded)
    path = Path(os.path.abspath(candidate if candidate.is_absolute() else destination_parent / candidate))
    _reject_symlink_components(path)
    return path


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            if current.is_symlink():
                raise PermissionError("portable worker filesystem authority denied")
            current.lstat()
        except FileNotFoundError:
            break
        except OSError:
            raise PermissionError("portable worker filesystem authority denied") from None


def _require_allowed(path: Path, roots: tuple[Path, ...]) -> None:
    if not any(path == root or path.is_relative_to(root) for root in roots):
        raise PermissionError("portable worker filesystem authority denied")


__all__ = ["install_portable_authority_guard"]
