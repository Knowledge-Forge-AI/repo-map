from __future__ import annotations

import json
from pathlib import Path

import pytest

import scale11_profile_analysis as scale11_profile_analysis
import scale11_profile_contracts as scale11_profile_contracts

setattr(
    scale11_profile_contracts,
    "analyze_scaling",
    scale11_profile_analysis.analyze_scaling,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
FAMILIES = (
    "files",
    "raw_observations",
    "canonical_nodes",
    "canonical_edges",
    "canonical_evidence",
    "canonical_node_evidence",
    "canonical_edge_evidence",
)


def load_tool_module():
    return scale11_profile_contracts


def _family(tool, family, rows, elapsed):
    return tool.FamilyProfile(
        family=family,
        row_count=rows,
        normalized_bytes=rows * 40,
        spool_bytes=rows * 20,
        encoded_bytes=tool.MetricValue.unavailable("not_observed"),
        preparation_seconds=tool.MetricValue.available(elapsed * 0.2),
        checksum_seconds=tool.MetricValue.available(elapsed * 0.1),
        copy_seconds=tool.MetricValue.available(elapsed * 0.4),
        statistics_seconds=tool.MetricValue.unavailable("aggregate_scope"),
        completeness_validation_seconds=tool.MetricValue.unavailable("aggregate_scope"),
        semantic_guard_seconds=tool.MetricValue.unavailable("aggregate_scope"),
        merge_seconds=tool.MetricValue.unavailable("aggregate_scope"),
        cleanup_seconds=tool.MetricValue.unavailable("aggregate_scope"),
    )


def _result(tool, size, repetition, elapsed, multiplier=10):
    families = tuple(
        _family(tool, family, size * multiplier, elapsed)
        for family in FAMILIES
    )
    return tool.ProfileResult(
        profile="mixed",
        size_band=size,
        repetition=repetition,
        work_items=size,
        observation_count=size * 2,
        elapsed_seconds=elapsed,
        families=families,
        aggregate_metrics={
            "wal_upper_bound_bytes": tool.MetricValue.available(size * 100),
            "postgres_group_peak_rss_bytes": tool.MetricValue.unavailable(
                "ownership_unavailable"
            ),
            "statement_count": tool.MetricValue.unavailable("not_observed"),
        },
        receipt_complete=True,
        generation=2,
        structural_digest="a" * 64,
        cleanup_complete=True,
        threshold_evaluation={"schema_version": 1, "metrics": []},
        boundary_occurrences={
            "semantic_guard_seconds": (
                tool.MetricValue.available(elapsed * 0.05),
            ),
            "merge_seconds": (tool.MetricValue.available(elapsed * 0.2),),
        },
    )


def test_metric_availability_is_explicit_and_closed() -> None:
    tool = load_tool_module()

    available = tool.MetricValue.available(1.25)
    unavailable = tool.MetricValue.unavailable("aggregate_scope")

    assert available.to_payload() == {"availability": "available", "value": 1.25}
    assert unavailable.to_payload() == {
        "availability": "unavailable",
        "reason": "aggregate_scope",
        "value": None,
    }
    with pytest.raises(tool.Scale11ContractError):
        tool.MetricValue(value=None, availability="available", reason=None)


def test_profile_result_requires_exact_family_manifest_and_bounded_payload() -> None:
    tool = load_tool_module()
    result = _result(tool, 128, 1, 2.0)

    payload = result.to_payload()
    encoded = json.dumps(payload, sort_keys=True).encode()

    assert payload["schema_version"] == 1
    assert payload["workload_profile"] == "mixed"
    assert payload["execution_mode"] == "direct"
    assert payload["result_category"] == "complete"
    assert payload["publication_result"] == "complete_receipt"
    assert payload["family_count"] == 7
    assert payload["total_rows"] > 0
    assert payload["total_normalized_bytes"] > 0
    assert payload["total_spool_bytes"] > 0
    assert payload["total_encoded_bytes"] is None
    assert payload["statement_count"] is None
    assert payload["receipt_complete"] is True
    assert payload["repeat_equal"] is None
    assert payload["cleanup_complete"] is True
    assert "threshold_crossings" in payload
    assert payload["boundary_metrics"]["statement_count"] == {
        "availability": "unavailable",
        "reason": "not_observed",
        "value": None,
    }
    assert payload["boundary_occurrences"]["semantic_guard_seconds"] == [
        {"availability": "available", "value": 0.1}
    ]
    assert tuple(family["family"] for family in payload["families"]) == FAMILIES
    assert set(payload["families"][0]) == {
        "family",
        "row_count",
        "normalized_bytes",
        "spool_bytes",
        "encoded_bytes",
        "prepare_elapsed",
        "checksum_elapsed",
        "copy_elapsed",
        "statistics_elapsed",
        "completeness_validation_elapsed",
        "semantic_guard_elapsed",
        "merge_elapsed",
        "cleanup_elapsed",
        "bytes_per_row",
        "rows_per_second",
        "elapsed_seconds_per_thousand_rows",
    }
    assert len(encoded) < 1_048_576
    forbidden = ("/Users/", "postgresql://", "repository_name", "graph_name", "source_id")
    assert not any(token in encoded.decode() for token in forbidden)

    with pytest.raises(tool.Scale11ContractError):
        tool.ProfileResult(
            **{
                **result.__dict__,
                "families": result.families[:-1],
            }
        )


def test_scaling_analysis_retains_repetitions_and_computes_medians_cv_and_ratios() -> None:
    tool = load_tool_module()
    results = tuple(
        _result(tool, size, repetition, elapsed)
        for size, base in ((128, 1.0), (512, 4.0), (2_048, 16.0), (8_192, 64.0))
        for repetition, elapsed in enumerate((base * 0.99, base, base * 1.01), 1)
    )

    aggregate = tool.analyze_scaling(results)

    assert aggregate.profile == "mixed"
    assert aggregate.repetition_count == 12
    assert aggregate.size_bands == (128, 512, 2_048, 8_192)
    assert aggregate.elapsed_medians == (1.0, 4.0, 16.0, 64.0)
    assert aggregate.elapsed_ratios == (4.0, 4.0, 4.0)
    assert max(aggregate.elapsed_coefficients_of_variation) < 0.02
    assert aggregate.classification == "stable_linear_characterization"
    assert len(aggregate.repetitions) == 12


@pytest.mark.parametrize(
    ("elapsed", "classification"),
    (
        ((1.0, 1.1, 1.2, 1.3), "fixed_overhead_dominated"),
        ((1.0, 4.0, 20.0, 120.0), "superlinear_suspect"),
    ),
)
def test_scaling_classification_uses_multiple_bands(elapsed, classification) -> None:
    tool = load_tool_module()
    results = tuple(
        _result(tool, size, repetition, band_elapsed)
        for size, band_elapsed in zip((128, 512, 2_048, 8_192), elapsed, strict=True)
        for repetition in range(1, 4)
    )

    assert tool.analyze_scaling(results).classification == classification


def test_missing_repetitions_or_bands_are_insufficient_evidence() -> None:
    tool = load_tool_module()
    result = _result(tool, 128, 1, 1.0)

    aggregate = tool.analyze_scaling((result,))

    assert aggregate.classification == "insufficient_evidence"
