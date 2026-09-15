from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.observations import RawObservation
from repomap_kg.ops.direct_publication import (
    build_observation_publication_authority,
    publish_observation_generation,
)
from repomap_kg.storage.main import LoadSummary


def _observations() -> tuple[RawObservation, ...]:
    return (
        RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="extracted",
            extractor="fixture-discovery",
            extractor_version="1.2.3",
            metadata={"content_hash": "a" * 64},
        ),
    )


def test_arch4a_external_observation_authority_has_deterministic_generations() -> None:
    first = build_observation_publication_authority(
        _observations(), repository_name="fixture", root_path="synthetic-root"
    )
    second = build_observation_publication_authority(
        _observations(), repository_name="fixture", root_path="synthetic-root"
    )

    assert first.execution_mode == "direct"
    assert first.operation_id != second.operation_id
    assert first.source_generation == second.source_generation
    assert first.config_generation == second.config_generation
    assert first.extractor_generation == second.extractor_generation
    assert first.canonicalizer_generation == second.canonicalizer_generation
    assert first.receipt().generations.source_generation.startswith("sg1:")
    assert first.receipt().generations.config_generation.startswith("cg1:")
    assert first.receipt().generations.extractor_generation.startswith("eg1:")
    assert first.receipt().generations.canonicalizer_generation.startswith("kg1:")


def test_arch4a_direct_observation_publication_delegates_to_staged_refresh() -> None:
    expected = LoadSummary(repository_id=7, run_id=11, files=1)
    with patch(
        "repomap_kg.ops.direct_publication.run_staged_full_refresh",
        return_value=expected,
    ) as staged:
        actual = publish_observation_generation(
            ["-h", "socket", "-d", "graph"],
            _observations(),
            repository_name="fixture",
            root_path="synthetic-root",
            git_commit="abc123",
            psql_command="/opt/postgres/bin/psql",
        )

    assert actual is expected
    assert staged.call_args.args[:2] == (
        ["-h", "socket", "-d", "graph"],
        _observations(),
    )
    assert staged.call_args.kwargs["repository_name"] == "fixture"
    assert staged.call_args.kwargs["root_path"] == "synthetic-root"
    assert staged.call_args.kwargs["git_commit"] == "abc123"
    assert staged.call_args.kwargs["authority"].execution_mode == "direct"


def test_arch4a_direct_observation_publication_rejects_empty_psql_selector() -> None:
    with pytest.raises(ValueError, match="psql command is invalid"):
        publish_observation_generation(
            [],
            _observations(),
            repository_name="fixture",
            root_path="synthetic-root",
            psql_command="",
        )
