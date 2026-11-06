"""ADR 0154 closed legacy baseline: exact membership resolved from source."""

from __future__ import annotations

import ast
import copy
import re
from dataclasses import replace
from pathlib import Path

import pytest

from common_lore_index.extractors.contracts import legacy_registry as registry
from common_lore_index.extractors.contracts.legacy_registry import (
    LEGACY_ENTRYPOINTS,
    LEGACY_EXTRACTOR_OWNERS,
    LegacyMembershipError,
)
from repomap_test_support.extractor_contracts import legacy_source

TREES = legacy_source.product_trees()


def test_owner_map_equals_every_resolved_raw_observation_emitter() -> None:
    owners, unresolved = legacy_source.resolve_extractor_owners(TREES)
    assert unresolved == ()
    assert legacy_source.raw_observation_calls_without_extractor(TREES) == ()
    assert dict(owners) == dict(LEGACY_EXTRACTOR_OWNERS)


def test_splat_and_attribute_extractor_values_are_reported_not_skipped() -> None:
    trees = {
        "common_lore_index.example": ast.parse(
            "from common_lore_index.observations.raw import RawObservation\n"
            "from common_lore_index import names\n"
            "def splat(fields):\n"
            "    return RawObservation(**fields)\n"
            "def attribute(record):\n"
            "    return RawObservation(kind='x', extractor=names.REPO_RUST)\n"
            "def copied(record):\n"
            "    return RawObservation(kind='x', extractor=record.extractor)\n"
        ),
    }
    assert legacy_source.raw_observation_calls_without_extractor(trees) == (
        "common_lore_index.example:4",
    )
    owners, unresolved = legacy_source.resolve_extractor_owners(trees)
    assert owners == {}
    assert unresolved == (
        "common_lore_index.example:names.REPO_RUST",
        "common_lore_index.example:record.extractor",
    )


def test_caller_parameter_and_getattr_aliases_are_resolved_not_exempted() -> None:
    shared = "common_lore_index.extractors.shared.observations"
    assert {name for name, owners in LEGACY_EXTRACTOR_OWNERS.items() if shared in owners} == {
        "repo-bash", "repo-zsh",
    }
    assert "common_lore_index.extractors.config.xml" in LEGACY_EXTRACTOR_OWNERS["repo-config"]
    assert "common_lore_index.extractors.shell.zsh_common" not in LEGACY_EXTRACTOR_OWNERS["repo-zsh"]


def test_entrypoints_equal_the_actual_discovery_dispatch_calls() -> None:
    assert legacy_source.dispatch_call_names(TREES) == frozenset(LEGACY_ENTRYPOINTS)
    imports = legacy_source.dispatch_import_sources(TREES)
    for entry in LEGACY_ENTRYPOINTS.values():
        bound = entry.name.split(".", 1)[0]
        module = imports[bound]
        reexported = any(
            isinstance(node, ast.ImportFrom) and node.module == entry.defining_module
            and any(alias.name == bound for alias in node.names)
            for node in TREES[module].body
        )
        assert module == entry.defining_module or reexported, entry.name
        assert entry.implementation.startswith(entry.defining_module + ".") or (
            entry.defining_module == registry.DISCOVERY_ADAPTERS
        ), entry.name


def test_entrypoint_names_are_the_static_import_closure_upper_bound() -> None:
    owners = dict(LEGACY_EXTRACTOR_OWNERS)
    for entry in LEGACY_ENTRYPOINTS.values():
        assert set(entry.extractor_names) <= set(owners)
        if entry.stage == "S2":
            assert entry.extractor_names == ()
            continue
        assert legacy_source.reachable_extractor_names(
            TREES, owners, entry.implementation
        ) == frozenset(entry.extractor_names), entry.name
    emitted = {name for entry in LEGACY_ENTRYPOINTS.values() for name in entry.extractor_names}
    assert emitted | registry.SOURCE_INGESTION_NAMES == set(owners)
    assert emitted.isdisjoint(registry.SOURCE_INGESTION_NAMES)


