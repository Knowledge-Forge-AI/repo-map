"""Boundary tests for request-bound controller admission publication."""

import hashlib
import io
import json
import tarfile

import pytest

from retrieval_semantic_bridge_admission import (
    ADMISSION_MAX_BYTES,
    CONTROLLER_ADMISSION_NAME,
    CONTROLLER_ADMISSION_READY_NAME,
    REMOTE_ADMISSION_SOURCE,
    admission_publish_argv,
    encode_admission_marker,
    encode_admission_tar,
)
from retrieval_semantic_bridge_transport import BridgeTransportError

NONCE = "a" * 64
ATTEMPT = "attempt-1"
REQUEST_SHA = "sha256:" + hashlib.sha256(b"request").hexdigest()
ADMISSION = b'{"decision":"approved"}'


def test_marker_and_tar_bind_exact_admission_payload() -> None:
    marker = encode_admission_marker(
        ADMISSION,
        nonce=NONCE,
        attempt_id=ATTEMPT,
        request_sha256=REQUEST_SHA,
    )
    document = json.loads(marker)
    assert document == {
        "admission_bytes": len(ADMISSION),
        "admission_sha256": "sha256:" + hashlib.sha256(ADMISSION).hexdigest(),
        "attempt_id": ATTEMPT,
        "nonce": NONCE,
        "request_sha256": REQUEST_SHA,
        "schema": "cloe-w5-controller-admission-ready-v1",
    }
    output = encode_admission_tar(ADMISSION, marker)
    with tarfile.open(fileobj=io.BytesIO(output), mode="r:") as archive:
        members = archive.getmembers()
        assert [member.name for member in members] == [
            CONTROLLER_ADMISSION_NAME,
            CONTROLLER_ADMISSION_READY_NAME,
        ]
        admission_file = archive.extractfile(members[0])
        marker_file = archive.extractfile(members[1])
        assert admission_file is not None and admission_file.read() == ADMISSION
        assert marker_file is not None and marker_file.read() == marker


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"x" * (ADMISSION_MAX_BYTES + 1),
    ],
)
def test_marker_refuses_payload_bounds(raw: bytes) -> None:
    with pytest.raises(BridgeTransportError, match="admission_bounds"):
        encode_admission_marker(
            raw,
            nonce=NONCE,
            attempt_id=ATTEMPT,
            request_sha256=REQUEST_SHA,
        )


def test_tar_refuses_tampered_marker_identity() -> None:
    marker = encode_admission_marker(
        ADMISSION,
        nonce=NONCE,
        attempt_id=ATTEMPT,
        request_sha256=REQUEST_SHA,
    )
    document = json.loads(marker)
    document["admission_sha256"] = "sha256:" + "f" * 64
    tampered = json.dumps(document, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    with pytest.raises(BridgeTransportError, match="admission_marker_identity"):
        encode_admission_tar(ADMISSION, tampered)


def test_publish_argv_is_fixed_and_path_bound() -> None:
    cid = "1" * 64
    relative = f"run-1/w5-component-{NONCE}/request.json"
    argv = admission_publish_argv(cid, relative)
    assert argv == (
        "docker",
        "exec",
        "-i",
        cid,
        "/usr/local/bin/python3",
        "-I",
        "-B",
        "-c",
        REMOTE_ADMISSION_SOURCE,
        relative,
    )
    with pytest.raises(BridgeTransportError):
        admission_publish_argv("docker", relative)
    with pytest.raises(BridgeTransportError):
        admission_publish_argv(cid, "../w5-component-" + NONCE + "/request.json")
    with pytest.raises(BridgeTransportError):
        admission_publish_argv(cid, f"run-1/w5-component-{'b' * 63}/request.json")


def test_remote_publisher_is_marker_last_closed_domain_and_no_follow() -> None:
    assert 'os.open("/", flags)' in REMOTE_ADMISSION_SOURCE
    assert "os.O_NOFOLLOW" in REMOTE_ADMISSION_SOURCE
    assert 'mode="r:"' in REMOTE_ADMISSION_SOURCE
    assert 'mode="r:*"' not in REMOTE_ADMISSION_SOURCE
    assert "info.pax_headers" in REMOTE_ADMISSION_SOURCE
    assert "created_names.append(name)" in REMOTE_ADMISSION_SOURCE
    assert "for name in reversed(created_names)" in REMOTE_ADMISSION_SOURCE
    assert 'write_file(directory, "controller.admission.json"' in REMOTE_ADMISSION_SOURCE
    assert 'write_file(directory, "controller.admission.ready.json"' in REMOTE_ADMISSION_SOURCE
