"""Readback decoding/verification, confinement facts, runtime facts and probe classes (5.4, 5.6, 14.2)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot.archive_verifier import ExpectedEntry
from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult, run_bounded
from common_lore_index.extractors.rust_pilot.construction import (
    ConstructionRefused,
    check_runtime_facts,
    encode_setup_stream,
)
from common_lore_index.extractors.rust_pilot.containment import ALL_PROBES, classify_probe, expected_outcome
from common_lore_index.extractors.rust_pilot.readback import (
    Readback,
    ReadbackRefused,
    decode_readback,
    verify_confinement,
    verify_install_tree,
)
from repomap_test_support.rust_pilot_fake_tree_sitter.wheels import guest_text

MOUNTS = ("1 0 0:1 / / ro,nosuid,nodev - overlay overlay ro",
          "2 1 0:2 / /opt/repomap-rust rw,nosuid,nodev,relatime - tmpfs tmpfs rw,size=16384k,mode=755",
          "3 1 0:3 / /scratch rw,nosuid,nodev,noexec,relatime - tmpfs tmpfs rw,size=4096k,mode=700")
STATUS = ("Uid:\t10001\t10001\t10001\t10001", "Gid:\t10001\t10001\t10001\t10001", "CapPrm:\t0000000000000000",
          "CapEff:\t0000000000000000", "CapAmb:\t0000000000000000", "NoNewPrivs:\t1", "Seccomp:\t2")


def _readback(**changes: Any) -> Readback:
    fields: dict[str, Any] = {"entries": (), "mounts": MOUNTS, "status": STATUS, "scratch": (), "ifaces": ("lo",)}
    return Readback(**{**fields, **changes})


def test_guest_observed_confinement_is_checked_and_labelled() -> None:
    facts = verify_confinement(_readback())
    assert (facts.label, facts.uid, facts.seccomp) == ("guest_observed", "10001", "2")


@pytest.mark.parametrize(("change", "code"), [
    ({"mounts": (MOUNTS[0].replace(" ro,", " rw,"), *MOUNTS[1:])}, "guest_root_writable"),
    ({"mounts": (MOUNTS[0], MOUNTS[1].replace("nosuid,", "nosuid,noexec,"), MOUNTS[2])}, "guest_runtime_mount"),
    ({"mounts": (*MOUNTS[:2], MOUNTS[2].replace("noexec,", ""))}, "guest_scratch_mount"),
    ({"mounts": MOUNTS[:2]}, "guest_mount_scratch"),
    ({"status": ("Uid:\t0\t0\t0\t0", *STATUS[1:])}, "guest_credentials"),
    ({"status": (*STATUS[:3], "CapEff:\t00000000a80425fb", *STATUS[4:])}, "guest_capabilities"),
    ({"status": (*STATUS[:5], "NoNewPrivs:\t0", STATUS[6])}, "guest_no_new_privs"),
    ({"scratch": ("leftover",)}, "guest_scratch_not_empty"),
    ({"scratch": None}, "guest_scratch_not_empty"),
    ({"ifaces": ("eth0", "lo")}, "guest_network"),
])
def test_each_confinement_deviation_refuses(change: dict[str, Any], code: str) -> None:
    with pytest.raises(ReadbackRefused) as raised:
        verify_confinement(_readback(**change))
    assert raised.value.code == code


def _sealed_tree(root: Path) -> list[ExpectedEntry]:
    (root / "helper").mkdir()
    (root / "helper" / "parse_helper.py").write_bytes(b"pass\n")
    for path, mode in ((root / "helper" / "parse_helper.py", 0o444), (root / "helper", 0o555), (root, 0o555)):
        path.chmod(mode)
    return [ExpectedEntry("", "d", 0o555, None), ExpectedEntry("helper", "d", 0o555, None),
            ExpectedEntry("helper/parse_helper.py", "f", 0o444, b"pass\n")]


def _guest_readback(root: Path, scratch: Path) -> ExecResult:
    source = guest_text("install_readback.py", root, scratch).decode("ascii")
    return run_bounded([sys.executable, "-I", "-S", "-B", "-c", source], stdout_limit=8 * 1_048_576, deadline=60)


def test_real_guest_readback_round_trips_through_strict_verification(tmp_path: Path) -> None:
    root, scratch = tmp_path / "runtime", tmp_path / "scratch"
    root.mkdir()
    scratch.mkdir()
    expected = _sealed_tree(root)
    try:
        result = _guest_readback(root, scratch)
        assert result.returncode == 0
        decoded = decode_readback(result.stdout)
        owner = (os.getuid(), root.stat().st_gid)
        assert len(verify_install_tree(decoded, expected, owner=owner)) == 64
        with pytest.raises(ReadbackRefused, match="install_owner"):
            verify_install_tree(decoded, expected, owner=(owner[0] + 1, owner[1]))
        with pytest.raises(ReadbackRefused, match="install_bytes"):
            verify_install_tree(decoded, [*expected[:2], ExpectedEntry("helper/parse_helper.py", "f", 0o444, b"x")],
                                owner=owner)
        with pytest.raises(ReadbackRefused, match="install_path_set"):
            verify_install_tree(decoded, expected[:2], owner=owner)
        with pytest.raises(ReadbackRefused):
            verify_confinement(decoded)
        for cut in (len(result.stdout) - 1, 40):
            with pytest.raises(ReadbackRefused):
                decode_readback(result.stdout[:cut])
        root.chmod(0o755)
        (root / "link").symlink_to(root / "helper")
        assert _guest_readback(root, scratch).returncode == 4
    finally:
        for path in (root, root / "helper"):
            path.chmod(0o755)


def _facts(**changes: Any) -> dict[str, Any]:
    kinds = ("mod_item", "function_item", "function_signature_item", "struct_item", "enum_item", "union_item",
             "type_item", "trait_item", "impl_item", "macro_definition", "macro_invocation", "const_item",
             "static_item", "use_declaration", "extern_crate_declaration", "foreign_mod_item",
             "inner_attribute_item", "attribute_item", "declaration_list", "visibility_modifier")
    facts = {"import": "ok", "executable": "/usr/local/bin/python3.13", "version": "3.13.12",
             "cache_tag": "cpython-313", "soabi": "cpython-313-aarch64-linux-gnu", "abiflags": "",
             "machine": "aarch64", "libc": ["glibc", "2.41"], "ts_version": "0.26.0",
             "min_compatible_language_version": 13, "abi_version": 15, "language_version": 15,
             "kind_ids": {kind: index + 1 for index, kind in enumerate(kinds)},
             "field_ids": {"name": 1, "type": 2, "trait": 3, "body": 4},
             "module_files": ["/opt/repomap-rust/site/tree_sitter/__init__.py",
                              "/opt/repomap-rust/site/tree_sitter_rust/__init__.py"]}
    return {**facts, **changes}


@pytest.mark.parametrize("change", [
    {"version": "3.13.11"}, {"machine": "x86_64"}, {"soabi": "cpython-313-x86_64-linux-gnu"}, {"abiflags": "t"},
    {"libc": ["glibc", "2.27"]}, {"libc": ["musl", "1.2"]}, {"ts_version": "0.25.0"}, {"abi_version": 14},
    {"language_version": 14}, {"kind_ids": {}}, {"field_ids": {"name": None}}, {"import": "failed"},
    {"module_files": ["/usr/lib/python3/site-packages/tree_sitter/__init__.py", "/x"]},
])
def test_runtime_observations_outside_the_contract_refuse_the_run(change: dict[str, Any]) -> None:
    check_runtime_facts(_facts(), "aarch64")
    with pytest.raises(ConstructionRefused, match="runtime_mismatch"):
        check_runtime_facts(_facts(**change), "aarch64")


def test_setup_stream_is_magic_header_then_exact_payloads() -> None:
    stream = encode_setup_stream([("a-1.0-py3-none-any.whl", b"WHEEL", "a-1.0.dist-info", ("a",), [("a/x", 1, "0" * 64, 0o644)])],
                                 b"helper", [("core-notice", b"N")])
    magic, header, body = stream.split(b"\n", 2)
    document = json.loads(header)
    assert magic == b"REPOMAP-RUST-SETUP-1" and body == b"WHEELhelperN"
    assert [item["class"] for item in document["payloads"]] == ["wheel", "helper", "notice"]
    with pytest.raises(ConstructionRefused, match="setup_stream_too_large"):
        encode_setup_stream([], b"x" * (4 * 1_048_576 + 1), [])


@pytest.mark.parametrize("count", [True, 1.0, "1"])
def test_readback_entry_count_requires_an_exact_integer(count: object) -> None:
    rows: list[dict[str, object]] = [
        {"t": "entry", "path": "", "type": "d", "mode": 0o555,
         "uid": 0, "gid": 0, "nlink": 1, "size": 0},
        {"t": "mounts", "lines": []}, {"t": "status", "lines": []},
        {"t": "scratch", "names": []}, {"t": "ifaces", "names": ["lo"]},
        {"t": "end", "entries": 1},
    ]
    def encode() -> bytes:
        return b"".join(json.dumps(row).encode("ascii") + b"\n" for row in rows)
    assert len(decode_readback(encode()).entries) == 1
    rows[-1]["entries"] = count
    with pytest.raises(ReadbackRefused, match="readback_framing"):
        decode_readback(encode())


def _result(code: int | None, out: bytes = b"", *, timed_out: bool = False, overflow: bool = False) -> ExecResult:
    return ExecResult(code, out, overflow, 0, "0" * 64, False, timed_out, True, 0.0)


def test_containment_probe_outcomes_come_from_parent_observations() -> None:
    assert len(ALL_PROBES) == 15 and expected_outcome("tcp") == "refused" and expected_outcome("sleep") == "time_bound"
    assert classify_probe("tcp", _result(0, b"REFUSED tcp ENETUNREACH\n"), False) == "refused"
    assert classify_probe("tcp", _result(1, b"ALLOWED tcp\n"), False) == "allowed"
    assert classify_probe("udp", _result(0, b"REFUSED tcp EPERM\n"), False) == "unexpected"
    assert classify_probe("memory", _result(137), True) == "memory_bound"
    assert classify_probe("sleep", _result(None, timed_out=True), False) == "time_bound"
    assert classify_probe("stdout_flood", _result(-9, overflow=True), False) == "output_bound"
    assert classify_probe("abort", _result(134), False) == "crashed"
    with pytest.raises(ContractError, match="unknown_probe"):
        expected_outcome("format_disk")
