"""Boundary contracts for the inert W5 component exchange."""

import hashlib
import io
import json
import struct
import tarfile
import zipfile

import pytest

from retrieval_semantic_bridge_transport import (
    BridgeRefusal,
    BridgeTransportError,
    ReadyEvent,
    RESPONSE_MEMBERS,
    encode_response_bundle,
    encode_response_tar,
    decode_response_bundle,
    decode_response_tar,
    parse_readiness_line,
    read_response_files,
    reply_copy_argv,
    read_request_tar,
    request_copy_argv,
)
import retrieval_semantic_bridge_transport as transport
from retrieval_semantic_bridge_remote_io import (
    REMOTE_REQUEST_SOURCE,
    REMOTE_RESPONSE_SOURCE,
    reply_exec_argv,
    request_exec_argv,
)
from retrieval_semantic_bridge_transport_io import write_request_file


NONCE = "a" * 64
ATTEMPT = "attempt-1"
REQUEST = b'{"records":[]}'
REQUEST_SHA = "sha256:" + hashlib.sha256(REQUEST).hexdigest()


def _ready(**changes):
    document = {
        "schema": "cloe-w5-component-ready-v1",
        "nonce": NONCE,
        "attempt_id": ATTEMPT,
        "request_relative_path": f"run-1/w5-component-{NONCE}/request.json",
        "request_sha256": REQUEST_SHA,
        "request_bytes": len(REQUEST),
    }
    document.update(changes)
    return parse_readiness_line("CLOE_W5_COMPONENT_READY " + json.dumps(document))


def _tar(members, mode="w"):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode=mode) as archive:
        for name, content, kind in members:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o600
            if kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "request.json"
                info.size = 0
            archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


def _declared_tar(size):
    output = bytearray(_tar([("request.json", REQUEST, "regular")]))
    header = output[:512]
    header[124:136] = f"{size:o}".encode().ljust(12, b"\0")
    header[148:156] = b"        "
    checksum = sum(header)
    header[148:156] = f"{checksum:06o}\0 ".encode()
    output[:512] = header
    return bytes(output)


def _source_archive(name="sources/example.py", content=b"pass\n"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, content)
    return output.getvalue()


def _response_files(**changes):
    files = {name: b"{}" for name in RESPONSE_MEMBERS}
    files["sources.zip"] = _source_archive()
    files["terminal.json"] = b'{"observation_count":0,"status":"completed"}'
    files.update(changes)
    return files


