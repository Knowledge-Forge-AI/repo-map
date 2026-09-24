"""Quoted HCL delimiters preserve following declarations through staged rows."""

import json

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_test_support.composition_extraction_fixtures import create_composition_graph_config


HCL = r'''variable "message" {
  type = string
  default = "a quoted \" } # // [ marker"
  description = "Keep \" delimiters literal"
}
resource "fixture_item" "first" {
  value = var.message
  lifecycle {
    prevent_destroy = true
  }
}
output "result" {
  value = fixture_item.first.id
  sensitive = true
}
'''


def test_escaped_delimiters_do_not_swallow_following_blocks_and_rows(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    path = project / "main.tf"
    path.write_text(HCL)
    config = create_composition_graph_config(project)
    captured = capture_multi_source_candidate(config)
    observations = captured.observations
    resources = [item for item in observations if item.kind == "terraform.resource"]
    assert [item.name for item in resources] == ["fixture_item.first"]
    assert resources[0].metadata["lifecycle_present"] is True
    variables = [item for item in observations if item.kind == "terraform.variable"]
    assert [item.name for item in variables] == ["message"]
    assert variables[0].metadata["default_value_type"] == "string"
    outputs = [item for item in observations if item.kind == "terraform.output"]
    assert [item.name for item in outputs] == ["result"]
    assert outputs[0].metadata["sensitive"] is True
    canonical = canonicalize_observations(observations, repository_scope="slice20")
    assert canonical.ok
    rows = build_staged_rows(observations, repository_name="slice20", stage_id="quoted")
    try:
        raw = list(rows.family_rows["raw_observations"])
        assert rows.row_counts["canonical_edges"] == len(canonical.graph.edges)
        assert [row["payload_json"] for row in raw if row["kind"] == "terraform.resource"] == [resources[0].to_dict()]
        assert "a quoted" not in json.dumps([item.to_dict() for item in observations])
    finally:
        rows.close()
    # A real structural change, unlike quoted punctuation, removes a declaration.
    path.write_text(HCL[:HCL.index('output "result"')])
    changed = capture_multi_source_candidate(config)
    assert changed.source_generation != captured.source_generation
    assert not any(item.kind == "terraform.output" for item in changed.observations)
    path.write_text(HCL)
    recovered = capture_multi_source_candidate(config)
    assert recovered.source_generation == captured.source_generation
    assert recovered.observations == observations
