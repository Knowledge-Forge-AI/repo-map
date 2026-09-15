"""Pure identity and relationship context for Go canonicalization."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

from repomap_kg.canonicalization._go_context_finalize import GoContextFinalizerMixin
from repomap_kg.canonicalization._go_context_model import (
    GO_DECLARATION_KINDS,
    GO_SUPPORTING_KINDS,
    GO_UNRESOLVED_RELATIONSHIP_KINDS,
    GoCanonicalContext,
    GoEdgeClaim,
    GoModuleIdentity,
    GoNodeClaimInput,
    GoPackageIdentity,
    declaration_identity,
    is_repository_relative_path,
    location_key,
    parent,
)
from repomap_kg.canonicalization._go_context_relationships import (
    GoRelationshipContextMixin,
)
from repomap_kg.canonicalization._go_context_sources import GoSourceContextMixin
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.graph.go_source_keys import validate_go_repository_scope
from repomap_kg.graph.keys import GraphKeyError
from repomap_kg.observations.raw import RawObservation


class _ContextBuilder(
    GoSourceContextMixin,
    GoContextFinalizerMixin,
    GoRelationshipContextMixin,
):
    def __init__(
        self,
        observations: Sequence[RawObservation],
        repository_scope: str | None,
    ) -> None:
        self.observations = tuple(
            item for item in observations if item.kind.startswith("go.")
        )
        self.repository_scope: str | None = None
        self.repository_scope_error: str | None = None
        if self.observations:
            try:
                self.repository_scope = validate_go_repository_scope(
                    repository_scope or ""
                )
            except GraphKeyError as error:
                self.repository_scope_error = str(error)
        self.observation_by_source_id = {
            item.source_id: item for item in self.observations
        }
        self.modules_by_root: dict[str, GoModuleIdentity] = {}
        self.module_keys_by_path: dict[str, str] = {}
        self.ambiguous_module_roots: set[str] = set()
        self.invalid_module_roots: set[str] = set()
        self.packages_by_directory_name: dict[
            tuple[str, str], GoPackageIdentity
        ] = {}
        self.package_by_source_id: dict[str, GoPackageIdentity] = {}
        self.deferred_vendor_directories: set[str] = set()
        self.node_inputs: defaultdict[str, list[GoNodeClaimInput]] = defaultdict(list)
        self.node_keys_by_source_id: defaultdict[str, set[str]] = defaultdict(set)
        self.edge_claims_by_source_id: defaultdict[
            str, list[GoEdgeClaim]
        ] = defaultdict(list)
        self.declaration_key_by_source_id: dict[str, str] = {}
        self.function_keys_by_location: defaultdict[
            tuple[Any, ...], set[str]
        ] = defaultdict(set)
        self.diagnostics: list[CanonicalizationDiagnostic] = []
        self.invalid_keys: set[str] = set()
        self.invalid_source_ids: set[str] = set()
        self.identity_collisions = 0
        self.unresolved_relationships = sum(
            1
            for item in self.observations
            if item.kind in GO_UNRESOLVED_RELATIONSHIP_KINDS
        )

    def build(self) -> GoCanonicalContext:
        self._collect_repository_scope_error()
        self._collect_input_path_errors()
        self._collect_modules()
        self._collect_packages()
        self._collect_declarations()
        self._collect_supporting_evidence()
        self._collect_relationships()
        node_claims, invalid_keys, duplicate_count = self._finalize_node_claims()
        invalid_keys.update(self.invalid_keys)
        node_claims = {
            key: claim for key, claim in node_claims.items() if key not in invalid_keys
        }
        edges_by_source = self._finalize_edge_claims(invalid_keys)
        node_keys_by_source = {
            source_id: tuple(sorted(keys - invalid_keys))
            for source_id, keys in self.node_keys_by_source_id.items()
            if keys - invalid_keys
        }
        return GoCanonicalContext(
            node_claims=node_claims,
            node_keys_by_source_id=node_keys_by_source,
            edge_claims_by_source_id=edges_by_source,
            diagnostics=tuple(self.diagnostics),
            duplicate_declaration_evidence=duplicate_count,
            identity_collisions=self.identity_collisions,
            unresolved_relationships=self.unresolved_relationships,
            invalid_source_ids=frozenset(self.invalid_source_ids),
        )

    def _collect_repository_scope_error(self) -> None:
        if not self.repository_scope_error or not self.observations:
            return
        self.invalid_source_ids.update(item.source_id for item in self.observations)
        self.identity_collisions += 1
        self._error(
            self.observations[0],
            "go_repository_scope_invalid",
            self.repository_scope_error,
        )

    def _collect_input_path_errors(self) -> None:
        source_id_counts = Counter(item.source_id for item in self.observations)
        for source_id, count in sorted(source_id_counts.items()):
            if count <= 1:
                continue
            self.invalid_source_ids.add(source_id)
            item = next(
                item for item in self.observations if item.source_id == source_id
            )
            self.identity_collisions += 1
            self._error(
                item,
                "go_duplicate_source_id",
                "Go evidence source identifier is not unique",
            )
        for item in self.observations:
            if not is_repository_relative_path(item.path):
                self.invalid_source_ids.add(item.source_id)
                self._identity_error(
                    item,
                    "Go evidence path must be repository-relative",
                )

    def _collect_declarations(self) -> None:
        for item in self.observations:
            if item.kind not in GO_DECLARATION_KINDS or not item.name:
                continue
            if item.source_id in self.invalid_source_ids:
                continue
            package = self._package_for_observation(item)
            if package is None:
                if parent(item.path) in self.deferred_vendor_directories:
                    continue
                self._warning(
                    item,
                    "go_package_context_missing",
                    "Go declaration has no package context",
                )
                continue
            try:
                key, node_kind, display_name = declaration_identity(item, package)
            except GraphKeyError as error:
                self._identity_error(item, str(error))
                continue
            metadata = {
                "identity_format": "go-source-v2",
                "source_package_key": package.canonical_key,
                "declaration_name": item.name,
                "declaration_kind": node_kind,
                "exported": bool(item.metadata.get("exported")),
                "generic": bool(item.metadata.get("generic"))
                or bool(item.metadata.get("type_parameter_count")),
                "generated": bool(item.metadata.get("generated")),
                "vendor": bool(item.metadata.get("vendor")),
            }
            if item.kind == "go.method":
                metadata.update(
                    {
                        "receiver_base": item.metadata.get("receiver_base"),
                        "receiver_pointer": bool(
                            item.metadata.get("receiver_pointer")
                        ),
                    }
                )
            self.declaration_key_by_source_id[item.source_id] = key
            self._add_node_input(
                key,
                node_kind,
                display_name,
                metadata,
                item,
                primary=True,
            )
            self._add_edge(
                item,
                package.canonical_key,
                "declares",
                key,
                metadata={"resolution": "exact", "declaration_kind": node_kind},
            )
            if item.kind == "go.function":
                self.function_keys_by_location[location_key(item)].add(key)

    def _collect_supporting_evidence(self) -> None:
        for item in self.observations:
            if item.kind not in GO_SUPPORTING_KINDS:
                continue
            if item.source_id in self.invalid_source_ids:
                continue
            target_key = None
            parent_source_id = item.metadata.get("parent_source_id")
            if isinstance(parent_source_id, str):
                target_key = self.declaration_key_by_source_id.get(parent_source_id)
            if target_key is None and item.kind in {
                "go.test",
                "go.benchmark",
                "go.fuzz",
                "go.example",
                "go.test_main",
            }:
                candidates = self.function_keys_by_location.get(
                    location_key(item), set()
                )
                if len(candidates) == 1:
                    target_key = next(iter(candidates))
            if target_key is None:
                continue
            primary = self.node_inputs.get(target_key)
            if not primary:
                continue
            first = sorted(primary, key=lambda claim: claim.source_id)[0]
            self._add_node_input(
                target_key,
                first.kind,
                first.display_name,
                first.metadata,
                item,
                primary=False,
            )


def build_go_canonical_context(
    observations: Sequence[RawObservation],
    *,
    repository_scope: str | None = None,
) -> GoCanonicalContext:
    return _ContextBuilder(observations, repository_scope).build()
