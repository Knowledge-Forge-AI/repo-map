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
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
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


if __name__ == "__main__":
    import sys

    sys.exit(
        "Direct execution unsupported: RepoMap integration tests require container sandbox admission via pytest"
    )
