"""Derived Docker operation accounting over an observed closed population."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repomap_test_support.resource_docker_operations import (
    DERIVED_OPERATION_FIELDS,
    DockerAuthorityClass,
    DockerOperationJournal,
    DockerOperationJournalError,
    DockerOperationKind,
    DockerOperationResult,
    JOURNAL_FILENAME,
    JOURNAL_SCHEMA,
)


def journal(tmp_path, *, run_id: str = "run-1") -> DockerOperationJournal:
    return DockerOperationJournal(tmp_path / JOURNAL_FILENAME, run_id=run_id)


def managed_build(subject: DockerOperationJournal, *, request: str = "tag") -> str:
    return subject.begin(
        kind=DockerOperationKind.MANAGED_RUNTIME_LOGICAL_BUILD,
        authority=DockerAuthorityClass.MANAGED_TEST_RUNTIME,
        owner="TestImageManager",
        mechanism="managed-runtime-materialization",
        request=request,
    )


def managed_pull(subject: DockerOperationJournal, *, request: str = "ref") -> str:
    return subject.begin(
        kind=DockerOperationKind.DOCKER_PULL,
        authority=DockerAuthorityClass.MANAGED_EXTERNAL_BASE,
        owner="TestImageManager",
        mechanism="docker-sdk-high",
        request=request,
    )


def test_obs1_recover1_constant_zero_accounting_would_pass_an_executed_build(
    tmp_path,
) -> None:
    """Red-first: the predecessor's literal projection cannot see this event."""
    subject = journal(tmp_path)
    event_id = managed_build(subject)
    subject.complete(
        event_id,
        result=DockerOperationResult.SUCCEEDED,
        image_ids=("sha256:final",),
    )

    predecessor_projection = {field: 0 for field in DERIVED_OPERATION_FIELDS}
    derived = subject.derive_counters()

    assert predecessor_projection["managed_test_runtime_image_build_count"] == 0
    assert derived["managed_test_runtime_image_build_count"] == 1
    assert derived != predecessor_projection


def test_obs1_recover1_reuse_derives_zero_from_an_observed_empty_population(
    tmp_path,
) -> None:
    subject = journal(tmp_path)

    evidence = subject.derivation_evidence()

    assert evidence["event_count"] == 0
    assert evidence["materialization_count"] == 0
    assert evidence["derived"] == {field: 0 for field in DERIVED_OPERATION_FIELDS}


def test_obs1_recover1_local_base_reuse_derives_zero_pulls(tmp_path) -> None:
    subject = journal(tmp_path)
    subject.complete(
        managed_build(subject), result=DockerOperationResult.SUCCEEDED
    )

    assert subject.derive_counters()["managed_external_base_pull_count"] == 0


def test_obs1_recover1_exact_digest_managed_base_pull_is_one_event(tmp_path) -> None:
    subject = journal(tmp_path)
    event_id = managed_pull(subject, request="repo@sha256:abc")
    subject.complete(
        event_id, result=DockerOperationResult.SUCCEEDED, image_ids=("sha256:base",)
    )

    counters = subject.derive_counters()

    assert counters["managed_external_base_pull_count"] == 1
    assert counters["unmanaged_pull_count"] == 0
    assert len(subject.events()) == 1


def test_obs1_recover1_refused_operation_is_counted_without_execution(
    tmp_path,
) -> None:
    subject = journal(tmp_path)
    subject.refuse(
        kind=DockerOperationKind.DOCKER_BUILD,
        owner="ImageCollection.build",
        mechanism="docker-sdk-high",
        request="path=/tmp/ctx",
        failure_category="unauthorized_canonical_operation",
    )

    (event,) = subject.events()

    assert event.result is DockerOperationResult.REFUSED
    assert event.started is False
    assert event.executed is False
    assert subject.derive_counters()["unmanaged_build_count"] == 1


