"""Cross-component integration tests for multi-source discovery and canonicalization.

Exercises:
1. Multi-source folder structure setup across distinct directory boundaries.
2. Candidate capture and raw observation namespacing across source boundaries.
3. Canonicalization engine resolving multi-source candidate graphs without collision.
4. Ordering determinism across binding permutations.
5. Concrete node, edge, and evidence link verification.
6. Nix cross-source relation resolution across binding boundaries.
7. Malformed path traversal and unavailable source refusal.
8. Privacy boundary inheritance across heterogeneous source bindings.
9. Mixed-source Nix and JavaScript routing ownership and framework semantics.
10. Bounded Nix resolver non-exact outcomes and opaque targets without invented edges.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.extractors.config.nix_resolver import ResolutionOutcome
from repomap_kg.graph.keys import (
    js_class_key,
    js_component_key,
    js_function_key,
    js_method_key,
    js_module_key,
    js_route_key,
    js_variable_key,
    nix_app_key,
    nix_package_key,
)
from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_kg.graph.multi_source_pipeline import (
    MultiSourceCaptureError,
    capture_multi_source_candidate,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_test_support.test_scratch import select_scratch_root


def _binding(
    graph_id: str,
    root: Path,
    alias: str,
    *,
    privacy: str = "public-dev",
    role: str = "module",
    input_name: str | None = None,
) -> OpsGraphSourceBindingConfig:
    return OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id(graph_id, alias),
        source_definition_id=f"src1:{alias}",
        alias=alias,
        revision=1,
        source_kind=SourceKind.FOLDER,
        root_path=str(root),
        root_path_expanded=str(root),
        repository_name=f"fixture-{alias}",
        logical_root=".",
        privacy=privacy,
        evidence_retention="metadata-only",
        extractor_profile="default",
        include_paths=(),
        exclude_paths=(),
        selection_policy_id=source_selection_policy_id((), ()),
        resolution_policy="allow-declared",
        enabled=True,
        role=role,
        input_name=input_name,
    )


def _graph(
    graph_id: str,
    *bindings: OpsGraphSourceBindingConfig,
    privacy: str = "public-dev",
) -> OpsGraphConfig:
    return OpsGraphConfig(
        id=graph_id,
        name=graph_id,
        root_path="",
        root_path_expanded="",
        repository_name="[multi-source]",
        privacy=privacy,
        enabled=True,
        mcp_visible=True,
        extractor_profile="",
        refresh_policy="manual",
        source_bindings=tuple(bindings),
        explicit_source_bindings=True,
    )


class MultiSourceCanonicalPipelineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(
            tempfile.mkdtemp(
                dir=select_scratch_root(),
                prefix="repomap-int-multisource-pipeline-",
            )
        ).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_same_relative_path_namespace_isolation_and_evidence_links(self) -> None:
        src1 = self.tmpdir / "src1"
        src2 = self.tmpdir / "src2"
        (src1 / "scripts").mkdir(parents=True)
        (src2 / "scripts").mkdir(parents=True)
        (src1 / "scripts" / "deploy.sh").write_text(
            "#!/usr/bin/env bash\nexport SERVICE=\"svc1\"\necho \"Deploy svc1\"\n",
            encoding="utf-8",
        )
        (src2 / "scripts" / "deploy.sh").write_text(
            "#!/usr/bin/env bash\nexport SERVICE=\"svc2\"\necho \"Deploy svc2\"\n",
            encoding="utf-8",
        )

        b1 = _binding("g-iso", src1, "service1")
        b2 = _binding("g-iso", src2, "service2")
        bundle = capture_multi_source_candidate(_graph("g-iso", b1, b2))

        paths = {o.path for o in bundle.observations}
        self.assertIn("service1/scripts/deploy.sh", paths)
        self.assertIn("service2/scripts/deploy.sh", paths)

        result = canonicalize_observations(bundle.observations)
        self.assertTrue(result.ok)
        node_keys = {n.canonical_key for n in result.graph.nodes}
        self.assertTrue(any("service1/scripts/deploy.sh" in k for k in node_keys))
        self.assertTrue(any("service2/scripts/deploy.sh" in k for k in node_keys))
        matching_nodes = [k for k in node_keys if "deploy.sh" in k]
        self.assertTrue(len(matching_nodes) >= 2)
        self.assertTrue(len(result.graph.evidence) >= 2)
        self.assertTrue(len(result.graph.edges) >= 2)

    def test_ordering_determinism_across_binding_permutations(self) -> None:
        src1 = self.tmpdir / "det1"
        src2 = self.tmpdir / "det2"
        src1.mkdir(parents=True)
        src2.mkdir(parents=True)
        (src1 / "tool.sh").write_text("#!/usr/bin/env bash\necho 1\n", encoding="utf-8")
        (src2 / "tool.sh").write_text("#!/usr/bin/env bash\necho 2\n", encoding="utf-8")

        b1 = _binding("g-det", src1, "b1")
        b2 = _binding("g-det", src2, "b2")

        first = capture_multi_source_candidate(_graph("g-det", b1, b2))
        second = capture_multi_source_candidate(_graph("g-det", b2, b1))
        self.assertEqual(first.candidate, second.candidate)

        res1 = canonicalize_observations(first.observations)
        res2 = canonicalize_observations(second.observations)
        self.assertEqual(
            {n.canonical_key for n in res1.graph.nodes},
            {n.canonical_key for n in res2.graph.nodes},
        )
        self.assertEqual(
            {(e.source_key, e.kind, e.target_key) for e in res1.graph.edges},
            {(e.source_key, e.kind, e.target_key) for e in res2.graph.edges},
        )

    def test_nix_cross_source_relation_resolution(self) -> None:
        entry = self.tmpdir / "nix_entry"
        composition = self.tmpdir / "nix_composition"
        (entry / "modules").mkdir(parents=True)
        (entry / "modules" / "default.nix").write_text("{ ... }: {}\n", encoding="utf-8")
        (entry / "flake.nix").write_text(
            "{ inputs, ... }: { imports = [ ./modules/default.nix inputs.composition.nixosModules.default ]; }\n",
            encoding="utf-8",
        )
        (composition / "modules").mkdir(parents=True)
        (composition / "modules" / "default.nix").write_text("{ ... }: {}\n", encoding="utf-8")
        (composition / "flake.nix").write_text(
            "{ ... }: { nixosModules.default = import ./modules/default.nix; }\n",
            encoding="utf-8",
        )

        b_entry = _binding("nix-g", entry, "entry", role="entry", input_name=None)
        b_comp = _binding(
            "nix-g", composition, "composition", role="module", input_name="composition"
        )
        bundle = capture_multi_source_candidate(_graph("nix-g", b_entry, b_comp))

        exact_cross = [
            r for r in bundle.resolutions if r.cross_binding and r.outcome.value == "exact"
        ]
        self.assertTrue(len(exact_cross) >= 1)

        result = canonicalize_observations(bundle.observations)
        self.assertTrue(result.ok)
        node_keys = {n.canonical_key for n in result.graph.nodes}
        self.assertTrue(any("entry" in k for k in node_keys))
        self.assertTrue(any("composition" in k for k in node_keys))

    def test_unavailable_source_and_disabled_binding_refusal(self) -> None:
        missing_root = self.tmpdir / "missing_dir"
        bad_b = _binding("g-err", missing_root, "missing")
        with self.assertRaises(MultiSourceCaptureError) as ctx:
            capture_multi_source_candidate(_graph("g-err", bad_b))
        self.assertEqual(ctx.exception.category, "source_unavailable")

        valid_dir = self.tmpdir / "valid"
        valid_dir.mkdir(parents=True)
        (valid_dir / "f.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        disabled_b = replace(_binding("g-err", valid_dir, "valid"), enabled=False)
        with self.assertRaises(MultiSourceCaptureError) as ctx2:
            capture_multi_source_candidate(_graph("g-err", disabled_b))
        self.assertEqual(ctx2.exception.category, "source_invalid")

    def test_privacy_boundary_inheritance(self) -> None:
        p1 = self.tmpdir / "priv1"
        p2 = self.tmpdir / "priv2"
        p1.mkdir(parents=True)
        p2.mkdir(parents=True)
        (p1 / "a.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (p2 / "b.sh").write_text("#!/bin/sh\n", encoding="utf-8")

        b_pub1 = _binding("g-priv", p1, "pub1", privacy="public-dev")
        b_pub2 = _binding("g-priv", p2, "pub2", privacy="public-dev")
        pub_bundle = capture_multi_source_candidate(
            _graph("g-priv", b_pub1, b_pub2, privacy="public-dev")
        )
        self.assertEqual(pub_bundle.privacy, "public-dev")

        b_priv = _binding("g-priv", p2, "priv", privacy="private-ops")
        priv_bundle = capture_multi_source_candidate(
            _graph("g-priv", b_pub1, b_priv, privacy="public-dev")
        )
        self.assertEqual(priv_bundle.privacy, "private-ops")

    def test_mixed_source_nix_and_javascript_routing_and_non_exact_resolution(self) -> None:
        infra = self.tmpdir / "infra"
        frontend = self.tmpdir / "frontend"
        shared_a = self.tmpdir / "shared_a"
        shared_b = self.tmpdir / "shared_b"
        conflict = self.tmpdir / "conflict"
        for path in (infra, frontend, shared_a, shared_b, conflict):
            path.mkdir(parents=True)
        (infra / "modules").mkdir()
        (infra / "modules" / "srv.nix").write_text("{ ... }: {}\n", encoding="utf-8")
        (infra / "flake.nix").write_text(
            "{\n  inputs = {\n"
            '    nixpkgs.url = "github:NixOS/nixpkgs";\n'
            '    ui.url = "path:../frontend";\n'
            '    ui.follows = "nixpkgs";\n'
            '    shared.url = "path:../shared_a";\n'
            '    conflict.url = "path:../conflict";\n'
            "  };\n"
            "  outputs = { self, nixpkgs, ui }: {\n"
            "    packages.x86_64-linux.srv = ./modules/srv.nix;\n"
            '    apps.x86_64-linux.srv = { type = "app"; program = "${self.packages.x86_64-linux.srv}/bin/srv"; };\n'
            "    nixosModules.srv = ./modules/srv.nix;\n"
            "  };\n}\n",
            encoding="utf-8",
        )
        (infra / "deploy.nix").write_text(
            "{\n  imports = [\n"
            "    inputs.ui.nixosModules.web\n"
            "    inputs.shared.nixosModules.srv\n"
            "    inputs.conflict.nixosModules.dup\n"
            "    inputs.unregistered.nixosModules.missing\n"
            "    inputs.ui.nixosModules.${dyn}\n"
            "  ];\n}\n",
            encoding="utf-8",
        )
        (frontend / "modules").mkdir()
        (frontend / "modules" / "web.nix").write_text("{ ... }: {}\n", encoding="utf-8")
        (frontend / "flake.nix").write_text(
            "{ outputs = { self }: { nixosModules.web = ./modules/web.nix; }; }\n",
            encoding="utf-8",
        )
        (frontend / "src").mkdir()
        (frontend / "src" / "svc.js").write_text(
            "export function query() { return 1; }\n", encoding="utf-8"
        )
        (frontend / "src" / "app.jsx").write_text(
            'import React, { useState } from "react";\n'
            'import express from "express";\n'
            'import { query } from "./svc.js";\n'
            "const api = express();\n"
            'api.get("/api/health", (req, res) => res.send("ok"));\n'
            "export class Runner {\n"
            "  run() {\n"
            "    return query();\n"
            "  }\n"
            "}\n"
            "export function Widget() {\n"
            "  const [val] = useState(0);\n"
            "  return <div>{val}</div>;\n"
            "}\n",
            encoding="utf-8",
        )
        for path in (shared_a, shared_b):
            (path / "mod.nix").write_text("{ ... }: {}\n", encoding="utf-8")
            (path / "flake.nix").write_text(
                "{ outputs = { self }: { nixosModules.srv = ./mod.nix; }; }\n",
                encoding="utf-8",
            )
        (conflict / "m1.nix").write_text("{ ... }: {}\n", encoding="utf-8")
        (conflict / "m2.nix").write_text("{ ... }: {}\n", encoding="utf-8")
        (conflict / "flake.nix").write_text(
            "{\n  outputs = { self }: {\n"
            "    nixosModules.dup = ./m1.nix;\n"
            "    nixosModules.dup = ./m2.nix;\n"
            "  };\n}\n",
            encoding="utf-8",
        )

        bindings = (
            _binding("g-all", infra, "infra", role="entry"),
            _binding("g-all", frontend, "frontend", role="frontend", input_name="ui"),
            _binding("g-all", shared_a, "sa", input_name="shared"),
            _binding("g-all", shared_b, "sb", input_name="shared"),
            _binding("g-all", conflict, "conflict", input_name="conflict"),
        )
        graph = _graph("g-all", *bindings)
        bundle = capture_multi_source_candidate(graph)
        inputs_by_name = {
            o.name: o.metadata for o in bundle.observations if o.kind == "nix.flake_input"
        }
        self.assertEqual(inputs_by_name["ui"]["source_type"], "follows")
        self.assertTrue(inputs_by_name["ui"]["has_follows"])

        for obs in bundle.observations:
            self.assertIn("binding_alias", obs.metadata)
            self.assertIn("snapshot_id", obs.metadata)

        res_by_outcome = {r.outcome: r for r in bundle.resolutions}
        self.assertIn(ResolutionOutcome.EXACT, res_by_outcome)
        self.assertIn(ResolutionOutcome.AMBIGUOUS, res_by_outcome)
        self.assertIn(ResolutionOutcome.CONFLICTING, res_by_outcome)
        self.assertIn(ResolutionOutcome.UNSUPPORTED, res_by_outcome)
        self.assertIn(ResolutionOutcome.EVALUATION_DEPENDENT, res_by_outcome)
        self.assertEqual(res_by_outcome[ResolutionOutcome.EXACT].target_path, "frontend/modules/web.nix")
        self.assertEqual(res_by_outcome[ResolutionOutcome.AMBIGUOUS].candidate_bindings, ("sa", "sb"))
        self.assertEqual(res_by_outcome[ResolutionOutcome.CONFLICTING].target_binding, "conflict")

        canon = canonicalize_observations(bundle.observations)
        self.assertTrue(canon.ok)
        self.assertTrue(canon.graph.edge_evidence_links)
        nodes = {n.canonical_key for n in canon.graph.nodes}
        edges = {(e.source_key, e.kind, e.target_key) for e in canon.graph.edges}

        self.assertIn(nix_package_key("infra", "x86_64-linux", "srv"), nodes)
        self.assertIn(nix_app_key("infra", "x86_64-linux", "srv"), nodes)
        self.assertIn(("file:infra/deploy.nix", "sources", "file:frontend/modules/web.nix"), edges)

        cls_key = js_class_key("src/app.jsx", "Runner")
        mth_key = js_method_key(cls_key, "run")
        mod_key = js_module_key("src/app.jsx")
        self.assertIn(cls_key, nodes)
        self.assertIn(mth_key, nodes)
        self.assertIn(js_component_key("src/app.jsx", "Widget"), nodes)
        self.assertIn(js_function_key("src/app.jsx", "Widget"), nodes)
        self.assertIn(js_variable_key("src/app.jsx", "api"), nodes)
        self.assertIn(js_route_key("src/app.jsx", "/routes/get:/api/health"), nodes)
        self.assertIn(js_function_key("src/svc.js", "query"), nodes)
        self.assertIn("external:js-package:react", nodes)
        self.assertIn("external:js-package:express", nodes)

        self.assertIn((mod_key, "defines", cls_key), edges)
        self.assertIn((cls_key, "defines", mth_key), edges)
        self.assertIn((mod_key, "defines", js_component_key("src/app.jsx", "Widget")), edges)
        self.assertIn((mod_key, "defines", js_route_key("src/app.jsx", "/routes/get:/api/health")), edges)
        self.assertIn((mod_key, "references", "external:js-package:react"), edges)
        self.assertIn((mod_key, "references", "external:js-package:express"), edges)
        self.assertIn((mod_key, "references", "file:frontend/src/svc.js"), edges)

        opaque = {d.placeholder_key for d in canon.diagnostics if "opaque" in d.category}
        self.assertEqual(len(opaque), 4)
        real_targets = {"file:sa/mod.nix", "file:sb/mod.nix", "file:conflict/m1.nix", "file:conflict/m2.nix"}
        edge_targets = {e.target_key for e in canon.graph.edges if e.source_key == "file:infra/deploy.nix"}
        self.assertTrue(real_targets.isdisjoint(edge_targets))
        self.assertTrue(opaque.issubset(edge_targets))


if __name__ == "__main__":
    import sys

    sys.exit(
        "Direct execution unsupported: RepoMap integration tests require container sandbox admission via pytest"
    )
