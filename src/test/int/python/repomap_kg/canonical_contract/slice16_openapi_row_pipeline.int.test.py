"""Static OpenAPI references remain bounded through canonical staged-row composition."""
import json
from pathlib import Path
import pytest
from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_test_support.composition_extraction_fixtures import create_composition_graph_config


@pytest.mark.parametrize("reference,scope,redacted,reason,target_prefix", [
    ("https://fixture-user:fixture-password@example.invalid/schema.json", "remote", True, "credentialed-url", "external:url:"),
    ("../../../outside.json", "local_file", True, "local-ref-outside-root", "unknown:file:"),
    ("https://example.invalid/schema.json", "remote", False, None, "external.url:"),
    ("#/components/schemas/Pet", "internal", False, None, "config.path:"),
], ids=["credentialed", "outside-root", "remote", "internal"])
def test_reference_privacy_survives_extraction_canonicalization_and_rows(tmp_path: Path, reference, scope, redacted, reason, target_prefix):
    project = tmp_path / "project"
    project.mkdir()
    document = {"openapi": "3.0.3", "info": {"title": "Fixture", "version": "1"},
                "paths": {}, "components": {"schemas": {"Pet": {"type": "object"}, "Alias": {"$ref": reference}}}}
    (project / "openapi.json").write_text(json.dumps(document))
    candidate = capture_multi_source_candidate(create_composition_graph_config(project))
    references = [item for item in candidate.observations if item.kind == "openapi.reference"]
    assert len(references) == 1
    observation = references[0]
    assert observation.metadata["reference_scope"] == scope
    assert observation.metadata["redacted"] is redacted
    assert observation.metadata.get("redaction_reason") == reason
    assert observation.metadata["not_fetched"] is True
    assert observation.target is not None and observation.target.startswith(target_prefix)
    assert "fixture-password" not in json.dumps(observation.to_dict())
    result = canonicalize_observations(candidate.observations, repository_scope="slice16")
    assert result.ok
    # OpenAPI profile records are retained raw; canonical support is config.*.
    assert not any(item.raw_kind == "openapi.reference" for item in result.graph.evidence)
    assert any(diagnostic.raw_source_id == observation.source_id and diagnostic.category == "unsupported_raw_observation_kind" for diagnostic in result.diagnostics)
    rows = build_staged_rows(candidate.observations, repository_name="slice16", stage_id="stage-a")
    try:
        assert rows.files == 1
        assert rows.row_counts["raw_observations"] == len(candidate.observations)
        assert rows.row_counts["canonical_edges"] == len(result.graph.edges)
        raw = [row for row in rows.family_rows["raw_observations"] if row["kind"] == "openapi.reference"]
        assert len(raw) == 1 and raw[0]["payload_json"] == observation.to_dict()
        encoded = json.dumps({family: list(items) for family, items in rows.family_rows.items()})
        assert "fixture-password" not in encoded
        assert observation.target in encoded
    finally:
        rows.close()
