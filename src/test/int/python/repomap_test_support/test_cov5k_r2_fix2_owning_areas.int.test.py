from __future__ import annotations

from pathlib import Path

import pytest

import repomap_test_support.test_cov5k_r2_fix2_observer as observer
from repomap_test_support.test_cov5k_r2_fix2_catalog import (
    CatalogEntry,
    build_closed_catalog,
)
from repomap_test_support.test_cov5k_r2_fix2_observer import (
    execute_owning_area_execution,
)
from repomap_test_support.test_scratch import ENV_SCRATCH_ROOT, establish_run


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]


def _representatives() -> tuple[CatalogEntry, ...]:
    selected: dict[str, CatalogEntry] = {}
    for entry in build_closed_catalog():
        if entry.semantic_group == "I":
            owning_area = dict(entry.parameter_values)["owning_area"]
            assert isinstance(owning_area, str)
            selected.setdefault(owning_area, entry)
    return tuple(selected.values())


@pytest.mark.parametrize(
    "entry",
    _representatives(),
    ids=lambda entry: str(dict(entry.parameter_values)["owning_area"]),
)
def test_one_group_i_sample_per_owning_area_uses_actual_runner(entry) -> None:
    evidence = execute_owning_area_execution(entry, repository_root=Path.cwd())

    assert evidence.owner_entered
    assert evidence.model_rehearsal_only
    assert evidence.qualification_status == "unqualified"
    assert dict(evidence.observed_fields)["parent_readiness"] == (
        True,
        True,
        True,
        True,
    )


def test_nested_tmp_path_materializes_dedicated_owning_area_basetemp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = establish_run(
        {ENV_SCRATCH_ROOT: str(tmp_path)},
        project="repo-map_dev",
        phase="run-tests-all",
    )
    for key, value in parent.child_environment().items():
        monkeypatch.setenv(key, value)
    node = (
        "src/test/unit/python/repomap_test_support/"
        "scale28_diag1_fix1_test_scratch_boundaries.unit.test.py::"
        "test_run_allocation_is_exclusive_and_short"
    )
    monkeypatch.setitem(observer._OWNING_AREA_NODES, "scale14", node)
    entry = next(
        item
        for item in _representatives()
        if dict(item.parameter_values)["owning_area"] == "scale14"
    )

    execute_owning_area_execution(entry, repository_root=_REPOSITORY_ROOT)

    owning_area_root = parent.tmp / "owning-area"
    assert owning_area_root.is_dir()
    assert owning_area_root.stat().st_mode & 0o777 == 0o700
    assert (owning_area_root / "scale14").is_dir()
