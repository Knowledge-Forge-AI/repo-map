"""Real fixture acquisition preserves prior artifacts through refusal and recovery."""

import json
from pathlib import Path
import shutil

import pytest

from repomap_kg.ops.ingestion.api import ApiPolicyError, acquire_api_source
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_test_support.source_ingestion_integration import api_fixture_root
from repomap_test_support.run25_acquisition_fixtures import snapshot_directory_state


@pytest.mark.parametrize("response", [
    {"status": "ready"}, [{"id": "first"}, {"id": "second"}], "ready",
], ids=["mapping-without-items", "top-level-list", "scalar"])
def test_response_shape_survives_acquisition_rows_and_failed_replacement(tmp_path: Path, response):
    source = tmp_path / "source"
    shutil.copytree(api_fixture_root() / "readonly_fixture_api", source)
    config = source / "api-source.toml"
    original_config = config.read_text().replace("max_items_per_run = 100", f"max_items_per_run = {len(response) if isinstance(response, list) else 1}")
    config.write_text(original_config)
    response_path = source / "responses/items.json"
    encoded = json.dumps(response)
    response_path.write_text(encoded)
    summary = acquire_api_source(config, root_path=tmp_path)
    assert summary.requests == summary.responses == 1
    assert summary.publication.publication_state == "not_published"
    before = snapshot_directory_state(summary.output_path)
    assert "redacted-responses.jsonl" in before
    rows = build_staged_rows(summary.raw_observations, repository_name="slice19", stage_id="acquired")
    try:
        raw = list(rows.family_rows["raw_observations"])
        assert rows.row_counts["raw_observations"] == len(summary.raw_observations)
        assert [row["payload_json"] for row in raw] == [item.to_dict() for item in summary.raw_observations]
        assert any(row["kind"] == "api.response" for row in raw)
    finally:
        rows.close()

    # The per-run item budget couples each response-shape branch to refusal.
    # Two identical endpoints exceed the exact successful single-response limit.
    prior_runs = snapshot_directory_state(summary.output_path.parent)
    endpoint = original_config[original_config.index("[[endpoints]]"):]
    config.write_text(original_config + "\n" + endpoint.replace('name = "items"', 'name = "second"'))
    with pytest.raises(ApiPolicyError, match="response items exceed max_items_per_run"):
        acquire_api_source(config, root_path=tmp_path)
    assert snapshot_directory_state(summary.output_path.parent) == prior_runs
    config.write_text(original_config)
    response_path.write_bytes(b"\xff")
    with pytest.raises(ApiPolicyError, match="did not return safe JSON"):
        acquire_api_source(config, root_path=tmp_path)
    assert snapshot_directory_state(summary.output_path) == before
    assert snapshot_directory_state(summary.output_path.parent) == prior_runs
    response_path.write_text(encoded)
    recovered = acquire_api_source(config, root_path=tmp_path)
    assert recovered.raw_observations == summary.raw_observations
    assert recovered.response_records == summary.response_records
    assert snapshot_directory_state(recovered.output_path) == before
