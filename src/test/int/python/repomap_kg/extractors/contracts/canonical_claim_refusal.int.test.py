"""ADR 0154 offline raw JSONL through the public canonicalization refusal boundary.

The fixture repository is synthetic and public-safe. RepoMap's static legacy
discovery reads it; nothing in it is executed, and it contains no Go source so
no helper process starts.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from common_lore_index.canonicalization import canonicalize_observations
from common_lore_index.canonicalization.claim_guard import CLAIM_REFUSED_CATEGORY
from common_lore_index.extractors.contracts.bounded_io import open_directory
from common_lore_index.extractors.contracts.legacy_registry import (
    LEGACY_ENTRYPOINTS,
    is_legacy_extractor_name,
)
from common_lore_index.extractors.contracts.receipt_codec import load_receipt, store_receipt
from common_lore_index.extractors.contracts.vocabulary import RECEIPT_REFERENCE_METADATA_KEY
from common_lore_index.graph.discovery import discover_observations
from common_lore_index.observations.raw import (
    RawObservation,
    read_observations_jsonl,
    write_observations_jsonl,
)
from repomap_test_support.extractor_contracts.receipt_fixtures import receipt

FIXTURE = {
    "README.md": "# Fixture\n\nSee [the tool](tool.py).\n\n```rust\nfn main() {}\n```\n",
    "tool.py": "import json\n\n\ndef run() -> str:\n    return json.dumps({})\n",
    "scripts/build.sh": "#!/usr/bin/env bash\nset -eu\necho build\n",
    "src/lib.rs": "pub fn add(left: u64, right: u64) -> u64 {\n    left + right\n}\n",
    "src/main.rs": "#![allow(clippy::shadow_unrelated)]\nfn main() {}\n",
    "config.toml": "[tool]\nname = \"fixture\"\n",
}


@pytest.fixture
def repository() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="cloe-claims-") as temporary:
        root = Path(temporary) / "repo"
        for relative, text in FIXTURE.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        yield root


def _names_by_language(observations: list[RawObservation]) -> dict[str, set[str]]:
    languages = {item.path: item.metadata["language"] for item in observations if item.kind == "file"}
    allowed: dict[str, set[str]] = {}
    for entry in LEGACY_ENTRYPOINTS.values():
        for selector in entry.selectors:
            allowed.setdefault(selector, set()).update(entry.extractor_names)
    return {path: allowed.get(language, set()) | allowed["*"] for path, language in languages.items()}


def test_legacy_discovery_outputs_are_registered_and_stable(repository: Path) -> None:
    first = discover_observations(repository)
    assert discover_observations(repository) == first
    assert all(is_legacy_extractor_name(item.extractor) for item in first)
    allowed = _names_by_language(first)
    for item in first:
        if item.path in allowed:
            assert item.extractor in allowed[item.path], (item.path, item.extractor)
    rust_library = [item for item in first if item.path == "src/lib.rs"]
    assert [(item.kind, item.extractor, item.metadata["language"]) for item in rust_library] == [
        ("file", "repo-discovery", "unknown")
    ]
    fences = [item for item in first if item.kind == "markdown.code_fence"]
    assert [(item.path, item.metadata["language"]) for item in fences] == [("README.md", "rust")]
    result = canonicalize_observations(first)
    assert not [item for item in result.diagnostics if item.category == CLAIM_REFUSED_CATEGORY]
    fence_evidence = [item for item in result.graph.evidence if item.raw_kind == "markdown.code_fence"]
    assert [(item.path, item.metadata.get("language")) for item in fence_evidence] == [
        ("README.md", "rust")
    ]


def test_offline_raw_jsonl_claims_are_refused_and_legacy_is_preserved(repository: Path) -> None:
    legacy = discover_observations(repository)
    with tempfile.TemporaryDirectory(prefix="cloe-raw-") as temporary:
        receipts = Path(temporary) / "receipts"
        receipts.mkdir(mode=0o700)
        fd = open_directory(receipts)
        try:
            digest = store_receipt(fd, receipt())
            assert load_receipt(fd, digest) == receipt()
        finally:
            os.close(fd)
        rs_file = next(item for item in legacy if item.path == "src/lib.rs")
        python = next(item for item in legacy if item.path == "tool.py" and item.kind != "file")
        forged = [
            replace(rs_file, metadata={**rs_file.metadata, "language": "rust"}),
            replace(rs_file, extractor="example-rust-parser",
                    metadata={**rs_file.metadata, "achieved_capabilities": ["syntax.tree"]}),
            replace(python, path="src/lib.rs",
                    metadata={**python.metadata, RECEIPT_REFERENCE_METADATA_KEY: digest}),
            replace(python, metadata={**python.metadata, "parent_witness": True,
                                      "effect_vector": {"network": "none"}}),
            RawObservation(kind="rust.function", source_id="src/lib.rs#fn:add", path="src/lib.rs",
                           confidence="unknown", extractor="example-rust-parser",
                           extractor_version="1", start_line=1, end_line=3, name="add"),
        ]
        raw_template = forged[-1]
        forged.extend(replace(raw_template, kind=kind, source_id="src/lib.rs#" + kind)
                      for kind in ("rust.parse", "rust.item", "rust.unsupported"))
        legacy_path = Path(temporary) / "legacy.jsonl"
        mixed_path = Path(temporary) / "mixed.jsonl"
        write_observations_jsonl(legacy, legacy_path)
        write_observations_jsonl([*legacy, *forged], mixed_path)
        raw_legacy = read_observations_jsonl(legacy_path)
        raw_mixed = read_observations_jsonl(mixed_path)
    assert [item.to_json_line() for item in raw_mixed[len(legacy):]] == [
        item.to_json_line() for item in forged
    ]
    assert all(item.schema_version == 1 for item in raw_mixed)
    assert set(raw_mixed[len(legacy) + 2].to_dict()) == set(python.to_dict())
    baseline = canonicalize_observations(raw_legacy)
    result = canonicalize_observations(raw_mixed)
    assert result.graph.nodes == baseline.graph.nodes
    assert result.graph.edges == baseline.graph.edges
    assert result.graph.evidence == baseline.graph.evidence
    start = len(legacy)
    refused = [item for item in result.diagnostics if item.category == CLAIM_REFUSED_CATEGORY]
    assert [(item.raw_observation_ordinal, item.value) for item in refused] == [
        (start, "rust_language_claim"),
        (start + 1, "capability_claim_metadata"),
        (start + 2, "receipt_reference_metadata"),
        (start + 3, "capability_claim_metadata"),
        (start + 5, "rust_raw_kind"),
        (start + 6, "rust_raw_kind"),
        (start + 7, "rust_raw_kind"),
    ]
    unsupported = [item for item in result.diagnostics
                   if item.category == "unsupported_raw_observation_kind"
                   and item.raw_observation_ordinal == start + 4]
    assert len(unsupported) == 1
    assert [item for item in result.diagnostics
            if item not in refused and item not in unsupported] == list(baseline.diagnostics)
    rendered = repr([item.to_dict() for item in refused])
    assert digest not in rendered and "syntax.tree" not in rendered
    language = [node.metadata.get("language") for node in result.graph.nodes
                if node.display_name == "src/lib.rs"]
    assert language == ["unknown"]
