"""Synthetic admission/domain diagnostics; these tests grant no live witness."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast
import pytest

from common_lore_index.canonicalization import rust_pilot_family
from common_lore_index.canonicalization.records import (
    CanonicalGraph,
    CanonicalNode,
    CanonicalizationResult,
)
from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot.controller import RustPilotController
from common_lore_index.extractors.rust_pilot.witness_state import Admission
from common_lore_index.graph.keys import GRAPH_KEY_VERSION, file_key
from common_lore_index.graph.rust_keys import rust_item_key, rust_source_file_key
from common_lore_index.observations.raw import RawObservation

PATH = "src/lib.rs"


def _legacy(path: str = PATH) -> CanonicalizationResult:
    file_node = CanonicalNode(
        canonical_key=file_key(path),
        graph_key_version=GRAPH_KEY_VERSION,
        kind="file",
        display_name=path,
        metadata={},
        confidence="extracted",
        conflict=False,
    )
    return CanonicalizationResult(
        graph=replace(CanonicalGraph.empty(), nodes=(file_node,)),
    )


def _raw(kind: str, *, metadata: dict[str, object] | None = None,
         path: str = PATH, name: str | None = None) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id="rust-pilot-test",
        path=path,
        confidence="extracted",
        extractor="rust-pilot",
        extractor_version="test",
        name=name,
        metadata={} if metadata is None else metadata,
    )


def _build(items: list[RawObservation], *, path: str = PATH,
           legacy_path: str = PATH) -> CanonicalizationResult:
    return rust_pilot_family._build(
        _legacy(legacy_path), tuple(items), {path: tuple(items)}, ()
    )


class _AdmissionRun:
    def __init__(self, result: object) -> None:
        self.result = result

    def selected_paths(self) -> tuple[str, ...]:
        return (PATH,)

    def admit(self, path: str) -> object:
        assert path == PATH
        return self.result


def _run(result: object) -> RustPilotController:
    return cast(RustPilotController, _AdmissionRun(result))


def test_admit_preserves_refusal_codes_and_accepts_only_tuples() -> None:
    refused = Admission(PATH, (), ("clean_exit", "proven_cleanup"))
    admitted, diagnostics = rust_pilot_family._admit(_run(refused))

    assert admitted == {}
    assert [(item.category, item.field, item.value) for item in diagnostics] == [
        ("rust_pilot_binding_refused", "binding", "clean_exit"),
        ("rust_pilot_binding_refused", "binding", "proven_cleanup"),
    ]

    observation = _raw("rust.parse", metadata={"outcome": "succeeded"})
    accepted, accepted_diagnostics = rust_pilot_family._admit(
        _run(Admission(PATH, (observation,), ()))
    )
    assert accepted == {PATH: (observation,)}
    assert accepted_diagnostics == ()

    with pytest.raises(ContractError, match="rust_pilot_admission_type"):
        rust_pilot_family._admit(_run(object()))
    with pytest.raises(ContractError, match="rust_pilot_observation_tuple"):
        rust_pilot_family._admit(_run(Admission(PATH, cast(Any, []), ())))


def test_partial_tree_maps_only_usable_items_and_binds_completeness() -> None:
    parse = _raw(
        "rust.parse",
        metadata={"outcome": "succeeded", "completeness": "partial"},
    )
    module = _raw(
        "rust.item",
        name="inside",
        metadata={
            "namespace": "rust.module",
            "item_kind": "mod",
            "pointer": "/mod:inside",
            "parent_pointer": "/",
            "usable_scope": True,
        },
    )
    unusable = _raw(
        "rust.item",
        name="skipped",
        metadata={
            "namespace": "rust.function",
            "item_kind": "fn",
            "pointer": "/fn:skipped",
            "parent_pointer": "/",
            "usable_scope": False,
        },
    )

    result = _build([parse, module, unusable])
    source_key = rust_source_file_key(PATH)
    module_key = rust_item_key("rust.module", PATH, "/mod:inside")
    nodes = {node.canonical_key: node for node in result.graph.nodes}
    edges = {(edge.source_key, edge.kind, edge.target_key): edge
             for edge in result.graph.edges}

    assert result.ok
    assert source_key in nodes and module_key in nodes
    assert rust_item_key("rust.function", PATH, "/fn:skipped") not in nodes
    assert nodes[source_key].metadata["completeness_basis"] == "partial_tree_usable_scope"
    assert edges[(file_key(PATH), "contains", source_key)].metadata == {
        "completeness_basis": "partial_tree_usable_scope"
    }
    assert edges[(source_key, "defines", module_key)].target_key == module_key


@pytest.mark.parametrize(
    ("items", "category"),
    [
        (
            [
                _raw("rust.item", metadata={
                    "namespace": "rust.function", "item_kind": "fn",
                    "pointer": "/fn:missing-parse", "parent_pointer": "/",
                    "usable_scope": True,
                }),
            ],
            "rust_pilot_parse_cardinality",
        ),
        (
            [
                _raw("rust.parse", metadata={"outcome": "succeeded", "completeness": "complete"}),
                _raw("rust.item", metadata={
                    "namespace": "rust.function", "item_kind": "struct",
                    "pointer": "/fn:bad", "parent_pointer": "/", "usable_scope": True,
                }),
            ],
            "rust_pilot_item_contract",
        ),
        (
            [
                _raw("rust.parse", metadata={"outcome": "succeeded", "completeness": "complete"}),
                _raw("rust.item", metadata={
                    "namespace": "rust.function", "item_kind": "fn",
                    "pointer": "/not-a-pointer", "parent_pointer": "/", "usable_scope": True,
                }),
            ],
            "rust_pilot_key_invalid",
        ),
    ],
)
def test_invalid_parse_or_item_records_produce_bounded_diagnostics(
    items: list[RawObservation], category: str,
) -> None:
    result = _build(items)

    assert not result.ok
    assert category in {item.category for item in result.diagnostics}
    assert all(node.kind != "rust.function" for node in result.graph.nodes)


def test_parent_and_duplicate_refusals_never_create_orphan_claims() -> None:
    parse = _raw(
        "rust.parse",
        metadata={"outcome": "succeeded", "completeness": "complete"},
    )
    parent = _raw(
        "rust.item",
        name="function_parent",
        metadata={
            "namespace": "rust.function", "item_kind": "fn",
            "pointer": "/fn:parent", "parent_pointer": "/", "usable_scope": True,
        },
    )
    child = _raw(
        "rust.item",
        name="child",
        metadata={
            "namespace": "rust.function", "item_kind": "fn",
            "pointer": "/fn:parent/fn:child", "parent_pointer": "/fn:parent",
            "usable_scope": True,
        },
    )
    duplicate = _raw("rust.item", metadata={
        "namespace": "rust.function", "item_kind": "fn",
        "pointer": "/fn:parent", "parent_pointer": "/", "usable_scope": True,
    })

    result = _build([parse, parent, child, duplicate])
    categories = {item.category for item in result.diagnostics}
    parent_key = rust_item_key("rust.function", PATH, "/fn:parent")
    child_key = rust_item_key("rust.function", PATH, "/fn:parent/fn:child")

    assert {"rust_pilot_parent_invalid", "rust_pilot_duplicate_key"} <= categories
    assert parent_key in {node.canonical_key for node in result.graph.nodes}
    assert child_key not in {node.canonical_key for node in result.graph.nodes}

    missing = _raw("rust.item", metadata={
        "namespace": "rust.function", "item_kind": "fn",
        "pointer": "/fn:orphan", "parent_pointer": "/fn:absent", "usable_scope": True,
    })
    missing_result = _build([parse, missing])
    assert any(item.category == "rust_pilot_parent_missing" for item in missing_result.diagnostics)
    assert rust_item_key("rust.function", PATH, "/fn:orphan") not in {
        node.canonical_key for node in missing_result.graph.nodes
    }


def test_unknown_live_kind_and_missing_legacy_file_are_refused() -> None:
    unknown = _raw("rust.future_kind")
    result = _build([unknown])
    assert {item.category for item in result.diagnostics} >= {
        "rust_pilot_raw_kind", "rust_pilot_parse_cardinality",
    }

    parse = _raw(
        "rust.parse",
        path="src/other.rs",
        metadata={"outcome": "succeeded", "completeness": "complete"},
    )
    missing = _build([parse], path="src/other.rs", legacy_path=PATH)
    assert any(item.category == "rust_pilot_legacy_file_missing" for item in missing.diagnostics)
    assert rust_source_file_key("src/other.rs") not in {
        node.canonical_key for node in missing.graph.nodes
    }
