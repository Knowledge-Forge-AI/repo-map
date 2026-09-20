"""Shell extraction/canonicalization path and decoder boundary matrix."""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.graph.discovery_extractors import (
    extract_awk_file_observations_from_file,
    extract_bash_file_observations_from_file,
    extract_bats_file_observations_from_file,
    extract_powershell_file_observations_from_file,
    extract_shell_file_observations,
    extract_zsh_file_observations_from_file,
    extract_zunit_file_observations_from_file,
)
from repomap_kg.graph.keys import bash_script_key
from repomap_kg.graph.readback.bash import summarize_bash_evidence
from repomap_test_support.test_scratch import select_scratch_root


class ShellPipelineBoundariesIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(
            tempfile.mkdtemp(dir=select_scratch_root(), prefix="repomap-int-shell-pipeline-")
        ).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_shell_pipeline_nested_traversal_repo_escape_and_binary_boundaries(self) -> None:
        worker_sh = self.tmpdir / "pkg" / "nested" / "worker.sh"
        worker_sh.parent.mkdir(parents=True, exist_ok=True)
        worker_sh.write_text("#!/usr/bin/env bash\nsource ../shared/util.sh\nexport WORKER_PID=123\n", encoding="utf-8")
        util_sh = self.tmpdir / "pkg" / "shared" / "util.sh"
        util_sh.parent.mkdir(parents=True, exist_ok=True)
        util_sh.write_text("#!/usr/bin/env bash\nexport SHARED_TOKEN=\"active\"\n", encoding="utf-8")
        worker_obs = extract_bash_file_observations_from_file(self.tmpdir, "pkg/nested/worker.sh")
        util_obs = extract_bash_file_observations_from_file(self.tmpdir, "pkg/shared/util.sh")
        res_traversal = canonicalize_observations((*worker_obs, *util_obs))
        self.assertTrue(res_traversal.ok)
        traversal_edges = {(e.source_key, e.kind, e.target_key) for e in res_traversal.graph.edges}
        worker_script_key = bash_script_key("pkg/nested/worker.sh")
        self.assertIn((worker_script_key, "sources", "file:pkg/shared/util.sh"), traversal_edges)
        self.assertIn(("file:pkg/nested/worker.sh", "writes_env", "env:WORKER_PID"), traversal_edges)
        self.assertIn(("file:pkg/shared/util.sh", "writes_env", "env:SHARED_TOKEN"), traversal_edges)

        escape_sh = self.tmpdir / "pkg" / "escape.sh"
        escape_sh.write_text("#!/usr/bin/env bash\nsource ../../outside.sh\nsource /etc/profile\n", encoding="utf-8")
        escape_obs = extract_bash_file_observations_from_file(self.tmpdir, "pkg/escape.sh")
        res_escape = canonicalize_observations(escape_obs)
        self.assertTrue(res_escape.ok)
        source_obs = [item for item in escape_obs if item.kind == "shell.source"]
        self.assertEqual(len(source_obs), 2)
        self.assertEqual(source_obs[0].metadata["unknown_reason"], "repo-escaping-source")
        self.assertEqual(source_obs[1].metadata["dynamic_reason"], "computed-source")
        self.assertTrue(all(item.target is None for item in source_obs))
        self.assertIn("file:pkg/escape.sh", {n.canonical_key for n in res_escape.graph.nodes})
        self.assertGreaterEqual(len(res_escape.graph.evidence), 2)
        self.assertFalse(any(e.kind == "sources" for e in res_escape.graph.edges))

        binary_sh = self.tmpdir / "pkg" / "corrupt.sh"
        binary_sh.write_bytes(b"\x7fELF\x02\x01\x01\x00\xff\xfe\x00\x00")
        self.assertEqual(extract_shell_file_observations(self.tmpdir, "pkg/corrupt.sh"), ())
        self.assertEqual(extract_bash_file_observations_from_file(self.tmpdir, "pkg/corrupt.sh"), ())
        empty_res = canonicalize_observations(())
        self.assertTrue(empty_res.ok)
        self.assertEqual(len(empty_res.graph.nodes), 0)

        bash_summary = summarize_bash_evidence((*worker_obs, *util_obs), res_traversal)
        self.assertTrue(bash_summary.safety["bounded"])
        self.assertFalse(bash_summary.safety["shell_executed"])
        self.assertEqual(bash_summary.bash["files"], 2)
        self.assertEqual(bash_summary.bash["sources"], 1)


    def test_six_family_relative_references_keep_evidence_and_refuse_escape(self) -> None:
        shared = self.tmpdir / "pkg" / "shared" / "helper.sh"
        shared.parent.mkdir(parents=True)
        shared.write_text("# Shared static dependency\n", encoding="utf-8")
        cases = (
            ("bash", "bash", "source", "sources", extract_bash_file_observations_from_file),
            ("zsh", "zsh", "source", "includes", extract_zsh_file_observations_from_file),
            ("awk", "awk", "@include", "includes", extract_awk_file_observations_from_file),
            ("powershell", "ps1", ".", "sources", extract_powershell_file_observations_from_file),
            ("bats", "bats", "load", "loads", extract_bats_file_observations_from_file),
            ("zunit", "zunit", "load_helper", "uses_helper", extract_zunit_file_observations_from_file),
        )
        for family, extension, command, relationship, extractor in cases:
            with self.subTest(family=family):
                relative = f"pkg/scripts/entry.{extension}"
                entry = self.tmpdir / relative
                entry.parent.mkdir(parents=True, exist_ok=True)
                entry.write_text(
                    f'{command} "../shared/helper.sh"\n{command} "../../../outside.sh"\n',
                    encoding="utf-8",
                )
                observations = extractor(self.tmpdir, relative)
                result = canonicalize_observations(observations)
                self.assertTrue(result.ok, result.diagnostics)
                matching = [e for e in result.graph.edges if e.kind == relationship
                            and e.target_key == "file:pkg/shared/helper.sh"]
                self.assertEqual(len(matching), 1)
                self.assertFalse(any(e.target_key.startswith("file:") and "outside" in e.target_key
                                     for e in result.graph.edges))
                evidence = {item.evidence_key: item for item in result.graph.evidence}
                links = [link for link in result.graph.edge_evidence_links
                         if link.edge_key == matching[0].edge_key]
                self.assertTrue(links)
                self.assertTrue(all(evidence[link.evidence_key].path == relative for link in links))
                self.assertTrue(all(evidence[link.evidence_key].start_line == 1 for link in links))
                # Decoder refusal must not invent a dependency from invalid source bytes.
                entry.write_bytes(b"\xff\xfe")
                self.assertEqual(extractor(self.tmpdir, relative), ())


if __name__ == "__main__":
    import sys

    sys.exit(
        "Direct execution unsupported: RepoMap integration tests require container sandbox admission via pytest"
    )
