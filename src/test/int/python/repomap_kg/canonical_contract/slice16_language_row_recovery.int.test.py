"""Caller-driven malformed language observations refuse rows and recover exactly."""
from dataclasses import replace
import pytest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.staged_rows import build_staged_rows


CASES = [
    ("python-module-name", "python.module", "pkg.app", {}, None, {}, "module name"),
    ("python-function-module", "python.function", "serve", {"module": "pkg.app"}, "serve", {}, "module metadata"),
    ("python-function-name", "python.function", "serve", {"module": "pkg.app"}, None, {"module": "pkg.app"}, "requires name"),
    ("python-method-class", "python.method", "serve", {"module": "pkg.app", "class": "App"}, "serve", {"module": "pkg.app"}, "class metadata"),
    ("ruby-source-namespace", "ruby.class", "App", {}, "App", {"source_key": "python.module:pkg"}, "unsupported namespace"),
    ("ruby-test-owner-missing", "ruby.test_method", "test_run", {"test_case_key": "ruby.test_case:test%2Fapp.rb:AppTest"}, "test_run", {}, "test_case_key"),
    ("ruby-test-owner-namespace", "ruby.test_method", "test_run", {"test_case_key": "ruby.test_case:test%2Fapp.rb:AppTest"}, "test_run", {"test_case_key": "ruby.class:App"}, "test_case_key"),
    ("ruby-method-owner", "ruby.method", "run", {"owner": "App"}, "run", {}, "owner metadata"),
    ("ruby-method-owner-kind", "ruby.method", "run", {"owner": "App"}, "run", {"owner": "App", "owner_kind": "python.class"}, "unsupported namespace"),
    ("ruby-class-name", "ruby.class", "App", {}, None, {}, "name or target"),
    ("ruby-method-target-owner", "ruby.method", "run", {"source_key": "ruby.class:App", "owner": "App"}, "run", {"source_key": "ruby.class:App"}, "owner metadata"),
    ("ruby-singleton-target-owner", "ruby.singleton_method", "instance", {"source_key": "ruby.class:App", "owner": "App"}, "instance", {"source_key": "ruby.class:App"}, "owner metadata"),
    ("ruby-constant-target-owner", "ruby.constant", "PORT", {"source_key": "ruby.class:App", "owner": "App"}, "PORT", {"source_key": "ruby.class:App"}, "owner metadata"),
    ("ruby-test-target-owner", "ruby.test_method", "test_run", {"source_key": "ruby.class:App", "test_case_key": "ruby.test_case:test%2Fapp.rb:AppTest"}, "test_run", {"source_key": "ruby.class:App"}, "test_case_key"),
    ("ruby-route-pointer", "ruby.route", "index", {"route_pointer": "/routes/index"}, "index", {}, "route_pointer"),
]


@pytest.mark.parametrize("case,kind,name,metadata,bad_name,bad_metadata,message", CASES,
                         ids=[case[0] for case in CASES])
def test_language_row_refusal_then_exact_recovery(case, kind, name, metadata, bad_name, bad_metadata, message):
    observation = RawObservation(kind=kind, source_id="fixture:" + case, path="pkg/app.rb",
                                 name=name, confidence="extracted", extractor="fixture-language",
                                 extractor_version="1", metadata=metadata)
    valid = canonicalize_observations((observation,))
    assert valid.ok and not valid.diagnostics
    assert len(valid.graph.edges) == 1
    original = build_staged_rows((observation,), repository_name="slice16", stage_id="stage-a")
    try:
        original_rows = {family: tuple(rows) for family, rows in original.family_rows.items()}
        bad = replace(observation, name=bad_name, metadata=bad_metadata)
        rejected = canonicalize_observations((bad,))
        assert not rejected.ok
        assert any(message in diagnostic.message for diagnostic in rejected.diagnostics)
        assert not rejected.graph.edges
        with pytest.raises(StorageSchemaError, match=message):
            build_staged_rows((bad,), repository_name="slice16", stage_id="stage-a")
        recovered = build_staged_rows((observation,), repository_name="slice16", stage_id="stage-a")
        try:
            assert recovered.checksums == original.checksums
            assert {family: tuple(rows) for family, rows in recovered.family_rows.items()} == original_rows
            assert recovered.row_counts["raw_observations"] == 1
            assert recovered.row_counts["canonical_edges"] == 1
            assert recovered.row_counts["canonical_evidence"] == 1
            assert recovered.row_counts["canonical_edge_evidence"] == 1
            assert recovered.row_counts["canonical_node_evidence"] == 2
        finally:
            recovered.close()
    finally:
        original.close()
