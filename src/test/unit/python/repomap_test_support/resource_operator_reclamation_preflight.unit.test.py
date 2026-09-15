"""TEST-HYGIENE3B3-FIX3 D1-D12 pre-record diagnostic contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import repomap_test_support.resource_operator_reclamation as reclamation

import test_hygiene_maintenance as maintenance_tool
from repomap_test_support.resource_operator_reclamation import (
    CONFIRMATION_LITERAL,
    PREFLIGHT_CATEGORIES,
    OperatorReclamationPreflightError,
    OperatorReclamationRequest,
    reclaim_run_population,
)
from repomap_test_support.resource_operator_reclamation_test_support import (
    add_run,
    dead,
    private_root,
)
from repomap_test_support.resource_operator_scope import OperatorScopeIdentityError


EXPECTED_CATEGORIES = frozenset(
    {
        "scratch_root_authority_unavailable",
        "maintenance_authority_unavailable",
        "index_authority_unavailable",
        "admission_barrier_unavailable",
        "inventory_authority_unavailable",
        "inventory_identity_changed",
        "liveness_authority_unavailable",
        "protection_authority_unavailable",
        "monitoring_authority_unavailable",
        "index_record_authority_unavailable",
        "operator_evidence_authority_unavailable",
    }
)


def approved() -> OperatorReclamationRequest:
    return OperatorReclamationRequest(CONFIRMATION_LITERAL, False, False)


def reclaim(root: Path):
    return reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
    )


def failure() -> None:
    raise RuntimeError("private synthetic cause")


def assert_category(root: Path, category: str) -> None:
    run = root / "r" / "preserved"
    with pytest.raises(OperatorReclamationPreflightError) as raised:
        reclaim(root)
    assert raised.value.category == category
    assert run.exists()
    maintenance = root / ".maintenance" / "repo-map_dev"
    assert not maintenance.exists() or not tuple(maintenance.iterdir())
    assert not (root / ".index" / "repo-map_dev" / "admission.lock").exists()


def test_preflight_category_vocabulary_is_exact_and_closed() -> None:
    assert PREFLIGHT_CATEGORIES == EXPECTED_CATEGORIES
    with pytest.raises(ValueError, match="category is invalid"):
        OperatorReclamationPreflightError("private arbitrary text")


def test_d1_root_authority_failure_is_typed(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    add_run(root, "preserved")
    root.chmod(0o755)
    assert_category(root, "scratch_root_authority_unavailable")


def test_d2_registry_and_maintenance_failure_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    add_run(root, "preserved")
    monkeypatch.setattr(reclamation, "ClaimRegistry", lambda *_args: failure())
    assert_category(root, "maintenance_authority_unavailable")


def test_d3_index_binding_failure_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    add_run(root, "preserved")
    monkeypatch.setattr(
        reclamation.MaintenanceIndexBinding,
        "bind",
        classmethod(lambda _cls, *_args: failure()),
    )
    assert_category(root, "index_authority_unavailable")


def test_d4_barrier_failure_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    add_run(root, "preserved")
    monkeypatch.setattr(reclamation, "acquire_admission_barrier", failure)
    assert_category(root, "admission_barrier_unavailable")


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (OperatorScopeIdentityError("changed"), "inventory_identity_changed"),
        (RuntimeError("private"), "inventory_authority_unavailable"),
    ],
)
def test_d5_inventory_failures_are_typed_without_message_matching(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    category: str,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "preserved")

    def fail_inventory(_root: Path):
        raise error

    monkeypatch.setattr(reclamation, "inventory_operator_scope", fail_inventory)
    assert_category(root, category)


@pytest.mark.parametrize(
    ("owner", "category"),
    [
        ("classify_liveness", "liveness_authority_unavailable"),
        ("capture_protections", "protection_authority_unavailable"),
        ("capture_monitoring", "monitoring_authority_unavailable"),
        ("capture_index_records", "index_record_authority_unavailable"),
    ],
)
def test_d6_d8_stage_failures_are_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner: str,
    category: str,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "preserved")
    monkeypatch.setattr(reclamation, owner, lambda *_args: failure())
    assert_category(root, category)


def test_d9_operation_record_failure_is_typed_before_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    add_run(root, "preserved")
    finished = []
    monkeypatch.setattr(reclamation, "create_operation_record", failure)
    monkeypatch.setattr(
        reclamation,
        "_finish",
        lambda *_args, **_kwargs: finished.append(True),
    )

    assert_category(root, "operator_evidence_authority_unavailable")
    assert finished == []


def test_d10_typed_cli_projection_excludes_raw_private_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = private_root(tmp_path)
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))

    def fail_reclaim(*_args, **_kwargs):
        try:
            raise RuntimeError(f"private failure at {root}")
        except RuntimeError as cause:
            raise OperatorReclamationPreflightError(
                "protection_authority_unavailable"
            ) from cause

    monkeypatch.setattr(maintenance_tool, "reclaim_run_population", fail_reclaim)
    assert maintenance_tool.main(
        ["operator-reclaim", "--confirm", CONFIRMATION_LITERAL]
    ) == 2
    rendered = capsys.readouterr().out
    assert str(root) not in rendered
    assert "private failure" not in rendered
    assert json.loads(rendered)["physical_mutation_performed"] is False


def test_d11_generic_cli_fallback_keeps_mutation_unobserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "possibly-mutated")
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))

    def fail_after_possible_mutation(*_args, **_kwargs):
        (run / "payload.bin").unlink()
        raise RuntimeError(f"private release failure at {root}")

    monkeypatch.setattr(
        maintenance_tool, "reclaim_run_population", fail_after_possible_mutation
    )
    assert maintenance_tool.main(
        ["operator-reclaim", "--confirm", CONFIRMATION_LITERAL]
    ) == 2
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "category": "operator_authority_unavailable",
        "outcome": "operator_reclamation_refused",
        "physical_mutation_performed": "unobserved",
    }


def test_d12_normal_refusal_is_not_exception_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = private_root(tmp_path)
    add_run(root, "normal-refusal")
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))

    assert maintenance_tool.main(["operator-reclaim"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["outcome"] == "confirmation_refused"
    assert "category" not in output
