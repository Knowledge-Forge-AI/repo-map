from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation

from repomap_kg.graph.go_source_keys import (
    go_source_method_key,
    go_source_module_key,
    go_source_package_key,
    go_source_type_key,
)
from repomap_kg.graph.keys import file_key, go_module_key
from repomap_test_support.go_canonicalization import (
    accounting,
    file_observation,
    observation,
    package_observation,
)

REPOSITORY_SCOPE = "general1-go-routing-fixture"


def _canonicalize(items: tuple[RawObservation, ...], *, scope: str = REPOSITORY_SCOPE) -> Any:
    return canonicalize_observations(items, repository_scope=scope)


def _edge_tuples(result: Any) -> set[tuple[str, str, str]]:
    return {(e.source_key, e.kind, e.target_key) for e in result.graph.edges}


class General1GoRoutingContractsUnitTests(unittest.TestCase):
    """Pure public contract tests for Go relationship routing and boundary failures."""

    def test_module_require_metadata_and_boundary_failures(self) -> None:
        """Module require asserts canonical requires_module edge and fails closed on malformed keys."""
        owner = "example.invalid/app"
        dep = "example.invalid/dep"
        valid_req = observation(
            "go.module_require", "go.mod", name=dep,
            metadata={"owner_module_path": owner, "version": "v1.2.3", "indirect": True},
        )
        result = _canonicalize((observation("go.module", "go.mod", name=owner), valid_req))
        self.assertTrue(result.ok)
        edge = next(e for e in result.graph.edges if e.kind == "requires_module")
        self.assertEqual(edge.source_key, go_module_key(owner))
        self.assertEqual(edge.target_key, go_module_key(dep))
        self.assertEqual(edge.metadata["resolution"], "exact")
        self.assertEqual(edge.metadata["version"], "v1.2.3")
        self.assertTrue(edge.metadata["indirect"])

        # Boundary failure 1: missing owner_module_path leaves requirement unresolved
        missing_owner = _canonicalize((
            observation("go.module", "go.mod", name=owner),
            observation("go.module_require", "go.mod", name=dep,
                        metadata={"owner_module_path": None, "version": "v1.2.3"}),
        ))
        self.assertTrue(missing_owner.ok)
        self.assertFalse(any(e.kind == "requires_module" for e in missing_owner.graph.edges))
        self.assertEqual(accounting(missing_owner)["unresolved_relationships"], 1)

        # Boundary failure 2: illegal module name causes GraphKeyError and fails closed
        invalid_name = _canonicalize((
            observation("go.module", "go.mod", name=owner),
            observation("go.module_require", "go.mod", name="invalid name with spaces",
                        metadata={"owner_module_path": owner}),
        ))
        self.assertFalse(invalid_name.ok)
        self.assertEqual(accounting(invalid_name)["identity_collisions"], 1)
        self.assertIn("go_canonical_identity_invalid", {d.category for d in invalid_name.diagnostics})

    def test_workspace_and_module_replace_contracts_and_boundary_failures(self) -> None:
        """Module and workspace replace emit replaces_module edges or increment unresolved count."""
        ws_owner, target_mod, replacement_mod = (
            "example.invalid/workspace", "example.invalid/target", "example.invalid/replacement"
        )
        # Valid workspace replace in go.work
        ws_replace = observation(
            "go.workspace_replace", "go.work", name=target_mod,
            metadata={
                "owner_module_path": ws_owner, "replacement_kind": "module",
                "replacement": replacement_mod, "old_version": "v1.0.0", "replacement_version": "v1.1.0",
            },
        )
        result = _canonicalize((file_observation("go.work"), ws_replace))
        self.assertTrue(result.ok)
        self.assertIn((go_module_key(ws_owner), "replaces_module", go_module_key(replacement_mod)), _edge_tuples(result))
        edge = next(e for e in result.graph.edges if e.kind == "replaces_module")
        self.assertEqual(edge.identity_metadata["replaced_module"], target_mod)
        self.assertEqual(edge.identity_metadata["old_version"], "v1.0.0")
        self.assertEqual(edge.metadata["resolution"], "exact")
        self.assertEqual(edge.metadata["replacement_version"], "v1.1.0")

        # Boundary failure 1: non-module replacement (e.g. local directory path)
        non_module = _canonicalize((
            observation("go.module_replace", "go.mod", name=target_mod,
                        metadata={"owner_module_path": ws_owner, "replacement_kind": "file", "replacement": "./local"}),
        ))
        self.assertTrue(non_module.ok)
        self.assertFalse(any(e.kind == "replaces_module" for e in non_module.graph.edges))
        self.assertEqual(accounting(non_module)["unresolved_relationships"], 1)

        # Boundary failure 2: missing replacement target or missing owner module
        for bad_meta in (
            {"owner_module_path": ws_owner, "replacement_kind": "module", "replacement": ""},
            {"owner_module_path": None, "replacement_kind": "module", "replacement": replacement_mod},
        ):
            with self.subTest(meta=bad_meta):
                res = _canonicalize((
                    observation("go.module_replace", "go.mod", name=target_mod, metadata=bad_meta),
                ))
                self.assertTrue(res.ok)
                self.assertFalse(any(e.kind == "replaces_module" for e in res.graph.edges))
                self.assertEqual(accounting(res)["unresolved_relationships"], 1)

    def test_workspace_use_multi_module_routing_and_unresolved_boundary(self) -> None:
        """go.workspace_use routes to multiple sibling modules and tracks unresolved roots."""
        cmd_module_key = go_source_module_key(REPOSITORY_SCOPE, "cmd", "example.invalid/cmd")
        svc_module_key = go_source_module_key(REPOSITORY_SCOPE, "internal/svc", "example.invalid/svc")
        observations = (
            file_observation("go.work"),
            observation("go.module", "cmd/go.mod", name="example.invalid/cmd"),
            observation("go.module", "internal/svc/go.mod", name="example.invalid/svc"),
            observation("go.workspace_use", "go.work", name="./cmd",
                        metadata={"resolved_under_root": True}, source_suffix="use:cmd"),
            observation("go.workspace_use", "go.work", name="internal/svc",
                        metadata={"resolved_under_root": True}, source_suffix="use:svc"),
            observation("go.workspace_use", "go.work", name="missing/pkg",
                        metadata={"resolved_under_root": True}, source_suffix="use:missing"),
        )
        result = _canonicalize(observations)
        self.assertTrue(result.ok)
        work_key = file_key("go.work")
        edges = _edge_tuples(result)
        self.assertIn((work_key, "workspace_uses", cmd_module_key), edges)
        self.assertIn((work_key, "workspace_uses", svc_module_key), edges)

        # Evidence attribution on workspace_use source IDs
        cmd_use = next(o for o in observations if o.source_id.endswith("use:cmd"))
        svc_use = next(o for o in observations if o.source_id.endswith("use:svc"))
        links_by_source = {link.evidence_key: link.canonical_key for link in result.graph.node_evidence_links}
        evidence_by_raw_id = {ev.raw_source_id: ev.evidence_key for ev in result.graph.evidence}
        self.assertEqual(links_by_source[evidence_by_raw_id[cmd_use.source_id]], cmd_module_key)
        self.assertEqual(links_by_source[evidence_by_raw_id[svc_use.source_id]], svc_module_key)
        self.assertEqual(accounting(result)["unresolved_relationships"], 1)

    def test_multi_source_cross_binding_package_import_routing_and_attributes(self) -> None:
        """Cross-source package import resolves bounded_local edges with alias and blank/dot import."""
        app_mod = go_source_module_key(REPOSITORY_SCOPE, "app", "example.invalid/app")
        app_pkg = go_source_package_key(app_mod, ".", "main")
        lib_mod = go_source_module_key(REPOSITORY_SCOPE, "lib", "example.invalid/lib")
        lib_pkg = go_source_package_key(lib_mod, "service", "service")

        cases = [
            ({"alias": "svc", "blank_import": False, "dot_import": False}, "svc", False, False),
            ({"alias": "_", "blank_import": True, "dot_import": False}, "_", True, False),
            ({"alias": ".", "blank_import": False, "dot_import": True}, ".", False, True),
        ]
        for import_meta, exp_alias, exp_blank, exp_dot in cases:
            with self.subTest(meta=import_meta):
                observations = (
                    observation("go.module", "app/go.mod", name="example.invalid/app"),
                    package_observation("app/main.go", "main"),
                    observation("go.module", "lib/go.mod", name="example.invalid/lib"),
                    package_observation("lib/service/service.go", "service"),
                    observation("go.import", "app/main.go", name="example.invalid/lib/service",
                                metadata={"package_name": "main", **import_meta}),
                )
                result = _canonicalize(observations)
                self.assertTrue(result.ok)
                self.assertIn((app_pkg, "imports", lib_pkg), _edge_tuples(result))
                edge = next(e for e in result.graph.edges if e.kind == "imports")
                self.assertEqual(edge.metadata["resolution"], "bounded_local")
                self.assertEqual(edge.metadata["alias"], exp_alias)
                self.assertEqual(edge.metadata["blank_import"], exp_blank)
                self.assertEqual(edge.metadata["dot_import"], exp_dot)

    def test_import_routing_boundary_failures_and_intra_module_collisions(self) -> None:
        """Import collision, cross-source ambiguity, and external test imports fail predictably."""
        # 1. Intra-module collision: same module and directory has multiple package identities
        collision_obs = (
            observation("go.module", "app/go.mod", name="example.invalid/app"),
            package_observation("app/main.go", "main"),
            observation("go.package", "app/pkg/alpha.go", name="alpha", metadata={"package_name": "alpha"}),
            observation("go.package", "app/pkg/beta.go", name="beta", metadata={"package_name": "beta"}),
            observation("go.import", "app/main.go", name="example.invalid/app/pkg", metadata={"package_name": "main"}),
        )
        collision_res = _canonicalize(collision_obs)
        self.assertFalse(collision_res.ok)
        self.assertEqual(accounting(collision_res)["identity_collisions"], 1)
        self.assertEqual(accounting(collision_res)["unresolved_relationships"], 1)
        self.assertFalse(any(e.kind == "imports" for e in collision_res.graph.edges))
        collision_diag = next(d for d in collision_res.diagnostics if d.category == "go_canonical_identity_collision")
        self.assertEqual(collision_diag.severity, "error")
        self.assertIn("local Go import resolves to multiple package identities", collision_diag.message)

        # 2. Ambiguous cross-source import: multiple candidates across distinct source module instances
        ambiguous_obs = (
            observation("go.module", "app/go.mod", name="example.invalid/app"),
            package_observation("app/main.go", "main"),
            observation("go.module", "one/go.mod", name="example.invalid/shared"),
            package_observation("one/pkg/pkg.go", "pkg"),
            observation("go.module", "two/go.mod", name="example.invalid/shared"),
            package_observation("two/pkg/pkg.go", "pkg"),
            observation("go.import", "app/main.go", name="example.invalid/shared/pkg", metadata={"package_name": "main"}),
        )
        ambiguous_res = _canonicalize(ambiguous_obs)
        self.assertTrue(ambiguous_res.ok)
        self.assertFalse(any(e.kind == "imports" for e in ambiguous_res.graph.edges))
        self.assertEqual(accounting(ambiguous_res)["unresolved_relationships"], 1)

        # 3. External test package cannot be imported
        ext_test_obs = (
            observation("go.module", "app/go.mod", name="example.invalid/app"),
            package_observation("app/main.go", "main"),
            observation("go.module", "lib/go.mod", name="example.invalid/lib"),
            observation("go.package", "lib/pkg/pkg_test.go", name="pkg_test",
                        metadata={"package_name": "pkg_test", "external_test_package": True, "test_file": True}),
            observation("go.import", "app/main.go", name="example.invalid/lib/pkg", metadata={"package_name": "main"}),
        )
        ext_res = _canonicalize(ext_test_obs)
        self.assertTrue(ext_res.ok)
        self.assertFalse(any(e.kind == "imports" for e in ext_res.graph.edges))
        self.assertEqual(accounting(ext_res)["unresolved_relationships"], 1)

        # 4. Import observation without enclosing package context
        no_ctx = _canonicalize((
            observation("go.import", "orphan.go", name="example.invalid/lib/pkg", metadata={"package_name": "missing"}),
        ))
        self.assertTrue(no_ctx.ok)
        self.assertFalse(any(e.kind == "imports" for e in no_ctx.graph.edges))
        self.assertEqual(accounting(no_ctx)["unresolved_relationships"], 1)

    def test_method_relationship_resolution_and_receiver_boundary_failures(self) -> None:
        """Method resolves method_of edge to existing type and increments unresolved count for missing type."""
        app_mod = go_source_module_key(REPOSITORY_SCOPE, "app", "example.invalid/app")
        app_pkg = go_source_package_key(app_mod, ".", "app")
        item_type_key = go_source_type_key(app_pkg, "Item")
        validate_method_key = go_source_method_key(app_pkg, "Item", "Validate")

        # 1. Valid method on declared struct type
        valid_method_obs = (
            observation("go.module", "app/go.mod", name="example.invalid/app"),
            package_observation("app/main.go", "app"),
            observation("go.type", "app/main.go", name="Item",
                        metadata={"package_name": "app", "exported": True}, source_suffix="type:Item"),
            observation("go.struct", "app/main.go", name="Item",
                        metadata={"package_name": "app", "parent_source_id": "app/main.go#type:Item"}),
            observation("go.method", "app/main.go", name="Validate",
                        metadata={"package_name": "app", "receiver_base": "Item", "exported": True}),
        )
        valid_res = _canonicalize(valid_method_obs)
        self.assertTrue(valid_res.ok)
        self.assertIn((validate_method_key, "method_of", item_type_key), _edge_tuples(valid_res))
        method_edge = next(e for e in valid_res.graph.edges if e.kind == "method_of")
        self.assertEqual(method_edge.metadata["resolution"], "exact")

        # 2. Method on undeclared receiver type in package leaves relationship unresolved
        unresolved_type_obs = (
            observation("go.module", "app/go.mod", name="example.invalid/app"),
            package_observation("app/main.go", "app"),
            observation("go.method", "app/main.go", name="OrphanMethod",
                        metadata={"package_name": "app", "receiver_base": "UndeclaredType"}),
        )
        unresolved_res = _canonicalize(unresolved_type_obs)
        self.assertTrue(unresolved_res.ok)
        self.assertFalse(any(e.kind == "method_of" for e in unresolved_res.graph.edges))
        self.assertEqual(accounting(unresolved_res)["unresolved_relationships"], 1)

        # 3. Method missing receiver_base fails closed with invalid identity diagnostic
        missing_rcvr_obs = (
            observation("go.module", "app/go.mod", name="example.invalid/app"),
            package_observation("app/main.go", "app"),
            observation("go.method", "app/main.go", name="InvalidMethod",
                        metadata={"package_name": "app", "receiver_base": None}),
        )
        missing_res = _canonicalize(missing_rcvr_obs)
        self.assertFalse(missing_res.ok)
        self.assertEqual(accounting(missing_res)["identity_collisions"], 1)
        self.assertIn("go_canonical_identity_invalid", {d.category for d in missing_res.diagnostics})


if __name__ == "__main__":
    unittest.main()
