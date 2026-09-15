from __future__ import annotations

import json

import pytest

import scale28_runtime_identity


class _IdentityClient:
    api_version = "1.47"

    def __init__(self) -> None:
        self.closed = False

    def version(self):
        return {
            "Version": "27.5.1",
            "ApiVersion": "1.47",
            "Components": [
                {
                    "Name": "Engine",
                    "Version": "27.5.1",
                    "Details": {
                        "ApiVersion": "1.47",
                        "GitCommit": "public-commit",
                    },
                }
            ],
        }

    def info(self):
        return {
            "OperatingSystem": "Public Engine",
            "OSType": "linux",
            "Architecture": "aarch64",
            "CgroupVersion": "2",
        }

    def inspect_container(self, container):
        assert container == "public-postgres"
        return {"Image": "sha256:" + "a" * 64}

    def stats(self, container, *, stream, one_shot):
        assert (container, stream, one_shot) == (
            "public-postgres",
            False,
            True,
        )
        return {
            "memory_stats": {
                "usage": 100,
                "stats": {"inactive_file": 20},
            }
        }

    def close(self):
        self.closed = True


def test_runtime_identity_receipt_contains_every_discriminating_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_identity = scale28_runtime_identity
    client = _IdentityClient()
    monkeypatch.setattr(
        runtime_identity,
        "_create_docker_api_client",
        lambda _runtime: (client, "unix_socket"),
    )

    identity = runtime_identity.capture_runtime_identity(
        runtime="docker",
        container_name="public-postgres",
        repomap_commit="b" * 40,
        postgresql_server_version="PostgreSQL 16.9",
    )

    assert identity is not None
    payload = identity.to_mapping()
    assert set(payload) == {
        "schema_version",
        "python_implementation",
        "python_version",
        "repomap_commit",
        "psycopg_version",
        "libpq_version",
        "postgresql_server_version",
        "psutil_version",
        "host_operating_system",
        "host_kernel",
        "docker_sdk_version",
        "docker_api_version",
        "engine_server_version",
        "engine_components",
        "engine_operating_system",
        "engine_os_type",
        "engine_architecture",
        "cgroup_version",
        "container_image_digest",
        "container_stats_field_shape",
        "transport_class",
        "operation_shape",
        "qualification_status",
    }
    assert payload["docker_api_version"] == "1.47"
    assert payload["container_stats_field_shape"] == (
        "memory_stats.usage+memory_stats.stats.inactive_file"
    )
    assert payload["operation_shape"] == "one_shot_stats_no_subprocess"
    assert payload["qualification_status"] == "unqualified"
    components = payload["engine_components"]
    assert isinstance(components, list)
    first_component = components[0]
    assert isinstance(first_component, dict)
    assert components == [
        {
            "name": "Engine",
            "version": "27.5.1",
            "detail_fields": ["ApiVersion", "GitCommit"],
            "details_digest": first_component["details_digest"],
        }
    ]
    digest = first_component["details_digest"]
    assert isinstance(digest, (str, bytes, list, dict))
    assert len(digest) == 64
    encoded = json.dumps(payload, sort_keys=True)
    for forbidden in ("username", "hostname", "endpoint", "/Users/"):
        assert forbidden not in encoded
    assert client.closed is True
    assert runtime_identity.SCALE_QUALIFICATION_STATUS == "Q2"
    assert (
        runtime_identity.runtime_identity_matches_qualification_receipt(
            identity,
            None,
        )
        is False
    )
    assert (
        runtime_identity.runtime_identity_matches_qualification_receipt(
            identity,
            {
                "phase_id": "TEST-COV5K-R2",
                "outcome": "B",
                "runtime_identity": payload,
            },
        )
        is False
    )
    mismatched = dict(payload)
    mismatched["docker_api_version"] = "mismatch"
    assert (
        runtime_identity.runtime_identity_matches_qualification_receipt(
            identity,
            {
                "phase_id": "TEST-COV5K-R2",
                "outcome": "A",
                "runtime_identity": mismatched,
            },
        )
        is False
    )
    assert runtime_identity.runtime_identity_matches_qualification_receipt(
        identity,
        {
            "phase_id": "TEST-COV5K-R2",
            "outcome": "A",
            "runtime_identity": payload,
        },
    )


def test_runtime_identity_capture_failure_is_unqualified_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_identity = scale28_runtime_identity

    class Broken(_IdentityClient):
        def info(self):
            raise runtime_identity.docker.errors.APIError("failed")

    client = Broken()
    monkeypatch.setattr(
        runtime_identity,
        "_create_docker_api_client",
        lambda _runtime: (client, "unix_socket"),
    )

    assert (
        runtime_identity.capture_runtime_identity(
            runtime="docker",
            container_name="public-postgres",
            repomap_commit="b" * 40,
            postgresql_server_version="PostgreSQL 16.9",
        )
        is None
    )
    assert client.closed is True
