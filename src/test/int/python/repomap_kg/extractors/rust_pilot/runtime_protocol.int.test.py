"""T1 runtime protocol: real guest writer, readback and helper as stdlib subprocesses.

The writer installs synthetic wheels carrying the stdlib stand-in packages,
the parent verifies every read-back byte, and the real parse helper runs from
that installed tree over the frozen public fixtures with complete framed IO.
No wheel, Docker command or native import is involved: this is fake-protocol
evidence (spec tier T1) and never native component evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.extractors.rust_pilot.archive_verifier import (
    expected_install_tree,
    expected_tree_digest,
    verify_wheel,
)
from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult, run_bounded
from common_lore_index.extractors.rust_pilot.construction import (
    ConstructionRefused,
    check_runtime_facts,
    encode_setup_stream,
)
from common_lore_index.extractors.rust_pilot.helper_protocol import (
    MAX_OUTPUT,
    ProtocolViolation,
    decode_frames,
    encode_request,
    invocation_nonce,
)
from common_lore_index.extractors.rust_pilot.observations import build_file_observations
from common_lore_index.extractors.rust_pilot.readback import (
    ReadbackRefused,
    decode_readback,
    verify_confinement,
    verify_install_tree,
)
from repomap_test_support.rust_pilot_fake_tree_sitter.wheels import NOTICES, guest_text, payload, stand_in_wheels

FIXTURES = Path(__file__).resolve().parents[5] / "fixtures" / "rust_pilot"
NATIVE_ONLY = {"q04_malformed_scopes.rs"}
RUN_NONCE = hashlib.sha256(b"runtime-protocol-int").digest()
PY = [sys.executable, "-I", "-S", "-B"]


@pytest.fixture(scope="module")
def runtime(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    base = tmp_path_factory.mktemp("rust-pilot-runtime")
    root, scratch = base / "opt-repomap-rust", base / "scratch"
    root.mkdir(mode=0o755)
    scratch.mkdir(mode=0o700)
    wheels = stand_in_wheels()
    helper = guest_text("parse_helper.py", root)
    stream = encode_setup_stream([payload(wheel) for wheel in wheels], helper, NOTICES)
    try:
        writer = run_bounded([*PY, "-c", guest_text("setup_writer.py", root).decode("ascii")], stdin=stream,
                             stdout_limit=4096, deadline=60)
        assert writer.clean and writer.stdout.startswith(b"REPOMAP-RUST-SETUP-OK ")
        readback = run_bounded([*PY, "-c", guest_text("install_readback.py", root, scratch).decode("ascii")],
                               stdout_limit=8 * 1_048_576, deadline=60)
        assert readback.clean
        decoded = decode_readback(readback.stdout)
        expected = expected_install_tree([verify_wheel(w.data, w.lock).members for w in wheels], helper, NOTICES)
        owner = (os.getuid(), root.stat().st_gid)
        assert verify_install_tree(decoded, expected, owner=owner) == expected_tree_digest(expected)
        with pytest.raises(ReadbackRefused):
            verify_confinement(decoded)
        yield root
    finally:
        for path in [root, *root.rglob("*")]:
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o755)


def _parse(root: Path, request: bytes, deadline: float = 30.0) -> ExecResult:
    return run_bounded([*PY, "-X", "utf8", str(root / "helper" / "parse_helper.py")], stdin=request,
                       stdout_limit=MAX_OUTPUT, deadline=deadline)


def _golds() -> list[dict[str, Any]]:
    golds = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((FIXTURES / "golds").glob("*.json"))]
    return [gold for gold in golds if gold["outcome"] == "succeeded" and gold["fixture"] not in NATIVE_ONLY]


@pytest.mark.parametrize("gold", _golds(), ids=lambda gold: str(gold["fixture"]))
def test_frozen_fixture_round_trips_through_the_installed_helper(runtime: Path, gold: dict[str, Any]) -> None:
    data = (FIXTURES / str(gold["fixture"])).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    nonce = invocation_nonce(RUN_NONCE, 7, digest)
    result = _parse(runtime, encode_request(data, nonce))
    assert result.clean and result.stderr_bytes == 0
    decoded = decode_frames(result.stdout, nonce=nonce, input_length=len(data))
    built = build_file_observations(str(gold["fixture"]), data, decoded, input_sha256=digest,
                                    build_script_name=Path(str(gold["fixture"])).name == "build.rs")
    parse = next(item for item in built.observations if item.kind == "rust.parse")
    assert (parse.metadata["completeness"], parse.metadata["item_list"], parse.metadata["build_script_name"],
            parse.metadata["line_count"]) == (gold["completeness"], gold["item_list"], gold["build_script_name"],
                                               gold["line_count"])
    items = [(i.metadata["namespace"], i.metadata["pointer"], i.name, i.metadata["item_kind"], i.start_line,
              i.end_line, i.metadata["start_byte"], i.metadata["end_byte"], i.metadata["usable_scope"])
             for i in built.observations if i.kind == "rust.item"]
    keys = ("namespace", "pointer", "name", "item_kind", "start_line", "end_line", "start_byte", "end_byte",
            "usable_scope")
    assert items == [tuple(item[key] for key in keys) for item in gold["items"]]
    unsupported = [(u.metadata["scope_pointer"], u.metadata["construct"], u.metadata["count"])
                   for u in built.observations if u.kind == "rust.unsupported"]
    assert unsupported == [(u["scope_pointer"], u["construct"], u["count"]) for u in gold["unsupported"]]


def test_helper_input_framing_refusals_exit_without_output(runtime: Path) -> None:
    data = b"pub fn f() {}\n"
    nonce = invocation_nonce(RUN_NONCE, 1, hashlib.sha256(data).hexdigest())
    request = encode_request(data, nonce)
    header = request.split(b"\n", 1)[0]
    for bad in (request + b"x", request[:-1], header.replace(b'"v":1', b'"v":2') + b"\n" + data,
                header.replace(nonce.encode(), b"Z" * 64) + b"\n" + data, b"\n", b"{" * 300 + b"\n",
                json.dumps({"n": len(data), "nonce": nonce, "sha256": "0" * 64, "v": 1}).encode() + b"\n" + data):
        result = _parse(runtime, bad)
        assert (result.returncode, result.stdout) == (3, b"")


def test_boundary_failures_are_observed_by_the_parent(runtime: Path) -> None:
    def run(source: bytes, deadline: float = 30.0) -> tuple[ExecResult, str]:
        nonce = invocation_nonce(RUN_NONCE, 2, hashlib.sha256(source).hexdigest())
        return _parse(runtime, encode_request(source, nonce), deadline), nonce

    noisy, nonce = run(b"//@fake:noise\npub struct A;\n")
    assert noisy.returncode == 0
    with pytest.raises(ProtocolViolation):
        decode_frames(noisy.stdout, nonce=nonce, input_length=len(b"//@fake:noise\npub struct A;\n"))
    aborted, _ = run(b"//@fake:abort\n")
    assert aborted.returncode not in (0, None) and aborted.stdout == b""
    stalled, _ = run(b"//@fake:sleep\n", deadline=2.0)
    assert stalled.events == ("time_bound",) and stalled.settled
    good, nonce = run(b"pub struct A;\n")
    with pytest.raises(ProtocolViolation):
        decode_frames(good.stdout, nonce="0" * 64, input_length=14)
    assert decode_frames(good.stdout, nonce=nonce, input_length=14).items[0].tag == 4


def test_runtime_probe_reports_stand_in_facts_that_the_parent_still_refuses(runtime: Path) -> None:
    result = run_bounded([*PY, "-c", guest_text("runtime_probe.py", runtime).decode("ascii")],
                         stdout_limit=65_536, deadline=60)
    facts = json.loads(result.stdout)
    assert result.clean and facts["import"] == "ok" and facts["ts_version"] == "0.26.0"
    assert facts["abi_version"] == 15 and all(path.startswith(str(runtime / "site")) for path in facts["module_files"])
    with pytest.raises(ConstructionRefused, match="runtime_mismatch"):
        check_runtime_facts(facts, facts["machine"])
