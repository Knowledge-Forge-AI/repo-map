"""Preparation cancellation is cooperative at the actual owned row boundary."""
from __future__ import annotations

from pathlib import Path
from enum import IntEnum
import threading

import pytest

from common_lore_index.observations.raw import RawObservation
from common_lore_index.artifacts._canonical import canonical_json
from common_lore_index.coordinator._portable_preparation_control import _PreparedRowAdmission
from common_lore_index.storage import staged_rows as module
from common_lore_index.storage.row_spool import RowSpool
from common_lore_index.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS


class Interrupted(BaseException):
    """A deterministic control exception without an operating-system signal."""


class ExistingIntegerBound(IntEnum):
    BYTES = 10
    RECORDS = 1


def _observations() -> tuple[RawObservation, ...]:
    return tuple(
        RawObservation(
            kind="file", source_id=f"public/file-{index}.txt", path=f"public/file-{index}.txt",
            confidence="extracted", extractor="preparation-fixture", extractor_version="1.0.0",
            metadata={"extension": ".txt", "size_bytes": index + 1},
        )
        for index in range(6)
    )


def test_cancel_during_row_acquisition_stops_before_the_next_row_and_cleans_spools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = Interrupted()
    event = threading.Event()
    consumed: list[str] = []
    original = module._indexed
    sentinel = tmp_path / "unrelated"
    sentinel.write_bytes(b"preserved")

    def indexed(descriptor, stage_id, rows, adapter):
        for row in original(descriptor, stage_id, rows, adapter):
            consumed.append(descriptor.family)
            if len(consumed) == 2:
                event.set()
            yield row

    def check() -> None:
        if event.is_set():
            raise marker

    monkeypatch.setattr(module, "_indexed", indexed)
    monkeypatch.setattr(module, "_ROW_SPOOL_THRESHOLD", 1)
    with pytest.raises(Interrupted) as caught:
        module.build_staged_rows(
            _observations(), repository_name="public", stage_id="stage-preparation",
            spool_dir=tmp_path, cancel_check=check,
        )
    assert caught.value is marker
    assert consumed == ["files", "files"]
    assert tuple(tmp_path.iterdir()) == (sentinel,)
    assert sentinel.read_bytes() == b"preserved"


def test_spooled_admission_shares_equality_and_does_not_charge_a_refused_row() -> None:
    admit = _PreparedRowAdmission(10, 3)
    admit("files", 4)
    admit("raw_observations", 4)
    with pytest.raises(ValueError, match="publication bundle byte bounds exceeded"):
        admit("files", 7)
    admit("files", 6)
    for _ in range(2):
        with pytest.raises(ValueError, match="publication bundle record bounds exceeded"):
            admit("raw_observations", 5)


def test_admission_retains_the_capability_integer_subclass_domain() -> None:
    admit = _PreparedRowAdmission(ExistingIntegerBound.BYTES, ExistingIntegerBound.RECORDS)
    admit("files", 10)
    with pytest.raises(ValueError, match="publication bundle record bounds exceeded"):
        admit("files", 11)


@pytest.mark.parametrize("value", [True, -1])
def test_invalid_growth_does_not_change_the_next_admitted_projection(value: int) -> None:
    admit = _PreparedRowAdmission(2, 1)
    with pytest.raises(ValueError, match="invalid prepared spool growth"):
        admit("files", value)
    admit("files", 2)


@pytest.mark.parametrize("text", ["plain", '"\\\n\t', "\x7f", "Héllo Ελληνικά 中文", "🐦", "\x00\b\f\r"])
def test_actual_utf8_spool_payload_is_smaller_than_its_canonical_bundle_line(
    tmp_path: Path, text: str,
) -> None:
    row: dict[str, object] = {"stage_id": "stage-unassigned", "value": text, "nested": {"key": [None, True, 1, text]}}
    observed: list[int] = []
    line = canonical_json({"family": "raw_observations", "frame": "record", "record": row})
    with RowSpool.from_rows((row,), dir=tmp_path, artifact_observer=observed.append) as spool:
        assert spool.byte_count == spool.path.stat().st_size
        assert spool.byte_count < len(line)
        assert observed == [spool.byte_count]
        assert tuple(spool) == (row,)
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("metadata", [{1: "public"}, {float("nan"): "one", float("nan"): "two"}])
def test_existing_checksum_rejects_ambiguous_keys_before_spool_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata: dict[object, str],
) -> None:
    observed: list[int] = []
    monkeypatch.setattr(module, "_ROW_SPOOL_THRESHOLD", 0)
    row: dict[str, object] = {"stage_id": "stage-unassigned", "path": "public.py", "metadata_json": {"nested": metadata}}
    with pytest.raises(ValueError, match="unsupported checksum value"):
        module._materialize_or_spool(
            (row,), descriptor=STAGING_FAMILY_DESCRIPTORS["files"], staging_measurements=None,
            spool_artifact_observer=lambda _family, size: observed.append(size), spool_dir=tmp_path,
        )
    assert observed == []
    assert not tuple(tmp_path.iterdir())


def test_cancellation_interrupts_buffered_replay_before_another_spool_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = Interrupted()
    event = threading.Event()
    observed: list[tuple[str, int]] = []

    def check() -> None:
        if event.is_set():
            raise marker

    def observe(family: str, size: int) -> None:
        observed.append((family, size))
        event.set()

    monkeypatch.setattr(module, "_ROW_SPOOL_THRESHOLD", 3)
    with pytest.raises(Interrupted) as caught:
        module.build_staged_rows(
            _observations(), repository_name="public", stage_id="stage-preparation",
            spool_dir=tmp_path, cancel_check=check, spool_artifact_observer=observe,
        )
    assert caught.value is marker
    assert len(observed) == 1 and observed[0][0] == "files"
    assert not tuple(tmp_path.iterdir())


def test_explicit_no_control_keeps_default_rows_checksums_and_public_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "_ROW_SPOOL_THRESHOLD", 1)
    with module.build_staged_rows(
        _observations(), repository_name="public", stage_id="stage-preparation", spool_dir=tmp_path,
    ) as ordinary:
        with module.build_staged_rows(
            _observations(), repository_name="public", stage_id="stage-preparation",
            spool_dir=tmp_path, cancel_check=None,
        ) as explicit:
            assert type(ordinary) is type(explicit) is module.PreparedStageRows
            assert ordinary.checksums == explicit.checksums
            assert ordinary.normalized_byte_counts == explicit.normalized_byte_counts
            assert ordinary.row_counts == explicit.row_counts
            assert ordinary.files == explicit.files
            assert {name: tuple(rows) for name, rows in ordinary.family_rows.items()} == {
                name: tuple(rows) for name, rows in explicit.family_rows.items()
            }
    assert not tuple(tmp_path.iterdir())
