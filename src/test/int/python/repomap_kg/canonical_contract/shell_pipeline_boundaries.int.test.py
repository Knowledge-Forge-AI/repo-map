"""Shell extraction/canonicalization path and decoder boundary matrix."""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.graph.keys import bash_script_key
from repomap_kg.graph.discovery_extractors import (
    extract_bash_file_observations_from_file, extract_shell_file_observations,
)
from repomap_test_support.test_scratch import select_scratch_root


class ShellPipelineBoundariesIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(
            tempfile.mkdtemp(dir=select_scratch_root(), prefix="repomap-int-shell-pipeline-")
        ).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_shell_pipeline_nested_traversal_repo_escape_and_binary_boundaries(self) -> None:
        # 1. Intra-repo relative path traversal across nested subdirectories
        worker_sh = self.tmpdir / "pkg" / "nested" / "worker.sh"
        worker_sh.parent.mkdir(parents=True, exist_ok=True)
        worker_sh.write_text(
            "#!/usr/bin/env bash\nsource ../shared/util.sh\nexport WORKER_PID=123\n",
            encoding="utf-8",
        )
        util_sh = self.tmpdir / "pkg" / "shared" / "util.sh"
        util_sh.parent.mkdir(parents=True, exist_ok=True)
        util_sh.write_text(
            "#!/usr/bin/env bash\nexport SHARED_TOKEN=\"active\"\n",
            encoding="utf-8",
        )
        worker_obs = extract_bash_file_observations_from_file(self.tmpdir, "pkg/nested/worker.sh")
        util_obs = extract_bash_file_observations_from_file(self.tmpdir, "pkg/shared/util.sh")
        res_traversal = canonicalize_observations((*worker_obs, *util_obs))
        self.assertTrue(res_traversal.ok)
        traversal_edges = {(e.source_key, e.kind, e.target_key) for e in res_traversal.graph.edges}
        worker_script_key = bash_script_key("pkg/nested/worker.sh")
        self.assertIn(
            (worker_script_key, "sources", "file:pkg/shared/util.sh"),
            traversal_edges,
        )
        self.assertIn(
            ("file:pkg/nested/worker.sh", "writes_env", "env:WORKER_PID"),
            traversal_edges,
        )
        self.assertIn(
            ("file:pkg/shared/util.sh", "writes_env", "env:SHARED_TOKEN"),
            traversal_edges,
        )

        # 2. Negative repo-escaping source traversal: evidence recorded, but no edge created
        escape_sh = self.tmpdir / "pkg" / "escape.sh"
        escape_sh.write_text(
            "#!/usr/bin/env bash\nsource ../../outside.sh\nsource /etc/profile\n",
            encoding="utf-8",
        )
        escape_obs = extract_bash_file_observations_from_file(self.tmpdir, "pkg/escape.sh")
        res_escape = canonicalize_observations(escape_obs)
        self.assertTrue(res_escape.ok)
        source_observations = [item for item in escape_obs if item.kind == "shell.source"]
        self.assertEqual(len(source_observations), 2)
        self.assertEqual(source_observations[0].metadata["unknown_reason"], "repo-escaping-source")
        self.assertEqual(source_observations[1].metadata["dynamic_reason"], "computed-source")
        self.assertTrue(all(item.target is None for item in source_observations))

        self.assertIn("file:pkg/escape.sh", {n.canonical_key for n in res_escape.graph.nodes})
        self.assertGreaterEqual(len(res_escape.graph.evidence), 2)
        self.assertFalse(any(e.kind == "sources" for e in res_escape.graph.edges))

        # 3. Malformed/binary non-UTF8 script safety boundary: returns () without raising
        binary_sh = self.tmpdir / "pkg" / "corrupt.sh"
        binary_sh.write_bytes(b"\x7fELF\x02\x01\x01\x00\xff\xfe\x00\x00")
        self.assertEqual(extract_shell_file_observations(self.tmpdir, "pkg/corrupt.sh"), ())
        self.assertEqual(
            extract_bash_file_observations_from_file(self.tmpdir, "pkg/corrupt.sh"),
            (),
        )
        empty_res = canonicalize_observations(())
        self.assertTrue(empty_res.ok)
        self.assertEqual(len(empty_res.graph.nodes), 0)
        self.assertEqual(len(empty_res.graph.edges), 0)

