"""Source routing identity and discovery diagnostic contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from common_lore_index.extractors.config.nix_resolver import (
    NixResolution,
    ResolutionOutcome,
)
from common_lore_index.extractors.languages.python_modules import PythonModuleIndex
from common_lore_index.graph.discovery_extractors import (
    extract_awk_file_observations_from_file, extract_bash_file_observations_from_file,
    extract_bats_file_observations_from_file, extract_config_file_observations_from_file,
    extract_css_file_observations_from_file, extract_document_file_observations_from_file,
    extract_eml_file_observations_from_file, extract_feed_file_observations_from_file,
    extract_go_metadata_observations_from_file, extract_html_file_observations_from_file,
    extract_javascript_file_observations_from_file, extract_markdown_file_observations_from_file,
    extract_mbox_file_observations_from_file, extract_nix_file_observations_from_file,
    extract_python_file_observations_from_file, extract_ruby_file_observations_from_file,
    extract_shell_file_observations, extract_zsh_file_observations_from_file,
    extract_zunit_file_observations_from_file, markdown_anchor_index,
)
from common_lore_index.graph.discovery_records import FileInfo
from common_lore_index.graph.keys import (
    config_document_key,
    config_path_key,
    css_custom_property_key,
    css_document_key,
    css_rule_key,
    css_selector_key,
    doc_page_key,
    doc_section_key,
    file_key,
    html_anchor_key,
    html_document_key,
    html_element_key,
    xml_attribute_key,
    xml_document_key,
    xml_element_key,
)
from common_lore_index.graph.multi_source import SnapshotManifestEntry, SourceSnapshot, graph_source_binding_id
from common_lore_index.graph.multi_source_capture import MultiSourceCaptureError, _CapturedSource
from common_lore_index.graph.multi_source_routing import (
    _binding_view,
    _module_exports,
    _namespaced_observation,
    _rebase_graph_key,
    _resolved_observation,
    _validate_provenance,
)
from common_lore_index.observations.raw import RawObservation
from repomap_test_support.sealing_governance_fixtures import binding_for


def _source(
    *,
    alias: str = "entry",
    input_name: str | None = None,
    files: tuple[str, ...] = ("modules/default.nix",),
) -> _CapturedSource:
    root = Path("/fixture-root")
    config = replace(binding_for(alias, root), binding_id=graph_source_binding_id("fixture-graph", alias),
                     revision=3, role="entry", input_name=input_name)
    snapshot = SourceSnapshot.create(
        config.domain_binding("fixture-graph"),
        manifest_entries=tuple(SnapshotManifestEntry(path, hashlib.sha256(b"").hexdigest(), 0) for path in files),
        git_commit=None, git_tree=None, ignore_policy_id="ignore1:fixture", metadata_identity="meta1:fixture")
    return _CapturedSource(config, root, (), snapshot, ())


def _observation(*, kind: str = "file", source_id: str = "raw:file:1",
                  path: str = "docs/guide.md", name: str | None = "guide.md",
                  target: str | None = None,
                  metadata: dict[str, object] | None = None) -> RawObservation:
    return RawObservation(kind=kind, source_id=source_id, path=path, name=name,
                          target=target, confidence="extracted", extractor="fixture",
                          extractor_version="1.0", metadata=metadata or {})


@pytest.mark.parametrize(
    ("original", "expected"),
    (
        (file_key("docs/guide.md"), file_key("entry/docs/guide.md")),
        (doc_page_key(file_key("docs/guide.md")), doc_page_key(file_key("entry/docs/guide.md"))),
        (doc_section_key(file_key("docs/guide.md"), "/intro"), doc_section_key(file_key("entry/docs/guide.md"), "/intro")),
        (config_document_key(file_key("config/app.yaml")), config_document_key(file_key("entry/config/app.yaml"))),
        (config_path_key(file_key("config/app.yaml"), "/server/port"), config_path_key(file_key("entry/config/app.yaml"), "/server/port")),
        (css_document_key(file_key("web/site.css")), css_document_key(file_key("entry/web/site.css"))),
        (css_rule_key(file_key("web/site.css"), "/0"), css_rule_key(file_key("entry/web/site.css"), "/0")),
        (css_selector_key(file_key("web/site.css"), "/0"), css_selector_key(file_key("entry/web/site.css"), "/0")),
        (css_custom_property_key(file_key("web/site.css"), "--surface"), css_custom_property_key(file_key("entry/web/site.css"), "--surface")),
        (html_document_key(file_key("web/index.html")), html_document_key(file_key("entry/web/index.html"))),
        (html_element_key(file_key("web/index.html"), "/0"), html_element_key(file_key("entry/web/index.html"), "/0")),
        (html_anchor_key(file_key("web/index.html"), "intro"), html_anchor_key(file_key("entry/web/index.html"), "intro")),
        (xml_document_key(file_key("config/app.xml")), xml_document_key(file_key("entry/config/app.xml"))),
        (xml_element_key(file_key("config/app.xml"), "/0"), xml_element_key(file_key("entry/config/app.xml"), "/0")),
        (xml_attribute_key(file_key("config/app.xml"), "/0", "id"), xml_attribute_key(file_key("entry/config/app.xml"), "/0", "id")),
    ),
)
def test_rebase_graph_key_preserves_each_public_file_derived_namespace(original, expected):
    assert _rebase_graph_key(original, "entry") == expected


def test_namespaced_observation_rebases_public_keys_and_binds_snapshot_identity():
    assert (_rebase_graph_key("python.module:fixture.module", "entry"), _rebase_graph_key("not-a-canonical-key", "entry")) == ("python.module:fixture.module", "not-a-canonical-key")
    source = _source(files=("docs/guide.md",))
    original_file = file_key("docs/guide.md")
    raw = _observation(
        target=doc_section_key(original_file, "/intro"),
        metadata={
            "resolved_path": "docs/guide.md",
            "source_key": original_file,
            "page_key": doc_page_key(original_file),
            "source_element_key": html_element_key(original_file, "/0"),
        },
    )

    namespaced = _namespaced_observation(raw, source)

    assert namespaced.source_id == f"{source.config.binding_id}:raw:file:1"
    assert namespaced.path == "entry/docs/guide.md"
    assert namespaced.name == namespaced.path
    assert namespaced.target == doc_section_key(file_key("entry/docs/guide.md"), "/intro")
    expected_file = file_key("entry/docs/guide.md")
    assert namespaced.metadata["resolved_path"] == "entry/docs/guide.md"
    assert namespaced.metadata["source_key"] == expected_file
    assert namespaced.metadata["page_key"] == doc_page_key(expected_file)
    assert namespaced.metadata["source_element_key"] == html_element_key(expected_file, "/0")
    assert namespaced.metadata["source_relative_path"] == raw.path
    assert namespaced.metadata["graph_id"] == "fixture-graph"
    assert namespaced.metadata["snapshot_id"] == source.snapshot.snapshot_id


def test_module_exports_accept_fixture_local_forms_and_discard_unknown_paths():
    source = _source(files=("modules/default.nix", "modules/extra.nix"))
    extracted = (
        _observation(kind="file"),
        _observation(kind="nix.module_export", metadata={"module_name": None, "export_path": "modules/default.nix"}),
        _observation(
            kind="nix.module_export",
            metadata={
                "module_name": "default",
                "resolved_path": "file:entry/./modules/default.nix",
            },
        ),
        _observation(
            kind="nix.module_export",
            metadata={
                "module_name": "default",
                "export_path": "./modules/default.nix",
            },
        ),
        _observation(
            kind="nix.module_export",
            metadata={
                "module_name": "extra",
                "export_path": "modules/extra.nix",
            },
        ),
        _observation(
            kind="nix.module_export",
            metadata={"module_name": "missing", "export_path": "modules/nope.nix"},
        ),
    )

    exports = _module_exports(source, extracted)

    assert exports == {
        "default": ("modules/default.nix",),
        "extra": "modules/extra.nix",
    }
    view = _binding_view(source, exports)
    assert view.input_name == "entry"
    assert view.files == frozenset(source_file.relative_path for source_file in source.snapshot.manifest_entries)
    assert view.module_exports == exports


def _provenance_observation(source: _CapturedSource) -> RawObservation:
    return _observation(source_id=f"{source.config.binding_id}:file:docs/guide.md",
        path="entry/docs/guide.md", metadata={
            "graph_id": "fixture-graph", "binding_id": source.config.binding_id,
            "binding_alias": "entry", "binding_role": "entry", "binding_revision": 3,
            "snapshot_id": source.snapshot.snapshot_id,
            "snapshot_manifest_digest": source.snapshot.manifest_digest,
            "source_relative_path": "docs/guide.md", "candidate_id": "cand1:expected",
        })


@pytest.mark.parametrize(
    ("mutation", "value"),
    (
        ("binding_id", "bind1:wrong"),
        ("binding_alias", "other"),
        ("graph_id", "other-graph"),
        ("binding_role", "module"),
        ("binding_revision", 4),
        ("snapshot_id", "snap1:wrong"),
        ("snapshot_manifest_digest", "dig1:wrong"),
        ("source_relative_path", "docs/other.md"),
        ("candidate_id", "cand1:wrong"),
    ),
)
def test_validate_provenance_rejects_each_tampered_public_identity_field(mutation, value):
    source = _source(files=("docs/guide.md",))
    observation = _provenance_observation(source)
    metadata = dict(observation.metadata)
    metadata[mutation] = value
    observation = RawObservation(**{**observation.__dict__, "metadata": metadata})

    with pytest.raises(MultiSourceCaptureError) as raised:
        _validate_provenance((observation,), (source,), candidate_id="cand1:expected")

    assert str(raised.value) == "source observation provenance is invalid"
    assert raised.value.category == "source_capture"


def test_resolved_observation_projects_exact_cross_binding_to_public_file_key():
    source = _source(files=("modules/default.nix",))
    observation = _provenance_observation(source)
    resolution = NixResolution(
        observation=observation,
        outcome=ResolutionOutcome.EXACT,
        source_binding="entry",
        target_binding="composition",
        target_path="composition/modules/default.nix",
        cross_binding=True,
    )

    resolved = _resolved_observation(resolution, candidate_id="cand1:expected")

    assert resolved.kind == "nix.import"
    assert resolved.target == "file:composition/modules/default.nix"
    assert resolved.metadata["candidate_id"] == "cand1:expected"
    assert resolved.metadata["resolution_outcome"] == "exact"
    assert resolved.metadata["resolution_evidence_class"] == "static-literal"
    assert resolved.metadata["cross_binding"] is True
    assert resolved.metadata["source_binding"] == "entry"
    assert resolved.metadata["target_binding"] == "composition"
    assert resolved.metadata["resolved_path"] == "composition/modules/default.nix"


def test_text_adapters_fail_closed_on_non_utf8_without_observations(tmp_path):
    cases: tuple[tuple[Callable[..., tuple[RawObservation, ...]], str, dict[str, Any]], ...] = (
        (extract_shell_file_observations, "probe.sh", {}),
        (extract_bash_file_observations_from_file, "probe.sh", {}),
        (extract_bats_file_observations_from_file, "probe.bats", {}),
        (extract_awk_file_observations_from_file, "probe.awk", {}),
        (extract_zsh_file_observations_from_file, "probe.zsh", {}),
        (extract_zunit_file_observations_from_file, "probe.zunit", {}),
        (extract_python_file_observations_from_file, "probe.py", {"module_index": PythonModuleIndex.empty()}),
        (extract_nix_file_observations_from_file, "flake.nix", {}),
        (extract_config_file_observations_from_file, "settings.yaml", {}),
        (extract_go_metadata_observations_from_file, "metadata.go", {}),
        (extract_ruby_file_observations_from_file, "probe.rb", {"repository_paths": frozenset()}),
        (extract_javascript_file_observations_from_file, "probe.js", {"repository_paths": frozenset()}),
        (extract_feed_file_observations_from_file, "feed.xml", {}),
        (extract_html_file_observations_from_file, "page.html", {}),
        (extract_css_file_observations_from_file, "style.css", {}),
    )
    for adapter, relative_path, kwargs in cases:
        (tmp_path / relative_path).write_bytes(b"\xff\xfe\x00")
        assert adapter(tmp_path, relative_path, **kwargs) == ()

    markdown_path = tmp_path / "notes.md"
    markdown_path.write_bytes(b"\xff\xfe\x00")
    info = FileInfo("notes.md", "markdown", "source", "hash", False, False)
    assert extract_markdown_file_observations_from_file(
        tmp_path,
        info,
        repository_paths=frozenset({"notes.md"}),
        markdown_anchors={},
    ) == ()


def test_nix_adapter_preserves_source_path_and_flake_identity():
    root = Path("src/test/fixtures/multi_source_nix_constellation/composition")
    content = (root / "flake.nix").read_text(encoding="utf-8")
    sentinel = (_observation(kind="nix.module_export"),)
    with patch(
        "common_lore_index.graph.discovery_extractors.extract_nix_file_observations",
        return_value=sentinel,
    ) as parser:
        assert extract_nix_file_observations_from_file(
            root, "flake.nix", include_input_references=True
        ) is sentinel
        parser.assert_called_once_with("flake.nix", content, flake_ref="composition", include_input_references=True)
        parser.reset_mock()
        assert extract_nix_file_observations_from_file(root, "flake.nix", flake_ref="fixture-ref") is sentinel
        parser.assert_called_once_with("flake.nix", content, flake_ref="fixture-ref", include_input_references=False)


def test_markdown_anchor_index_keeps_public_anchor_identity_and_skips_nontext(tmp_path):
    (tmp_path / "README.md").write_text("# Intro\n## Second Section\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not markdown\n", encoding="utf-8")
    (tmp_path / "broken.md").write_bytes(b"\xff\xfe\x00")
    infos = (
        FileInfo("README.md", "markdown", "source", "h1", False, False),
        FileInfo("notes.txt", "text", "source", "h2", False, False),
        FileInfo("broken.md", "markdown", "source", "h3", False, False),
    )

    anchors = markdown_anchor_index(tmp_path, infos)

    assert anchors == {"README.md": frozenset({"intro", "second-section"})}


@pytest.mark.parametrize(
    ("adapter", "relative_path", "kind", "format_name", "source_suffix"),
    (
        (extract_eml_file_observations_from_file, "missing.eml", "email.parse_error", "eml", "email-parse-error:read"),
        (extract_mbox_file_observations_from_file, "missing.mbox", "email.parse_error", "mbox", "email-parse-error:read"),
        (extract_document_file_observations_from_file, "missing.odt", "document.parse_error", "odt", "document-parse-error:read"),
    ),
)
def test_file_adapters_emit_stable_read_error_diagnostics(
    tmp_path, adapter, relative_path, kind, format_name, source_suffix
):
    observations = adapter(tmp_path, relative_path)

    assert len(observations) == 1
    observation = observations[0]
    assert observation.kind == kind
    assert observation.source_id == f"{relative_path}#{source_suffix}"
    assert observation.path == relative_path
    assert observation.metadata["format"] == format_name
    assert observation.metadata["error_kind"] == "read-error"
    assert observation.metadata["recovered"] is False


def test_document_adapter_distinguishes_decode_diagnostics(tmp_path):
    path = tmp_path / "broken.txt"
    path.write_bytes(b"\xff\xfe\x00")

    observations = extract_document_file_observations_from_file(tmp_path, "broken.txt")

    assert len(observations) == 1
    observation = observations[0]
    assert observation.kind == "document.parse_error"
    assert observation.source_id == "broken.txt#document-parse-error:decode"
    assert observation.metadata == {
        "format": "txt",
        "parser": "stdlib-document-conservative",
        "error_kind": "decode-error",
        "message_summary": "file is not valid UTF-8",
        "recovered": False,
    }
