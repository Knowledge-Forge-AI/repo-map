"""Integration tests for Slice 13 multi-source acquisition (Group S13-B).

Covers:
- S13-B01: Alias-qualified collision of identical relative paths
- S13-B02: One-binding content change and generation separation
- S13-B03: Whole-vector mutation detection during capture
- S13-B04: Mixed source privacy aggregation
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.graph.multi_source_pipeline import (
    MultiSourceCaptureError,
    capture_multi_source_candidate,
    scan_multi_source_generations,
)
import repomap_kg.graph.multi_source_pipeline as msp
from repomap_kg.graph.multi_source_records import (
    SourceKind,
    graph_source_binding_id,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_test_support.test_scratch import select_scratch_root


class Slice13MultiSourceAcquisitionIntegrationTests(unittest.TestCase):
    """Slice 13 Group S13-B integration tests for multi-source candidate capture and provenance."""

    def _make_folder_binding(
        self,
        *,
        graph_id: str,
        alias: str,
        root_path: Path,
        privacy: str = "public-dev",
        seq: int = 1,
    ) -> OpsGraphSourceBindingConfig:
        hex_id = f"{seq:064x}"
        return OpsGraphSourceBindingConfig(
            schema_version=1,
            binding_id=graph_source_binding_id(graph_id, alias),
            source_definition_id=f"src1:{hex_id}",
            alias=alias,
            revision=1,
            source_kind=SourceKind.FOLDER,
            root_path=str(root_path),
            root_path_expanded=str(root_path),
            repository_name="slice13-test-repo",
            logical_root=".",
            privacy=privacy,
            evidence_retention="inherit",
            extractor_profile="default",
            include_paths=(),
            exclude_paths=(),
            selection_policy_id=f"select1:{hex_id}",
            resolution_policy="isolated",
            enabled=True,
            role="source",
        )

    def test_s13_b01_alias_qualified_relative_path_collision_separation(self) -> None:
        """Separates observations and canonical representations when distinct bindings share relative paths."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            d1 = root / "service_a"
            d2 = root / "service_b"
            d1.mkdir()
            d2.mkdir()
            (d1 / "common.py").write_text("MODULE_NAME = 'service_a'\n", encoding="utf-8")
            (d2 / "common.py").write_text("MODULE_NAME = 'service_b'\n", encoding="utf-8")

            b1 = self._make_folder_binding(graph_id="g-s13-b01", alias="svc_a", root_path=d1, seq=1)
            b2 = self._make_folder_binding(graph_id="g-s13-b01", alias="svc_b", root_path=d2, seq=2)
            graph = OpsGraphConfig(
                id="g-s13-b01",
                name="S13 B01 Graph",
                root_path=str(root),
                root_path_expanded=str(root),
                repository_name="slice13-test-repo",
                privacy="public-dev",
                enabled=True,
                mcp_visible=True,
                extractor_profile="default",
                refresh_policy="manual",
                source_bindings=(b1, b2),
                explicit_source_bindings=True,
            )

            bundle = capture_multi_source_candidate(graph)
            obs_a = [o for o in bundle.observations if o.path == "svc_a/common.py"]
            obs_b = [o for o in bundle.observations if o.path == "svc_b/common.py"]
            self.assertTrue(len(obs_a) >= 1)
            self.assertTrue(len(obs_b) >= 1)

            file_obs_a = next(o for o in obs_a if o.kind == "file")
            file_obs_b = next(o for o in obs_b if o.kind == "file")
            self.assertNotEqual(file_obs_a.source_id, file_obs_b.source_id)
            self.assertNotEqual(file_obs_a.metadata.get("content_hash"), file_obs_b.metadata.get("content_hash"))

            res = canonicalize_observations(bundle.observations)
            self.assertTrue(res.ok)
            node_keys = {n.canonical_key for n in res.graph.nodes}
            self.assertIn("file:svc_a/common.py", node_keys)
            self.assertIn("file:svc_b/common.py", node_keys)

    def test_s13_b02_single_binding_mutation_generation_divergence(self) -> None:
        """Distinguishes source generation updates upon file mutation from unchanged config generation."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            d1 = root / "src_alpha"
            d2 = root / "src_beta"
            d1.mkdir()
            d2.mkdir()
            (d1 / "core.py").write_text("x = 10\n", encoding="utf-8")
            (d2 / "core.py").write_text("y = 20\n", encoding="utf-8")

            b1 = self._make_folder_binding(graph_id="g-s13-b02", alias="alpha", root_path=d1, seq=1)
            b2 = self._make_folder_binding(graph_id="g-s13-b02", alias="beta", root_path=d2, seq=2)
            graph = OpsGraphConfig(
                id="g-s13-b02",
                name="S13 B02 Graph",
                root_path=str(root),
                root_path_expanded=str(root),
                repository_name="slice13-test-repo",
                privacy="public-dev",
                enabled=True,
                mcp_visible=True,
                extractor_profile="default",
                refresh_policy="manual",
                source_bindings=(b1, b2),
                explicit_source_bindings=True,
            )

            bundle1 = capture_multi_source_candidate(graph)
            scan1 = scan_multi_source_generations(graph)
            self.assertEqual(scan1.source_generation, bundle1.source_generation)
            self.assertEqual(scan1.config_generation, bundle1.config_generation)

            # Mutate one file in binding alpha only
            (d1 / "core.py").write_text("x = 1000\n", encoding="utf-8")

            bundle2 = capture_multi_source_candidate(graph)
            scan2 = scan_multi_source_generations(graph)

            # Source generation diverged due to content hash difference
            self.assertNotEqual(bundle2.source_generation, bundle1.source_generation)
            self.assertEqual(scan2.source_generation, bundle2.source_generation)

            # Semantic configuration generation remains constant because binding structure is unchanged
            self.assertEqual(bundle2.config_generation, bundle1.config_generation)
            self.assertEqual(scan2.config_generation, bundle1.config_generation)

    def test_s13_b03_whole_vector_mutation_detection_and_recovery(self) -> None:
        """Detects in-flight source mutations between initial and final inventory checks and recovers."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            d1 = root / "live_src"
            d1.mkdir()
            (d1 / "state.py").write_text("initial = True\n", encoding="utf-8")

            b1 = self._make_folder_binding(graph_id="g-s13-b03", alias="live", root_path=d1, seq=1)
            graph = OpsGraphConfig(
                id="g-s13-b03",
                name="S13 B03 Graph",
                root_path=str(root),
                root_path_expanded=str(root),
                repository_name="slice13-test-repo",
                privacy="public-dev",
                enabled=True,
                mcp_visible=True,
                extractor_profile="default",
                refresh_policy="manual",
                source_bindings=(b1,),
                explicit_source_bindings=True,
            )

            original_resolve = msp.resolve_nix_relations

            def mutate_during_capture(observations: Any, views: Any) -> Any:
                (d1 / "state.py").write_text("in_flight_mutation = True\n", encoding="utf-8")
                return original_resolve(observations, views)

            with patch.object(msp, "resolve_nix_relations", side_effect=mutate_during_capture):
                with self.assertRaises(MultiSourceCaptureError) as ctx:
                    capture_multi_source_candidate(graph)
                self.assertEqual(ctx.exception.category, "source_changed")
                self.assertIn("source binding changed during capture", str(ctx.exception))

            # Without race mutations, capture recovers cleanly and produces a valid bundle
            recovered = capture_multi_source_candidate(graph)
            self.assertEqual(recovered.candidate.graph_id, "g-s13-b03")
            self.assertTrue(len(recovered.observations) >= 1)

    def test_s13_b04_mixed_privacy_source_aggregation_and_provenance(self) -> None:
        """Aggregates mixed binding privacy levels to private-ops while preserving all-public privacy."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            d1 = root / "sub_pub"
            d2 = root / "sub_sec"
            d1.mkdir()
            d2.mkdir()
            (d1 / "open.py").write_text("PUBLIC = 1\n", encoding="utf-8")
            (d2 / "secret.py").write_text("SECRET = 1\n", encoding="utf-8")

            b_pub1 = self._make_folder_binding(graph_id="g-s13-b04", alias="pub1", root_path=d1, privacy="public-dev", seq=1)
            b_pub2 = self._make_folder_binding(graph_id="g-s13-b04", alias="pub2", root_path=d2, privacy="public-dev", seq=2)
            b_priv2 = replace(b_pub2, privacy="private-ops")

            graph_all_public = OpsGraphConfig(
                id="g-s13-b04",
                name="S13 B04 Graph",
                root_path=str(root),
                root_path_expanded=str(root),
                repository_name="slice13-test-repo",
                privacy="public-dev",
                enabled=True,
                mcp_visible=True,
                extractor_profile="default",
                refresh_policy="manual",
                source_bindings=(b_pub1, b_pub2),
                explicit_source_bindings=True,
            )
            bundle_pub = capture_multi_source_candidate(graph_all_public)
            self.assertEqual(bundle_pub.privacy, "public-dev")
            self.assertEqual(len(bundle_pub.candidate.snapshot_vector), 2)

            graph_mixed = replace(graph_all_public, source_bindings=(b_pub1, b_priv2))
            bundle_mixed = capture_multi_source_candidate(graph_mixed)
            self.assertEqual(bundle_mixed.privacy, "private-ops")
            self.assertEqual(len(bundle_mixed.candidate.snapshot_vector), 2)


if __name__ == "__main__":
    import sys
    sys.exit(
        "Direct execution unsupported; use tools/run_tests.py for container sandbox admission."
    )
