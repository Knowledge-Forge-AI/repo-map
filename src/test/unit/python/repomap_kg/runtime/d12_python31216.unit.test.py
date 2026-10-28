"""Regression for the exact ADR0100 Python security input."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from repomap_kg.runtime import release


def test_security_release_selects_exact_inspected_python_31216() -> None:
    assert release.PYTHON_RELEASE_VERSION == "3.12.16"
    assert release.PYTHON_RELEASE_IMAGE == (
        "python:3.12-slim-trixie@sha256:"
        "aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159"
    )


def test_python_31216_payload_oci_identities_and_native_arm_baseline() -> None:
    import ast
    import hashlib

    import pytest

    from repomap_kg.runtime import python_payload as payload
    from repomap_kg.runtime import release_manifest as historical

    assert payload.PYTHON_31216_INDEX == (
        "sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159"
    )
    assert payload.PYTHON_31216_ARM64_MANIFEST == (
        "sha256:b224e2fe306f9d303251ada22961635e5b52a69c0414a0050611be31c59f5f5b"
    )
    assert payload.PYTHON_31216_ARM64_CONFIG == (
        "sha256:ff710677e697054c516f12c53c92166f1aef075f21b2a593f4c615e522112b4e"
    )
    assert payload.PYTHON_31216_AMD64_MANIFEST == (
        "sha256:1148dbb014615300fa7e713b2f94f550c0d1c69780c0805f84f093ceee34dd0b"
    )
    assert payload.PYTHON_31216_AMD64_CONFIG == (
        "sha256:ae4e8b7c575fabea88a029b6cae757f342ca2525e07f7c22272d5105c346b35e"
    )
    baseline = payload.ARM64_31216_NATIVE_BASELINE_IMPORTS
    assert len(baseline) == 77 and baseline == tuple(sorted(set(baseline)))
    assert hashlib.sha256(" ".join(baseline).encode()).hexdigest() == (
        "049267074bee42d4449e7a3ed866076d6529b44106e0e3676f41a5e1da277a1b"
    )
    tree = ast.parse(Path(str(payload.__file__)).read_text())
    declaration = next(n for n in tree.body if isinstance(n, ast.AnnAssign)
                       and isinstance(n.target, ast.Name) and n.target.id == "ARM64_31216_NATIVE_BASELINE_IMPORTS")
    assert isinstance(declaration.value, ast.Tuple) and ast.literal_eval(declaration.value) == baseline
    assert set(payload.PYTHON_PAYLOAD_EXCLUSIONS) == {"arm64", "amd64"}
    assert payload.PYTHON_PAYLOAD_EXCLUSIONS["arm64"].baseline_imports == baseline
    for name in ("ARM64_BASELINE_IMPORTS", "AMD64_BASELINE_IMPORTS",
                 "ARM64_31216_PREDICTED_IMPORTS_AWAITING_NATIVE_PROOF"):
        assert not hasattr(payload, name), f"{name}: no 3.12.15 import set is reachable from the payload contract"

    # Synthetic mechanics only: a 3.12.15 import set is never a 3.12.16 baseline.
    arm_entry = payload.build_31216_exclusion("arm64", historical.ARM64_BASELINE_IMPORTS)
    assert arm_entry.python_index == payload.PYTHON_31216_INDEX
    assert arm_entry.platform_manifest == payload.PYTHON_31216_ARM64_MANIFEST
    assert arm_entry.python_config == payload.PYTHON_31216_ARM64_CONFIG
    assert arm_entry.size == 70584 and arm_entry.elf_machine == 183

    enrolled = {"arm64": payload.build_31216_exclusion("arm64", payload.ARM64_31216_NATIVE_BASELINE_IMPORTS)}
    assert set(enrolled) == {"arm64"}
    assert "amd64" not in enrolled

    with pytest.raises(payload.PayloadRefusal, match="unsupported 3.12.16 payload architecture"):
        payload.build_31216_exclusion("riscv64", ("math",))


def test_amd64_expected_default_is_a_separate_literal_bound_to_the_refreshed_candidate() -> None:
    import ast
    import hashlib

    from repomap_kg.runtime import python_payload as payload

    tree = ast.parse(Path(str(payload.__file__)).read_text())
    declared = {n.target.id: n.value for n in tree.body if isinstance(n, ast.AnnAssign)
                and isinstance(n.target, ast.Name) and n.target.id.endswith("_31216_NATIVE_BASELINE_IMPORTS")}
    amd = declared["AMD64_31216_NATIVE_BASELINE_IMPORTS"]
    assert isinstance(amd, ast.Tuple) and all(isinstance(e, ast.Constant) for e in amd.elts), "a literal, no alias"
    names = ast.literal_eval(amd)
    assert names == payload.AMD64_31216_NATIVE_BASELINE_IMPORTS and len(names) == 77
    assert hashlib.sha256(" ".join(names).encode()).hexdigest() == (
        "049267074bee42d4449e7a3ed866076d6529b44106e0e3676f41a5e1da277a1b")
    assert payload.PYTHON_PAYLOAD_EXCLUSIONS["amd64"] == payload.build_31216_exclusion("amd64", names) == (
        "amd64", "sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159",
        "sha256:1148dbb014615300fa7e713b2f94f550c0d1c69780c0805f84f093ceee34dd0b",
        "sha256:ae4e8b7c575fabea88a029b6cae757f342ca2525e07f7c22272d5105c346b35e",
        "/usr/local/lib/python3.12/lib-dynload/_tkinter.cpython-312-x86_64-linux-gnu.so",
        "4505ea29e626d11865106c975d7bed84d472bc6a4c0f2aedd670c6a3ecf233a8", 62448, 62, "_tkinter",
        ("libtcl8.6.so", "libtk8.6.so"), names)


def test_default_exclusions_refuse_amd64_observation_with_unchanged_frozen_tkinter_bytes(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    import json
    import subprocess
    import sys

    from repomap_kg.runtime import python_payload as payload
    from repomap_kg.runtime import release_manifest as historical

    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    amd_hist = historical.HISTORICAL_31215_PYTHON_PAYLOAD_EXCLUSIONS["amd64"]
    tk_rel = amd_hist.path
    ssl_rel = f"{payload.DYNLOAD}/_ssl.cpython-312-x86_64-linux-gnu.so"
    libc_rel = "/lib/x86_64-linux-gnu/libc.so.6"

    # Build a 62448-byte ELF-64 x86_64 (machine 62) _tkinter file and a valid _ssl file.
    elf_head = b"\x7fELF\x02\x01\x01" + bytes(11) + (62).to_bytes(2, "little")
    tk_bytes = elf_head + bytes(amd_hist.size - len(elf_head))
    assert len(tk_bytes) == 62448
    ssl_bytes = elf_head + b"ssl"

    for rel, data in ((tk_rel, tk_bytes), (ssl_rel, ssl_bytes), (libc_rel, b"libc")):
        target = tmp_path / rel.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def fake_run(cmd: list[str], **opts: Any) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "ldd":
            logical = "/" + Path(cmd[1]).relative_to(tmp_path).as_posix()
            out = f"\tlibc.so.6 => {libc_rel} (0x1)\n"
            if logical == tk_rel:
                out += "\tlibtcl8.6.so => not found\n\tlibtk8.6.so => not found\n"
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if cmd[0] == "dpkg-query":
            return subprocess.CompletedProcess(cmd, 0, f"libc6:amd64: {cmd[2]}\n", "")
        assert cmd[1:4] == ["-I", "-B", "-c"] and opts["env"]["LD_BIND_NOW"] == "1"
        bad = cmd[4] == "import _tkinter"
        return subprocess.CompletedProcess(cmd, int(bad), "", "ImportError: libtk8.6.so" * bad)

    # The default map (omitted exclusions=) now applies the admitted AMD entry (ADR 0103); these synthetic Tk bytes
    # and import set are not its frozen identity, so it refuses before removal and leaves _tkinter intact.
    assert payload.PYTHON_PAYLOAD_EXCLUSIONS["amd64"] == payload.build_31216_exclusion(
        "amd64", payload.AMD64_31216_NATIVE_BASELINE_IMPORTS)
    rc = payload.main(["amd64"], run=fake_run, mount=tmp_path, executable="py", machine=lambda: "x86_64")
    rep = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert rc == 1 and rep["result"] == "refused" and rep["exclusion"] is None
    assert "frozen exclusion refused: target hash, size or ELF class/machine differs" in rep["reasons"][0]
    assert (tmp_path / tk_rel.lstrip("/")).read_bytes() == tk_bytes

    # ARM enrollment never enrolls AMD; its default observation still refuses without changing bytes.
    enrolled_arm = {"arm64": payload.build_31216_exclusion("arm64", payload.ARM64_31216_NATIVE_BASELINE_IMPORTS)}
    rc_arm = payload.main(
        ["amd64"],
        run=fake_run,
        mount=tmp_path,
        executable="py",
        machine=lambda: "x86_64",
        exclusions=enrolled_arm,
    )
    rep_arm = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert rc_arm == 1 and rep_arm["result"] == "refused" and rep_arm["exclusion"] is None
    assert "no frozen exclusion applies" in rep_arm["reasons"][0]
    assert (tmp_path / tk_rel.lstrip("/")).read_bytes() == tk_bytes


def _amd_observed(entry: Any, *, raw: bool = True) -> dict[str, Any]:
    from repomap_kg.runtime import python_payload as payload

    names = sorted((*entry.baseline_imports, *(["_tkinter"] if raw else [])))
    return {"machine": "x86_64", "dynload_real": payload.DYNLOAD, "targets": {}, "elves": {entry.path: {
        "sha256": entry.sha256, "size": entry.size, "elf": [2, 1, entry.elf_machine], "ldd_exit": 0,
        "ldd": "".join(f"\t{library} => not found\n" for library in entry.missing)}} if raw else {},
        "dynload": [[f"{name}.cpython-312-x86_64-linux-gnu.so", "file"] for name in names],
        "imports": list(entry.baseline_imports),
        "failed": {"_tkinter": {"exit": 1, "error": "ImportError: libtk8.6.so"}} if raw else {}}


def test_default_map_refuses_amd64_carrying_the_exact_frozen_tkinter_identity_and_keeps_raw_baseline(
    capsys: Any, monkeypatch: Any
) -> None:
    """ADR 0103: the default map is admitted, so this refusal now uses explicit isolated held-map doubles."""
    import json
    import sys

    from repomap_kg.runtime import python_payload as payload
    from repomap_kg.runtime import release_manifest as historical

    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    amd = historical.HISTORICAL_31215_PYTHON_PAYLOAD_EXCLUSIONS["amd64"]
    observed = _amd_observed(amd)
    assert payload.classify(observed, amd) is not None, "the observation carries the exact frozen _tkinter bytes"
    monkeypatch.setattr(payload, "observe", lambda *_args: ({}, observed))

    def no_run(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the refusal must precede any removal or ownership probe")

    held_maps: tuple[dict[str, Any], ...] = ({}, {"amd64": None})
    for held in held_maps:
        code = payload.main(["amd64"], run=no_run, mount=Path("/nonexistent"), executable="py",
                            machine=lambda: "x86_64", exclusions=held)
        report = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert code == 1 and report["result"] == "refused" and report["exclusion"] is None
        assert "no frozen exclusion applies" in report["reasons"][0]
        assert report["baseline"] == observed, "the raw baseline is recorded before classification can refuse"


def test_default_map_trims_exactly_the_admitted_amd64_entry(capsys: Any, monkeypatch: Any) -> None:
    import json
    import sys

    from repomap_kg.runtime import python_payload as payload

    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    entry = payload.PYTHON_PAYLOAD_EXCLUSIONS["amd64"]
    raw, after = _amd_observed(entry), _amd_observed(entry, raw=False)
    views = iter([({entry.path: ["file", entry.sha256, entry.size, 33188]}, raw), ({}, after)])
    removed: list[Any] = []
    monkeypatch.setattr(payload, "observe", lambda *_args: next(views))  # canned raw and post-removal observations
    monkeypatch.setattr(payload, "remove_exclusion", lambda _mount, found: removed.append(found))

    def no_owner_probe(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("no retained target needs an ownership probe")

    code = payload.main(["amd64"], run=no_owner_probe, mount=Path("/nonexistent"), executable="py",
                        machine=lambda: "x86_64")
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert code == 0 and report["result"] == "trimmed" and report["reasons"] == [], report["reasons"]
    assert removed == [entry] and report["exclusion"]["python_config"] == payload.PYTHON_31216_AMD64_CONFIG
    assert report["retained"]["imports"] == list(payload.AMD64_31216_NATIVE_BASELINE_IMPORTS)
