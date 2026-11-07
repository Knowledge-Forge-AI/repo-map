"""ADR 0154: no positive witness path and pre-dispatch claim refusal.

Contract doubles here prove only refusal logic and establish no native evidence.
"""

from __future__ import annotations

import copy
import pickle
from dataclasses import replace
from typing import Any, cast

import pytest

from common_lore_index.canonicalization import canonicalize_observations
from common_lore_index.canonicalization.claim_guard import (
    CLAIM_REFUSED_CATEGORY,
    capability_claim_reason,
    find_claim_refusals,
)
from common_lore_index.canonicalization.dispatch import CanonicalizationState
from common_lore_index.extractors.contracts.receipt_codec import encode_receipt, receipt_digest
from common_lore_index.extractors.contracts.vocabulary import (
    RECEIPT_REFERENCE_METADATA_KEY,
    ContractError,
)
from common_lore_index.extractors.contracts.witness import (
    NATIVE_OBSERVER_UNAVAILABLE,
    REQUIRED_BINDINGS,
    ObservationBatch,
    ParentWitness,
    refuse_capability_admission,
)
from common_lore_index.observations.raw import RawObservation
from repomap_test_support.extractor_contracts.receipt_fixtures import receipt

SECRET = "PRIVATE-PAYLOAD-VALUE"


def _file(path: str, language: str = "unknown", **metadata: Any) -> RawObservation:
    return RawObservation(
        kind="file", source_id=path, path=path, name=path, confidence="extracted",
        extractor="repo-discovery", extractor_version="0.0.3",
        metadata={"language": language, "role": "source", "content_hash": "sha256:" + "0" * 64,
                  "executable": False, "generated": False, **metadata},
    )


def _content(kind: str, path: str, **metadata: Any) -> RawObservation:
    return RawObservation(
        kind=kind, source_id=f"{path}#{kind}:1", path=path, confidence="extracted",
        extractor="repo-markdown", extractor_version="0.0.3", start_line=1, end_line=3,
        metadata=metadata,
    )


def _python(path: str, **metadata: Any) -> RawObservation:
    return RawObservation(
        kind="python.function", source_id=f"{path}#function:run", path=path, name="run",
        confidence="extracted", extractor="repo-python", extractor_version="0.0.3",
        start_line=1, end_line=2, metadata={"module": "tool", **metadata},
    )


def test_parent_witness_cannot_be_constructed_copied_or_pickled() -> None:
    with pytest.raises(ContractError) as raised:
        ParentWitness()
    assert raised.value.code == NATIVE_OBSERVER_UNAVAILABLE
    forged = object.__new__(ParentWitness)
    for action in (lambda: copy.copy(forged), lambda: copy.deepcopy(forged),
                   lambda: pickle.dumps(forged)):
        with pytest.raises(ContractError):
            action()


@pytest.mark.parametrize("evidence", [
    True, 1, "0" * 64, b"nonce", {"admitted": True, "witness": "parent"},
    lambda *_args: True, receipt(), object.__new__(ParentWitness), None,
])
def test_no_input_manufactures_admission(evidence: object) -> None:
    refusal = refuse_capability_admission(evidence)
    assert refusal.code == NATIVE_OBSERVER_UNAVAILABLE
    assert refusal.missing_bindings == REQUIRED_BINDINGS
    assert not hasattr(refusal, "admitted")


def test_observation_batch_preserves_raw_schema_and_has_no_witnessed_origin() -> None:
    items = (_file("src/lib.rs"), _python("tool.py"))
    batch = ObservationBatch.from_observations("offline-raw", list(items))
    assert batch.observations == items
    assert [item.to_dict() for item in batch.observations] == [item.to_dict() for item in items]
    assert batch.capability_admission().code == NATIVE_OBSERVER_UNAVAILABLE
    for origin in ("parent-witnessed", "native", "", None):
        with pytest.raises(ContractError):
            ObservationBatch(origin=cast(Any, origin), observations=items)
    with pytest.raises(ContractError):
        ObservationBatch("legacy-discovery", cast(Any, (items[0].to_dict(),)))


def test_batch_rejects_unbounded_iterables_before_consumption() -> None:
    class UnboundedInput:
        def __iter__(self) -> Any:
            raise AssertionError("input was consumed before validating its bound")

    with pytest.raises(ContractError) as raised:
        ObservationBatch.from_observations("offline-raw", cast(Any, UnboundedInput()))
    assert raised.value.code == "invalid_batch"


@pytest.mark.parametrize("metadata,reason", [
    ({RECEIPT_REFERENCE_METADATA_KEY: "0" * 64}, "receipt_reference_metadata"),
    ({"extractor_receipt_ref_v9": "x"}, "receipt_reference_metadata"),
    ({"achieved_capabilities": ["syntax.tree"]}, "capability_claim_metadata"),
    ({"effect_vector": {"network": "none"}}, "capability_claim_metadata"),
    ({"parent_witness": True}, "capability_claim_metadata"),
    ({"language": "Rust"}, "rust_language_claim"),
    ({"language": " rust/2021 "}, "rust_language_claim"),
    ({"dialect": "rust-2024"}, "rust_language_claim"),
    ({"language_dialect": "rust.edition"}, "rust_language_claim"),
])
def test_explicit_claims_are_recognized_on_any_kind(metadata: dict[str, Any], reason: str) -> None:
    assert capability_claim_reason(_python("tool.py", **metadata)) == reason
    assert capability_claim_reason(_file("src/lib.rs", **metadata)) == reason


