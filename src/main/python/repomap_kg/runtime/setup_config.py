"""Runtime setup's configuration-family and exclusive target authority."""
from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import NoReturn
import unicodedata

from repomap_kg.ops.config_layout import discover_home_config_files
from repomap_kg.ops.config_loading import _read_ops_config_home_payload
from repomap_kg.ops.config_records import OpsConfigError
from repomap_kg.ops.config_storage import refuse_sqlite_home
from repomap_kg.runtime._home_authority import create_private_file, ensure_private_directory
from repomap_kg.runtime._plan_records import LocalRuntimeDiagnostic, LocalRuntimeError


def _refuse(code: str, message: str) -> NoReturn:
    raise LocalRuntimeError((LocalRuntimeDiagnostic(
        "error", code, "config-home", f"{code}: {message}",
    ),))


def _config_refusal(error: OpsConfigError) -> NoReturn:
    codes = [d.code for d in error.diagnostics if d.severity == "error"]
    _refuse(codes[0] if codes else "runtime-config-invalid", "configuration preflight refused")


def _validate_target(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or (
        hasattr(os, "getuid") and info.st_uid != os.getuid()
    ) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        _refuse("runtime-config-target-unsafe", "generated target must be an owned ordinary file")
    return True


def prepare_setup_config(
    home: Path, *, config_format: str | None = None, dry_run: bool = False,
) -> Path:
    """Select without changing configuration; actual setup validates home custody first."""
    if config_format not in (None, "legacy", "cloe"):
        _refuse("runtime-config-format-invalid", "choose legacy or cloe")
    if not dry_run:
        try:
            ensure_private_directory(home)
        except (OSError, ValueError):
            _refuse("repo-map-home-unsafe", "Local home must be an owned ordinary private directory")
    try:
        try:
            info = home.lstat()
        except FileNotFoundError:
            entries: list[Path] = []
        else:
            if not stat.S_ISDIR(info.st_mode):
                _refuse("repo-map-home-unsafe", "home must be an ordinary directory")
            entries = list(home.iterdir())
        files, _ignored = discover_home_config_files(home) if entries else ([], [])
        family = ("cloe" if files[0].name.endswith(".cloe.toml") else "legacy") if files else None
        if family is not None and config_format is not None and family != config_format:
            _refuse("runtime-config-format-conflict", "requested format conflicts with the existing home")
        selected = config_format or family or "legacy"
        target = home / ("repomap.local.cloe.toml" if selected == "cloe" else "repomap.rpl.toml")
        portable = unicodedata.normalize("NFC", target.name).casefold()
        if any(p.name != target.name and unicodedata.normalize("NFC", p.name).casefold() == portable for p in entries):
            _refuse("runtime-config-target-collision", "generated target has an occupied portable alias")
        _validate_target(target)
        if files:
            try:
                _home, payload, _names, diagnostics = _read_ops_config_home_payload(home)
            except OpsConfigError as error:
                # Preserve legacy bootstrap tolerance; the new CLOE producer fails closed.
                if selected == "cloe" or any(d.code == "config-home-mixed-format" for d in error.diagnostics):
                    _config_refusal(error)
            else:
                refuse_sqlite_home(payload.get("storage"), diagnostics)
                if selected == "cloe" and any(d.severity == "error" for d in diagnostics):
                    _config_refusal(OpsConfigError(diagnostics))
        return target
    except OpsConfigError as error:
        _config_refusal(error)
    except (OSError, UnicodeError):
        _refuse("runtime-config-unavailable", "configuration preflight could not inspect the selected home")


def create_setup_config(path: Path, template: str) -> bool:
    """Retain existing targets, or create once without following/replacing a target."""
    try:
        if _validate_target(path):
            return False
        create_private_file(path, template)
    except (OSError, ValueError):
        _refuse("runtime-config-target-unsafe", "generated configuration could not be created exclusively")
    return True
