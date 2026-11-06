from __future__ import annotations

from unittest.mock import patch

from common_lore_index.ops.direct_publication import publish_observation_generation
from common_lore_index.storage import LoadSummary, repository_run_prefix_sql


def test_repository_run_prefix_selects_stable_or_historical_identity() -> None:
    stable = repository_run_prefix_sql(
        repository_name="fixture",
        root_path="/workspace/current",
        repository_identity="repo1:fixture",
        git_commit=None,
        run_status="complete",
    )
    stable_upsert = next(sql for sql in stable if sql.startswith("INSERT INTO repositories"))
    assert "name, root_path, repository_identity" in stable_upsert
    assert "ON CONFLICT (repository_identity)" in stable_upsert
    assert "WHERE repository_identity IS NOT NULL" in stable_upsert
    assert "root_path = EXCLUDED.root_path" in stable_upsert

    historical = repository_run_prefix_sql(
        repository_name="fixture",
        root_path="/workspace/current",
        git_commit=None,
        run_status="complete",
    )
    historical_upsert = next(sql for sql in historical if sql.startswith("INSERT INTO repositories"))
    assert "repository_identity" not in historical_upsert
    assert "ON CONFLICT (root_path)" in historical_upsert


def test_direct_publication_forwards_optional_repository_identity() -> None:
    with patch(
        "common_lore_index.ops.direct_publication.run_staged_full_refresh",
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
