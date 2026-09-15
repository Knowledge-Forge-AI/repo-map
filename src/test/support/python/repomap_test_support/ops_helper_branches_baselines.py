import tempfile
import unittest
from pathlib import Path


from repomap_kg.ops import refresh as ops_refresh


class OpsBaselineHelperBranchContract(unittest.TestCase):
    __test__ = False

    def test_baseline_path_helpers_cover_safe_error_branches(self):
        self.assertEqual(ops_refresh._baseline_path_segment("repo-map", "graph"), "repo-map")
        for value in ("", ".", "..", "../x", "bad/value", "bad value"):
            with self.subTest(value=value):
                with self.assertRaises(ops_refresh.OpsRefreshError):
                    ops_refresh._baseline_path_segment(value, "graph")

        self.assertEqual(ops_refresh._baseline_kinds("stored"), ("stored",))
        self.assertEqual(ops_refresh._baseline_kinds("preflight"), ("preflight",))
        self.assertEqual(ops_refresh._baseline_kinds("both"), ("stored", "preflight"))
        with self.assertRaises(ops_refresh.OpsRefreshError):
            ops_refresh._baseline_kinds("raw")
        self.assertEqual(
            ops_refresh._baseline_display_path("flakes", "stored", "latest.json"),
            "status/baselines/flakes/stored/latest.json",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo-map-home" / "status" / "baselines"
            root.mkdir(parents=True)
            inside = root / "flakes" / "stored"
            inside.mkdir(parents=True)
            outside = Path(tmpdir) / "outside"
            outside.mkdir()

            ops_refresh._ensure_path_under_baseline_root(root, root)
            ops_refresh._ensure_path_under_baseline_root(inside, root)
            with self.assertRaises(ops_refresh.OpsRefreshError):
                ops_refresh._ensure_path_under_baseline_root(outside, root)

            target = inside / "20260703T000000Z.json"
            ops_refresh._atomic_write_text(target, "{}\n", replace_existing=False)
            with self.assertRaises(ops_refresh.OpsRefreshError):
                ops_refresh._atomic_write_text(target, "{}\n", replace_existing=False)
            ops_refresh._atomic_write_text(target, '{"ok": true}\n', replace_existing=True)
            self.assertEqual(target.read_text(encoding="utf-8"), '{"ok": true}\n')

    def test_baseline_prune_kind_handles_missing_and_ignored_files_safely(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline_root = Path(tmpdir) / "status" / "baselines"
            graph_root = baseline_root / "flakes"

            missing = ops_refresh._prune_baseline_kind(
                graph_root,
                graph_segment="flakes",
                kind="stored",
                keep=1,
                dry_run=True,
                baseline_root=baseline_root,
            )
            self.assertEqual(missing.timestamped_files_found, 0)
            self.assertEqual(missing.candidate_count, 0)
            self.assertFalse(missing.latest_exists)

            stored_dir = graph_root / "stored"
            stored_dir.mkdir(parents=True)
            (stored_dir / "latest.json").write_text("{}", encoding="utf-8")
            (stored_dir / "20260703T000000Z.json").write_text("{}", encoding="utf-8")
            (stored_dir / "20260702T000000Z.json").write_text("{}", encoding="utf-8")
            (stored_dir / "not-a-baseline.txt").write_text("x", encoding="utf-8")
            (stored_dir / "nested").mkdir()

            dry_run = ops_refresh._prune_baseline_kind(
                graph_root,
                graph_segment="flakes",
                kind="stored",
                keep=1,
                dry_run=True,
                baseline_root=baseline_root,
            )
            self.assertEqual(dry_run.timestamped_files_found, 2)
            self.assertEqual(dry_run.kept_count, 1)
            self.assertEqual(dry_run.candidate_count, 1)
            self.assertEqual(dry_run.ignored_count, 2)
            self.assertTrue(dry_run.latest_preserved)
            self.assertTrue((stored_dir / "20260702T000000Z.json").exists())

            actual = ops_refresh._prune_baseline_kind(
                graph_root,
                graph_segment="flakes",
                kind="stored",
                keep=1,
                dry_run=False,
                baseline_root=baseline_root,
            )
            self.assertEqual(actual.deleted_count, 1)
            self.assertFalse((stored_dir / "20260702T000000Z.json").exists())
            self.assertTrue((stored_dir / "latest.json").exists())
            self.assertTrue((stored_dir / "not-a-baseline.txt").exists())
            self.assertTrue((stored_dir / "nested").exists())

            preflight_path = graph_root / "preflight"
            preflight_path.write_text("not a directory", encoding="utf-8")
            with self.assertRaises(ops_refresh.OpsRefreshError):
                ops_refresh._prune_baseline_kind(
                    graph_root,
                    graph_segment="flakes",
                    kind="preflight",
                    keep=1,
                    dry_run=True,
                    baseline_root=baseline_root,
                )
