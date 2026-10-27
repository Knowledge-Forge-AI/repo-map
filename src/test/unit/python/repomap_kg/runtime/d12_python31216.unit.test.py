"""Regression for the exact ADR0100 Python security input."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from repomap_kg.runtime import release


def test_security_release_selects_exact_inspected_python_31216() -> None:
    assert release.PYTHON_RELEASE_VERSION == "3.12.16"
    assert release.PYTHON_RELEASE_IMAGE == (
        "python:3.12-slim-trixie@sha256:"
        "962f801b08c870ac2a51b72bf02dae38c9a4162319e5e882ec244e198188d54e"
    )


def test_python_31216_payload_oci_identities_and_native_arm_baseline() -> None:
    import ast
    import hashlib

    import pytest

    from repomap_kg.runtime import python_payload as payload
    from repomap_kg.runtime import release_manifest as historical

    assert payload.PYTHON_31216_INDEX == (
        "sha256:962f801b08c870ac2a51b72bf02dae38c9a4162319e5e882ec244e198188d54e"
    )
    assert payload.PYTHON_31216_ARM64_MANIFEST == (
        "sha256:0ced713d9b8336172d981d8f25f2422b6782bdad019fda4cb653c6ee187430de"
    )
    assert payload.PYTHON_31216_ARM64_CONFIG == (
        "sha256:7d0134fc196a9daa289acd038dd1c95b6873cacfaa4d6ea97c51501e0af515a3"
    )
    assert payload.PYTHON_31216_AMD64_MANIFEST == (
        "sha256:6d2b0577e6d1632f077331de8e4780535f54839d163ded7abb4b7dd37b5d37ac"
    )
    assert payload.PYTHON_31216_AMD64_CONFIG == (
        "sha256:3a1b98be05abc7ac60c8712a943688620a602c3e0e6bfbc567afbeabe2085b28"
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
    assert payload.AMD64_31216_NATIVE_BASELINE_IMPORTS is None
    assert set(payload.PYTHON_PAYLOAD_EXCLUSIONS) == {"arm64"}
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

    # Default PYTHON_PAYLOAD_EXCLUSIONS (omitted exclusions= argument) must refuse amd64 and leave _tkinter intact.
    rc = payload.main(["amd64"], run=fake_run, mount=tmp_path, executable="py", machine=lambda: "x86_64")
    rep = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert rc == 1 and rep["result"] == "refused" and rep["exclusion"] is None
    assert "no frozen exclusion applies" in rep["reasons"][0]
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


def test_default_map_refuses_amd64_carrying_the_exact_frozen_tkinter_identity_and_keeps_raw_baseline(
    capsys: Any, monkeypatch: Any
) -> None:
    import json
    import sys

    from repomap_kg.runtime import python_payload as payload
    from repomap_kg.runtime import release_manifest as historical

    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    amd = historical.HISTORICAL_31215_PYTHON_PAYLOAD_EXCLUSIONS["amd64"]
    names = sorted((*amd.baseline_imports, "_tkinter"))
    observed = {
        "machine": "x86_64", "dynload_real": payload.DYNLOAD, "targets": {},
        "elves": {amd.path: {"sha256": amd.sha256, "size": amd.size, "elf": [2, 1, amd.elf_machine], "ldd_exit": 0,
                             "ldd": "".join(f"\t{library} => not found\n" for library in amd.missing)}},
        "dynload": [[f"{name}.cpython-312-x86_64-linux-gnu.so", "file"] for name in names],
        "imports": list(amd.baseline_imports), "failed": {"_tkinter": {"exit": 1, "error": "ImportError: libtk8.6.so"}},
    }
    assert payload.classify(observed, amd) is not None, "the observation carries the exact frozen _tkinter bytes"
    monkeypatch.setattr(payload, "observe", lambda *_args: ({}, observed))

    def no_run(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the refusal must precede any removal or ownership probe")

    code = payload.main(["amd64"], run=no_run, mount=Path("/nonexistent"), executable="py", machine=lambda: "x86_64")
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert code == 1 and report["result"] == "refused" and report["exclusion"] is None
    assert "no frozen exclusion applies" in report["reasons"][0]
    assert report["baseline"] == observed, "the raw baseline is recorded before classification can refuse"
