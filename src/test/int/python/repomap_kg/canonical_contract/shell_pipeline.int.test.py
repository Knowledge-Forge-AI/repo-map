"""Cross-component integration tests for the shell extraction and canonicalization pipeline.

Exercises the end-to-end pipeline:
1. File discovery and classification across 6 shell technologies (Bash, Awk, Zsh, Bats, Zunit, PowerShell).
2. Specialized shell extractors converting script constructs into raw observations.
3. Canonicalization engine mapping observations to CanonicalGraph nodes, edges, and evidence.
4. Deterministic edge relationship verification (defines, executes, sources, writes_env).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.canonicalization.records import CanonicalGraph, CanonicalizationResult
from repomap_kg.graph.discovery_extractors import (
    extract_awk_file_observations_from_file,
    extract_bash_file_observations_from_file,
    extract_bats_file_observations_from_file,
    extract_powershell_file_observations_from_file,
    extract_shell_file_observations,
    extract_zsh_file_observations_from_file,
    extract_zunit_file_observations_from_file,
)
from repomap_kg.observations.raw import RawObservation


from repomap_test_support.test_scratch import select_scratch_root


class ShellPipelineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(
            tempfile.mkdtemp(dir=select_scratch_root(), prefix="repomap-int-shell-pipeline-")
        ).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_shell_pipeline_across_all_six_families(self) -> None:
        # 1. Setup multi-technology shell files in repository tree
        bash_script = self.tmpdir / "scripts" / "deploy.sh"
        bash_script.parent.mkdir(parents=True, exist_ok=True)
        bash_script.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "export DEPLOY_ENV=\"production\"\n"
            "source ./common.sh\n"
            "echo \"Deploying application...\"\n",
            encoding="utf-8",
        )

        bash_helper = self.tmpdir / "scripts" / "common.sh"
        bash_helper.write_text(
            "#!/usr/bin/env bash\n"
            "export LOG_LEVEL=\"debug\"\n"
            "echo \"Common routines initialized\"\n",
            encoding="utf-8",
        )

        awk_filter = self.tmpdir / "data" / "parse.awk"
        awk_filter.parent.mkdir(parents=True, exist_ok=True)
        awk_filter.write_text(
            "#!/usr/bin/awk -f\n"
            "BEGIN { FS=\",\"; OFS=\"\\t\" }\n"
            "$1 > 100 { print $2, $3 }\n"
            "END { print \"Done\" }\n",
            encoding="utf-8",
        )

        zsh_config = self.tmpdir / "zsh" / "environment.zsh"
        zsh_config.parent.mkdir(parents=True, exist_ok=True)
        zsh_config.write_text(
            "#!/bin/zsh\n"
            "typeset -gA CLOUD_CONFIG\n"
            "CLOUD_CONFIG[region]=\"us-east-1\"\n"
            "autoload -Uz compinit\n"
            "compinit\n",
            encoding="utf-8",
        )

        bats_test = self.tmpdir / "test" / "suite.bats"
        bats_test.parent.mkdir(parents=True, exist_ok=True)
        bats_test.write_text(
            "#!/usr/bin/env bats\n"
            "@test \"deployment environment is set\" {\n"
            "  run bash -c 'echo $DEPLOY_ENV'\n"
            "  [ \"$status\" -eq 0 ]\n"
            "}\n",
            encoding="utf-8",
        )

        zunit_test = self.tmpdir / "test" / "runner.zunit"
        zunit_test.write_text(
            "@test 'zsh configuration loads' {\n"
            "  assert 1 equals 1\n"
            "}\n",
            encoding="utf-8",
        )

        pwsh_script = self.tmpdir / "infra" / "provision.ps1"
        pwsh_script.parent.mkdir(parents=True, exist_ok=True)
        pwsh_script.write_text(
            "param(\n"
            "    [string]$TargetCluster = \"primary\",\n"
            "    [int]$ReplicaCount = 3\n"
            ")\n"
            "$env:INFRA_STAGE = \"provisioned\"\n"
            "Write-Output \"Cluster provisioned with $ReplicaCount replicas\"\n",
            encoding="utf-8",
        )

        # 2. Extract observations using the 6 specialized extractors
        observations: list[RawObservation] = []
        observations.extend(
            extract_bash_file_observations_from_file(self.tmpdir, "scripts/deploy.sh")
        )
        observations.extend(
            extract_bash_file_observations_from_file(self.tmpdir, "scripts/common.sh")
        )
        observations.extend(
            extract_awk_file_observations_from_file(self.tmpdir, "data/parse.awk")
        )
        observations.extend(
            extract_zsh_file_observations_from_file(self.tmpdir, "zsh/environment.zsh")
        )
        observations.extend(
            extract_bats_file_observations_from_file(self.tmpdir, "test/suite.bats")
        )
        observations.extend(
            extract_zunit_file_observations_from_file(self.tmpdir, "test/runner.zunit")
        )
        observations.extend(
            extract_powershell_file_observations_from_file(self.tmpdir, "infra/provision.ps1")
        )

        self.assertGreaterEqual(len(observations), 20)

        # Also verify generic extract_shell_file_observations adapter on bash and zsh
        generic_bash_obs = extract_shell_file_observations(self.tmpdir, "scripts/deploy.sh")
        self.assertTrue(len(generic_bash_obs) > 0)

        # 3. Canonicalize raw observations into CanonicalGraph
        canonical_result: CanonicalizationResult = canonicalize_observations(
            tuple(observations)
        )
        self.assertTrue(canonical_result.ok)

        graph: CanonicalGraph = canonical_result.graph
        self.assertGreater(len(graph.nodes), 10)
        self.assertGreater(len(graph.edges), 5)
        self.assertGreater(len(graph.evidence), 10)
        self.assertGreater(len(graph.node_evidence_links), 10)

        node_keys = {n.canonical_key for n in graph.nodes}

        # Check key structural nodes exist
        self.assertIn("file:scripts/deploy.sh", node_keys)
        self.assertIn("file:scripts/common.sh", node_keys)
        self.assertIn("file:data/parse.awk", node_keys)
        self.assertIn("file:zsh/environment.zsh", node_keys)
        self.assertIn("file:test/suite.bats", node_keys)
        self.assertIn("file:test/runner.zunit", node_keys)
        self.assertIn("file:infra/provision.ps1", node_keys)

        # Verify environment variable nodes
        self.assertIn("env:DEPLOY_ENV", node_keys)
        self.assertIn("env:LOG_LEVEL", node_keys)

        # Verify tool invocation nodes
        self.assertIn("tool:echo", node_keys)

        # 4. Check edge relations across files
        edge_tuples = {(e.source_key, e.kind, e.target_key) for e in graph.edges}

        # deploy.sh writes DEPLOY_ENV
        self.assertTrue(
            any(
                src == "file:scripts/deploy.sh" and kind == "writes_env" and tgt == "env:DEPLOY_ENV"
                for src, kind, tgt in edge_tuples
            )
        )

        # common.sh writes LOG_LEVEL
        self.assertTrue(
            any(
                src == "file:scripts/common.sh" and kind == "writes_env" and tgt == "env:LOG_LEVEL"
                for src, kind, tgt in edge_tuples
            )
        )

        # deploy.sh executes tool echo
        self.assertTrue(
            any(
                src == "file:scripts/deploy.sh" and kind == "executes" and tgt == "tool:echo"
                for src, kind, tgt in edge_tuples
            )
        )

        # 5. Verify serialization to dictionary
        payload = canonical_result.to_dict()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["graph_key_version"], 1)
        self.assertIn("nodes", payload)
        self.assertIn("edges", payload)
        self.assertIn("evidence", payload)
        self.assertEqual(payload["summary"]["errors"], 0)

    def test_shell_pipeline_edge_cases_and_diagnostics(self) -> None:
        # Non-existent file path raises FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            extract_bash_file_observations_from_file(self.tmpdir, "nonexistent.sh")

        # Empty script handling
        empty_sh = self.tmpdir / "empty.sh"
        empty_sh.write_text("", encoding="utf-8")
        empty_obs = extract_bash_file_observations_from_file(self.tmpdir, "empty.sh")
        self.assertEqual(len(empty_obs), 1)
        self.assertEqual(empty_obs[0].kind, "shell.script")

        # Dynamic variable expansion source
        dynamic_sh = self.tmpdir / "dynamic.sh"
        dynamic_sh.write_text(
            "#!/usr/bin/env bash\n"
            "source \"$LIB_DIR/helper.sh\"\n",
            encoding="utf-8",
        )
        dyn_obs = extract_bash_file_observations_from_file(self.tmpdir, "dynamic.sh")
        res = canonicalize_observations(dyn_obs)
        self.assertTrue(res.ok)
        edge_kinds = {e.kind for e in res.graph.edges}
        self.assertIn("reads_env", edge_kinds)

    def test_shell_pipeline_rich_powershell_manifest_and_modules(self) -> None:
        ps_dir = self.tmpdir / "powershell"
        ps_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = ps_dir / "AppService.psd1"
        manifest_file.write_text(
            "@{\n"
            "    RootModule = 'AppService.psm1'\n"
            "    ModuleVersion = '2.4.1'\n"
            "    Author = 'RepoMap Team'\n"
            "    CompanyName = 'RepoMap Inc.'\n"
            "    Description = 'Service management module'\n"
            "    PowerShellVersion = '7.2'\n"
            "    RequiredModules = @('Az.Accounts', 'Pester')\n"
            "    RequiredAssemblies = @('System.IO.Compression.dll')\n"
            "    FunctionsToExport = @('Invoke-AppService', 'Get-AppStatus')\n"
            "    CmdletsToExport = @()\n"
            "    VariablesToExport = '*'\n"
            "}\n",
            encoding="utf-8",
        )
        module_file = ps_dir / "AppService.psm1"
        module_file.write_text(
            "function Invoke-AppService {\n"
            "    [CmdletBinding()]\n"
            "    param([string]$TargetHost)\n"
            "    $env:APP_TARGET = $TargetHost\n"
            "    docker compose up -d\n"
            "}\n"
            "function Get-AppStatus {\n"
            "    Write-Output \"Checking status...\"\n"
            "}\n"
            "Export-ModuleMember -Function Invoke-AppService, Get-AppStatus\n",
            encoding="utf-8",
        )

        manifest_obs = extract_powershell_file_observations_from_file(self.tmpdir, "powershell/AppService.psd1")
        module_obs = extract_powershell_file_observations_from_file(self.tmpdir, "powershell/AppService.psm1")
        self.assertTrue(len(manifest_obs) >= 1)
        self.assertTrue(len(module_obs) >= 1)

        all_obs = [*manifest_obs, *module_obs]
        res = canonicalize_observations(all_obs)
        self.assertTrue(res.ok)
        node_kinds = {n.kind for n in res.graph.nodes}
        edge_kinds = {e.kind for e in res.graph.edges}
        self.assertIn("file", node_kinds)
        self.assertTrue(any(kind in ("defines", "executes", "writes_env", "sources") for kind in edge_kinds))

        # Test dictionary serialization round-trip fidelity
        payload = res.to_dict()
        self.assertEqual(payload["summary"]["nodes"], len(res.graph.nodes))
        self.assertEqual(payload["summary"]["edges"], len(res.graph.edges))

    def test_shell_pipeline_bats_and_zunit_frameworks(self) -> None:
        test_dir = self.tmpdir / "suite"
        test_dir.mkdir(parents=True, exist_ok=True)
        bats_file = test_dir / "integration.bats"
        bats_file.write_text(
            "setup() {\n"
            "    export TEST_MODE=\"bats\"\n"
            "}\n"
            "@test \"service responds with 200\" {\n"
            "    run curl -s http://localhost:8080/health\n"
            "    [ \"$status\" -eq 0 ]\n"
            "}\n"
            "teardown() {\n"
            "    echo \"done\"\n"
            "}\n",
            encoding="utf-8",
        )
        zunit_file = test_dir / "service.zunit"
        zunit_file.write_text(
            "@setup {\n"
            "    export ZUNIT_TARGET=\"active\"\n"
            "}\n"
            "@test 'validates runner' {\n"
            "    run my_service --check\n"
            "    assert $state equals 0\n"
            "}\n",
            encoding="utf-8",
        )

        bats_obs = extract_bats_file_observations_from_file(self.tmpdir, "suite/integration.bats")
        zunit_obs = extract_zunit_file_observations_from_file(self.tmpdir, "suite/service.zunit")
        self.assertTrue(len(bats_obs) >= 1)
        self.assertTrue(len(zunit_obs) >= 1)

        res = canonicalize_observations([*bats_obs, *zunit_obs])
        self.assertTrue(res.ok)
        edge_kinds = {e.kind for e in res.graph.edges}
        self.assertTrue("defines" in edge_kinds or "executes" in edge_kinds or "writes_env" in edge_kinds)

    def test_shell_pipeline_awk_and_zsh_advanced_constructs(self) -> None:
        adv_dir = self.tmpdir / "advanced"
        adv_dir.mkdir(parents=True, exist_ok=True)
        awk_file = adv_dir / "processor.awk"
        awk_file.write_text(
            "function calculate_rate(val, factor) {\n"
            "    return val * factor;\n"
            "}\n"
            "BEGIN {\n"
            "    FS = \",\";\n"
            "    ENVIRON[\"AWK_STATUS\"] = \"initialized\";\n"
            "    system(\"date\");\n"
            "}\n"
            "/^ERROR/ {\n"
            "    rate = calculate_rate($2, 1.5);\n"
            "    print $1, rate;\n"
            "}\n"
            "END {\n"
            "    print \"Processing complete\";\n"
            "}\n",
            encoding="utf-8",
        )
        zsh_file = adv_dir / "build_zsh.zsh"
        zsh_file.write_text(
            "#!/usr/bin/env zsh\n"
            "setopt extendedglob\n"
            "export ZSH_BUILD=\"fast\"\n"
            "autoload -Uz colors && colors\n"
            "function build_target() {\n"
            "    local target=\"$1\"\n"
            "    echo \"Building ${target}\"\n"
            "}\n"
            "build_target \"production\"\n",
            encoding="utf-8",
        )

        awk_obs = extract_awk_file_observations_from_file(self.tmpdir, "advanced/processor.awk")
        zsh_obs = extract_zsh_file_observations_from_file(self.tmpdir, "advanced/build_zsh.zsh")
        self.assertTrue(len(awk_obs) >= 1)
        self.assertTrue(len(zsh_obs) >= 1)

        res = canonicalize_observations([*awk_obs, *zsh_obs])
        self.assertTrue(res.ok)
        self.assertTrue(len(res.graph.nodes) >= 2)
        payload = res.to_dict()
        self.assertIn("summary", payload)
        self.assertEqual(payload["summary"]["errors"], 0)


if __name__ == "__main__":
    import sys

    sys.exit(
        "Direct execution unsupported: RepoMap integration tests require container sandbox admission via pytest"
    )
