from __future__ import annotations

from unittest.mock import patch

from repomap_kg.ops.direct_publication import publish_observation_generation
from repomap_kg.storage import LoadSummary, repository_run_prefix_sql


def test_repository_run_prefix_selects_stable_or_historical_identity() -> None:
    stable = repository_run_prefix_sql(
        repository_name="fixture",
        root_path="/workspace/current",
        repository_identity="repo1:fixture",
        git_commit=None,
        run_status="complete",
    )
    assert "name, root_path, repository_identity" in stable[1]
    assert "ON CONFLICT (repository_identity)" in stable[1]
    assert "WHERE repository_identity IS NOT NULL" in stable[1]
    assert "root_path = EXCLUDED.root_path" in stable[1]

    historical = repository_run_prefix_sql(
        repository_name="fixture",
        root_path="/workspace/current",
        git_commit=None,
        run_status="complete",
    )
    assert "repository_identity" not in historical[1]
    assert "ON CONFLICT (root_path)" in historical[1]


def test_direct_publication_forwards_optional_repository_identity() -> None:
    with patch(
        "repomap_kg.ops.direct_publication.run_staged_full_refresh",
        return_value=LoadSummary(repository_id=1, run_id=2, files=0),
    ) as staged:
        result = publish_observation_generation(
            ("psql",),
            (),
            repository_name="fixture",
            root_path="/workspace/current",
            repository_identity="repo1:fixture",
        )

    assert result.repository_id == 1
    assert staged.call_args.kwargs["repository_identity"] == "repo1:fixture"
