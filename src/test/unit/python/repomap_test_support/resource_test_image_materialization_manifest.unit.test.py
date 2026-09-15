from __future__ import annotations

import os
from pathlib import Path

import pytest

from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_ledger_io import write_private_json
from repomap_test_support.resource_run import TestResourceRun
from repomap_test_support.resource_test_image_base import (
    TestImageError as ImageLifecycleError,
)
from repomap_test_support.resource_test_image_cleanup import (
    MaterializationCleanupError,
)
from repomap_test_support.resource_test_image_materialization import (
    MaterializationContainerOwner,
    materialization_manifest_path,
    recover_interrupted_runtime_materialization,
)
from src.test.unit.python.repomap_test_support.resource_test_image_materialization_parts.fixtures import (
    FakeClient,
    FakeContainer,
)


class FakeResourceRun(TestResourceRun):
    def __init__(
        self, ledger: ResourceLedger, materialization_manifest_path: Path | None = None
    ) -> None:
        self.ledger = ledger
        self.materialization_manifest_path = materialization_manifest_path


def _claim_owner(tmp_path):
    ledger = ResourceLedger.create(
        tmp_path / "claim-ledger.json", RunIdentity("repo-map", "PHASE", "run")
    )
    owner = MaterializationContainerOwner(
        FakeResourceRun(
            ledger=ledger,
            materialization_manifest_path=tmp_path / "materialization-claim.json",
        ),
        FakeClient(),
        network_mode="none",
    )
    claim = owner._claim(
        name="repomap-test-materialization-" + "a" * 24,
        image_id="sha256:" + "b" * 64,
        container_id="c" * 64,
        network_id=None,
    )
    write_private_json(owner.manifest_path, dict(claim))
    return owner, claim


def test_materialization_manifest_lives_under_project_root_scratch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    path = materialization_manifest_path(repo)

    assert path.parent == repo / ".scratch"
    assert path.name == f"repomap-runtime-materialization-{os.getuid()}.json"

    source = (
        Path(__file__).parents[3]
        / "support/python/repomap_test_support"
        / "resource_test_image_materialization.py"
    ).read_text(encoding="utf-8")
    assert '"/tmp"' not in source
    assert "/private/tmp" not in source
    assert "gettempdir" not in source
    assert "TMPDIR" not in source


def test_materialization_manifest_path_is_stable_across_runs(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.setenv("TMPDIR", str(tmp_path / "env-a"))
    first = materialization_manifest_path(repo)
    monkeypatch.setenv("TMPDIR", str(tmp_path / "env-b"))
    second = materialization_manifest_path(repo)

    assert first == second


def test_materialization_manifest_refuses_symlinked_scratch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (repo / ".scratch").symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(ImageLifecycleError, match="scratch is a symlink"):
        materialization_manifest_path(repo)


def test_materialization_manifest_requires_a_project_root(tmp_path):
    ledger = ResourceLedger.create(
        tmp_path / "ledger.json", RunIdentity("repo-map", "PHASE", "run")
    )

    with pytest.raises(ImageLifecycleError, match="requires a project root"):
        MaterializationContainerOwner(FakeResourceRun(ledger=ledger), FakeClient())


@pytest.mark.parametrize(
    ("field", "replacement", "predicate"),
    (
        ("project", "another-project", "manifest_project"),
        ("phase", "ANOTHER-PHASE", "manifest_phase"),
        ("run_id", "another-run", "manifest_run_id"),
        ("ledger_path", None, "manifest_ledger_path"),
    ),
)
def test_live_cleanup_refuses_claim_identity_that_differs_from_current_ledger(
    tmp_path, field, replacement, predicate
):
    owner, claim = _claim_owner(tmp_path)
    if field == "ledger_path":
        replacement = str((tmp_path / "another-ledger.json").resolve())
    claim[field] = replacement
    write_private_json(owner.manifest_path, claim)

    with pytest.raises(MaterializationCleanupError) as caught:
        owner.cleanup("c" * 64)

    assert caught.value.failure_kind == (
        f"identity_or_state_validation_refused:{predicate}"
    )
    assert caught.value.cleanup_evidence["validation_predicate"] == predicate
    assert "differs from current ledger" in caught.value.cleanup_evidence[
        "validation_category"
    ]


def test_interrupted_recovery_refuses_claim_ledger_identity_mismatch(tmp_path):
    owner, claim = _claim_owner(tmp_path)
    claim["project"] = "repo-map_dev"
    write_private_json(owner.manifest_path, claim)
    client = FakeClient()
    container = FakeContainer(
        client.containers, "c" * 64, "sha256:" + "b" * 64, {}
    )
    client.containers.objects[container.id] = container

    with pytest.raises(
        ImageLifecycleError, match="materialization recovery ledger authority differs"
    ) as caught:
        recover_interrupted_runtime_materialization(
            client, manifest_path=owner.manifest_path
        )

    assert str(caught.value.__cause__) == "resource ledger belongs to another run"
    assert owner.manifest_path.exists()
