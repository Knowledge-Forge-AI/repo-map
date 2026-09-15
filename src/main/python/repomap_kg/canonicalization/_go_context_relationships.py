"""Bounded relationship resolution for Go canonical context construction."""

from __future__ import annotations

from repomap_kg.canonicalization._go_context_model import normalize_directory
from repomap_kg.graph.go_source_keys import go_source_type_key
from repomap_kg.graph.keys import GraphKeyError, file_key
from repomap_kg.observations.raw import RawObservation


class GoRelationshipContextMixin:
    """Resolve only relationships established by exact or bounded local evidence."""

    def _collect_relationships(self) -> None:
        self._collect_module_relationships()
        self._collect_import_relationships()
        self._collect_method_relationships()

    def _collect_module_relationships(self) -> None:
        for item in self.observations:
            if item.source_id in self.invalid_source_ids:
                continue
            if item.kind == "go.module_require":
                owner = item.metadata.get("owner_module_path")
                if isinstance(owner, str) and item.name:
                    source = self._ensure_module_reference(owner, item)
                    target = self._ensure_module_reference(item.name, item)
                    if source and target:
                        self._add_edge(
                            item,
                            source,
                            "requires_module",
                            target,
                            metadata={
                                "resolution": "exact",
                                "version": item.metadata.get("version"),
                                "indirect": bool(item.metadata.get("indirect")),
                            },
                        )
                else:
                    self.unresolved_relationships += 1
            elif item.kind in {"go.module_replace", "go.workspace_replace"}:
                self._collect_replacement(item)
            elif item.kind == "go.workspace_use":
                target = item.name if isinstance(item.name, str) else ""
                module = self.modules_by_root.get(normalize_directory(target))
                if bool(item.metadata.get("resolved_under_root")) and module:
                    self._add_edge(
                        item,
                        file_key(item.path),
                        "workspace_uses",
                        module.source_key,
                        metadata={"resolution": "bounded_local"},
                    )
                    self.node_keys_by_source_id[item.source_id].add(module.source_key)
                else:
                    self.unresolved_relationships += 1

    def _collect_replacement(self, item: RawObservation) -> None:
        if item.metadata.get("replacement_kind") != "module":
            self.unresolved_relationships += 1
            return
        replacement = item.metadata.get("replacement")
        owner = item.metadata.get("owner_module_path")
        if not isinstance(owner, str):
            self.unresolved_relationships += 1
            return
        if not isinstance(replacement, str) or not replacement:
            self.unresolved_relationships += 1
            return
        source = self._ensure_module_reference(owner, item)
        target = self._ensure_module_reference(replacement, item)
        if source and target:
            self._add_edge(
                item,
                source,
                "replaces_module",
                target,
                identity_metadata={
                    "replaced_module": item.name or "",
                    "old_version": item.metadata.get("old_version"),
                },
                metadata={
                    "resolution": "exact",
                    "replacement_version": item.metadata.get("replacement_version"),
                },
            )

    def _collect_import_relationships(self) -> None:
        for item in self.observations:
            if item.source_id in self.invalid_source_ids:
                continue
            if item.kind != "go.import" or not item.name:
                continue
            source = self._package_for_observation(item)
            local_identities = {
                identity.canonical_key: identity
                for identity in self.packages_by_directory_name.values()
                if not identity.external_test_package
                and identity.import_path == item.name
            }
            same_instance_targets = {
                key
                for key, identity in local_identities.items()
                if source is not None
                and source.source_module_key is not None
                and identity.source_module_key == source.source_module_key
            }
            targets = same_instance_targets
            if (
                source is not None
                and not targets
                and len(local_identities) == 1
            ):
                candidate = next(iter(local_identities.values()))
                if candidate.module_path != source.module_path:
                    targets = {candidate.canonical_key}
            if source is not None and len(targets) == 1:
                target = next(iter(targets))
                self._add_edge(
                    item,
                    source.canonical_key,
                    "imports",
                    target,
                    metadata={
                        "resolution": "bounded_local",
                        "alias": item.metadata.get("alias"),
                        "blank_import": bool(item.metadata.get("blank_import")),
                        "dot_import": bool(item.metadata.get("dot_import")),
                    },
                )
                self.node_keys_by_source_id[item.source_id].add(target)
            elif len(targets) > 1:
                self._collision(item, "local Go import resolves to multiple package identities")
                self.unresolved_relationships += 1
            else:
                self.unresolved_relationships += 1

    def _collect_method_relationships(self) -> None:
        type_kinds_by_key = {
            key: {claim.kind for claim in claims}
            for key, claims in self.node_inputs.items()
            if key.startswith("go.source-type.v2:")
        }
        for item in self.observations:
            if item.source_id in self.invalid_source_ids:
                continue
            if item.kind != "go.method":
                continue
            method_key = self.declaration_key_by_source_id.get(item.source_id)
            package = self._package_for_observation(item)
            receiver = item.metadata.get("receiver_base")
            if method_key is None or package is None or not isinstance(receiver, str):
                self.unresolved_relationships += 1
                continue
            try:
                type_key = go_source_type_key(package.canonical_key, receiver)
            except GraphKeyError as error:
                self._identity_error(item, str(error))
                continue
            kinds = type_kinds_by_key.get(type_key, set())
            if kinds == {"go.source_type"}:
                self._add_edge(
                    item,
                    method_key,
                    "method_of",
                    type_key,
                    metadata={"resolution": "exact"},
                )
                self.node_keys_by_source_id[item.source_id].add(type_key)
            elif "go.source_type_alias" in kinds:
                self.identity_collisions += 1
                self._error(
                    item,
                    "go_method_receiver_alias_unsupported",
                    "Go method receiver resolves only to a type alias",
                )
            else:
                self.unresolved_relationships += 1
