"""Shell extraction/canonicalization path and decoder boundary matrix."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import re
import tempfile
import unittest

import ast

from repomap_kg.artifacts.bundle import PublicationBundle
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.artifacts.source_sealer import seal_configured_sources
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.extractors.documents.css_support import _parse_declarations
from repomap_kg.extractors.languages.python_web_helpers import (
    _fastapi_dependencies,
    _python_web_import_aliases,
)
from repomap_kg.coordinator._portable_capability import (
    PortableExecutionCapability, create_portable_capability,
)
from repomap_kg.coordinator._portable_worker_launch import run_portable_worker
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
from repomap_kg.observations.raw import RawObservation
from repomap_test_support.portable_publication_fixtures import create_single_source_graph_config
from repomap_test_support.portable_worker_scenarios import coordinator_test_limits
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
                target = "../shared/helper.sh"
                expected_target = "file:pkg/shared/helper.sh"
                if family == "awk":
                    target = "shared/helper.awk"
                    expected_target = "file:pkg/scripts/shared/helper.awk"
                    awk_helper = entry.parent / target
                    awk_helper.parent.mkdir(parents=True, exist_ok=True)
                    awk_helper.write_text("# Static AWK include\n", encoding="utf-8")
                entry.write_text(
                    f'{command} "{target}"\n{command} "../../../outside.sh"\n'
                    + ('@include "../shared/helper.sh"\n' if family == "awk" else ""),
                    encoding="utf-8",
                )
                observations = extractor(self.tmpdir, relative)
                result = canonicalize_observations(observations)
                if family == "powershell":
                    self.assertFalse(result.ok, f"expected refusal for {family}: {result.diagnostics}")
                    self.assertEqual(
                        [item.category for item in result.diagnostics], ["repo_escaping_path"],
                        f"diagnostic category mismatch for {family}: {result.diagnostics}",
                    )
                else:
                    self.assertTrue(result.ok, f"unexpected refusal for {family}: {result.diagnostics}")
                matching = [e for e in result.graph.edges if e.kind == relationship
                            and e.target_key == expected_target]
                self.assertEqual(len(matching), 1)
                if family == "awk":
                    self.assertEqual(
                        [e.target_key for e in result.graph.edges if e.kind == "includes"],
                        [expected_target],
                    )
                    self.assertTrue({2, 3}.issubset(
                        {item.start_line for item in result.graph.evidence}
                    ))
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
                self.assertEqual(
                    extractor(self.tmpdir, relative), (),
                    f"decoder refusal produced non-empty observations for {family}",
                )

    def test_portable_dynamic_corpus_preserves_unknowns_without_false_publication(self) -> None:
        fixtures = Path(__file__).parents[4] / "fixtures"
        selected = (
            "shell/bash/dynamic.bash", "shell/zsh/dynamic.zsh",
            "shell/awk/dynamic.awk", "shell/bats/dynamic.bats",
            "shell/zunit/dynamic.zunit", "powershell/aliases-splats-dynamic.ps1",
            "shell/zsh/advanced-dynamic.zsh", "powershell/dynamic-and-secrets.ps1",
        )
        source = self.tmpdir / "source"
        for relative in selected:
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fixtures / relative, target)
        (source / "boundary.bash").write_text(
            'source "../outside.sh"\nsource "$DYNAMIC_SOURCE"\n', encoding="utf-8",
        )
        self.assertEqual(
            sorted(p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()),
            sorted((*selected, "boundary.bash")),
        )
        store_root, workspace, private = (self.tmpdir / name for name in ("store", "workspace", "private"))
        for directory in (store_root, workspace, private):
            directory.mkdir(mode=0o700)
        store = FileSystemArtifactStore(store_root)
        config = create_single_source_graph_config(source, graph_id="portable-diagnostics")
        manifest, reference, _ = seal_configured_sources(
            config, store, extractor_generation="eg1:diagnostics", canonicalizer_generation="kg1:diagnostics",
        )
        capability = PortableExecutionCapability(
            schema_version=1, job_id="job-diagnostics", attempt=1, graph_id=config.id,
            store_root=store_root, workspace_root=workspace, manifest_reference=reference,
            source_generation=manifest.source_generation, config_generation=manifest.config_generation,
            extractor_generation=manifest.extractor_generation,
            canonicalizer_generation=manifest.canonicalizer_generation,
            max_artifact_bytes=10 * 1024 * 1024, max_bundle_bytes=10 * 1024 * 1024,
        )
        # Retain malformed generation syntax validation coverage.
        for malformed in ("src1:stale", "invalid", "", "sg1:"):
            with self.assertRaises(ValueError):
                replace(capability, source_generation=malformed).validate()
        with self.assertRaises(ValueError):
            create_portable_capability(private, replace(capability, source_generation="src1:stale"))

        cases = (
            ("success", None, capability),
            ("contract_validation", "contract_validation", replace(capability, source_generation="sg1:stale")),
            ("config_mismatch", "contract_validation", replace(capability, config_generation="cg1:stale")),
            ("graph_mismatch", "contract_validation", replace(capability, graph_id="portable-mismatch")),
        )
        for name, failure_category, supplied in cases:
            with self.subTest(case=name):
                path = create_portable_capability(private, supplied)
                result = run_portable_worker(
                    path, {"job_id": supplied.job_id, "attempt": supplied.attempt}, coordinator_test_limits(),
                )
                # Bound and sanitize causal evidence before the first terminal assertion.
                evidence = repr({
                    "case": name,
                    "protocol_error": result.protocol_error, "terminal": result.terminal,
                    "returncode": result.returncode, "cleanup_error": result.cleanup_error,
                    "stderr": result.stderr,
                    "timeouts": (result.process_timed_out, result.heartbeat_timed_out, result.hello_timed_out),
                }).replace(str(self.tmpdir), "<test-root>")
                evidence = re.sub(r"FAKE_[A-Z0-9_]+", "<redacted-sentinel>", evidence)[:4000]
                self.assertEqual(result.terminal["status"], "failed" if failure_category else "succeeded", evidence)
                self.assertEqual(result.terminal["error_category"], failure_category, evidence)
                self.assertIsNone(result.protocol_error, evidence)
                self.assertEqual(result.returncode, 0, evidence)
                self.assertIsNone(result.cleanup_error, evidence)
                self.assertFalse(path.exists(), evidence)
                self.assertEqual(list(workspace.iterdir()), [], evidence)
                self.assertEqual(list(private.iterdir()), [], evidence)
                self.assertEqual(result.terminal["publication_state"], "not_started", evidence)
                self.assertIsNone(result.terminal["latest_run_identity"], evidence)
                snapshot = result.terminal["portable_snapshot"]
                assert isinstance(snapshot, dict), evidence
                receipt_ref = ArtifactReference.from_mapping(snapshot["receipt"])
                receipt = ExtractionReceipt.from_bytes(store.read(receipt_ref))
                if failure_category is not None:
                    self.assertEqual(snapshot["outcome"], failure_category, evidence)
                    self.assertIsNone(snapshot["bundle"], evidence)
                    self.assertEqual(receipt.diagnostic_category, failure_category, evidence)
                    self.assertIsNone(receipt.bundle_reference, evidence)
                    self.assertEqual(receipt.family_counts, {}, evidence)
                    continue
                self.assertEqual(snapshot["outcome"], "completed", evidence)
                bundle_ref = ArtifactReference.from_mapping(snapshot["bundle"])
                bundle = PublicationBundle.from_bytes(store.read(bundle_ref))
                self.assertEqual(receipt.bundle_id, bundle.bundle_id, evidence)
                alias = config.effective_source_bindings[0].alias
                self.assertEqual(
                    sorted(row["path"] for row in bundle.families["files"]),
                    sorted(f"{alias}/{item}" for item in (*selected, "boundary.bash")),
                )
                for relative in selected:
                    sentinels = re.findall(r"FAKE_[A-Z0-9_]+", (fixtures / relative).read_text())
                    self.assertTrue(all(value not in repr(bundle.families) for value in sentinels), evidence)
                # Extractor uncertainty lives in raw JSONL, not terminal diagnostics.
                observations = []
                for row in bundle.families["raw_observations"]:
                    payload = row["payload_json"]
                    assert isinstance(payload, dict)
                    observations.append(RawObservation.from_dict(payload))
                boundary = sorted(
                    (row for row in observations if row.kind == "shell.source"
                     and row.path.endswith("/boundary.bash")), key=lambda row: row.start_line or 0,
                )
                self.assertEqual(len(boundary), 2)
                self.assertEqual(boundary[0].metadata["unknown_reason"], "repo-escaping-source")
                self.assertEqual(boundary[1].metadata["dynamic_reason"], "computed-source")
                self.assertTrue(all(row.target is None for row in boundary))
                dynamic_paths = {row.path for row in observations if row.metadata.get("dynamic_reason")}
                self.assertTrue({f"{alias}/{item}" for item in (*selected, "boundary.bash")} <= dynamic_paths)
                self.assertFalse(any("outside.sh" in str(row["target_canonical_key"])
                                     for row in bundle.families["canonical_edges"]))

    def test_extractor_css_and_python_web_helper_branches(self) -> None:
        code = (
            "import fastapi as fa\n"
            "from fastapi import Depends\n"
            "\n"
            "@fa.get('/items')\n"
            "def get_items(dep1 = Depends(service), dep2 = fa.Depends(other)):\n"
            "    pass\n"
        )
        tree = ast.parse(code)
        aliases = _python_web_import_aliases(tree)
        self.assertEqual(aliases.get("fa"), "fastapi")
        self.assertEqual(aliases.get("Depends"), "fastapi.Depends")

        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef)][0]
        deps = _fastapi_dependencies(fn, aliases)
        self.assertGreaterEqual(len(deps), 2)

        css_block = 'color: red !important; background: url("image.png"); empty: ; no_colon'
        decls = _parse_declarations(css_block, css_block, 0)
        self.assertEqual(len(decls), 3)
        self.assertEqual(decls[0].property_name, "color")
        self.assertTrue(decls[0].important)
        self.assertEqual(decls[1].property_name, "background")
        self.assertFalse(decls[1].important)
        self.assertEqual(decls[2].property_name, "empty")
        self.assertEqual(decls[2].value, "")



if __name__ == "__main__":
    import sys

    sys.exit(
        "Direct execution unsupported: RepoMap integration tests require container sandbox admission via pytest"
    )