def test_obs1_recover1_refused_attempt_cannot_project_green(tmp_path) -> None:
    subject = journal(tmp_path)
    subject.refuse(
        kind=DockerOperationKind.DOCKER_PULL,
        owner="subprocess.Popen",
        mechanism="container-cli",
        request="docker pull busybox",
        failure_category="unauthorized_canonical_operation",
    )

    counters = subject.derive_counters()

    assert counters["unmanaged_pull_count"] == 1
    assert any(value for value in counters.values())


def test_obs1_recover1_deleted_output_remains_counted(tmp_path) -> None:
    subject = journal(tmp_path)
    event_id = managed_build(subject)
    subject.complete(
        event_id,
        result=DockerOperationResult.SUCCEEDED,
        image_ids=("sha256:final",),
        cleanup_disposition="removed",
    )

    (event,) = subject.events()

    assert event.image_ids == ("sha256:final",)
    assert event.cleanup_disposition == "removed"
    assert subject.derive_counters()["managed_test_runtime_image_build_count"] == 1


def test_obs1_recover1_failed_operation_remains_durably_represented(tmp_path) -> None:
    subject = journal(tmp_path)
    event_id = managed_build(subject)
    subject.complete(
        event_id,
        result=DockerOperationResult.FAILED,
        failure_category="authorized_operation_raised",
    )

    (event,) = subject.events()

    assert event.result is DockerOperationResult.FAILED
    assert event.executed is True
    assert subject.derive_counters()["managed_test_runtime_image_build_count"] == 1


def test_obs1_recover1_interrupted_operation_remains_counted(tmp_path) -> None:
    subject = journal(tmp_path)
    managed_build(subject)

    (event,) = subject.events()

    assert event.result is DockerOperationResult.STARTED
    assert event.completed is False
    assert subject.derive_counters()["managed_test_runtime_image_build_count"] == 1


def test_obs1_recover1_later_reader_cannot_erase_a_recorded_event(tmp_path) -> None:
    subject = journal(tmp_path)
    event_id = managed_build(subject)
    subject.complete(event_id, result=DockerOperationResult.SUCCEEDED)

    reader = journal(tmp_path)

    assert len(reader.events()) == 1
    assert reader.derive_counters()["managed_test_runtime_image_build_count"] == 1


def test_obs1_recover1_foreign_run_records_are_refused(tmp_path) -> None:
    subject = journal(tmp_path)
    managed_build(subject)
    with open(tmp_path / JOURNAL_FILENAME, "a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "schema": JOURNAL_SCHEMA,
                    "run_id": "other-run",
                    "ordinal": 99,
                    "event_id": "other-run:000001",
                }
            )
            + "\n"
        )

    with pytest.raises(DockerOperationJournalError, match="run identity differs"):
        subject.events()


def test_obs1_recover1_duplicate_requests_are_counted_deterministically(
    tmp_path,
) -> None:
    subject = journal(tmp_path)
    for _ in range(3):
        subject.refuse(
            kind=DockerOperationKind.DOCKER_BUILD,
            owner="BuildApiMixin.build",
            mechanism="docker-sdk-low",
            request="path=/tmp/ctx",
            failure_category="unauthorized_canonical_operation",
        )

    assert subject.derive_counters()["unmanaged_build_count"] == 3
    assert [event.ordinal for event in subject.events()] == [1, 2, 3]


def test_obs1_recover1_product_build_count_is_derived_from_authority_class(
    tmp_path,
) -> None:
    subject = journal(tmp_path)
    subject.complete(
        subject.begin(
            kind=DockerOperationKind.DOCKER_BUILD,
            authority=DockerAuthorityClass.PRODUCT_OR_BUILD_PROFILE,
            owner="TestImageManager.build_ephemeral_image",
            mechanism="docker-sdk-high",
            request="fileobj=<dockerfile>",
        ),
        result=DockerOperationResult.SUCCEEDED,
    )

    counters = subject.derive_counters()

    assert counters["product_or_build_profile_build_count"] == 1
    assert counters["managed_test_runtime_image_build_count"] == 0
    assert counters["unmanaged_build_count"] == 0


