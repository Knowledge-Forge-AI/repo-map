"""Collision checks and claim finalization for Go canonical context."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization._go_context_model import (
    MAX_GO_CANONICAL_DIAGNOSTICS,
    GoEdgeClaim,
    GoModuleIdentity,
    GoNodeClaim,
    GoNodeClaimInput,
    GoPackageIdentity,
    is_directory_ancestor,
    is_repository_relative_path,
    parent,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.graph.keys import GraphKeyError, go_module_key
from repomap_kg.observations.raw import RawObservation


class GoContextFinalizerMixin:
    """Finalize deterministic claims and provide bounded builder primitives."""

    def _finalize_node_claims(
        self,
    ) -> tuple[dict[str, GoNodeClaim], set[str], int]:
        node_claims: dict[str, GoNodeClaim] = {}
        invalid_keys: set[str] = set()
        duplicate_count = 0
        for key, collected_inputs in sorted(self.node_inputs.items()):
            inputs = [
                item
                for item in collected_inputs
                if item.source_id not in self.invalid_source_ids
            ]
            if not inputs:
                continue
            kinds = {item.kind for item in inputs}
            if len(kinds) != 1:
                invalid_keys.add(key)
                first = sorted(inputs, key=lambda item: item.source_id)[0]
                self._collision(
                    self.observation_by_source_id[first.source_id],
                    "one Go canonical identity has incompatible declaration families",
                )
                continue
            ordered = sorted(inputs, key=lambda item: (item.source_id, not item.primary))
            primary_count = sum(1 for item in ordered if item.primary)
            supporting_count = len(ordered) - primary_count
            duplicate = max(primary_count - 1, 0)
            duplicate_count += duplicate
            metadata = dict(ordered[0].metadata)
            for boolean_field in (
                "declaration_observed",
                "exported",
                "generic",
                "generated",
                "vendor",
                "external_test_package",
            ):
                if any(boolean_field in item.metadata for item in ordered):
                    metadata[boolean_field] = any(
                        bool(item.metadata.get(boolean_field)) for item in ordered
                    )
            metadata.update(
                {
                    "identity_format": metadata.get("identity_format", "go-v1"),
                    "declaration_evidence_count": primary_count,
                    "supporting_evidence_count": supporting_count,
                    "duplicate_declaration_evidence_count": duplicate,
                }
            )
            node_claims[key] = GoNodeClaim(
                canonical_key=key,
                kind=next(iter(kinds)),
                display_name=ordered[0].display_name,
                metadata=metadata,
            )
        return node_claims, invalid_keys, duplicate_count

    def _finalize_edge_claims(
        self,
        invalid_keys: set[str],
    ) -> dict[str, tuple[GoEdgeClaim, ...]]:
        return {
            source_id: tuple(
                sorted(
                    (
                        edge
                        for edge in claims
                        if edge.source_key not in invalid_keys
                        and edge.target_key not in invalid_keys
                    ),
                    key=lambda edge: (
                        edge.source_key,
                        edge.kind,
                        edge.target_key,
                        repr(sorted(edge.identity_metadata.items())),
                    ),
                )
            )
            for source_id, claims in self.edge_claims_by_source_id.items()
            if source_id not in self.invalid_source_ids
            and any(
                edge.source_key not in invalid_keys and edge.target_key not in invalid_keys
                for edge in claims
            )
        }

    def _module_for_directory(self, directory: str) -> GoModuleIdentity | None:
        candidates = [
            identity
            for root, identity in self.modules_by_root.items()
            if is_directory_ancestor(root, directory)
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: 0 if item.root == "." else len(item.root.split("/")),
        )

    def _package_for_observation(self, item: RawObservation) -> GoPackageIdentity | None:
        package_name = item.metadata.get("package_name")
        if not isinstance(package_name, str) or not package_name:
            return None
        return self.packages_by_directory_name.get((parent(item.path), package_name))

    def _ensure_module_reference(self, module_path: str, item: RawObservation) -> str | None:
        try:
            key = go_module_key(module_path)
        except GraphKeyError as error:
            self._identity_error(item, str(error))
            return None
        declared = module_path in self.module_keys_by_path
        self._add_node_input(
            key,
            "go.module",
            module_path,
            {
                "identity_format": "go-v1",
                "module_path": module_path,
                "declaration_observed": declared,
            },
            item,
            primary=False,
        )
        return key

    def _add_node_input(
        self,
        key: str,
        kind: str,
        display_name: str,
        metadata: Mapping[str, Any],
        item: RawObservation,
        *,
        primary: bool,
    ) -> None:
        self.node_inputs[key].append(
            GoNodeClaimInput(
                kind=kind,
                display_name=display_name,
                metadata=dict(metadata),
                source_id=item.source_id,
                primary=primary,
            )
        )
        self.node_keys_by_source_id[item.source_id].add(key)

    def _add_edge(
        self,
        item: RawObservation,
        source_key: str,
        kind: str,
        target_key: str,
        *,
        identity_metadata: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.edge_claims_by_source_id[item.source_id].append(
            GoEdgeClaim(
                source_key=source_key,
                kind=kind,
                target_key=target_key,
                identity_metadata=dict(identity_metadata or {}),
                metadata=dict(metadata or {}),
            )
        )

    def _identity_error(self, item: RawObservation, message: str) -> None:
        self.invalid_source_ids.add(item.source_id)
        self.identity_collisions += 1
        self._error(item, "go_canonical_identity_invalid", message)

    def _collision(self, item: RawObservation, message: str) -> None:
        self.identity_collisions += 1
        self._error(item, "go_canonical_identity_collision", message)

    def _error(self, item: RawObservation, category: str, message: str) -> None:
        self._append_diagnostic("error", category, message, item)

    def _warning(self, item: RawObservation, category: str, message: str) -> None:
        self._append_diagnostic("warning", category, message, item)

    def _append_diagnostic(
        self,
        severity: str,
        category: str,
        message: str,
        item: RawObservation,
    ) -> None:
        safe_path = is_repository_relative_path(item.path)
        safe_source_id = (
            item.source_id if len(item.source_id.encode("utf-8")) <= 512 else None
        )
        if len(self.diagnostics) < MAX_GO_CANONICAL_DIAGNOSTICS - 1:
            self.diagnostics.append(
                CanonicalizationDiagnostic(
                    severity=severity,
                    category=category,
                    message=message,
                    raw_source_id=safe_source_id if safe_path else None,
                    path=item.path if safe_path else None,
                )
            )
        elif len(self.diagnostics) == MAX_GO_CANONICAL_DIAGNOSTICS - 1:
            self.diagnostics.append(
                CanonicalizationDiagnostic(
                    severity="error",
                    category="go_canonical_diagnostics_truncated",
                    message="additional Go canonical diagnostics omitted",
                )
            )
