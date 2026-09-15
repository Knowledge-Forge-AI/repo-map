"""Observed Go source-module and source-package context construction."""

from __future__ import annotations

from collections import defaultdict

from repomap_kg.canonicalization._go_context_model import (
    GoModuleIdentity,
    GoPackageIdentity,
    is_vendor_path,
    parent,
    relative_directory,
)
from repomap_kg.graph.go_source_keys import (
    go_source_module_key,
    go_source_package_fallback_key,
    go_source_package_key,
)
from repomap_kg.graph.keys import GraphKeyError, file_key, go_module_key


class GoSourceContextMixin:
    """Collect repository-scoped source identities and semantic coordinates."""

    def _collect_modules(self) -> None:
        module_paths_by_root: defaultdict[str, set[str]] = defaultdict(set)
        source_keys_by_root: defaultdict[str, set[str]] = defaultdict(set)
        if self.repository_scope is None:
            return
        for item in self.observations:
            if item.kind != "go.module" or not item.name:
                continue
            if item.source_id in self.invalid_source_ids:
                continue
            root = parent(item.path)
            try:
                semantic_key = go_module_key(item.name)
                source_key = go_source_module_key(
                    self.repository_scope,
                    root,
                    item.name,
                )
            except GraphKeyError as error:
                self._identity_error(item, str(error))
                continue
            identity = GoModuleIdentity(
                root=root,
                module_path=item.name,
                semantic_key=semantic_key,
                source_key=source_key,
                repository_scope=self.repository_scope,
            )
            self.modules_by_root.setdefault(root, identity)
            self.module_keys_by_path[item.name] = semantic_key
            module_paths_by_root[root].add(item.name)
            source_keys_by_root[root].add(source_key)
            self._add_module_claims(item, identity)
        for root, module_paths in sorted(module_paths_by_root.items()):
            if len(module_paths) <= 1:
                continue
            self.ambiguous_module_roots.add(root)
            self.invalid_module_roots.add(root)
            self.invalid_keys.update(source_keys_by_root[root])
            self._collision(
                next(
                    item
                    for item in self.observations
                    if item.kind == "go.module" and parent(item.path) == root
                ),
                "one repository root declares multiple Go module identities",
            )

    def _add_module_claims(self, item, identity: GoModuleIdentity) -> None:
        self._add_node_input(
            identity.semantic_key,
            "go.module",
            item.name,
            {
                "identity_format": "go-v1",
                "module_path": item.name,
                "declaration_observed": True,
            },
            item,
            primary=True,
        )
        self._add_node_input(
            identity.source_key,
            "go.source_module",
            item.name,
            {
                "identity_format": "go-source-v2",
                "repository_scope": self.repository_scope,
                "repository_relative_module_root": identity.root,
                "module_path": item.name,
                "semantic_module_key": identity.semantic_key,
                "declaration_observed": True,
            },
            item,
            primary=True,
        )
        self._add_edge(
            item,
            file_key(item.path),
            "declares",
            identity.source_key,
            metadata={"resolution": "exact", "declaration_kind": "go.source_module"},
        )
        self._add_edge(
            item,
            identity.source_key,
            "instance_of",
            identity.semantic_key,
            metadata={"resolution": "exact"},
        )

    def _collect_packages(self) -> None:
        directories_by_key: defaultdict[str, set[str]] = defaultdict(set)
        if self.repository_scope is None:
            return
        for item in self.observations:
            if item.kind != "go.package" or not item.name:
                continue
            if item.source_id in self.invalid_source_ids:
                continue
            directory = parent(item.path)
            if is_vendor_path(item.path) or bool(item.metadata.get("vendor")):
                first_in_directory = directory not in self.deferred_vendor_directories
                self.deferred_vendor_directories.add(directory)
                if first_in_directory:
                    self._warning(
                        item,
                        "go_vendor_package_identity_deferred",
                        "vendored Go package identity is deferred pending a dedicated design phase",
                    )
                continue
            module = self._module_for_directory(directory)
            if module is not None and module.root in self.invalid_module_roots:
                continue
            relative = directory if module is None else relative_directory(directory, module.root)
            import_path = self._package_import_path(module, relative)
            try:
                key = (
                    go_source_package_key(module.source_key, relative, item.name)
                    if module is not None
                    else go_source_package_fallback_key(
                        self.repository_scope,
                        directory,
                        item.name,
                    )
                )
            except GraphKeyError as error:
                self._identity_error(item, str(error))
                continue
            identity = GoPackageIdentity(
                directory=directory,
                import_path=import_path,
                package_name=item.name,
                canonical_key=key,
                source_module_key=module.source_key if module else None,
                semantic_module_key=module.semantic_key if module else None,
                module_path=module.module_path if module else None,
                module_root=module.root if module else None,
                repository_scope=self.repository_scope,
                identity_source="module" if module else "repository_relative",
                external_test_package=bool(item.metadata.get("external_test_package")),
                vendor=bool(item.metadata.get("vendor")),
            )
            self.packages_by_directory_name.setdefault((directory, item.name), identity)
            self.package_by_source_id[item.source_id] = identity
            directories_by_key[key].add(directory)
            self._add_package_claims(item, identity, relative)
        self._collect_package_collisions(directories_by_key)

    @staticmethod
    def _package_import_path(module, relative: str) -> str | None:
        if module is None:
            return None
        return module.module_path if relative == "." else f"{module.module_path}/{relative}"

    def _add_package_claims(
        self,
        item,
        identity: GoPackageIdentity,
        relative: str,
    ) -> None:
        self._add_node_input(
            identity.canonical_key,
            "go.source_package",
            item.name,
            {
                "identity_format": "go-source-v2",
                "repository_scope": self.repository_scope,
                "repository_relative_directory": identity.directory,
                "module_relative_directory": relative if identity.source_module_key else None,
                "import_path": identity.import_path,
                "package_name": item.name,
                "identity_source": identity.identity_source,
                "module_path": identity.module_path,
                "external_test_package": identity.external_test_package,
                "vendor": identity.vendor,
            },
            item,
            primary=True,
        )
        self._add_edge(
            item,
            file_key(item.path),
            "declares",
            identity.canonical_key,
            metadata={"resolution": "exact", "declaration_kind": "go.source_package"},
        )
        if identity.source_module_key:
            self._add_edge(
                item,
                identity.source_module_key,
                "contains",
                identity.canonical_key,
                metadata={"resolution": "exact"},
            )

    def _collect_package_collisions(self, directories_by_key) -> None:
        for key, directories in sorted(directories_by_key.items()):
            if len(directories) <= 1:
                continue
            self.invalid_keys.add(key)
            source_id = next(
                source_id
                for source_id, identity in self.package_by_source_id.items()
                if identity.canonical_key == key
            )
            self._collision(
                self.observation_by_source_id[source_id],
                "one Go package identity is derived from multiple directories",
            )
