"""Containerized integration tests for the ADR 0089 D4 Python payload contract."""

from __future__ import annotations

import cmath
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
from types import ModuleType
from typing import Any

import pytest

from repomap_kg.runtime import python_payload as payload
from repomap_kg.runtime import release_manifest as historical
from repomap_test_support.python_payload_probes import make_stdlib_import_probe_runner
from runner_coverage_execution import launch_unified_coverage_process

DYN = payload.DYNLOAD
LICENSE = "/usr/local/lib/python3.12/LICENSE.txt"
LICENSE_LINK = "/usr/local/lib/python3.12/LICENSE-link.txt"
_SDK_EXT_MODULES: tuple[tuple[str, ModuleType], ...] = (
    ("math", math),
    ("cmath", cmath),
)


def _select_sdk_extensions(count: int = 2) -> list[tuple[str, Path]]:
    dest_shared = Path(sysconfig.get_config_var("DESTSHARED") or "").resolve()
    selected: list[tuple[str, Path]] = []
    for name, mod in _SDK_EXT_MODULES:
        raw_file = getattr(mod, "__file__", None)
        if not isinstance(raw_file, str) or not raw_file:
            continue
        so_path = Path(raw_file).resolve()
        if so_path.is_file() and so_path.parent == dest_shared and so_path.name.startswith(f"{name}."):
            selected.append((name, so_path))
            if len(selected) == count:
                break
    assert len(selected) == count, f"Expected {count} SDK extensions in {dest_shared}"
    return selected


def _copy_ldd_closure(mount: Path, binaries: list[Path]) -> None:
    queue = list(binaries)
    seen_real: set[Path] = set()
    while queue:
        cur = queue.pop()
        ldd_out = subprocess.run(["ldd", str(cur)], capture_output=True, text=True, check=True).stdout
        for dep_path in payload.LDD_TARGET.findall(ldd_out):
            src_dep = Path(dep_path)
            if not src_dep.is_file():
                continue
            real_dep = Path(os.path.realpath(src_dep))
            dst_real = mount / real_dep.as_posix().lstrip("/")
            if real_dep not in seen_real:
                seen_real.add(real_dep)
                dst_real.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(real_dep, dst_real)
                if real_dep.as_posix().startswith(payload.ROOT + "/"):
                    queue.append(real_dep)
            dst_dep = mount / dep_path.lstrip("/")
            if dst_dep != dst_real and not dst_dep.exists() and not dst_dep.is_symlink():
                dst_dep.parent.mkdir(parents=True, exist_ok=True)
                dst_dep.symlink_to(dst_real)


def _stage_sdk_mount(mount: Path) -> tuple[list[tuple[str, Path]], tuple[str, ...]]:
    selected = _select_sdk_extensions(2)
    dyn_dir = mount / DYN.lstrip("/")
    dyn_dir.mkdir(parents=True, exist_ok=True)
    for _mod_name, src_so in selected:
        dst_so = dyn_dir / src_so.name
        shutil.copy2(src_so, dst_so)
        assert dst_so.read_bytes() == src_so.read_bytes()
    lic_path = mount / LICENSE.lstrip("/")
    lic_path.parent.mkdir(parents=True, exist_ok=True)
    lic_path.write_bytes(b"PSF-2.0\n")
    link_path = mount / LICENSE_LINK.lstrip("/")
    if not link_path.exists() and not link_path.is_symlink():
        os.symlink("LICENSE.txt", link_path)
    _copy_ldd_closure(mount, [src_so for _, src_so in selected])
    return selected, tuple(sorted(name for name, _ in selected))