@pytest.mark.parametrize("kind", ["rust.parse", "rust.item", "rust.unsupported"])
@pytest.mark.parametrize("metadata,reason", [
    ({}, "rust_raw_kind"),
    ({"language": "rust"}, "rust_raw_kind"),
    ({"achieved_capabilities": ["syntax.tree"]}, "capability_claim_metadata"),
    ({RECEIPT_REFERENCE_METADATA_KEY: "0" * 64}, "receipt_reference_metadata"),
])
def test_rust_raw_kind_refusal_precedence_is_independent_of_language_metadata(
        kind: str, metadata: dict[str, Any], reason: str) -> None:
    item = replace(_file("src/lib.rs"), kind=kind, metadata=metadata)
    assert capability_claim_reason(item) == reason


@pytest.mark.parametrize("observation", [
    _file("src/lib.rs"),
    _file("src/lib.rs", language="shell"),
    _file("script.zsh", language="zsh"),
    _python("tool.py", language="python", capabilities=["x"], rusty="rust"),
    _python("tool.py", language="rusty", dialect="zsh"),
    _content("markdown.code_fence", "README.md", fence="```", info_string="rust", language="rust"),
    _content("markdown.code_fence", "README.md", info_string="Rust ignore", language="Rust"),
    _content("html.document", "index.html", format="html", language="rust"),
])
def test_legacy_shapes_including_unknown_rs_files_are_untouched(observation: RawObservation) -> None:
    assert capability_claim_reason(observation) is None


def test_content_language_kinds_still_refuse_reserved_metadata() -> None:
    fence = _content("markdown.code_fence", "README.md", language="rust",
                     **{RECEIPT_REFERENCE_METADATA_KEY: "0" * 64})
    page = _content("html.document", "index.html", language="rust", parent_witness=True)
    assert capability_claim_reason(fence) == "receipt_reference_metadata"
    assert capability_claim_reason(page) == "capability_claim_metadata"


def test_canonicalization_refuses_claims_and_preserves_legacy_graph() -> None:
    legacy = [_file("src/lib.rs"), _file("tool.py", language="python"), _python("tool.py")]
    digest = receipt_digest(encode_receipt(receipt()))
    forged = [
        _file("src/lib.rs", language="rust"),
        _python("src/lib.rs", **{RECEIPT_REFERENCE_METADATA_KEY: digest, "secret": SECRET}),
        _python("tool.py", capability_witness=SECRET, achieved_capabilities=["syntax.tree"]),
    ]
    baseline = canonicalize_observations(legacy)
    mixed = canonicalize_observations(legacy + forged)
    assert mixed.graph.nodes == baseline.graph.nodes
    assert mixed.graph.edges == baseline.graph.edges
    assert mixed.graph.evidence == baseline.graph.evidence
    assert mixed.graph.raw_observation_count == len(legacy) + len(forged)
    refused = [item for item in mixed.diagnostics if item.category == CLAIM_REFUSED_CATEGORY]
    assert [(item.raw_observation_ordinal, item.value) for item in refused] == [
        (3, "rust_language_claim"), (4, "receipt_reference_metadata"),
        (5, "capability_claim_metadata"),
    ]
    assert [item for item in mixed.diagnostics if item not in refused] == list(baseline.diagnostics)
    rendered = repr([item.to_dict() for item in refused])
    assert SECRET not in rendered and digest not in rendered and "syntax.tree" not in rendered
    file_nodes = [node for node in mixed.graph.nodes if node.display_name == "src/lib.rs"]
    assert [node.metadata["language"] for node in file_nodes] == ["unknown"]


def test_refused_go_claims_never_reach_shared_context() -> None:
    forged = RawObservation(
        kind="go.package", source_id="pkg/a.go#package", path="pkg/a.go", name="a",
        confidence="extracted", extractor="repo-go-ast", extractor_version="0.0.3",
        metadata={"effect_vector": {"network": "none"}},
    )
    result = canonicalize_observations([forged], repository_scope="example.test/module")
    assert result.graph.nodes == () and result.graph.evidence == ()
    assert [item.category for item in result.diagnostics] == [CLAIM_REFUSED_CATEGORY]


def test_unsupported_kinds_keep_their_existing_diagnostic() -> None:
    unknown = RawObservation(
        kind="rust.function", source_id="src/lib.rs#fn", path="src/lib.rs", confidence="unknown",
        extractor="example-parser", extractor_version="1",
    )
    result = canonicalize_observations([unknown])
    assert [item.category for item in result.diagnostics] == ["unsupported_raw_observation_kind"]


def test_dispatch_state_requires_exactly_one_claim_check() -> None:
    observations = [_python("tool.py"), _python("tool.py", parent_witness=True)]
    state = CanonicalizationState()
    with pytest.raises(RuntimeError):
        state.unrefused(observations)
    assert state.refuse_capability_claims(observations) == (observations[0],)
    assert [ordinal for ordinal, _ in state.unrefused(observations)] == [0]
    with pytest.raises(RuntimeError):
        state.refuse_capability_claims(observations)
    assert [item.ordinal for item in find_claim_refusals(observations)] == [1]
