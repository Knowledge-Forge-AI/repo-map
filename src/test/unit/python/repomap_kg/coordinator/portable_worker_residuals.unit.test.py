from __future__ import annotations

from dataclasses import fields
import inspect

import pytest

from repomap_kg.artifacts.bundle import PublicationBundle
from repomap_kg.artifacts.parity_harness import (
    ParityResult,
    _has_single_observed_worker_launch,
)
from repomap_kg.artifacts.store import ArtifactIntegrityError
from repomap_kg.coordinator._portable_materialization import _remove_attempt_root
from repomap_kg.coordinator._portable_semantic_adapter import _receipt_write_diagnostic


@pytest.mark.parametrize(
    ("error", "expected"),
    (
        (ArtifactIntegrityError("store missing", code="store_unavailable"), "store_unavailable"),
        (ArtifactIntegrityError("not permitted", code="permission_denied"), "permission_denied"),
        (ArtifactIntegrityError("too large", code="artifact_bounds"), "receipt_bounds"),
        (ArtifactIntegrityError("boundary write failed", code="write_failed"), "write_failed"),
    ),
)
def test_receipt_write_diagnostic_uses_typed_store_code_not_message(
    error: ArtifactIntegrityError,
    expected: str,
) -> None:
    assert _receipt_write_diagnostic(error) == expected


def test_parity_result_has_no_decorative_caller_source_authority_field() -> None:
    assert "worker_caller_source_authority" not in {
        field.name for field in fields(ParityResult)
    }


def test_observed_worker_launch_evidence_detects_an_extra_launch() -> None:
    launch = ("python", "-m", "repomap_kg.coordinator._portable_worker_entrypoint")

    assert _has_single_observed_worker_launch((launch,))
    assert not _has_single_observed_worker_launch((launch, launch))


def test_current_bundle_creation_requires_explicit_stage_row_contract() -> None:
    parameter = inspect.signature(PublicationBundle.create).parameters[
        "row_stage_contract"
    ]
    assert parameter.default is inspect.Parameter.empty


def test_attempt_cleanup_refuses_symlink_nodes_without_touching_target(tmp_path) -> None:
    target = tmp_path / "caller-owned"
    target.mkdir()
    sentinel = target / "sentinel"
    sentinel.write_bytes(b"caller-owned")
    target.chmod(0o755)
    attempt = tmp_path / "attempt"
    attempt.mkdir(mode=0o700)
    (attempt / "substituted").symlink_to(target, target_is_directory=True)

    with pytest.raises(RuntimeError, match="unexpected node"):
        _remove_attempt_root(attempt)

    assert sentinel.read_bytes() == b"caller-owned"
    assert target.stat().st_mode & 0o777 == 0o755
    assert attempt.exists()
