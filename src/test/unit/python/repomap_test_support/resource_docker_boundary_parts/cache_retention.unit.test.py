from __future__ import annotations

from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest

from repomap_test_support.resource_docker_boundary import (
    RunWideDockerBoundary,
    RunWideDockerResidueError,
)
from repomap_test_support.resource_docker_mediation import CanonicalDockerAuthority
from repomap_test_support.resource_docker_operations import (
    JOURNAL_FILENAME,
    DockerOperationJournal,
)
from repomap_test_support.resource_ledger import (
    RetainedReason,
    ResourceKind,
    ResourceLedger,
    RunIdentity,
)
from repomap_test_support.resource_run import TestResourceRun
from repomap_test_support.resource_scratch import ScratchRunOwner
from repomap_test_support.test_scratch import establish_run
from repomap_test_support.resource_test_image_base import (
    BaseImageProvenance,
    parse_immutable_image_authority,
)


class Item:
    def __init__(
        self, identity: str, labels=None, tags=(), repo_digests=(), architecture="arm64"
    ):
        self.id = identity
        self.tags = list(tags)
        self.attrs = {
            "Config": {"Labels": labels or {}},
            "Labels": labels or {},
            "RepoDigests": list(repo_digests),
            "Architecture": architecture,
        }


class Collection:
    def __init__(self, items=()):
        self.items = {item.id: item for item in items}
        self.removed: list[str] = []

    def list(self, **_kwargs):
        return list(self.items.values())

    def get(self, identity: str):
        return self.items[identity]


class Client:
    def __init__(self, *, architecture="arm64"):
        self.images = Collection((Item("sha256:baseline"),))
        self.volumes = Collection((Item("baseline-volume"),))
        self.architecture = architecture

    def info(self):
        return {"Architecture": self.architecture}


def managed_run(tmp_path):
    identity = RunIdentity("repo-map_dev", "SAFETY3", "run-1")
    ledger = ResourceLedger.create(tmp_path / "ledger.json", identity)
    return SimpleNamespace(ledger=ledger)


_INSTALLED: list[CanonicalDockerAuthority] = []


@pytest.fixture(autouse=True)
def _uninstall_authorities():
    yield
    while _INSTALLED:
        _INSTALLED.pop().uninstall()


def make_boundary(run, client) -> RunWideDockerBoundary:
    authority = CanonicalDockerAuthority(DockerOperationJournal.for_ledger(run.ledger))
    authority.install()
    _INSTALLED.append(authority)
    return RunWideDockerBoundary(run, client, authority=authority)


def _cache_labels(fingerprint: str) -> dict[str, str]:
    return {
        "org.repomap.test.managed": "true",
        "org.repomap.test.image.class": "runtime-cache",
        "org.repomap.test.image.schema": "1",
        "org.repomap.test.runtime-fingerprint": fingerprint,
        "org.repomap.test.repository": "repo-map",
    }


def _external_base_provenance(
    reference: str,
    image_id: str,
    *,
    image_architecture: str = "arm64",
    server_architecture: str = "arm64",
) -> BaseImageProvenance:
    authority = parse_immutable_image_authority(reference)
    return BaseImageProvenance(
        reference=reference,
        repository=authority.repository,
        digest=authority.digest,
        canonical_reference=authority.canonical_reference,
        optional_tag=authority.optional_tag,
        image_id=image_id,
        repo_digests=(authority.canonical_reference,),
        architecture="arm64",
        image_architecture=image_architecture,
        server_architecture=server_architecture,
        canonical_image_architecture="arm64",
        canonical_server_architecture="arm64",
        pulled=True,
    )


def test_runwide_boundary_refuses_external_base_with_deployment_tag(tmp_path) -> None:
    client = Client()
    run = managed_run(tmp_path)
    boundary = make_boundary(run, client)
    reference = "python:3.12-slim-bookworm@sha256:" + "c" * 64
    identity = "sha256:" + "f" * 64
    authority = parse_immutable_image_authority(reference)
    client.images.items[identity] = Item(
        identity,
        tags=("repomap-runtime:release-1",),
        repo_digests=(authority.canonical_reference,),
    )
    run.ledger.register(
        ResourceKind.DOCKER_IMAGE,
        identity,
        creation_owner="TestImageManager",
        created_before_run=False,
        creation_observed=True,
        cleanup_required=False,
    )
    with boundary.managed_external_base_pull(request=reference) as ticket:
        boundary.complete_operation(ticket, image_ids=(identity,))

    with pytest.raises(RuntimeError, match="external base readback failed"):
        boundary.register_managed_external_test_base(
            _external_base_provenance(reference, identity)
        )


def test_runwide_boundary_reports_current_run_ephemeral_image_residue(
    tmp_path,
) -> None:
    client = Client()
    run = managed_run(tmp_path)
    boundary = make_boundary(run, client)
    identity = "sha256:" + "c" * 64
    client.images.items[identity] = Item(
        identity,
        {
            "org.repomap.test.managed": "true",
            "org.repomap.test.image.class": "ephemeral",
            "org.repomap.test.image.schema": "1",
            "org.repomap.test.run-id": "run-1",
            "org.repomap.test.repository": "repo-map",
        },
        ("repomap-test-ephemeral:run-1-1",),
    )
    run.ledger.register(
        ResourceKind.DOCKER_IMAGE,
        identity,
        creation_owner="TestImageManager",
        created_before_run=False,
        creation_observed=True,
        cleanup_required=True,
    )

    with pytest.raises(RunWideDockerResidueError) as raised:
        boundary.verify_terminal()

    assert raised.value.projection["current_run_ephemeral_image_residue"] == 1


