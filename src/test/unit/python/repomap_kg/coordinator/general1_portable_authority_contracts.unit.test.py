"""Contracts for the audit hook installed by install_portable_authority_guard."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.coordinator import _portable_authority as pa

FILESYSTEM = "filesystem authority denied"
RUNTIME = "runtime authority denied"
IMPORT = "import authority denied"
HELPER = "repomap-go-extract"


class _BadFspath:
    def __fspath__(self) -> int:
        return 5


@pytest.fixture
def layout(tmp_path: Path) -> SimpleNamespace:
    root = tmp_path.resolve()
    paths = SimpleNamespace(
        root=root, store=root / "store", workspace=root / "workspace",
        code=root / "code", outside=root / "outside",
    )
    for directory in (
        paths.store / "objects", paths.store / "temporary",
        paths.workspace, paths.code, paths.outside,
    ):
        directory.mkdir(parents=True)
    with patch.object(pa.sys, "addaudithook") as register:
        pa.install_portable_authority_guard(
            store_root=paths.store, workspace_root=paths.workspace,
            code_roots=(paths.code,),
        )
    register.assert_called_once()
    paths.hook = register.call_args.args[0]
    return paths


def _allow(layout: SimpleNamespace, event: str, args: tuple[object, ...]) -> None:
    assert layout.hook(event, args) is None


def _deny(
    layout: SimpleNamespace, event: str, args: tuple[object, ...], kind: str = FILESYSTEM
) -> None:
    with pytest.raises(PermissionError, match=kind):
        layout.hook(event, args)


def test_open_access_is_bounded_to_store_workspace_and_code_roots(layout: SimpleNamespace) -> None:
    _allow(layout, "open", (str(layout.store / "index"), "rb"))
    _allow(layout, "open", (str(layout.workspace / "w.txt"), "r"))
    _allow(layout, "open", (str(layout.code / "module.py"), "r"))
    for writable in (
        layout.store / "objects" / "blob", layout.store / "temporary" / "tmp",
        layout.workspace / "out",
    ):
        _allow(layout, "open", (str(writable), "wb"))
    _deny(layout, "open", (str(layout.store / "index"), "wb"))
    _deny(layout, "open", (str(layout.code / "module.py"), "w"))
    _deny(layout, "open", (str(layout.outside / "f"), "r"))
    _deny(layout, "open", (str(layout.outside / "f"), None, os.O_RDWR))
    _deny(layout, "open", (str(layout.outside / "f"), None, os.O_CREAT | os.O_WRONLY))


def test_mkdir_is_limited_to_the_store_skeleton_and_write_roots(layout: SimpleNamespace) -> None:
    for exact in (
        layout.store, layout.store / "objects", layout.store / "temporary", layout.workspace,
    ):
        _allow(layout, "os.mkdir", (str(exact), 0o700, -1))
    _allow(layout, "os.mkdir", (str(layout.workspace / "attempt-1"), 0o700))
    _allow(layout, "os.mkdir", (str(layout.store / "objects" / "ab"), 0o700))
    _deny(layout, "os.mkdir", (str(layout.store / "other"), 0o700))
    _deny(layout, "os.mkdir", (str(layout.outside / "d"), 0o700))
    _deny(layout, "os.rmdir", (str(layout.store), -1))


@pytest.mark.parametrize(
    ("event", "extra"), (("os.remove", ()), ("os.rmdir", ()), ("os.chmod", (0o600,)))
)
def test_single_path_mutations_require_write_root_and_no_directory_descriptor(
    layout: SimpleNamespace, event: str, extra: tuple[object, ...]
) -> None:
    _allow(layout, event, (str(layout.workspace / "f"), *extra, -1))
    _allow(layout, event, (str(layout.store / "temporary" / "f"), *extra))
    _deny(layout, event, (str(layout.outside / "f"), *extra, -1))
    _deny(layout, event, (str(layout.store / "index"), *extra, -1))
    _deny(layout, event, (str(layout.workspace / "f"), *extra, 5))


@pytest.mark.parametrize("event", ("os.rename", "os.link"))
def test_two_path_mutations_require_both_ends_in_write_roots(
    layout: SimpleNamespace, event: str
) -> None:
    source = str(layout.workspace / "a")
    destination = str(layout.store / "temporary" / "b")
    _allow(layout, event, (source, destination, -1, -1))
    _deny(layout, event, (str(layout.outside / "victim"), destination, -1, -1))
    _deny(layout, event, (source, str(layout.store / "escaped"), -1, -1))
    _deny(layout, event, (source, destination, 7, -1))
    _deny(layout, event, (source, destination, -1, 7))
    _deny(layout, event, (source,))


def test_symlink_targets_resolve_against_the_destination_directory(layout: SimpleNamespace) -> None:
    link = str(layout.workspace / "link")
    _allow(layout, "os.symlink", ("target.txt", link))
    _allow(layout, "os.symlink", (str(layout.store / "objects" / "blob"), link))
    _deny(layout, "os.symlink", ("../escape", link))
    _deny(layout, "os.symlink", (str(layout.outside / "f"), link))
    _deny(layout, "os.symlink", (str(layout.workspace / "t"), str(layout.outside / "link")))
    _deny(layout, "os.symlink", ("target", link, 9))
    for malformed in (5, "", "bad\x00target"):
        _deny(layout, "os.symlink", (malformed, link))


def test_path_arguments_normalize_exact_forms_and_refuse_ambiguous_ones(
    layout: SimpleNamespace,
) -> None:
    target = layout.workspace / "f"
    _allow(layout, "open", (str(target), "r"))
    _allow(layout, "open", (os.fsencode(target), "r"))
    _allow(layout, "open", (target, "r"))
    _allow(layout, "open", (str(layout.workspace / "sub" / ".." / "f"), "r"))
    _deny(layout, "open", (str(layout.workspace / ".." / "outside" / "f"), "r"))
    for ambiguous in (3.5, None, "", "x\x00y", "\udc80", b"\xff", _BadFspath()):
        _deny(layout, "open", (ambiguous, "r"))


def test_symlink_and_non_directory_path_components_are_refused(layout: SimpleNamespace) -> None:
    real = layout.workspace / "real"
    real.mkdir()
    (real / "f").write_text("x", encoding="utf-8")
    (layout.workspace / "plain").write_text("x", encoding="utf-8")
    (layout.outside / "secret").write_text("s", encoding="utf-8")
    (layout.workspace / "alias").symlink_to(real, target_is_directory=True)
    (layout.workspace / "escape").symlink_to(layout.outside, target_is_directory=True)

    _allow(layout, "open", (str(real / "f"), "r"))
    _deny(layout, "open", (str(layout.workspace / "alias" / "f"), "r"))
    _deny(layout, "open", (str(layout.workspace / "alias"), "r"))
    _deny(layout, "open", (str(layout.workspace / "escape" / "secret"), "r"))
    _deny(layout, "open", (str(layout.workspace / "plain" / "child"), "r"))


def test_descriptor_arguments_are_attributed_to_their_backing_paths(layout: SimpleNamespace) -> None:
    owned_file = layout.workspace / "owned"
    foreign_file = layout.outside / "foreign"
    owned_file.write_text("x", encoding="utf-8")
    foreign_file.write_text("x", encoding="utf-8")
    descriptors = {
        "store": os.open(layout.store, os.O_RDONLY),
        "outside": os.open(layout.outside, os.O_RDONLY),
        "owned": os.open(owned_file, os.O_RDONLY),
        "foreign": os.open(foreign_file, os.O_RDONLY),
    }
    try:
        for event in ("os.listdir", "os.scandir"):
            _allow(layout, event, (descriptors["store"],))
            _allow(layout, event, (str(layout.store),))
            _deny(layout, event, (descriptors["outside"],))
            for refused in (-1, True, None):
                _deny(layout, event, (refused,))
        _allow(layout, "os.chmod", (descriptors["owned"], 0o600))
        _deny(layout, "os.chmod", (descriptors["foreign"], 0o600))
    finally:
        for descriptor in descriptors.values():
            os.close(descriptor)


@pytest.mark.parametrize(
    ("event", "args"),
    (
        ("socket.getaddrinfo", ("host", 80, 0, 0)),
        ("socket.bind", ()),
        ("os.execve", ("/bin/sh", ["sh"], {})),
        ("os.spawnv", (0, "sh", ["sh"])),
        ("os.posix_spawnp", ("sh", ["sh"], {})),
        ("os.fork", ()),
        ("subprocess.Popen", ("/bin/sh", ["sh"], None, None)),
    ),
)
def test_network_and_command_events_are_refused(
    layout: SimpleNamespace, event: str, args: tuple[object, ...]
) -> None:
    _deny(layout, event, args, RUNTIME)


def test_database_and_publisher_imports_are_refused_while_other_events_pass(
    layout: SimpleNamespace,
) -> None:
    for denied in (
        "psycopg2.extras", "sqlite3.dbapi2", "repomap_kg.storage.staged_publication",
        "repomap_kg.coordinator.startup_recovery", "repomap_kg.registry.service",
        "repomap_kg.coordinator._control_plane",
    ):
        _deny(layout, "import", (denied,), IMPORT)
    _allow(layout, "import", ("json",))
    _allow(layout, "import", ("repomap_kg.coordinator.portable_worker",))
    _allow(layout, "import", (None,))
    _allow(layout, "import", ())
    _allow(layout, "os.getcwd", ())


def test_go_helper_launch_is_limited_to_the_named_binary_under_code_or_env_override(
    layout: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("REPOMAP_GO_HELPER", raising=False)
    helper = layout.code / HELPER
    for event, args in (
        ("subprocess.Popen", (str(helper),)),
        ("subprocess.Popen", (None, [str(helper), "--root", "x"])),
        ("subprocess.Popen", (None, (os.fsencode(helper),))),
        ("subprocess.Popen", (helper, ["helper"])),
        ("os.posix_spawn", (str(layout.code / f"{HELPER}.exe"), [HELPER], {})),
    ):
        _allow(layout, event, args)
    foreign = layout.outside / HELPER
    refused_commands: tuple[tuple[object, ...], ...] = (
        (), (None,), (None, []), (None, ()), (None, "not-a-list"), (3,),
        (str(foreign),), (str(layout.code / "other-tool"),),
    )
    for refused in refused_commands:
        _deny(layout, "subprocess.Popen", refused, RUNTIME)

    monkeypatch.setenv("REPOMAP_GO_HELPER", str(foreign))
    _allow(layout, "subprocess.Popen", (str(foreign),))
    _deny(layout, "subprocess.Popen", (str(layout.outside / "sub" / HELPER),), RUNTIME)

    monkeypatch.setenv("REPOMAP_GO_HELPER", "")
    _deny(layout, "subprocess.Popen", (str(foreign),), RUNTIME)
