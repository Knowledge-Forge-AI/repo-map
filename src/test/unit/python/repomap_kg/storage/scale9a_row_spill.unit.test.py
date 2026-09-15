from __future__ import annotations

from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.row_spool import RowSpool
from repomap_kg.storage.staged_rows import build_staged_rows


def test_large_families_spill_and_prepared_rows_close_private_files() -> None:
    observations = [
        RawObservation(
            kind="file",
            source_id=f"file-{index}.txt",
            path=f"file-{index}.txt",
            confidence="extracted",
            extractor="test",
            extractor_version="1",
            metadata={"language": "text", "role": "source"},
        )
        for index in range(4_200)
    ]

    prepared = build_staged_rows(
        observations,
        repository_name="fixture",
        stage_id="stage-large",
    )
    spool_paths = [
        rows.path
        for rows in prepared.family_rows.values()
        if isinstance(rows, RowSpool)
    ]

    assert spool_paths
    assert prepared.row_counts["files"] == len(observations)
    assert prepared.row_counts["raw_observations"] == len(observations)
    assert all(path.exists() for path in spool_paths)

    prepared.close()

    assert all(not path.exists() for path in spool_paths)
