"""T1 stand-in guest processes, archive custody and strict parent protocol readback.

No native wheel, platform or parser qualification is established.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable

import pytest

from common_lore_index.extractors.rust_pilot.archive_verifier import (
    expected_install_tree,
    expected_tree_digest,
    verify_wheel,
)
from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult, run_bounded
from common_lore_index.extractors.rust_pilot.construction import encode_setup_stream
from common_lore_index.extractors.rust_pilot.helper_protocol import (
    ProtocolViolation,
    decode_frames,
    encode_request,
    invocation_nonce,
)
from common_lore_index.extractors.rust_pilot.observations import build_file_observations
from common_lore_index.extractors.rust_pilot.readback import decode_readback, verify_install_tree
from repomap_test_support.rust_pilot_fake_tree_sitter.wheels import (
    NOTICES,
    build_wheel,
    guest_text,
    payload,
    stand_in_wheels,
)


PYTHON = [sys.executable, "-I", "-S", "-B"]
WHEELS = stand_in_wheels()
RUN_NONCE = hashlib.sha256(b"ci121-t1-guest-protocol").digest()


@pytest.fixture
def runtime(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "opt-repomap-rust"
    scratch = tmp_path / "scratch"
    root.mkdir(mode=0o755)
    scratch.mkdir(mode=0o700)
    return root, scratch


def _tree(root: Path) -> dict[str, tuple[int, int, bytes | None]]:
    result: dict[str, tuple[int, int, bytes | None]] = {}
    for path in [root, *sorted(root.rglob("*"))]:
        info = path.lstat()
        relative = "" if path == root else path.relative_to(root).as_posix()
        data = path.read_bytes() if stat.S_ISREG(info.st_mode) else None
        result[relative] = (stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode), data)
    return result


def _run_writer(root: Path, stream: bytes) -> ExecResult:
    source = guest_text("setup_writer.py", root).decode("ascii")
    return run_bounded([*PYTHON, "-c", source], stdin=stream, stdout_limit=4096, deadline=60)


def _run_readback(root: Path, scratch: Path) -> ExecResult:
    source = guest_text("install_readback.py", root, scratch).decode("ascii")
    return run_bounded([*PYTHON, "-c", source], stdout_limit=8 * 1_048_576, deadline=60)


def _good_stream(root: Path) -> tuple[bytes, bytes]:
    helper = guest_text("parse_helper.py", root)
    stream = encode_setup_stream([payload(wheel) for wheel in WHEELS], helper, NOTICES)
    return stream, helper


def _base_stream() -> tuple[bytes, dict[str, Any], bytes]:
    """Return a header/blob stream whose helper bytes need not be installed."""

    stream = encode_setup_stream([payload(wheel) for wheel in WHEELS], b"helper\n", NOTICES)
    magic, header, rest = stream.split(b"\n", 2)
    return magic, json.loads(header), rest


def _wheel_stream(*, extra: dict[str, bytes] | None = None, mode: int = 0o100644,
                  record_rows: list[str] | None = None,
                  compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    files = {"evil/__init__.py": b"VALUE = 1\n"}
    data, contents = build_wheel(
        files,
        "evil-1.0.dist-info",
        extra=extra,
        record_rows=record_rows,
        mode=mode,
        compression=compression,
    )
    magic, document, rest = _base_stream()
    descriptor = document["payloads"][0]
    rest = rest[descriptor["size"]:]
    descriptor.update({
        "name": "evil-1.0-py3-none-any.whl",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "dist_info": "evil-1.0.dist-info",
        "top_level": ["evil", "evil-1.0.dist-info"],
        "members": [[name, len(blob), hashlib.sha256(blob).hexdigest(), 0o644]
                    for name, blob in contents.items()],
    })
    header = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")
    return magic + b"\n" + header + b"\n" + data + rest


def _reordered_stream() -> bytes:
    magic, document, rest = _base_stream()
    payloads = document["payloads"]
    payloads[1], payloads[2] = payloads[2], payloads[1]
    header = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")
    return magic + b"\n" + header + b"\n" + rest


def _digest_mutated_stream() -> bytes:
    magic, document, rest = _base_stream()
    document["payloads"][0]["sha256"] = "0" * 64
    header = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")
    return magic + b"\n" + header + b"\n" + rest


def _trailing_stream() -> bytes:
    magic, document, rest = _base_stream()
    header = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")
    return magic + b"\n" + header + b"\n" + rest + b"trailing-payload"


def test_synthetic_wheel_stream_is_accepted_before_negative_variants(tmp_path: Path) -> None:
    root = tmp_path / "opt-repomap-rust"
    root.mkdir(mode=0o755)
    result = _run_writer(root, _wheel_stream())
    assert result.clean and result.stdout.startswith(b"REPOMAP-RUST-SETUP-OK ")
    assert (root / "site" / "evil" / "__init__.py").read_bytes() == b"VALUE = 1\n"


@pytest.mark.parametrize(
    ("label", "stream_factory"),
    [
        ("unsafe_zip_member", lambda: _wheel_stream(extra={"../escape.py": b"x"})),
        ("mode_mismatch", lambda: _wheel_stream(mode=0o100755)),
        (
            "record_mismatch",
            lambda: _wheel_stream(record_rows=[
                "evil/__init__.py,sha256=bad,10",
                "evil-1.0.dist-info/RECORD,,",
            ]),
        ),
        ("compression_refused", lambda: _wheel_stream(compression=zipfile.ZIP_BZIP2)),
        ("payload_digest_mismatch", _digest_mutated_stream),
        ("payload_order_refused", _reordered_stream),
        ("trailing_payload_refused", _trailing_stream),
    ],
)
def test_setup_writer_refusals_return_code_two_without_partial_tree(
    tmp_path: Path, label: str, stream_factory: Callable[[], bytes],
) -> None:
    root = tmp_path / "opt-repomap-rust"
    root.mkdir(mode=0o755)
    before = _tree(root)
    result = _run_writer(root, stream_factory())
    assert (result.returncode, result.stdout, result.settled, result.timed_out) == (2, b"", True, False), label
    assert _tree(root) == before and list(root.iterdir()) == [], label


def test_setup_readback_round_trip_is_byte_and_digest_bound(runtime: tuple[Path, Path]) -> None:
    root, scratch = runtime
    stream, helper = _good_stream(root)
    writer = _run_writer(root, stream)
    assert writer.clean and writer.stdout.startswith(b"REPOMAP-RUST-SETUP-OK ")

    readback = _run_readback(root, scratch)
    assert readback.clean
    decoded = decode_readback(readback.stdout)
    expected = expected_install_tree(
        [verify_wheel(wheel.data, wheel.lock).members for wheel in WHEELS], helper, NOTICES
    )
    owner = (os.getuid(), root.stat().st_gid)
    assert verify_install_tree(decoded, expected, owner=owner) == expected_tree_digest(expected)
    assert list(scratch.iterdir()) == []


def _install(runtime: tuple[Path, Path]) -> tuple[Path, Path]:
    root, scratch = runtime
    stream, _helper = _good_stream(root)
    result = _run_writer(root, stream)
    assert result.clean
    return root, scratch


def _parse(root: Path, data: bytes, *, sequence: int = 1, deadline: float = 30.0) -> tuple[ExecResult, str]:
    digest = hashlib.sha256(data).hexdigest()
    nonce = invocation_nonce(RUN_NONCE, sequence, digest)
    request = encode_request(data, nonce)
    result = run_bounded(
        [*PYTHON, "-X", "utf8", str(root / "helper" / "parse_helper.py")],
        stdin=request,
        stdout_limit=4 * 1_048_576,
        deadline=deadline,
    )
    return result, nonce


def _assert_frame_invariants(decoded: Any, length: int) -> None:
    assert decoded.end.items == len(decoded.items)
    assert decoded.end.unsupported == len(decoded.unsupported)
    for item in decoded.items:
        assert 0 <= item.start <= item.end <= length
        for span in (item.name, item.visibility, item.self_type, item.trait_ref):
            if span is not None:
                assert 0 <= span[0] <= span[1] <= length
                assert item.start <= span[0] <= span[1] <= item.end
        for start, end in item.attributes:
            assert 0 <= start < end <= item.start
    for unsupported in decoded.unsupported:
        assert 0 <= unsupported.start <= unsupported.end <= length


@pytest.mark.parametrize(
    ("source", "construct"),
    [(b"foo!();\n", "macro_invocation"), (b"use crate::thing;\n", "use_declaration")],
)
def test_helper_unsupported_frames_round_trip_into_parent_observations(
    runtime: tuple[Path, Path], source: bytes, construct: str,
) -> None:
    root, scratch = _install(runtime)
    result, nonce = _parse(root, source)
    assert result.clean
    digest = hashlib.sha256(source).hexdigest()
    decoded = decode_frames(result.stdout, nonce=nonce, input_length=len(source))
    _assert_frame_invariants(decoded, len(source))
    built = build_file_observations(
        "src/lib.rs", source, decoded, input_sha256=digest, build_script_name=False,
    )
    assert any(
        observation.kind == "rust.unsupported"
        and observation.metadata["construct"] == construct
        for observation in built.observations
    )
    parse = next(item for item in built.observations if item.kind == "rust.parse")
    assert parse.metadata["input_sha256"] == digest
    assert built.completeness in {"complete", "partial", "truncated", "none"}
    assert list(scratch.iterdir()) == []


def test_attribute_spans_and_parent_derived_metadata_survive_the_guest_round_trip(
    runtime: tuple[Path, Path],
) -> None:
    root, scratch = _install(runtime)
    source = b"#[derive(Clone)]\nstruct Sample;\n"
    result, nonce = _parse(root, source, sequence=2)
    assert result.clean
    decoded = decode_frames(result.stdout, nonce=nonce, input_length=len(source))
    _assert_frame_invariants(decoded, len(source))
    assert decoded.items[0].attributes == ((0, len(b"#[derive(Clone)]")),)
    built = build_file_observations(
        "src/lib.rs", source, decoded, input_sha256=hashlib.sha256(source).hexdigest(),
        build_script_name=False,
    )
    assert any(
        observation.kind == "rust.item" and observation.metadata["attributes"]["derive"]
        for observation in built.observations
    )
    assert built.completeness == "complete"
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize("source", [b"\xff\n", b"struct Missing {\n"])
def test_non_utf8_and_incomplete_sources_keep_bounded_spans_and_completeness(
    runtime: tuple[Path, Path], source: bytes,
) -> None:
    root, scratch = _install(runtime)
    result, nonce = _parse(root, source, sequence=3)
    assert result.clean
    decoded = decode_frames(result.stdout, nonce=nonce, input_length=len(source))
    _assert_frame_invariants(decoded, len(source))
    built = build_file_observations(
        "src/lib.rs", source, decoded, input_sha256=hashlib.sha256(source).hexdigest(),
        build_script_name=False,
    )
    assert built.outcome == "parse_rejected"
    assert built.completeness == "none"
    assert list(scratch.iterdir()) == []


def test_malformed_input_nonzero_timeout_and_incomplete_framing_are_not_success(
    runtime: tuple[Path, Path],
) -> None:
    root, scratch = _install(runtime)
    sealed = _tree(root)
    source = b"pub struct Stable;\n"
    digest = hashlib.sha256(source).hexdigest()
    nonce = invocation_nonce(RUN_NONCE, 4, digest)
    request = encode_request(source, nonce)
    header, body = request.split(b"\n", 1)
    malformed = (
        request + b"x",
        request[:-1],
        header.replace(b'"v":1', b'"v":2') + b"\n" + body,
        header.replace(digest.encode("ascii"), b"0" * 64) + b"\n" + body,
    )
    for bad in malformed:
        result = run_bounded(
            [*PYTHON, "-X", "utf8", str(root / "helper" / "parse_helper.py")],
            stdin=bad, stdout_limit=4 * 1_048_576, deadline=30,
        )
        assert result.returncode == 3 and result.stdout == b"" and result.settled
        assert _tree(root) == sealed
        assert list(scratch.iterdir()) == []

    aborted, _ = _parse(root, b"//@fake:abort\n", sequence=5)
    assert aborted.returncode not in (0, None) and aborted.stdout == b"" and aborted.settled
    stalled, _ = _parse(root, b"//@fake:sleep\n", sequence=6, deadline=1.0)
    assert stalled.events == ("time_bound",) and stalled.settled

    noisy, noisy_nonce = _parse(root, b"//@fake:noise\npub struct A;\n", sequence=7)
    assert noisy.clean
    with pytest.raises(ProtocolViolation) as raised:
        decode_frames(noisy.stdout, nonce=noisy_nonce, input_length=len(b"//@fake:noise\npub struct A;\n"))
    assert raised.value.code == "invalid_frame"

    good, good_nonce = _parse(root, source, sequence=8)
    assert good.clean
    with pytest.raises(ProtocolViolation) as raised:
        decode_frames(good.stdout[:-1], nonce=good_nonce, input_length=len(source))
    assert raised.value.code == "output_shape"
    assert list(scratch.iterdir()) == []