def test_real_sdk_elf_observation_dpkg_owners_and_clean_main_verification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setenv("CALLER_PAYLOAD_SENTINEL", "int-preserved")
    env_before = dict(os.environ)
    real_m = platform.machine()
    arch = payload.NATIVE[real_m]

    mount = tmp_path / "clean_mount"
    selected, exp_imports = _stage_sdk_mount(mount)
    so1, so2 = selected[0][1], selected[1][1]
    log1, log2 = f"{DYN}/{so1.name}", f"{DYN}/{so2.name}"

    observed_calls: list[tuple[list[str], dict[str, str] | None]] = []

    def recording_run(command: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raw_env = kwargs.get("env")
        observed_calls.append((list(command), dict(raw_env) if isinstance(raw_env, dict) else None))
        return subprocess.run(command, *args, **kwargs)

    probe_run = make_stdlib_import_probe_runner(exp_imports, run=recording_run, executable=sys.executable)

    empty_m = tmp_path / "empty_mount"
    empty_m.mkdir()
    assert payload._walk(empty_m) == ({}, {})
    (empty_m / "usr/local/empty_dir").mkdir(parents=True)
    e_entries, e_obs = payload.observe(probe_run, empty_m, sys.executable, real_m)
    assert "/usr/local/empty_dir" in e_entries and e_obs["elves"] == {}
    assert payload.unresolved({}) == [] and payload.owners(probe_run, {}) == {}
    out_p = tmp_path / "outside.txt"
    out_p.write_text("outside", encoding="utf-8")
    assert payload._logical(empty_m, empty_m / "usr/local/empty_dir") == "/usr/local/empty_dir"
    assert payload._logical(empty_m, out_p).startswith("outside:")

    before_e, baseline = payload.observe(probe_run, mount, sys.executable, real_m)
    assert before_e[LICENSE][0] == "file"
    assert before_e[LICENSE_LINK] == ["symlink", "LICENSE.txt", 0, before_e[LICENSE_LINK][3]]
    assert baseline["elves"][log1]["sha256"] == hashlib.sha256(so1.read_bytes()).hexdigest()
    assert baseline["elves"][log2]["sha256"] == hashlib.sha256(so2.read_bytes()).hexdigest()
    assert baseline["imports"] == list(exp_imports) and baseline["failed"] == {}
    assert payload.unresolved(baseline["elves"]) == [] and payload.classify(baseline, None) is None

    rc = payload.main(
        [arch, "--no-exclusion"], run=probe_run, mount=mount, executable=sys.executable, machine=lambda: real_m
    )
    rep = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert rc == 0 and rep["result"] == "clean" and rep["exclusion"] is None
    assert rep["retained"]["imports"] == list(exp_imports)
    assert rep["retained"]["unresolved"] == [] and rep["retained"]["preserved"] is True
    assert all(owner for owner in rep["retained"]["owners"].values())

    s_target, s_info = next(iter(baseline["targets"].items()))
    u_target = str(out_p)
    own = payload.owners(
        probe_run,
        {
            "/usr/local/lib/libpython3.so": ["/usr/local/lib/libpython3.so", "a" * 64],
            s_target: s_info,
            u_target: [u_target, "b" * 64],
        },
    )
    assert own["/usr/local/lib/libpython3.so"] == "cpython"
    assert own[s_target] != "" and own[u_target] == ""
    assert dict(os.environ) == env_before

    probe_envs = [env for cmd, env in observed_calls if cmd[:4] == [sys.executable, "-I", "-B", "-c"]]
    non_probe_envs = [env for cmd, env in observed_calls if cmd[0] in ("ldd", "dpkg-query")]
    assert len(probe_envs) == 2 * len(exp_imports)
    assert non_probe_envs and all(env is None for env in non_probe_envs)
    for p_env in probe_envs:
        assert p_env is not None
        assert p_env["LD_BIND_NOW"] == "1" and p_env["CALLER_PAYLOAD_SENTINEL"] == "int-preserved"
        assert not any(key.startswith("COVERAGE_") for key in p_env)


def test_real_broken_elf_trim_lifecycle_and_refusal_boundaries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    real_m = platform.machine()
    arch = payload.NATIVE[real_m]

    mount = tmp_path / "trim_mount"
    selected, exp_imports = _stage_sdk_mount(mount)
    probe_run = make_stdlib_import_probe_runner((*exp_imports, "_tkinter"), executable=sys.executable)
    so1 = selected[0][1]
    suffix = "." + so1.name.split(".", 1)[1]
    tk_log = f"{DYN}/_tkinter{suffix}"
    tk_path = mount / tk_log.lstrip("/")

    raw1 = so1.read_bytes()
    assert b"libc.so.6\x00" in raw1
    patched_tk = raw1.replace(b"libc.so.6\x00", b"libno0.so\x00", 1)
    tk_path.write_bytes(patched_tk)
    tk_sha = hashlib.sha256(patched_tk).hexdigest()

    before_e, baseline = payload.observe(probe_run, mount, sys.executable, real_m)
    assert payload.unresolved(baseline["elves"]) == [f"{tk_log}: libno0.so => not found"]
    assert baseline["imports"] == list(exp_imports) and sorted(baseline["failed"]) == ["_tkinter"]

    with pytest.raises(payload.PayloadRefusal, match="no frozen exclusion applies"):
        payload.classify(baseline, None)

    rc_no = payload.main(
        [arch, "--no-exclusion"], run=probe_run, mount=mount, executable=sys.executable, machine=lambda: real_m
    )
    rep_no = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert rc_no == 1 and "no frozen exclusion applies" in rep_no["reasons"][0] and tk_path.is_file()

    tree_before_default = {
        str(p): os.readlink(p).encode() if p.is_symlink() else p.read_bytes()
        for p in mount.rglob("*") if p.is_file() or p.is_symlink()
    }
    rc_def = payload.main(
        [arch],
        run=probe_run,
        mount=mount,
        executable=sys.executable,
        machine=lambda: real_m,
        exclusions=historical.HISTORICAL_31215_PYTHON_PAYLOAD_EXCLUSIONS,
    )
    rep_def = json.loads(capsys.readouterr().out.splitlines()[-1])
    tree_after_default = {
        str(p): os.readlink(p).encode() if p.is_symlink() else p.read_bytes()
        for p in mount.rglob("*") if p.is_file() or p.is_symlink()
    }
    assert rc_def == 1 and rep_def["result"] == "refused" and rep_def["exclusion"] is None
    assert "frozen exclusion refused" in rep_def["reasons"][0]
    assert tree_after_default == tree_before_default and tk_path.is_file()

    elf_mach = baseline["elves"][tk_log]["elf"][2]
    native_entry = historical.HISTORICAL_31215_PYTHON_PAYLOAD_EXCLUSIONS[arch]
    assert native_entry.elf_machine == elf_mach
    sdk_entry = native_entry._replace(
        architecture=arch, path=tk_log, sha256=tk_sha, size=len(patched_tk),
        elf_machine=elf_mach, module="_tkinter", missing=("libno0.so",), baseline_imports=exp_imports,
    )

    classified = payload.classify(baseline, sdk_entry)
    assert classified is not None and classified["path"] == tk_log and classified["missing"] == ["libno0.so"]

    with pytest.raises(payload.PayloadRefusal, match="changed between classification and removal"):
        payload.remove_exclusion(mount, sdk_entry._replace(sha256="0" * 64))
    assert tk_path.is_file()

    payload.remove_exclusion(mount, sdk_entry)
    assert not tk_path.exists()

    after_e, after_obs = payload.observe(probe_run, mount, sys.executable, real_m)
    own = payload.owners(probe_run, after_obs["targets"])
    ret = payload.verify_retained(before_e, after_e, after_obs, sdk_entry, own)
    assert ret["excluded_absent"] is True and ret["preserved"] is True
    assert ret["imports"] == list(exp_imports) and ret["digest"] == ret["expected_digest"]

    with pytest.raises(payload.PayloadRefusal, match="retained payload refused"):
        payload.verify_retained(
            before={**before_e, "/usr/local/extra.txt": ["file", "a" * 64, 1, 0]},
            after_entries=before_e, after=baseline, entry=sdk_entry,
            ownership=dict.fromkeys(baseline["targets"], ""),
        )


def test_real_walk_special_entries_and_main_guard_refusals(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    real_m = platform.machine()
    arch = payload.NATIVE[real_m]
    assert "amd64" not in payload.PYTHON_PAYLOAD_EXCLUSIONS
    assert set(historical.HISTORICAL_31215_PYTHON_PAYLOAD_EXCLUSIONS) == {"arm64", "amd64"}
    for plat, ent in historical.HISTORICAL_31215_PYTHON_PAYLOAD_EXCLUSIONS.items():
        payload.validate_exclusion(ent, plat)
        with pytest.raises(payload.PayloadRefusal, match="not exact"):
            payload.validate_exclusion(ent._replace(size=0), plat)
    arm_entry = historical.HISTORICAL_31215_PYTHON_PAYLOAD_EXCLUSIONS[arch]

    edge_m = tmp_path / "edge_mount"
    selected, exp_imports = _stage_sdk_mount(edge_m)
    probe_run = make_stdlib_import_probe_runner(exp_imports, run=subprocess.run, executable=sys.executable)
    suffix = "." + selected[0][1].name.split(".", 1)[1]
    dyn_dir = edge_m / DYN.lstrip("/")
    (edge_m / "usr/local/share").mkdir(parents=True, exist_ok=True)
    (edge_m / "usr/local/share/short_elf").write_bytes(b"\x7fELF\x02\x02")
    (edge_m / "usr/local/share/big_elf").write_bytes(
        b"\x7fELF\x02\x02\x01" + bytes(11) + (62).to_bytes(2, "big") + b"tag"
    )
    os.mkfifo(edge_m / "usr/local/share/pipe.fifo")
    (dyn_dir / f"1bad{suffix}").write_bytes(b"not-an-elf")

    walked, obs = payload.observe(probe_run, edge_m, sys.executable, real_m)
    assert walked["/usr/local/share/pipe.fifo"][0] == "other"
    assert obs["elves"]["/usr/local/share/short_elf"]["elf"] == []
    assert obs["elves"]["/usr/local/share/big_elf"]["elf"] == [2, 2, 62]
    assert obs["failed"]["1bad"] == {"exit": None, "error": "not an importable module name"}

    with pytest.raises(payload.PayloadRefusal, match="import results do not match"):
        payload.classify({**obs, "imports": ["extra_mod"]}, None)
    with pytest.raises(payload.PayloadRefusal, match="not a regular file"):
        payload.classify({**obs, "targets": {"/lib/missing.so": [None, None]}}, None)
    with pytest.raises(payload.PayloadRefusal, match="frozen exclusion refused"):
        payload.classify(
            {
                **obs, "machine": "riscv64", "dynload_real": "/outside",
                "failed": {"1bad": {"exit": 1, "error": "err"}},
                "elves": {"/usr/local/share/short_elf": {"ldd": "", "sha256": "0" * 64, "size": 1, "elf": []}},
            },
            arm_entry,
        )

    rc_f = payload.main(
        [arch], run=probe_run, mount=edge_m, executable=sys.executable,
        machine=lambda: real_m, exclusions={arch: arm_entry._replace(architecture=arch)},
    )
    rep_f = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert rc_f == 1 and "frozen exclusion refused" in rep_f["reasons"][0]

    assert (
        payload.main(
            [arch, "--bad"], run=probe_run, mount=edge_m, executable=sys.executable, machine=lambda: real_m
        )
        == 1
    )
    assert "usage: ARCH [--no-exclusion]" in json.loads(capsys.readouterr().out.splitlines()[-1])["reasons"][0]
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    assert (
        payload.main([arch], run=probe_run, mount=edge_m, executable=sys.executable, machine=lambda: real_m)
        == 1
    )
    assert "run with -B" in json.loads(capsys.readouterr().out.splitlines()[-1])["reasons"][0]
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    assert (
        payload.main([arch], run=probe_run, mount=edge_m, executable=sys.executable, machine=lambda: "riscv64")
        == 1
    )
    assert "native architecture 'riscv64'" in json.loads(capsys.readouterr().out.splitlines()[-1])["reasons"][0]

    src_root = str(Path(payload.__file__).resolve().parents[2])
    guard_proc = launch_unified_coverage_process(
        [sys.executable, "-B", "-m", "repomap_kg.runtime.python_payload", "riscv64"],
        family="cli_module",
        pid_namespace_relation="shared",
        extra_env={"PYTHONPATH": src_root},
    )
    assert guard_proc.returncode == 1
    guard_out = json.loads(guard_proc.stdout.splitlines()[-1])
    assert guard_out["result"] == "refused"
    assert f"native architecture {real_m!r} is not 'riscv64'" in guard_out["reasons"][0]
