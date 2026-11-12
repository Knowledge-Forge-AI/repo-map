"""Prepared row ownership survives measurement and cleanup-chain failures."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from common_lore_index.observations.raw import RawObservation
from common_lore_index.storage import staged_rows as module
from common_lore_index.storage.row_spool import RowSpool
from common_lore_index.storage.staging_observability import StagingMeasurements


class Interrupted(BaseException):
    """A deterministic in-process interruption."""


def _observations() -> tuple[RawObservation, ...]:
    return tuple(
        RawObservation(
            kind="file", source_id=f"public/file-{index}.txt", path=f"public/file-{index}.txt",
            confidence="extracted", extractor="spool-custody-fixture", extractor_version="1.0.0",
            metadata={"extension": ".txt", "size_bytes": index + 1},
        )
        for index in range(3)
    )


def test_family_measurement_exit_cannot_lose_its_returned_spool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_measure = module.measure_family_preparation
    marker = Interrupted()
    observed: list[Path] = []

    def measure(measurements, family, operation):
        prepared = original_measure(measurements, family, operation)
        if isinstance(prepared.rows, RowSpool):
            observed.append(prepared.rows.path)
            raise marker
        return prepared

    monkeypatch.setattr(module, "_ROW_SPOOL_THRESHOLD", 1)
    monkeypatch.setattr(module, "measure_family_preparation", measure)
    with pytest.raises(Interrupted) as caught:
        module.build_staged_rows(_observations(), repository_name="public", stage_id="stage-custody", spool_dir=tmp_path)
    assert caught.value is marker
    assert len(observed) == 1
    assert all(not path.exists() for path in observed)
    assert not tuple(tmp_path.iterdir())


def test_checksum_phase_exit_reclaims_the_already_written_spool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = Interrupted()
    observed: list[Path] = []
    original_from_rows = RowSpool.from_rows

    def spool(cls, rows, **kwargs):
        result = original_from_rows(rows, **kwargs)
        observed.append(result.path)
        return result

    class Measurements(StagingMeasurements):
        @contextmanager
        def phase(self, phase_code):
            with super().phase(phase_code):
                yield
            if phase_code == "staging.family_spool.files":
                raise marker

    monkeypatch.setattr(module, "_ROW_SPOOL_THRESHOLD", 1)
    monkeypatch.setattr(RowSpool, "from_rows", classmethod(spool))
    with pytest.raises(Interrupted) as caught:
        module.build_staged_rows(
            _observations(), repository_name="public", stage_id="stage-custody", spool_dir=tmp_path,
            staging_measurements=Measurements(lambda _: None),
        )
    assert caught.value is marker
    assert len(observed) == 1
    assert all(not path.exists() for path in observed)
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("existing_failure", [False, True])
def test_every_family_cleanup_is_attempted_without_replacing_a_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_failure: bool,
) -> None:
    monkeypatch.setattr(module, "_ROW_SPOOL_THRESHOLD", 1)
    prepared = module.build_staged_rows(
        _observations(), repository_name="public", stage_id="stage-custody", spool_dir=tmp_path,
    )
    spools = [rows for rows in prepared.family_rows.values() if isinstance(rows, RowSpool)]
    assert len(spools) == 5
    closed: list[Path] = []
    original_close = RowSpool.close
    primary = Interrupted()
    secondary = OSError("synthetic cleanup refusal after unlink")

    def close(spool):
        original_close(spool)
        closed.append(spool.path)
        if len(closed) == 1:
            raise secondary

    monkeypatch.setattr(RowSpool, "close", close)
    expected = Interrupted if existing_failure else OSError
    with pytest.raises(expected) as caught:
        with prepared:
            if existing_failure:
                raise primary
    assert caught.value is (primary if existing_failure else secondary)
    assert len(closed) == len(set(closed)) == len(spools)
    assert all(not spool.path.exists() for spool in spools)
    assert not tuple(tmp_path.iterdir())
