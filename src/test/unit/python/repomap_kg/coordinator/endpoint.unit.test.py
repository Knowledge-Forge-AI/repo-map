import json
from pathlib import Path
from typing import Any, Mapping, cast

import pytest

from repomap_kg.coordinator.endpoint import (
    EndpointDescriptorError,
    LoopbackEndpointDescriptor,
    load_endpoint_descriptor,
    write_endpoint_descriptor,
)


def descriptor(**updates):
    values = {
        "schema_version": 1,
        "host": "127.0.0.1",
        "port": 43123,
        "instance_id": "instance-1",
        "fencing_epoch": 7,
        "auth_token": "token-1234567890",
    }
    values.update(updates)
    return LoopbackEndpointDescriptor(**cast(dict[str, Any], values))


def test_descriptor_round_trips_exact_versioned_fields(tmp_path: Path):
    path = tmp_path / "coordinator.endpoint.json"

    write_endpoint_descriptor(path, descriptor())

    loaded = load_endpoint_descriptor(path)
    assert loaded == descriptor()
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {
        "schema_version",
        "host",
        "port",
        "instance_id",
        "fencing_epoch",
        "auth_token",
    }


@pytest.mark.parametrize(
    "updates",
    [
        {"schema_version": 2},
        {"schema_version": True},
        {"host": "0.0.0.0"},
        {"host": "localhost"},
        {"port": 0},
        {"port": -1},
        {"port": 65536},
        {"port": True},
        {"port": "8080"},
        {"fencing_epoch": 0},
        {"fencing_epoch": -5},
        {"fencing_epoch": True},
        {"fencing_epoch": "7"},
        {"auth_token": ""},
        {"auth_token": "a" * 257},
        {"auth_token": 12345},
        {"instance_id": ""},
        {"instance_id": "a" * 129},
        {"instance_id": 12345},
        {"instance_id": "C:\\private\\worker"},
    ],
)
def test_descriptor_rejects_unsafe_values(updates):
    with pytest.raises(EndpointDescriptorError, match="descriptor"):
        descriptor(**updates).validate()


def test_descriptor_rejects_extra_or_missing_fields(tmp_path: Path):
    path = tmp_path / "coordinator.endpoint.json"
    path.write_text(
        json.dumps({**descriptor().__dict__, "extra": "nope"}),
        encoding="utf-8",
    )

    with pytest.raises(EndpointDescriptorError, match="descriptor"):
        load_endpoint_descriptor(path)


def test_descriptor_rotation_replaces_only_the_known_file(tmp_path: Path):
    path = tmp_path / "coordinator.endpoint.json"
    write_endpoint_descriptor(path, descriptor())
    write_endpoint_descriptor(path, descriptor(port=43124, fencing_epoch=8))

    assert load_endpoint_descriptor(path).port == 43124
    assert load_endpoint_descriptor(path).fencing_epoch == 8


def test_descriptor_rejects_symlink_without_following_it(tmp_path: Path):
    backing = tmp_path / "backing.json"
    write_endpoint_descriptor(backing, descriptor())
    path = tmp_path / "coordinator.endpoint.json"
    path.symlink_to(backing)

    with pytest.raises(EndpointDescriptorError, match="descriptor"):
        load_endpoint_descriptor(path)


def test_descriptor_can_require_the_current_instance_and_epoch(tmp_path: Path):
    path = tmp_path / "coordinator.endpoint.json"
    write_endpoint_descriptor(path, descriptor())

    assert load_endpoint_descriptor(
        path, expected_instance_id="instance-1", expected_fencing_epoch=7
    ) == descriptor()
    with pytest.raises(EndpointDescriptorError, match="stale"):
        load_endpoint_descriptor(path, expected_instance_id="instance-2")
    with pytest.raises(EndpointDescriptorError, match="stale"):
        load_endpoint_descriptor(path, expected_fencing_epoch=8)


def test_write_descriptor_requires_absolute_path():
    with pytest.raises(EndpointDescriptorError, match="path is invalid"):
        write_endpoint_descriptor(Path("relative/path.json"), descriptor())


def test_descriptor_fresh_factory():
    desc = LoopbackEndpointDescriptor.fresh(
        port=54321,
        instance_id="fresh-instance",
        fencing_epoch=3,
    )
    assert desc.port == 54321
    assert desc.instance_id == "fresh-instance"
    assert desc.fencing_epoch == 3
    assert len(desc.auth_token) >= 16


def test_descriptor_from_mapping_type_errors():
    with pytest.raises(EndpointDescriptorError, match="fields are invalid"):
        LoopbackEndpointDescriptor.from_mapping(cast(Mapping[str, object], "not-a-mapping"))


@pytest.mark.parametrize(
    "token",
    [
        " whitespace_prefix123456",
        "whitespace_suffix123456 ",
        "token\x00withnull123456",
        "short",
    ],
)
def test_descriptor_rejects_malformed_auth_tokens(token):
    with pytest.raises(EndpointDescriptorError, match="descriptor is invalid"):
        descriptor(auth_token=token).validate()


def test_load_descriptor_rejects_empty_or_bad_permission_file(tmp_path: Path):
    empty_path = tmp_path / "empty.json"
    empty_path.write_bytes(b"")
    empty_path.chmod(0o600)
    with pytest.raises(EndpointDescriptorError, match="unsafe"):
        load_endpoint_descriptor(empty_path)

    perm_path = tmp_path / "badperm.json"
    write_endpoint_descriptor(perm_path, descriptor())
    perm_path.chmod(0o644)
    with pytest.raises(EndpointDescriptorError, match="unsafe"):
        load_endpoint_descriptor(perm_path)


def test_load_descriptor_oversized_or_malformed(tmp_path: Path):
    oversized_path = tmp_path / "oversized.json"
    oversized_path.write_bytes(b"{" + b"a" * 4096 + b"}")
    oversized_path.chmod(0o600)
    with pytest.raises(EndpointDescriptorError, match="unsafe"):
        load_endpoint_descriptor(oversized_path)

    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_bytes(b"not-json-content\n")
    malformed_path.chmod(0o600)
    with pytest.raises(EndpointDescriptorError, match="invalid"):
        load_endpoint_descriptor(malformed_path)
