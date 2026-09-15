from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from repomap_kg.storage.authority import PublicationGenerations
import scale18_digest_campaign as campaign
from scale15_terminal_contracts import FINAL_FAMILY_CODES
from scale20_prelaunch_handoff import (
    OrderedFinalFamilyCounts,
    ProtectedPrelaunchResult,
    decode_prelaunch_result,
    encode_prelaunch_result,
)


REPO_ROOT = Path(__file__).resolve().parents[5]
PUBLIC_GO_FIXTURE = REPO_ROOT / "src" / "test" / "fixtures" / "go" / "module_basic"


def _source_snapshot() -> dict[str, bytes]:
    return {
        path.relative_to(PUBLIC_GO_FIXTURE).as_posix(): path.read_bytes()
        for path in sorted(PUBLIC_GO_FIXTURE.rglob("*"))
        if path.is_file()
    }


def _complete_result(payload: dict[str, object]) -> ProtectedPrelaunchResult:
    source_generation = payload["source_generation"]
    family_counts = payload["family_counts"]
    structural_digest = payload["structural_digest"]
    assert isinstance(source_generation, str)
    assert isinstance(family_counts, dict)
    assert isinstance(structural_digest, str)
    return ProtectedPrelaunchResult(
        category="complete",
        repository_identity="repo1:public-go-fixture",
        repository_name="public-go-fixture",
        generations=PublicationGenerations(
            source_generation,
            "cg1:public-config",
            "eg1:public-extractor",
            "kg1:public-canonicalizer",
        ),
        execution_mode="direct",
        zero_state_first_publication=True,
        family_counts=OrderedFinalFamilyCounts.from_mapping(
            family_counts
        ),
        structural_digest=structural_digest,
    )


def _disk_space_worker_wrapper(tmp_path_factory, free_bytes: int) -> Path:
    wrapper = tmp_path_factory.mktemp("scale20-worker-wrapper") / "worker.py"
    wrapper.write_text(
        "\n".join(
            (
                "from types import SimpleNamespace",
                "import scale18_digest_campaign as campaign",
                "campaign.shutil.disk_usage = (",
                f"    lambda _path: SimpleNamespace(free={free_bytes})",
                ")",
                "raise SystemExit(campaign.main())",
                "",
            )
        ),
        encoding="utf-8",
    )
    return wrapper


def test_public_go_prelaunch_process_repeats_with_exact_order_and_cleanup(
    tmp_path,
    tmp_path_factory,
    monkeypatch,
) -> None:
    policy = campaign._WorkerResourcePolicy.CI_SAFE_QUALIFICATION
    simulated_free_bytes = 15 * 1024**3
    worker = _disk_space_worker_wrapper(tmp_path_factory, simulated_free_bytes)
    assert tmp_path not in worker.parents
    helper = Path(os.environ["REPOMAP_GO_HELPER"])
    assert helper.is_absolute() and helper.is_file()
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(campaign, "__file__", str(worker))
    monkeypatch.setattr(
        campaign.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=simulated_free_bytes),
    )
    source_before = _source_snapshot()
    artifacts_before = set(tmp_path.iterdir())
    arguments = (
        "_worker-repository",
        "--root",
        str(PUBLIC_GO_FIXTURE),
        "--label",
        "explicit_public_repository",
    )

    first = campaign._run_worker(arguments, policy=policy)
    second = campaign._run_worker(arguments, policy=policy)

    for payload in (first, second):
        campaign._require_case_limits(payload, policy)
        family_counts = payload["family_counts"]
        temporary_artifact_peak_bytes = payload["temporary_artifact_peak_bytes"]
        assert isinstance(family_counts, dict)
        assert isinstance(temporary_artifact_peak_bytes, int)
        assert tuple(family_counts) == FINAL_FAMILY_CODES
        assert temporary_artifact_peak_bytes < 64 * 1024**2
        authority = decode_prelaunch_result(
            encode_prelaunch_result(_complete_result(payload))
        ).to_expected_refresh_authority()
        assert authority.validate() is authority
        assert tuple(authority.expected_family_counts) == FINAL_FAMILY_CODES
    assert first["family_counts"] == second["family_counts"]
    assert first["source_generation"] == second["source_generation"]
    assert first["structural_digest"] == second["structural_digest"]
    assert encode_prelaunch_result(_complete_result(first)) == (
        encode_prelaunch_result(_complete_result(second))
    )
    assert _source_snapshot() == source_before
    assert set(tmp_path.iterdir()) == artifacts_before
