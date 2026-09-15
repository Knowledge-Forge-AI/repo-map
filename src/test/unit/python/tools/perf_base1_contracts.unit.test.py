"""Unit contracts and regressions for PERF-BASE1 campaign, worker, and reporting."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

import perf_base1_campaign as campaign
import perf_base1_reporting as reporting
import perf_base1_worker as worker
from perf_base1_reporting import (
    _jsonable,
    _median_stages,
    _report,
    _require_equivalent_results,
    _require_small_equivalence,
    build_campaign_report,
    coerce_int,
    jsonable,
    median_stages,
    require_equivalent_results,
    require_small_equivalence,
)
from perf_base1_worker import _SpoolSequence
from repomap_kg.observations.raw import RawObservation
from repomap_kg.observations.spool import ObservationSpool
from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS


class _TrackingSpool(ObservationSpool):
    """Spool subclass that counts disk replay iterations."""

    iter_count: int = 0

    @classmethod
    def from_observations(
        cls, observations: Iterable[RawObservation]
    ) -> _TrackingSpool:
        base = super().from_observations(observations)
        return cls(base.path, base.count, base.byte_count, base.allocated_byte_count)

    def __enter__(self) -> _TrackingSpool:
        return self

    def __iter__(self) -> Iterator[RawObservation]:
        self.iter_count += 1
        return super().__iter__()


def _make_obs(index: int) -> RawObservation:
    return RawObservation(
        kind="token",
        source_id=f"src-{index:03d}",
        path=f"file_{index:03d}.py",
        confidence="extracted",
        extractor="perf-test",
        extractor_version="1.0",
    )


@dataclass(frozen=True)
class _SampleRecord:
    name: str
    count: int


def _sample_overhead_runs() -> list[dict[str, object]]:
    return [
        {"instrumented": False, "total_wall_ns": 4_000_000},
        {"instrumented": True, "total_wall_ns": 4_100_000},
        {"instrumented": False, "total_wall_ns": 4_020_000},
        {"instrumented": True, "total_wall_ns": 4_120_000},
        {"instrumented": False, "total_wall_ns": 4_010_000},
        {"instrumented": True, "total_wall_ns": 4_110_000},
    ]


def _sample_run_result(
    *,
    structural_digest: str = "digest-alpha",
    family_count_override: int | None = None,
) -> dict[str, object]:
    counts = {
        family: (family_count_override if family_count_override is not None else 1)
        for family in STAGING_FAMILY_DESCRIPTORS
    }
    return {
        "structural_digest": structural_digest,
        "family_counts": counts,
        "source_input_digest": "src-input-digest",
        "configuration_digest": "cfg-digest",
        "extractor_digest": "ext-digest",
        "publication_state": "published",
        "spool_elapsed_ns": 100_000,
        "pre_final_elapsed_ns": 200_000,
        "total_wall_ns": 500_000,
        "phase_wall_ns": {
            "refresh.total": 500_000,
            "stage.copy": 150_000,
            "staging.pre_final_commit": 200_000,
        },
        "stage_reconciliation": "passed",
    }


def test_spool_sequence_no_eager_materialization_and_len() -> None:
    observations = [_make_obs(i) for i in range(6)]
    with _TrackingSpool.from_observations(observations) as spool:
        seq = _SpoolSequence(spool)
        assert spool.iter_count == 0
        assert len(seq) == 6
        assert spool.iter_count == 0


def test_spool_sequence_indexing_honest() -> None:
    observations = [_make_obs(i) for i in range(5)]
    with _TrackingSpool.from_observations(observations) as spool:
        seq = _SpoolSequence(spool)
        assert seq[0].source_id == "src-000"
        assert spool.iter_count == 1
        assert seq[4].source_id == "src-004"
        assert seq[-1].source_id == "src-004"
        assert seq[-5].source_id == "src-000"
        with pytest.raises(IndexError):
            _ = seq[5]
        with pytest.raises(IndexError):
            _ = seq[-6]
        with pytest.raises(TypeError):
            _ = getattr(seq, "__getitem__")("invalid")


def test_spool_sequence_slicing_honest() -> None:
    observations = [_make_obs(i) for i in range(5)]
    with _TrackingSpool.from_observations(observations) as spool:
        seq = _SpoolSequence(spool)
        forward_slice = seq[1:4]
        assert isinstance(forward_slice, Sequence)
        assert [obs.source_id for obs in forward_slice] == [
            "src-001",
            "src-002",
            "src-003",
        ]
        reverse_slice = seq[3:0:-1]
        assert [obs.source_id for obs in reverse_slice] == [
            "src-003",
            "src-002",
            "src-001",
        ]
        empty_slice = seq[10:20]
        assert empty_slice == ()


def test_spool_sequence_replay_and_streaming() -> None:
    observations = [_make_obs(i) for i in range(4)]
    with _TrackingSpool.from_observations(observations) as spool:
        seq = _SpoolSequence(spool)
        stream_iter = iter(seq)
        assert isinstance(stream_iter, Iterator)
        first_pass = [obs.source_id for obs in stream_iter]
        assert spool.iter_count == 1
        second_pass = [obs.source_id for obs in seq]
        assert spool.iter_count == 2
        assert first_pass == second_pass == ["src-000", "src-001", "src-002", "src-003"]


def test_numeric_coercion_supported_scalars() -> None:
    assert coerce_int(42) == 42
    assert coerce_int(12.0) == 12
    assert coerce_int(12.9) == 12
    assert coerce_int(True) == 1
    assert coerce_int(False) == 0
    assert coerce_int("100") == 100
    assert coerce_int(b"250") == 250


def test_numeric_coercion_failures() -> None:
    with pytest.raises(TypeError):
        coerce_int(None)
    with pytest.raises(TypeError):
        coerce_int([])
    with pytest.raises(TypeError):
        coerce_int({})
    with pytest.raises(ValueError):
        coerce_int("not_a_number")
    with pytest.raises(ValueError):
        coerce_int("12.5")


def test_median_stages_fail_closed_empty_input() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        median_stages([])


def test_median_stages_fail_closed_missing_or_nonmapping() -> None:
    with pytest.raises(KeyError):
        median_stages([{"other": 1}])
    with pytest.raises(TypeError):
        median_stages([{"phase_wall_ns": None}])
    with pytest.raises(TypeError):
        median_stages([{"phase_wall_ns": 42}])
    with pytest.raises(ValueError):
        median_stages([{"phase_wall_ns": {"p1": "not_numeric"}}])


def test_median_stages_calculation() -> None:
    results: list[Mapping[str, object]] = [
        {"phase_wall_ns": {"stage.a": 10, "stage.b": 20.0, "stage.c": 99}},
        {"phase_wall_ns": {"stage.a": 30, "stage.b": 40, "stage.c": 100}},
        {"phase_wall_ns": {"stage.a": 20, "stage.b": 30}},
    ]
    computed = median_stages(results)
    assert computed == {"stage.a": 20, "stage.b": 30}


def test_build_campaign_report_contract() -> None:
    small_run = _sample_run_result(structural_digest="small-dig")
    rep_run_1 = _sample_run_result(structural_digest="rep-dig")
    rep_run_2 = _sample_run_result(structural_digest="rep-dig")
    report = build_campaign_report(
        workload={"work_items": 10},
        admissions=[],
        small=[small_run, small_run],
        overhead_runs=_sample_overhead_runs(),
        representative=[rep_run_1, rep_run_2],
        queries=[],
        connection={},
        elapsed_seconds=2.5,
    )
    assert report["schema"] == "repomap-performance-baseline-v1"
    assert "overhead_summary" in report
    assert "median_stage_wall_ns" in report
    assert "top_bottlenecks" in report
    assert report["elapsed_seconds"] == 2.5


def test_build_campaign_report_digest_mismatch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    small_run = _sample_run_result(structural_digest="small-dig")
    rep_run_1 = _sample_run_result(structural_digest="rep-dig-1")
    rep_run_2 = _sample_run_result(structural_digest="rep-dig-2")
    monkeypatch.setattr(reporting, "require_equivalent_results", lambda _results: None)
    with pytest.raises(RuntimeError, match="representative digest differs"):
        build_campaign_report(
            workload={"work_items": 10},
            admissions=[],
            small=[small_run, small_run],
            overhead_runs=_sample_overhead_runs(),
            representative=[rep_run_1, rep_run_2],
            queries=[],
            connection={},
            elapsed_seconds=1.0,
        )


def test_build_campaign_report_family_counts_mismatch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    small_run = _sample_run_result(structural_digest="small-dig")
    rep_run_1 = _sample_run_result(structural_digest="rep-dig", family_count_override=1)
    rep_run_2 = _sample_run_result(structural_digest="rep-dig", family_count_override=2)
    monkeypatch.setattr(reporting, "require_equivalent_results", lambda _results: None)
    with pytest.raises(RuntimeError, match="family counts differ"):
        build_campaign_report(
            workload={"work_items": 10},
            admissions=[],
            small=[small_run, small_run],
            overhead_runs=_sample_overhead_runs(),
            representative=[rep_run_1, rep_run_2],
            queries=[],
            connection={},
            elapsed_seconds=1.0,
        )


def test_equivalence_helpers() -> None:
    small_run = _sample_run_result(structural_digest="small-dig")
    require_small_equivalence([small_run, small_run])
    with pytest.raises(RuntimeError, match="small equivalence set is incomplete"):
        require_small_equivalence([small_run])
    with pytest.raises(RuntimeError, match="equivalence set is incomplete"):
        require_equivalent_results([])


def test_jsonable_contract() -> None:
    assert jsonable(42) == 42
    assert jsonable((1, 2)) == [1, 2]
    assert jsonable(_SampleRecord("test", 5)) == {"name": "test", "count": 5}


def test_stable_campaign_helper_aliases() -> None:
    assert campaign._report is reporting.build_campaign_report
    assert campaign._jsonable is reporting.jsonable
    assert campaign._median_stages is reporting.median_stages
    assert campaign._require_small_equivalence is reporting.require_small_equivalence
    assert campaign._require_equivalent_results is reporting.require_equivalent_results
    assert _report is build_campaign_report
    assert _jsonable is jsonable
    assert _median_stages is median_stages
    assert _require_small_equivalence is require_small_equivalence
    assert _require_equivalent_results is require_equivalent_results


def test_worker_normalized_observations_numeric_coercion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_sizes: list[int] = []

    class _FakeWorkload:
        observations = ()
        work_items = 0

    def fake_build_workload(name: str, size: int) -> _FakeWorkload:
        assert name == "mixed"
        captured_sizes.append(size)
        return _FakeWorkload()

    monkeypatch.setattr(worker, "build_workload", fake_build_workload)
    obs, label = worker._normalized_observations({"size": 32.0})
    assert label == "scale11-mixed-0"
    assert captured_sizes == [32]
    worker._normalized_observations({"size": 64})
    assert captured_sizes == [32, 64]
    with pytest.raises(ValueError):
        worker._normalized_observations({"size": "invalid"})