def test_obs1_recover1_intermediate_counters_are_derived_from_observed_ids(
    tmp_path,
) -> None:
    subject = journal(tmp_path)
    event_id = managed_build(subject)
    subject.record_materialization(
        event_id=event_id,
        final_image_id="sha256:final",
        intermediate_created_ids=("sha256:a", "sha256:b"),
        intermediate_removed_ids=("sha256:a",),
    )
    subject.complete(event_id, result=DockerOperationResult.SUCCEEDED)

    counters = subject.derive_counters()
    (observation,) = subject.materializations()

    assert counters["managed_runtime_build_intermediate_created_count"] == 2
    assert counters["managed_runtime_build_intermediate_removed_count"] == 1
    assert counters["managed_runtime_build_intermediate_residue_count"] == 1
    assert observation.intermediate_terminal_ids == ("sha256:b",)


def test_obs1_recover1_zero_intermediates_are_an_observed_empty_delta(
    tmp_path,
) -> None:
    subject = journal(tmp_path)
    event_id = managed_build(subject)
    subject.record_materialization(
        event_id=event_id,
        final_image_id="sha256:final",
        intermediate_created_ids=(),
        intermediate_removed_ids=(),
    )
    subject.complete(event_id, result=DockerOperationResult.SUCCEEDED)

    evidence = subject.derivation_evidence()

    assert evidence["materialization_count"] == 1
    assert evidence["materializations"][0]["final_image_id"] == "sha256:final"
    assert evidence["derived"]["managed_runtime_build_intermediate_created_count"] == 0


def test_obs1_recover1_derivation_evidence_explains_every_field(tmp_path) -> None:
    subject = journal(tmp_path)

    evidence = subject.derivation_evidence()

    assert evidence["schema"] == JOURNAL_SCHEMA
    assert set(evidence["derived"]) == set(DERIVED_OPERATION_FIELDS)
    assert evidence["journal_path"].endswith(JOURNAL_FILENAME)


def test_obs1_recover1_journal_file_is_private_and_append_only(tmp_path) -> None:
    subject = journal(tmp_path)
    managed_build(subject)
    first = (tmp_path / JOURNAL_FILENAME).read_text(encoding="utf-8")
    managed_pull(subject)
    second = (tmp_path / JOURNAL_FILENAME).read_text(encoding="utf-8")

    assert second.startswith(first)
    assert (tmp_path / JOURNAL_FILENAME).stat().st_mode & 0o777 == 0o600


def test_obs1_recover1_relative_journal_path_is_refused(tmp_path) -> None:
    with pytest.raises(DockerOperationJournalError):
        DockerOperationJournal(Path(JOURNAL_FILENAME), run_id="run-1")


def test_obs1_recover1_completion_result_must_be_terminal(tmp_path) -> None:
    subject = journal(tmp_path)

    with pytest.raises(DockerOperationJournalError, match="terminal"):
        subject.complete(
            managed_build(subject), result=DockerOperationResult.STARTED
        )


def test_managed_system_candidate_build_accounting(tmp_path) -> None:
    subject = journal(tmp_path)
    event_id = subject.begin(
        kind=DockerOperationKind.DOCKER_BUILD,
        authority=DockerAuthorityClass.MANAGED_SYSTEM_CANDIDATE,
        owner="SystemCandidateImageBuilder",
        mechanism="docker-candidate-build",
        request="candidate-build:tag",
    )
    subject.complete(event_id, result=DockerOperationResult.SUCCEEDED)

    derived = subject.derive_counters()
    assert derived["managed_system_candidate_image_build_count"] == 1
    assert derived["managed_test_runtime_image_build_count"] == 0
    assert derived["unmanaged_build_count"] == 0
