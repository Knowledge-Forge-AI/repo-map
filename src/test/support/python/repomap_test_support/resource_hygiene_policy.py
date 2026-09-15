"""ADR 0048 profile quotas and closed nonsecret hygiene configuration."""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping

from repomap_test_support.resource_validation import nonnegative_int


GIB = 1024**3
ENV_PREFIX = "REPOMAP_TEST_HYGIENE_"
MAX_HARD_BYTES = 256 * GIB
MAX_HARD_INODES = 8_000_000
MIN_FREE_DISK_BYTES = 10 * GIB
CONFIG_KEYS = {
    "PROFILE",
    "SOFT_WATERMARK_BYTES",
    "SOFT_WATERMARK_INODES",
    "HARD_WATERMARK_BYTES",
    "HARD_WATERMARK_INODES",
    "MIN_FREE_DISK_BYTES",
    "MIN_FREE_DISK_PERCENT",
    "PROFILE_FREE_DISK_RESERVE_BYTES",
}


class HygieneConfigError(RuntimeError):
    """Hygiene configuration is malformed or exceeds architectural bounds."""


class QuotaExceeded(RuntimeError):
    """The exact current-run quota reached its fail-closed boundary."""


class HygieneProfile(str, Enum):
    ORDINARY = "ordinary"
    INTEGRATION = "integration"
    BUILD = "build"
    EXHAUSTIVE = "exhaustive"
    HEAVY = "heavy"
    QUALIFICATION = "qualification"

    @property
    def quota(self) -> tuple[int, int]:
        # EXHAUSTIVE's 4 GiB byte quota is an operator-selected runaway ceiling
        # (ADR 0053), not measured demand. Its inode quota reuses HEAVY's
        # source-backed 750_000 so this correction changes only one dimension.
        return {
            self.ORDINARY: (2 * GIB, 50_000),
            self.INTEGRATION: (8 * GIB, 200_000),
            self.BUILD: (16 * GIB, 300_000),
            self.EXHAUSTIVE: (4 * GIB, 750_000),
            self.HEAVY: (32 * GIB, 750_000),
            self.QUALIFICATION: (64 * GIB, 1_500_000),
        }[self]


