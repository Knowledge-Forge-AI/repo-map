"""Retained Slice14 multi-source capture workflows; isolated telemetry and catalog controls moved to unit ownership."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from repomap_kg.graph.multi_source_pipeline import (
    MultiSourceCaptureError,
    capture_multi_source_candidate,
)
from repomap_kg.graph.multi_source_records import (
    SourceKind,
    graph_source_binding_id,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_test_support.test_scratch import select_scratch_root


class Slice14StagingLifecycleIntegrationTests(unittest.TestCase):
    """Slice 14 Group S14-C integration tests for candidate capture, staging descriptors, and telemetry."""

    def _make_folder_binding(
        self,
        *,
        graph_id: str,
        alias: str,
        root_path: Path,
        logical_root: str = ".",
        exclude_paths: tuple[str, ...] = (),
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
            repository_name="slice14-test-repo",
            logical_root=logical_root,
            privacy="public-dev",
            evidence_retention="inherit",
            extractor_profile="default",
            include_paths=(),
            exclude_paths=exclude_paths,
            selection_policy_id=f"select1:{hex_id}",
            resolution_policy="isolated",
            enabled=True,
            role="source",
        )

    def _make_graph_config(
        self,
        graph_id: str,
        root_path: Path,
        bindings: tuple[OpsGraphSourceBindingConfig, ...],
    ) -> OpsGraphConfig:
        return OpsGraphConfig(
            id=graph_id,
            name=f"Graph {graph_id}",
            root_path=str(root_path),
            root_path_expanded=str(root_path),
            repository_name="slice14-test-repo",
            privacy="public-dev",
            enabled=True,
            mcp_visible=True,
            extractor_profile="default",
            refresh_policy="manual",
            source_bindings=bindings,
            explicit_source_bindings=True,
        )

    def test_s14_c01_multi_source_candidate_logical_root_binding(self) -> None:
        """Multi-source candidate capture preserves configured logical root in source bindings."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            sub = root / "service_core"
            sub.mkdir()
            (sub / "app.py").write_text("VALUE = 42\n", encoding="utf-8")

            binding = self._make_folder_binding(
                graph_id="g-s14-c01",
                alias="core",
                root_path=sub,
                logical_root="services/core",
                seq=1,
            )
            graph = self._make_graph_config("g-s14-c01", root, (binding,))

            bundle = capture_multi_source_candidate(graph)
            self.assertEqual(len(bundle.candidate.snapshots), 1)
            self.assertEqual(
                bundle.candidate.snapshots[0].binding.logical_root,
                "services/core",
            )
            self.assertGreater(len(bundle.observations), 0)

    def test_s14_c02_multi_source_candidate_exclude_filtering(self) -> None:
        """Multi-source candidate capture excludes paths specified in binding configuration."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            sub = root / "repo_dir"
            sub.mkdir()
            (sub / "keep.py").write_text("KEEP = True\n", encoding="utf-8")
            (sub / "skip.txt").write_text("SKIP = True\n", encoding="utf-8")

            binding = self._make_folder_binding(
                graph_id="g-s14-c02",
                alias="sub_repo",
                root_path=sub,
                exclude_paths=("skip.txt",),
                seq=2,
            )
            graph = self._make_graph_config("g-s14-c02", root, (binding,))

            bundle = capture_multi_source_candidate(graph)
            manifest_paths = {
                entry.relative_path
                for entry in bundle.candidate.snapshots[0].manifest_entries
            }
            self.assertIn("keep.py", manifest_paths)
            self.assertNotIn("skip.txt", manifest_paths)

    def test_s14_c03_multi_source_candidate_missing_root_refusal(self) -> None:
        """Attempting to capture candidate from a non-existent directory raises MultiSourceCaptureError."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            non_existent = root / "does_not_exist"

            binding = self._make_folder_binding(
                graph_id="g-s14-c03",
                alias="missing",
                root_path=non_existent,
                seq=3,
            )
            graph = self._make_graph_config("g-s14-c03", root, (binding,))

            with self.assertRaises(MultiSourceCaptureError) as cm:
                capture_multi_source_candidate(graph)
            self.assertEqual(cm.exception.category, "source_unavailable")


if __name__ == "__main__":
    import sys
    sys.exit(
        "Direct execution unsupported; use tools/run_tests.py for container sandbox admission."
    )
