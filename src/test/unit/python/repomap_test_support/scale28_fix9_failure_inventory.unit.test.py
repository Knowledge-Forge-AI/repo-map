from __future__ import annotations

from pathlib import Path

from repomap_test_support.scale28_fix9_failure_inventory import (
    FORMER_FAILURES,
    PrimaryCandidate,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]


def test_fix9_inventory_maps_all_fourteen_failures_to_executable_nodes() -> None:
    assert len(FORMER_FAILURES) == 14
    assert len({case.case_id for case in FORMER_FAILURES}) == 14
    assert len({case.node_id for case in FORMER_FAILURES}) == 14
    for case in FORMER_FAILURES:
        relative_path, separator, node = case.node_id.partition("::")
        assert separator == "::"
        assert node.startswith("test_")
        assert _REPOSITORY_ROOT.joinpath(relative_path).is_file()


def test_fix9_inventory_has_no_unclassified_case_or_private_value() -> None:
    for case in FORMER_FAILURES:
        assert case.primary_candidate is not PrimaryCandidate.UNCLASSIFIED
        assert case.source_category
        assert case.outer_category
        assert case.cleanup_expected in {"exact", "not_started"}
        assert "/Users/" not in repr(case)
        assert "password" not in repr(case).lower()
