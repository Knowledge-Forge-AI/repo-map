"""Documented-API acquisition admits all responses before writing redacted artifacts."""

from pathlib import Path
import json

import pytest

from repomap_kg.ops.ingestion.api import ApiPolicyError, acquire_api_source
from repomap_test_support.policy_helper_branches import write_api_fixture


def _two_endpoint_fixture(root: Path):
    config = write_api_fixture(root)
    text = config.read_text()
    endpoint = text[text.index("[[endpoints]]"):]
    endpoint = endpoint.replace('name = "items"', 'name = "events"')
    endpoint = endpoint.replace('path = "/v1/items"', 'path = "/v1/events"')
    endpoint = endpoint.replace('"responses/items.json"', '"responses/events.json"')
    config.write_text(text + "\n" + endpoint)
    response = config.parent / "responses" / "events.json"
    response.write_text('{"items":[{"id":"event-1"}]}\n')
    return config, response


@pytest.mark.parametrize("failure", ["bytes", "items", "json", "utf8", "missing", "symlink"])
def test_later_response_refusal_preserves_existing_runs_and_writes_no_partial_artifact(tmp_path, failure):
    config, later = _two_endpoint_fixture(tmp_path)
    run_root = tmp_path / ".repomap" / "api-runs"
    run_root.mkdir(parents=True)
    prior = run_root / "prior.txt"
    prior.write_bytes(b"previous owned receipt\n")
    before = {str(p.relative_to(run_root)): p.read_bytes() for p in run_root.rglob("*") if p.is_file()}
    if failure == "bytes":
        # First response fits exactly; the second exceeds the complete run budget.
        limit = (config.parent / "responses" / "items.json").stat().st_size
        config.write_text(config.read_text().replace("max_bytes_per_run = 1048576", f"max_bytes_per_run = {limit}"))
        message = "response bytes exceed max_bytes_per_run"
    elif failure == "items":
        config.write_text(config.read_text().replace("max_items_per_run = 100", "max_items_per_run = 1"))
        message = "response items exceed max_items_per_run"
    elif failure in {"json", "utf8"}:
        later.write_bytes(b'{"items":' if failure == "json" else b'\xff')
        message = "endpoint events did not return safe JSON"
    elif failure == "missing":
        later.unlink()
        message = "fixture response is not readable for endpoint events"
    else:
        foreign = tmp_path / "outside-config.json"
        foreign.write_bytes(b'{"items":[]}\n')
        later.unlink()
        later.symlink_to(foreign)
        message = "fixture response path escapes repository root"
    with pytest.raises(ApiPolicyError, match=message):
        acquire_api_source(config, root_path=tmp_path)
    after = {str(p.relative_to(run_root)): p.read_bytes() for p in run_root.rglob("*") if p.is_file()}
    assert after == before
    assert not any(p.is_dir() for p in run_root.iterdir())
    if failure == "symlink":
        assert foreign.read_bytes() == b'{"items":[]}\n'


def test_complete_fixture_acquisition_persists_only_redacted_downstream_artifacts(tmp_path):
    config, later = _two_endpoint_fixture(tmp_path)
    later.write_text(json.dumps({"items": [{"id": "event-1", "Access-Token": "fixture-token-value"}]}))
    result = acquire_api_source(config, root_path=tmp_path)
    assert (result.requests, result.responses) == (2, 2)
    assert result.publication.publication_state == "not_published"
    output = result.output_path
    assert output.is_relative_to(tmp_path)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["manifest_sha256"] == result.manifest.manifest_sha256
    assert manifest["no_network"] is True and manifest["no_mutation"] is True
    assert manifest["no_credentials_resolved"] is True
    artifacts = output / "artifacts"
    assert {p.name for p in artifacts.iterdir()} == {"items.json", "events.json"}
    event = json.loads((artifacts / "events.json").read_text())
    assert event["items"][0]["id"] == "event-1"
    assert event["items"][0]["Access-Token"]["redacted"] is True
    for path in output.rglob("*"):
        if path.is_file():
            payload = path.read_text()
            assert "fixture-token-value" not in payload
            assert "fixture-secret-value" not in payload
            assert "fixture-api-token" not in payload
    assert result.response_records[1].response_sha256
    assert result.response_records[1].response_byte_count == later.stat().st_size
    serialized = json.dumps(result.to_jsonable())
    assert str(tmp_path) not in serialized
    assert "fixture-token-value" not in serialized
    assert all(observation.metadata["api_run_id"] == result.api_run_id for observation in result.raw_observations)