def _response_marker(response, nonce=NONCE):
    return json.dumps(
        {
            "nonce": nonce,
            "response_sha256": "sha256:" + hashlib.sha256(response).hexdigest(),
            "response_bytes": len(response),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode() + b"\n"


def test_unrelated_log_lines_are_not_protocol_input_and_valid_readiness_binds_path():
    assert parse_readiness_line("worker: still running") is None
    event = _ready()
    assert isinstance(event, ReadyEvent)
    assert event.request_path == f"/sandbox-scratch/test-scratch/run-1/w5-component-{NONCE}/request.json"


@pytest.mark.parametrize(
    "changes",
    [
        ({"nonce": "A" * 64},),
        ({"request_relative_path": "../request.json"},),
        ({"request_relative_path": f"w5-component-{NONCE}\\request.json"},),
        ({"request_bytes": 0},),
        ({"request_sha256": "sha256:" + "g" * 64},),
        ({"attempt_id": "x\n"},),
    ],
)
def test_matching_readiness_is_refused_before_any_path_or_payload_access(changes):
    assert isinstance(_ready(**changes[0]), BridgeRefusal)


def test_readiness_rejects_duplicate_keys_and_constants():
    duplicate = (
        "CLOE_W5_COMPONENT_READY {\"schema\":\"cloe-w5-component-ready-v1\","
        f"\"nonce\":\"{NONCE}\",\"nonce\":\"{NONCE}\"}}"
    )
    assert isinstance(parse_readiness_line(duplicate), BridgeRefusal)
    assert isinstance(_ready(attempt_id=float("nan")), BridgeRefusal)


def test_request_tar_requires_one_regular_member_and_exact_identity():
    event = _ready()
    assert isinstance(event, ReadyEvent)
    valid = _tar([("request.json", REQUEST, "regular")])
    assert read_request_tar(valid, event) == REQUEST
    assert isinstance(read_request_tar(_tar([("request.json", b"other", "regular")]), event), BridgeRefusal)
    assert isinstance(read_request_tar(_tar([("request.json", REQUEST, "regular"), ("extra", b"x", "regular")]), event), BridgeRefusal)
    assert isinstance(read_request_tar(_tar([("request.json", b"", "symlink")]), event), BridgeRefusal)
    assert isinstance(read_request_tar(valid[:512], event), BridgeRefusal)
    assert isinstance(read_request_tar(_declared_tar(len(REQUEST) + 1), event), BridgeRefusal)


def test_request_tar_rejects_a_valid_compressed_archive():
    event = _ready()
    compressed = _tar([("request.json", REQUEST, "regular")], mode="w:gz")
    assert isinstance(read_request_tar(compressed, event), BridgeRefusal)


def test_request_tar_rejects_pax_metadata_before_member_payload():
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        info = tarfile.TarInfo("request.json")
        info.size = len(REQUEST)
        info.mode = 0o600
        info.pax_headers = {"comment": "metadata"}
        archive.addfile(info, io.BytesIO(REQUEST))
    event = _ready()
    assert isinstance(read_request_tar(output.getvalue(), event), BridgeRefusal)


def test_response_bundle_round_trip_and_terminal_observation_refusal():
    bundle = encode_response_bundle(_response_files())
    decoded = decode_response_bundle(bundle)
    assert isinstance(decoded, dict)
    assert set(decoded) == RESPONSE_MEMBERS
    malformed = dict(_response_files())
    malformed["terminal.json"] = b'{"observation_count":1}'
    with pytest.raises(BridgeTransportError, match="terminal_observations"):
        encode_response_bundle(malformed)
    assert isinstance(decode_response_bundle(bundle[:-20]), BridgeRefusal)


def test_response_bundle_rejects_declared_uncompressed_bomb_before_read():
    bundle = bytearray(encode_response_bundle(_response_files()))
    marker = b"PK\x01\x02"
    offset = bundle.index(marker)
    bundle[offset + 24 : offset + 28] = struct.pack("<I", 32 * 1024 * 1024 + 1)
    assert isinstance(decode_response_bundle(bytes(bundle)), BridgeRefusal)


def test_response_bundle_rejects_unsafe_source_archive_observation_member():
    malformed = dict(_response_files())
    malformed["sources.zip"] = _source_archive("inputs/observations.jsonl")
    with pytest.raises(BridgeTransportError, match="source_archive_member"):
        encode_response_bundle(malformed)


def test_response_tar_binds_nonce_and_hash():
    bundle = encode_response_bundle(_response_files())
    tar = encode_response_tar(bundle, NONCE)
    decoded = decode_response_tar(tar, expected_nonce=NONCE)
    assert isinstance(decoded, dict)
    assert isinstance(decode_response_tar(tar, expected_nonce="b" * 64), BridgeRefusal)
    tampered_zip = bytes([bundle[0] ^ 1]) + bundle[1:]
    tampered = tar.replace(bundle, tampered_zip, 1)
    assert isinstance(decode_response_tar(tampered, expected_nonce=NONCE), BridgeRefusal)


def test_copy_argv_is_fixed_to_validated_container_and_exchange_root():
    cid = "1" * 64
    relative = f"run-1/w5-component-{NONCE}/request.json"
    argv = request_copy_argv(cid, relative)
    assert argv == ("docker", "exec", cid, "/usr/local/bin/python3", "-I", "-B", "-c", REMOTE_REQUEST_SOURCE, relative)
    assert reply_copy_argv(cid, relative) == (
        "docker", "exec", "-i", cid, "/usr/local/bin/python3", "-I", "-B", "-c", REMOTE_RESPONSE_SOURCE, relative
    )
    assert request_exec_argv(cid, relative) == argv
    assert reply_exec_argv(cid, relative) == reply_copy_argv(cid, relative)
    assert "O_NOFOLLOW" in REMOTE_REQUEST_SOURCE
    assert "O_EXCL" in REMOTE_RESPONSE_SOURCE
    with pytest.raises(BridgeTransportError):
        request_copy_argv("docker", relative)
    with pytest.raises(BridgeTransportError):
        request_copy_argv(cid, "../../etc/passwd")
    with pytest.raises(BridgeTransportError):
        reply_copy_argv(cid, "run-1/w5-component-invalid/request.json")
    too_deep = "/".join(["run"] * 15 + [f"w5-component-{NONCE}", "request.json"])
    with pytest.raises(BridgeTransportError):
        request_copy_argv(cid, too_deep)


def test_remote_helpers_pin_no_follow_root_tar_and_exact_cleanup_contracts():
    assert 'os.open("/", flags)' in REMOTE_REQUEST_SOURCE
    assert 'os.open("/", flags)' in REMOTE_RESPONSE_SOURCE
    assert "os.O_NOFOLLOW" in REMOTE_RESPONSE_SOURCE
    assert 'mode="r:"' in REMOTE_RESPONSE_SOURCE
    assert 'mode="r:*"' not in REMOTE_RESPONSE_SOURCE
    assert "info.pax_headers" in REMOTE_RESPONSE_SOURCE
    assert "created_names.append(name)" in REMOTE_RESPONSE_SOURCE
    assert "for name in reversed(created_names)" in REMOTE_RESPONSE_SOURCE


def test_file_io_is_bounded_and_no_follow(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "SANDBOX_SCRATCH_ROOT", str(tmp_path))
    import retrieval_semantic_bridge_transport_io as transport_io

    monkeypatch.setattr(transport_io, "SANDBOX_SCRATCH_ROOT", str(tmp_path))
    exchange = tmp_path / "run-1" / f"w5-component-{NONCE}"
    exchange.mkdir(parents=True)
    event = _ready()
    assert isinstance(event, ReadyEvent)
    assert write_request_file(exchange / "request.json", REQUEST, event) is None
    assert (exchange / "request.json").read_bytes() == REQUEST
    bundle = encode_response_bundle(_response_files())
    assert read_response_files(exchange, NONCE) is None
    (exchange / "response.zip").write_bytes(bundle)
    assert read_response_files(exchange, NONCE) is None
    marker = _response_marker(bundle)
    (exchange / "response.ready.json").write_bytes(marker[:-1])
    assert read_response_files(exchange, NONCE) is None
    (exchange / "response.ready.json").write_bytes(marker)
    result = read_response_files(exchange, NONCE)
    assert isinstance(result, dict)
    assert set(result) == RESPONSE_MEMBERS


def test_response_files_refuse_foreign_nonce_hash_and_missing_data(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "SANDBOX_SCRATCH_ROOT", str(tmp_path))
    import retrieval_semantic_bridge_transport_io as transport_io

    monkeypatch.setattr(transport_io, "SANDBOX_SCRATCH_ROOT", str(tmp_path))
    exchange = tmp_path / "run-1" / f"w5-component-{NONCE}"
    exchange.mkdir(parents=True)
    bundle = encode_response_bundle(_response_files())
    marker = _response_marker(bundle)
    (exchange / "response.ready.json").write_bytes(marker)
    assert isinstance(read_response_files(exchange, NONCE), BridgeRefusal)
    (exchange / "response.zip").write_bytes(bundle)
    bad = json.loads(marker)
    bad["response_sha256"] = "sha256:" + "f" * 64
    (exchange / "response.ready.json").write_bytes(
        json.dumps(bad, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    assert isinstance(read_response_files(exchange, NONCE), BridgeRefusal)
    foreign = tmp_path / "run-1" / f"w5-component-{'b' * 64}"
    foreign.mkdir(parents=True)
    assert isinstance(read_response_files(foreign, NONCE), BridgeRefusal)
