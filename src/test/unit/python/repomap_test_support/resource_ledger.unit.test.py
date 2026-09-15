"""TEST-HYGIENE1 contracts for the private current-run resource ledger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repomap_test_support.resource_ledger import (
    CleanupResult,
    FinalPresence,
    ResourceKind,
    ResourceLedger,
    ResourceLedgerError,
    RetainedReason,
    RunIdentity,
)


def _identity(run_id: str = "run1") -> RunIdentity:
    return RunIdentity("repo-map_dev", "TEST-HYGIENE1", run_id)


def _ledger(tmp_path: Path) -> ResourceLedger:
    return ResourceLedger.create(tmp_path / "ledger.json", _identity())


def _observe_no_foreign_mutation(ledger: ResourceLedger) -> None:
    ledger.set_fact("pre_existing_objects_mutated", False)
    ledger.set_fact("foreign_scratch_runs_mutated", False)


def test_valid_resource_registration_is_private_and_persisted(tmp_path):
    ledger = _ledger(tmp_path)

    record = ledger.register(
        ResourceKind.PROCESS,
        "opaque-process-1",
        creation_owner="unit-fixture",
        created_before_run=False,
        creation_observed=True,
        cleanup_required=True,
    )

    assert record.identity == "opaque-process-1"
    payload = json.loads((tmp_path / "ledger.json").read_text())
    assert payload["schema"] == "repomap-test-resource-ledger-v2"
    assert payload["identity"] == {
        "phase": "TEST-HYGIENE1",
        "project": "repo-map_dev",
        "run_id": "run1",
    }
    assert payload["resources"][0]["identity"] == "opaque-process-1"
    assert (tmp_path / "ledger.json").stat().st_mode & 0o777 == 0o600


def test_duplicate_identity_conflict_is_rejected(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.register(
        ResourceKind.DOCKER_CONTAINER,
        "container-1",
        creation_owner="owner-a",
        created_before_run=False,
        creation_observed=True,
        cleanup_required=True,
    )

    with pytest.raises(ResourceLedgerError, match="conflicting resource identity"):
        ledger.register(
            ResourceKind.DOCKER_CONTAINER,
            "container-1",
            creation_owner="owner-b",
            created_before_run=False,
            creation_observed=True,
            cleanup_required=True,
        )


def test_identical_duplicate_registration_is_idempotent(tmp_path):
    ledger = _ledger(tmp_path)
    def register_port():
        return ledger.register(
            ResourceKind.TCP_PORT, "port-token", creation_owner="owner-a",
            created_before_run=False, creation_observed=True, cleanup_required=True,
        )

    first = register_port()
    second = register_port()

    assert first == second
    assert len(ledger.records) == 1


def test_open_refuses_foreign_run(tmp_path):
    ledger = _ledger(tmp_path)

    with pytest.raises(ResourceLedgerError, match="another run"):
        ResourceLedger.open(ledger.path, _identity("run2"))


def test_open_refuses_malformed_ledger(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("not json")
    path.chmod(0o600)

    with pytest.raises(ResourceLedgerError, match="valid JSON"):
        ResourceLedger.open(path, _identity())


def test_retained_and_transient_classification_is_closed(tmp_path):
    ledger = _ledger(tmp_path)
    retained = ledger.register(
        ResourceKind.SCRATCH_EVIDENCE_GROUP,
        "evidence-1",
        creation_owner="runner",
        created_before_run=False,
        creation_observed=True,
        cleanup_required=False,
        retained=True,
        retained_reason=RetainedReason.DIAGNOSTIC_EVIDENCE,
        size_bytes=42,
        inode_count=2,
    )

    assert retained.retained_reason is RetainedReason.DIAGNOSTIC_EVIDENCE
    with pytest.raises(ResourceLedgerError, match="retained reason"):
        ledger.register(
            ResourceKind.SCRATCH_FILE,
            "bad-retention",
            creation_owner="runner",
            created_before_run=False,
            creation_observed=True,
            cleanup_required=False,
            retained=True,
            retained_reason="because I said so",
        )


def test_cleanup_success_requires_attempt_result_and_final_absence(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.register(
        ResourceKind.UNIX_SOCKET,
        "socket-1",
        creation_owner="fixture",
        created_before_run=False,
        creation_observed=True,
        cleanup_required=True,
    )

    ledger.mark_cleanup_attempted(ResourceKind.UNIX_SOCKET, "socket-1")
    ledger.mark_cleanup_result(
        ResourceKind.UNIX_SOCKET, "socket-1", CleanupResult.REMOVED
    )
    ledger.mark_final_presence(
        ResourceKind.UNIX_SOCKET, "socket-1", FinalPresence.ABSENT
    )
    _observe_no_foreign_mutation(ledger)

    ledger.assert_current_run_teardown()


def test_teardown_refuses_unobserved_mutation_facts(tmp_path):
    ledger = _ledger(tmp_path)

    ledger.assert_current_run_teardown()
    with pytest.raises(ResourceLedgerError, match="mutation facts are unobserved"):
        ledger.assert_host_restoration()


def test_non_scratch_resource_cannot_be_retained(tmp_path):
    ledger = _ledger(tmp_path)

    with pytest.raises(ResourceLedgerError, match="only scratch evidence"):
        ledger.register(
            ResourceKind.DOCKER_IMAGE,
            "image-1",
            creation_owner="fixture",
            created_before_run=False,
            creation_observed=True,
            cleanup_required=False,
            retained=True,
            retained_reason=RetainedReason.DIAGNOSTIC_EVIDENCE,
        )


def test_cleanup_failure_is_preserved_and_fails_teardown(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.register(
        ResourceKind.DOCKER_VOLUME,
        "volume-1",
        creation_owner="fixture",
        created_before_run=False,
        creation_observed=True,
        cleanup_required=True,
    )
    ledger.mark_cleanup_attempted(ResourceKind.DOCKER_VOLUME, "volume-1")
    ledger.mark_cleanup_result(
        ResourceKind.DOCKER_VOLUME, "volume-1", CleanupResult.FAILED
    )
    ledger.mark_final_presence(
        ResourceKind.DOCKER_VOLUME, "volume-1", FinalPresence.PRESENT
    )

    with pytest.raises(ResourceLedgerError, match="teardown is incomplete"):
        ledger.assert_current_run_teardown()
    assert ledger.get(ResourceKind.DOCKER_VOLUME, "volume-1").cleanup_result is (
        CleanupResult.FAILED
    )


def test_unobserved_creation_cannot_claim_current_run_cleanup(tmp_path):
    ledger = _ledger(tmp_path)

    with pytest.raises(ResourceLedgerError, match="creation must be observed"):
        ledger.register(
            ResourceKind.DOCKER_IMAGE,
            "image-1",
            creation_owner="fixture",
            created_before_run=False,
            creation_observed=False,
            cleanup_required=True,
        )


def test_pre_existing_resource_cannot_require_cleanup(tmp_path):
    ledger = _ledger(tmp_path)

    with pytest.raises(ResourceLedgerError, match="pre-existing"):
        ledger.register(
            ResourceKind.DOCKER_CONTAINER,
            "old-container",
            creation_owner="baseline",
            created_before_run=True,
            creation_observed=True,
            cleanup_required=True,
        )


def test_public_projection_contains_counts_not_private_identities(tmp_path):
    ledger = _ledger(tmp_path)
    private_path = "/private/operator/path/resource.sock"
    ledger.register(
        ResourceKind.UNIX_SOCKET,
        private_path,
        creation_owner="fixture",
        created_before_run=False,
        creation_observed=True,
        cleanup_required=True,
    )
    ledger.mark_cleanup_attempted(ResourceKind.UNIX_SOCKET, private_path)
    ledger.mark_cleanup_result(
        ResourceKind.UNIX_SOCKET, private_path, CleanupResult.REMOVED
    )
    ledger.mark_final_presence(
        ResourceKind.UNIX_SOCKET, private_path, FinalPresence.ABSENT
    )

    projection = ledger.public_projection()
    rendered = json.dumps(projection, sort_keys=True)

    assert projection["phase_sockets_created"] == 1
    assert projection["phase_sockets_remaining"] == 0
    assert private_path not in rendered
    assert "identity" not in rendered


def test_fabricated_zero_delta_cleanup_is_rejected(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.register(
        ResourceKind.DOCKER_NETWORK,
        "network-1",
        creation_owner="fixture",
        created_before_run=False,
        creation_observed=True,
        cleanup_required=True,
    )

    with pytest.raises(ResourceLedgerError, match="cleanup was not attempted"):
        ledger.mark_cleanup_result(
            ResourceKind.DOCKER_NETWORK, "network-1", CleanupResult.REMOVED
        )
    with pytest.raises(ResourceLedgerError, match="terminal cleanup result"):
        ledger.mark_final_presence(
            ResourceKind.DOCKER_NETWORK, "network-1", FinalPresence.ABSENT
        )


@pytest.mark.parametrize(
    "kind",
    [
        ResourceKind.SCRATCH_DIRECTORY,
        ResourceKind.SCRATCH_FILE,
        ResourceKind.SCRATCH_EVIDENCE_GROUP,
        ResourceKind.PROCESS,
        ResourceKind.UNIX_SOCKET,
        ResourceKind.TCP_PORT,
        ResourceKind.POSTGRES_CLUSTER,
        ResourceKind.DOCKER_CONTAINER,
        ResourceKind.DOCKER_IMAGE,
        ResourceKind.DOCKER_TAG,
        ResourceKind.DOCKER_NETWORK,
        ResourceKind.DOCKER_VOLUME,
        ResourceKind.BUILDX_BUILDER,
        ResourceKind.BUILDKIT_STATE_VOLUME,
        ResourceKind.BUILD_HISTORY_RECORD,
    ],
)
def test_required_resource_kind_is_supported(tmp_path, kind):
    ledger = _ledger(tmp_path)
    record = ledger.register(
        kind,
        f"opaque-{kind.value}",
        creation_owner="fixture",
        created_before_run=False,
        creation_observed=True,
        cleanup_required=True,
    )

    assert record.kind is kind
