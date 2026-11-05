"""Prepared profile: offline copy, exact listing, owner-only entries, refusal codes (spec 3, Q07)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from common_lore_index.extractors.rust_pilot import prepared_profile
from common_lore_index.extractors.rust_pilot.prepared_profile import (
    PROFILE_NAME,
    ProfileUnavailable,
    load_profile,
    prepare_profile,
)
from repomap_test_support.rust_pilot_fake_tree_sitter.wheels import SyntheticWheel, synthetic_wheel

PAIRS = {cpu: (synthetic_wheel("tree_sitter", {"tree_sitter/__init__.py": cpu.encode()}, cpu=cpu),
               synthetic_wheel("tree_sitter_rust", {"tree_sitter_rust/__init__.py": b"x"}, cpu=cpu))
         for cpu in ("aarch64", "x86_64")}


@pytest.fixture(autouse=True)
def synthetic_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    def pair(cpu: str) -> tuple[object, object]:
        if cpu not in PAIRS:
            raise KeyError(cpu)
        return PAIRS[cpu][0].lock, PAIRS[cpu][1].lock

    monkeypatch.setattr(prepared_profile, "wheels_for_cpu", pair)


def _source(tmp_path: Path, wheels: tuple[SyntheticWheel, ...]) -> Path:
    source = tmp_path / "custody"
    source.mkdir(mode=0o700)
    for wheel in wheels:
        (source / wheel.lock.filename).write_bytes(wheel.data)
    return source


def _prepared(tmp_path: Path, cpu: str = "aarch64") -> Path:
    profile = tmp_path / "profile"
    prepare_profile(_source(tmp_path, PAIRS[cpu]), profile, cpu)
    return profile


def _code(profile: Path, **kwargs: str) -> str:
    with pytest.raises(ProfileUnavailable) as raised:
        load_profile(profile, **kwargs)
    return raised.value.code


def test_prepare_then_load_round_trips_verified_bytes(tmp_path: Path) -> None:
    profile = _prepared(tmp_path)
    assert sorted(os.listdir(profile)) == sorted([PROFILE_NAME, *(w.lock.filename for w in PAIRS["aarch64"])])
    assert all((os.stat(profile / name).st_mode & 0o777) == 0o600 for name in os.listdir(profile))
    loaded = load_profile(profile, server_cpu="aarch64")
    assert loaded.cpu == "aarch64" and [w.data for w in loaded.wheels] == [w.data for w in PAIRS["aarch64"]]
    assert (profile / PROFILE_NAME).read_bytes() == loaded.profile_bytes


def test_prepare_never_overwrites_and_requires_private_custody(tmp_path: Path) -> None:
    profile = _prepared(tmp_path)
    with pytest.raises(ProfileUnavailable, match="profile_exists"):
        prepare_profile(tmp_path / "custody", profile, "aarch64")
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    with pytest.raises(ProfileUnavailable, match="unsafe_directory"):
        prepare_profile(shared, tmp_path / "p2", "aarch64")
    with pytest.raises(ProfileUnavailable, match="unknown_cpu"):
        prepare_profile(tmp_path / "custody", tmp_path / "p3", "riscv64")


def test_missing_profile_is_one_unavailable_code(tmp_path: Path) -> None:
    assert _code(tmp_path / "absent") == "profile_missing"


def test_listing_modes_links_and_symlinks_are_refused(tmp_path: Path) -> None:
    profile = _prepared(tmp_path)
    (profile / "extra.whl").write_bytes(b"x")
    assert _code(profile) == "profile_listing"
    (profile / "extra.whl").unlink()
    wheel = profile / PAIRS["aarch64"][0].lock.filename
    wheel.chmod(0o644)
    assert _code(profile) == "profile_entry_unsafe"
    wheel.chmod(0o600)
    os.link(wheel, tmp_path / "second-link")
    assert _code(profile) == "profile_entry_unsafe"
    (tmp_path / "second-link").unlink()
    (tmp_path / "alias").symlink_to(profile, target_is_directory=True)
    assert _code(tmp_path / "alias") == "symlink_refused"


def test_tampered_bytes_json_and_platform_are_refused(tmp_path: Path) -> None:
    profile = _prepared(tmp_path)
    assert _code(profile, server_cpu="x86_64") == "wrong_platform"
    document = profile / PROFILE_NAME
    original = document.read_bytes()
    document.write_bytes(original.replace(b'"aarch64"', b'"x86_64"', 1))
    assert _code(profile) == "profile_json_mismatch"
    document.write_bytes(original)
    wheel = profile / PAIRS["aarch64"][0].lock.filename
    data = bytearray(wheel.read_bytes())
    data[-1] ^= 0xFF
    wheel.write_bytes(bytes(data))
    assert _code(profile) == "artifact_digest_mismatch"