@dataclass(frozen=True)
class HygieneConfig:
    requested_profile: HygieneProfile | None = None
    soft_watermark_bytes: int = 40 * GIB
    soft_watermark_inodes: int = 1_500_000
    hard_watermark_bytes: int = 80 * GIB
    hard_watermark_inodes: int = 3_000_000
    min_free_disk_bytes: int = 20 * GIB
    min_free_disk_percent: int = 5
    profile_free_disk_reserve_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.requested_profile is not None and not isinstance(
            self.requested_profile, HygieneProfile
        ):
            raise HygieneConfigError("requested profile is invalid")
        for name, value in (
            ("soft_watermark_bytes", self.soft_watermark_bytes),
            ("soft_watermark_inodes", self.soft_watermark_inodes),
            ("hard_watermark_bytes", self.hard_watermark_bytes),
            ("hard_watermark_inodes", self.hard_watermark_inodes),
            ("min_free_disk_bytes", self.min_free_disk_bytes),
            ("min_free_disk_percent", self.min_free_disk_percent),
        ):
            try:
                nonnegative_int(value, name)
            except ValueError as error:
                raise HygieneConfigError(str(error)) from error
        if self.profile_free_disk_reserve_bytes is not None:
            try:
                nonnegative_int(
                    self.profile_free_disk_reserve_bytes,
                    "profile_free_disk_reserve_bytes",
                )
            except ValueError as error:
                raise HygieneConfigError(str(error)) from error
            if self.profile_free_disk_reserve_bytes < MIN_FREE_DISK_BYTES:
                raise HygieneConfigError(
                    "profile free disk reserve violates architectural floor"
                )
        if self.hard_watermark_bytes > MAX_HARD_BYTES:
            raise HygieneConfigError("hard byte watermark exceeds architectural clamp")
        if self.hard_watermark_inodes > MAX_HARD_INODES:
            raise HygieneConfigError("hard inode watermark exceeds architectural clamp")
        if self.soft_watermark_bytes > self.hard_watermark_bytes:
            raise HygieneConfigError("soft byte watermark exceeds hard watermark")
        if self.soft_watermark_inodes > self.hard_watermark_inodes:
            raise HygieneConfigError("soft inode watermark exceeds hard watermark")
        if self.min_free_disk_bytes < MIN_FREE_DISK_BYTES:
            raise HygieneConfigError("free disk reserve violates architectural floor")
        if self.min_free_disk_percent > 100:
            raise HygieneConfigError("free disk percent is invalid")

    @property
    def digest(self) -> str:
        payload = json.dumps(
            {
                "soft_watermark_bytes": self.soft_watermark_bytes,
                "soft_watermark_inodes": self.soft_watermark_inodes,
                "hard_watermark_bytes": self.hard_watermark_bytes,
                "hard_watermark_inodes": self.hard_watermark_inodes,
                "min_free_disk_bytes": self.min_free_disk_bytes,
                "min_free_disk_percent": self.min_free_disk_percent,
                "profile_free_disk_reserve_bytes": self.profile_free_disk_reserve_bytes,
                "requested_profile": (
                    self.requested_profile.value if self.requested_profile else None
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class QuotaEvent:
    category: str
    label: str
    percent: int
    allocated_bytes: int
    inode_count: int


class QuotaTracker:
    def __init__(
        self,
        profile: HygieneProfile,
        record: Callable[[QuotaEvent], None],
        *,
        quota: tuple[int, int] | None = None,
    ) -> None:
        self.profile = HygieneProfile(profile)
        self._record = record
        self._warning_active = False
        self._quota = self.profile.quota if quota is None else (
            nonnegative_int(quota[0], "byte quota"),
            nonnegative_int(quota[1], "inode quota"),
        )
        if 0 in self._quota:
            raise HygieneConfigError("quota values must be positive")

    def checkpoint(self, label: str, *, allocated_bytes: int, inode_count: int) -> None:
        try:
            allocated_bytes = nonnegative_int(allocated_bytes, "allocated_bytes")
            inode_count = nonnegative_int(inode_count, "inode_count")
        except ValueError as error:
            raise HygieneConfigError(str(error)) from error
        byte_quota, inode_quota = self._quota
        percent = max(
            allocated_bytes * 100 // byte_quota,
            inode_count * 100 // inode_quota,
        )
        if percent >= 100:
            self._record(QuotaEvent("quota_exceeded", label, percent, allocated_bytes, inode_count))
            raise QuotaExceeded("quota_exceeded")
        warning = percent >= 80
        if warning and not self._warning_active:
            self._record(QuotaEvent("quota_warning", label, percent, allocated_bytes, inode_count))
        self._warning_active = warning


def load_hygiene_config(
    *,
    cli_overrides: Mapping[str, object],
    environ: Mapping[str, str],
    local_path: Path,
) -> HygieneConfig:
    defaults = {
        "SOFT_WATERMARK_BYTES": 40 * GIB,
        "SOFT_WATERMARK_INODES": 1_500_000,
        "HARD_WATERMARK_BYTES": 80 * GIB,
        "HARD_WATERMARK_INODES": 3_000_000,
        "MIN_FREE_DISK_BYTES": 20 * GIB,
        "MIN_FREE_DISK_PERCENT": 5,
    }
    file_values = _read_local_config(Path(local_path))
    env_values: dict[str, object] = {}
    for key, value in environ.items():
        if not key.startswith(ENV_PREFIX):
            continue
        short = key.removeprefix(ENV_PREFIX)
        if short not in CONFIG_KEYS:
            raise HygieneConfigError("unknown hygiene environment key")
        env_values[short] = _parse_environment_value(value, short)
    _validate_keys(cli_overrides)
    cli_values = _validate_layer_values(dict(cli_overrides), "command line")
    merged = defaults | file_values | env_values | cli_values
    profile_value = merged.pop("PROFILE", None)
    raw_reserve = merged.pop("PROFILE_FREE_DISK_RESERVE_BYTES", None)
    values = {key: nonnegative_int(value, key) for key, value in merged.items()}
    reserve_value: int | None = None
    if raw_reserve is not None:
        reserve_value = nonnegative_int(raw_reserve, "PROFILE_FREE_DISK_RESERVE_BYTES")
        if reserve_value < MIN_FREE_DISK_BYTES:
            raise HygieneConfigError(
                "profile free disk reserve violates architectural floor"
            )
    try:
        requested_profile = (
            None if profile_value is None else HygieneProfile(profile_value)
        )
    except (TypeError, ValueError) as error:
        raise HygieneConfigError("requested profile is invalid") from error
    if values["HARD_WATERMARK_BYTES"] > MAX_HARD_BYTES:
        raise HygieneConfigError("hard byte watermark exceeds architectural clamp")
    if values["HARD_WATERMARK_INODES"] > MAX_HARD_INODES:
        raise HygieneConfigError("hard inode watermark exceeds architectural clamp")
    if values["MIN_FREE_DISK_BYTES"] < MIN_FREE_DISK_BYTES:
        raise HygieneConfigError("free disk reserve violates architectural floor")
    if values["MIN_FREE_DISK_PERCENT"] > 100:
        raise HygieneConfigError("free disk percent is invalid")
    return HygieneConfig(
        requested_profile=requested_profile,
        soft_watermark_bytes=values["SOFT_WATERMARK_BYTES"],
        soft_watermark_inodes=values["SOFT_WATERMARK_INODES"],
        hard_watermark_bytes=values["HARD_WATERMARK_BYTES"],
        hard_watermark_inodes=values["HARD_WATERMARK_INODES"],
        min_free_disk_bytes=values["MIN_FREE_DISK_BYTES"],
        min_free_disk_percent=values["MIN_FREE_DISK_PERCENT"],
        profile_free_disk_reserve_bytes=reserve_value,
    )


def _read_local_config(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise HygieneConfigError("local hygiene configuration is unsafe")
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise HygieneConfigError("local hygiene configuration is invalid") from error
    if set(payload) != {"hygiene"} or type(payload["hygiene"]) is not dict:
        raise HygieneConfigError("local hygiene configuration schema is invalid")
    values = payload["hygiene"]
    _validate_keys(values)
    return _validate_layer_values(dict(values), "local configuration")


def _validate_keys(values: Mapping[str, object]) -> None:
    for key in values:
        if type(key) is not str or key not in CONFIG_KEYS:
            if type(key) is str and any(
                token in key.upper() for token in ("PASSWORD", "TOKEN", "SECRET", "KEY")
            ):
                raise HygieneConfigError("credential-shaped hygiene key is prohibited")
            raise HygieneConfigError("unknown hygiene configuration key")


def _validate_layer_values(values: dict[str, object], layer: str) -> dict[str, object]:
    validated: dict[str, object] = {}
    for key, value in values.items():
        if key == "PROFILE":
            if type(value) is not str:
                raise HygieneConfigError(f"{layer} profile must be a string")
            validated[key] = value
            continue
        try:
            validated[key] = nonnegative_int(value, key)
        except ValueError as error:
            raise HygieneConfigError(str(error)) from error
    return validated


def _parse_environment_value(value: str, name: str) -> object:
    if name == "PROFILE":
        return value
    if not value.isascii() or not value.isdecimal():
        raise HygieneConfigError(f"{name} must be an exact nonnegative integer")
    return int(value)


__all__ = [
    "GIB",
    "HygieneConfig",
    "HygieneConfigError",
    "HygieneProfile",
    "QuotaEvent",
    "QuotaExceeded",
    "QuotaTracker",
    "load_hygiene_config",
]