def test_execution_boundaries_and_stages_match_the_pipeline() -> None:
    boundaries = {entry.name: entry.execution_boundary for entry in LEGACY_ENTRYPOINTS.values()}
    assert {name for name, value in boundaries.items() if value != "pure-python"} == {
        "extract_go_repository_observations"
    }
    assert boundaries["extract_go_repository_observations"] == "subprocess"
    assert {entry.stage for entry in LEGACY_ENTRYPOINTS.values()} == {"S1", "S2", "S3", "S4"}


@pytest.mark.parametrize("name", [
    "extract_python", "extract_python_file_observations_from_file_v2", "extract_*",
    "EXTRACT_PYTHON_FILE_OBSERVATIONS_FROM_FILE", "", 3, None,
])
def test_entrypoint_lookup_is_exact(name: object) -> None:
    with pytest.raises(LegacyMembershipError):
        registry.legacy_entrypoint(name)


def test_only_the_registry_record_object_is_accepted() -> None:
    entry = registry.legacy_entrypoint("extract_python_file_observations_from_file")
    assert registry.require_registered_entrypoint(entry) is entry
    for forged in (
        replace(entry),
        copy.copy(entry),
        replace(entry, defining_module="common_lore_index.extractors.languages.rust"),
        replace(entry, name="extract_rust_file_observations_from_file"),
        entry.name,
    ):
        with pytest.raises(LegacyMembershipError) as raised:
            registry.require_registered_entrypoint(forged)
        assert raised.value.code == "unregistered_record"


def test_new_owner_behind_a_legacy_name_is_refused() -> None:
    registry.require_legacy_owner("repo-python", "common_lore_index.extractors.languages.python")
    for name, owner, code in (
        ("repo-python", "common_lore_index.extractors.languages.rust", "unregistered_owner"),
        ("repo-python", "common_lore_index.extractors.languages", "unregistered_owner"),
        ("repo-python", "common_lore_index.extractors.languages.python.extra", "unregistered_owner"),
        ("repo-rust", "common_lore_index.extractors.languages.python", "unknown_extractor_name"),
        ("repo-python-ng", "common_lore_index.extractors.languages.python", "unknown_extractor_name"),
        ("repo-", "common_lore_index.extractors.languages.python", "unknown_extractor_name"),
    ):
        with pytest.raises(LegacyMembershipError) as raised:
            registry.require_legacy_owner(name, owner)
        assert raised.value.code == code
    with pytest.raises(LegacyMembershipError):
        registry.require_legacy_owner(b"repo-python", "common_lore_index.extractors.languages.python")
    assert not registry.is_legacy_extractor_name("repo-")
    assert not registry.is_legacy_extractor_name(None)


def test_legacy_membership_never_reads_as_achieved_capability() -> None:
    for name in LEGACY_EXTRACTOR_OWNERS:
        facts = registry.legacy_lifecycle_facts(name)
        assert facts["capability_set"] == "undeclared"
        assert {facts["attempted"], facts["exercised"], facts["achieved"]} == {"unavailable"}
        assert facts["installed"] == facts["admitted"] == "undeclared"
        assert facts["effect_enforcement"] == facts["effect_observation"] == "unavailable"
    with pytest.raises(LegacyMembershipError):
        registry.legacy_lifecycle_facts("repo-rust")


def test_registry_source_has_no_loader_wildcard_or_hash_freeze() -> None:
    path = Path(registry.__file__)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                 for alias in node.names}
    assert imported <= {"__future__", "collections.abc", "dataclasses", "types",
                        "common_lore_index.extractors.contracts.vocabulary"}
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert called.isdisjoint({"__import__", "eval", "exec", "compile", "getattr", "open"})
    assert re.search(r"[0-9a-f]{64}", source) is None
    assert "*" not in "".join(name for names in LEGACY_EXTRACTOR_OWNERS.values() for name in names)



def test_opt_in_pilot_is_explicitly_outside_the_legacy_source_census() -> None:
    assert legacy_source.NON_LEGACY_PRODUCT_PREFIXES == (
        "common_lore_index.extractors.rust_pilot",
    )
    assert not any(name == prefix or name.startswith(prefix + ".")
                   for name in TREES for prefix in legacy_source.NON_LEGACY_PRODUCT_PREFIXES)
    assert not registry.is_legacy_extractor_name("rust-pilot-tree-sitter")
    assert "common_lore_index.extractors.languages.python" in TREES