def test_runwide_boundary_accepts_exact_manager_recorded_cache_gc(tmp_path) -> None:
    fingerprint = "d" * 64
    stale_id = "sha256:" + "d" * 64
    client = Client()
    client.images.items[stale_id] = Item(
        stale_id,
        _cache_labels(fingerprint),
        ("repomap-test-runtime:stale",),
    )
    boundary = make_boundary(managed_run(tmp_path), client)
    boundary.authorize_managed_runtime_cache_removal(stale_id)
    client.images.items.pop(stale_id)
    boundary.record_managed_runtime_cache_removal(stale_id)

    assert boundary.verify_terminal()["new_unattributed_images"] == 0


def test_runwide_boundary_refuses_cache_removal_without_preauthorization(
    tmp_path,
) -> None:
    fingerprint = "e" * 64
    stale_id = "sha256:" + "e" * 64
    client = Client()
    client.images.items[stale_id] = Item(
        stale_id,
        _cache_labels(fingerprint),
        ("repomap-test-runtime:stale",),
    )
    boundary = make_boundary(managed_run(tmp_path), client)
    client.images.items.pop(stale_id)

    with pytest.raises(RuntimeError, match="pre-delete authorization"):
        boundary.record_managed_runtime_cache_removal(stale_id)


def scratch_backed_run(tmp_path):
    """A run whose retention path is the production one, not a stand-in.

    ``managed_run`` above exposes only a ledger, so ``retain_operation_evidence``
    skips retention entirely and cannot observe a bad retained reason. This
    binds the real ``TestResourceRun.retain_evidence`` over a real scratch
    owner, so retention reaches ``ResourceLedger.register`` and the closed
    ``RetainedReason`` vocabulary exactly as it does under ``run_tests.py``.
    """
    layout = establish_run(
        {"REPOMAP_TEST_SCRATCH_ROOT": str(tmp_path / "scratch")},
        project="repo-map_dev",
        phase="REPOMAP-CI0B",
    )
    identity = RunIdentity(layout.project, layout.phase, layout.run_root.name)
    ledger = ResourceLedger.create(layout.run_root / "resource-ledger.json", identity)
    scratch = ScratchRunOwner(layout, ledger)
    scratch.register_layout()
    run = SimpleNamespace(layout=layout, ledger=ledger, scratch=scratch)
    run.retain_evidence = MethodType(TestResourceRun.retain_evidence, run)
    return run


def retained_reasons(run) -> dict[str, str]:
    return {
        Path(record.identity).name: RetainedReason(record.retained_reason).value
        for record in run.ledger.records
        if record.retained
    }


def test_ci0b_fix2_close_retains_operation_evidence_in_the_closed_vocabulary(
    tmp_path,
) -> None:
    """The live gate defect: close() invented a retained reason and threw."""
    run = scratch_backed_run(tmp_path)
    boundary = make_boundary(run, Client())
    with boundary.managed_external_base_pull(request="repo@sha256:abc") as ticket:
        boundary.complete_operation(ticket, image_ids=("sha256:base",))

    boundary.close(run)

    reasons = retained_reasons(run)
    assert reasons["docker-operation-derivation.json"] == "diagnostic_evidence"
    assert reasons[JOURNAL_FILENAME] == "diagnostic_evidence"


def test_ci0b_fix2_close_retains_evidence_after_a_prior_workload_failure(
    tmp_path,
) -> None:
    """Evidence closeout must still succeed once the workload has failed."""
    client = Client()
    run = scratch_backed_run(tmp_path)
    boundary = make_boundary(run, client)
    client.images.items["sha256:foreign"] = Item("sha256:foreign")
    with pytest.raises(RuntimeError):
        boundary.verify_terminal()

    boundary.close(run)

    journal = Path(run.ledger.path).parent / JOURNAL_FILENAME
    derivation = journal.with_name("docker-operation-derivation.json")
    assert journal.exists() and derivation.exists()
    assert set(retained_reasons(run)) >= {JOURNAL_FILENAME, derivation.name}


def test_ci0b_fix2_journal_is_retained_when_no_operation_was_recorded(
    tmp_path,
) -> None:
    """A zero-operation run retains an empty population, not a missing file."""
    run = scratch_backed_run(tmp_path)
    boundary = make_boundary(run, Client())

    boundary.close(run)

    journal = Path(run.ledger.path).parent / JOURNAL_FILENAME
    assert journal.read_bytes() == b""
    assert journal.stat().st_mode & 0o777 == 0o600
    assert retained_reasons(run)[JOURNAL_FILENAME] == "diagnostic_evidence"


def test_managed_system_candidate_build_boundary(tmp_path) -> None:
    run = scratch_backed_run(tmp_path)
    client = Client()
    boundary = make_boundary(run, client)

    with boundary.managed_system_candidate_build(request="candidate-build:tag") as ticket:
        boundary.complete_operation(ticket, image_ids=("sha256:candidate",))

    with pytest.raises(RuntimeError, match="exceeds one"):
        with boundary.managed_system_candidate_build(request="second-build"):
            pass

    projection = boundary.verify_terminal()
    assert projection["managed_system_candidate_image_build_count"] == 1
    assert projection["managed_test_runtime_image_build_count"] == 0
