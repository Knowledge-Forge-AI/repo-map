"""Integration tests for six-shell canonical graph durable publication and readback.

Composes:
1. Multi-family shell script generation across Awk, Bash, PowerShell, Zsh, Bats, and Zunit.
2. Real static extraction via discovery extractors without executing target repository scripts.
3. Source boundary and binary safety checks (repo-escaping source refusal and non-UTF8 decoding).
4. Direct staged publication into disposable PostgreSQL migrations.
5. Exact semantic graph readback: nodes, edges, edge explanations, neighborhoods, and direct-run identity.
6. Deterministic idempotent replay preserving run identity, followed by multi-run advancement.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
import unittest

import psycopg
from psycopg.conninfo import make_conninfo

from repomap_kg.graph.discovery import classify_path
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
from repomap_kg.ops.direct_publication import build_observation_publication_authority
from repomap_kg.storage.authority import AttemptNumber
from repomap_kg.storage.canonical import (
    query_canonical_edge_explanation,
    query_canonical_edge_records,
    query_canonical_neighborhood,
    query_canonical_node_records,
    query_canonical_storage_summary,
)
from repomap_kg.storage.main import apply_migrations, default_rdbms_root
from repomap_kg.storage.publication_readback import (
    read_latest_receipt_bearing_publication,
    read_run_publication,
)
from repomap_kg.storage.staged_ingestion import (
    _psycopg_connection_params_from_psql_args,
    run_staged_full_refresh,
    stage_id_for_authority,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.test_scratch import select_scratch_root


class StorageShellDurableReadbackIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(
            tempfile.mkdtemp(dir=select_scratch_root(), prefix="repomap-int-shell-durable-")
        ).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_six_shell_canonical_graph_durable_publication_readback_and_replay(self) -> None:
        require_postgres_binaries()
        repo_dir = self.tmpdir / "repo"
        for sub in ("scripts", "tests", "bin"):
            (repo_dir / sub).mkdir(parents=True, exist_ok=True)

        # 1. Author source fixtures across all six shell technologies
        (repo_dir / "scripts" / "deploy.sh").write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\nexport DEPLOY_ENV=\"production\"\n"
            "source ./common.sh\nsource ../../escaping_target.sh\n"
            "deploy_app() {\n    echo \"Starting deployment...\"\n}\ndeploy_app\n",
            encoding="utf-8",
        )
        (repo_dir / "scripts" / "common.sh").write_text(
            "#!/usr/bin/env bash\nexport LOG_LEVEL=\"info\"\n", encoding="utf-8"
        )
        (repo_dir / "scripts" / "parse.awk").write_text(
            "function calculate_metric(count, scale) { return count * scale; }\n"
            "BEGIN { FS=\",\"; ENVIRON[\"AWK_ENV\"]=\"active\"; system(\"date\"); }\n"
            "{ metric = calculate_metric($1, 2.0); print $2, metric; }\n"
            "END { print \"awk complete\"; }\n",
            encoding="utf-8",
        )
        (repo_dir / "scripts" / "env.zsh").write_text(
            "#!/bin/zsh\nexport ZSH_PROFILE=\"release\"\nautoload -Uz compinit\ncompinit\n"
            "setup_shell() {\n    echo \"zsh initialized\"\n}\nsetup_shell\n",
            encoding="utf-8",
        )
        (repo_dir / "scripts" / "provision.ps1").write_text(
            "param([string]$TargetCluster = \"cluster-a\", [int]$NodeCount = 2)\n"
            "$env:INFRA_STAGE = \"staging\"\n"
            "function Configure-Nodes { param([int]$Nodes) "
            "Write-Output \"Configuring $Nodes nodes\" }\n"
            "Configure-Nodes -Nodes $NodeCount\n",
            encoding="utf-8",
        )
        (repo_dir / "tests" / "suite.bats").write_text(
            "#!/usr/bin/env bats\nsetup() { export BATS_TARGET=\"local\"; }\n"
            "@test \"verify deployment environment\" {\n"
            "    run bash -c 'echo $DEPLOY_ENV'\n    [ \"$status\" -eq 0 ]\n}\n",
            encoding="utf-8",
        )
        (repo_dir / "tests" / "runner.zunit").write_text(
            "test \"zsh configuration loads\" { assert 1 equals 1 }\n",
            encoding="utf-8",
        )
        (repo_dir / "bin" / "corrupt.bin").write_bytes(b"\x7fELF\x02\x01\x01\x00\xff\xfe\x00\x00")

        # 2. Static extraction via specialized discovery extractors
        obs_bash = extract_bash_file_observations_from_file(repo_dir, "scripts/deploy.sh")
        obs_common = extract_bash_file_observations_from_file(repo_dir, "scripts/common.sh")
        obs_awk = extract_awk_file_observations_from_file(repo_dir, "scripts/parse.awk")
        obs_zsh = extract_zsh_file_observations_from_file(repo_dir, "scripts/env.zsh")
        obs_pwsh = extract_powershell_file_observations_from_file(
            repo_dir, "scripts/provision.ps1"
        )
        obs_bats = extract_bats_file_observations_from_file(repo_dir, "tests/suite.bats")
        obs_zunit = extract_zunit_file_observations_from_file(repo_dir, "tests/runner.zunit")

        # Source boundaries: non-UTF8 binary returns () and escaping source has no target
        self.assertEqual(extract_shell_file_observations(repo_dir, "bin/corrupt.bin"), ())
        escape_sources = [
            item for item in obs_bash
            if item.kind == "shell.source"
            and item.metadata.get("unknown_reason") == "repo-escaping-source"
        ]
        self.assertEqual(len(escape_sources), 1)
        self.assertIsNone(escape_sources[0].target)

        # Base file observations from discovery alongside specialized observations
        file_paths = (
            "scripts/deploy.sh",
            "scripts/common.sh",
            "scripts/parse.awk",
            "scripts/env.zsh",
            "scripts/provision.ps1",
            "tests/suite.bats",
            "tests/runner.zunit",
        )
        base_file_obs = [
            classify_path(repo_dir, repo_dir / path).to_observation()
            for path in file_paths
        ]

        all_observations: list[RawObservation] = [
            *base_file_obs,
            *obs_bash,
            *obs_common,
            *obs_awk,
            *obs_zsh,
            *obs_pwsh,
            *obs_bats,
            *obs_zunit,
        ]
        self.assertGreater(len(all_observations), 20)
        repo_name, root_path = "fixture-shell-durable", str(repo_dir)

        # 3. Disposable PostgreSQL publication
        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
            )
            authority = build_observation_publication_authority(
                all_observations, repository_name=repo_name, root_path=root_path
            )
            summary = run_staged_full_refresh(
                postgres.psql_args, all_observations, repository_name=repo_name,
                root_path=root_path, authority=authority,
            )
            self.assertGreater(summary.run_id, 0)
            self.assertGreater(summary.repository_id, 0)
            self.assertGreaterEqual(summary.files, 7)

            # 4. Storage summary readback
            storage_summary = query_canonical_storage_summary(
                postgres.psql_args, root_path=root_path, psql_command=postgres.psql_command
            )
            self.assertEqual(storage_summary.runs, 1)
            self.assertEqual(storage_summary.latest_run_id, summary.run_id)
            self.assertEqual(storage_summary.repository_name, repo_name)
            self.assertGreaterEqual(storage_summary.files, 7)

            # 5. Canonical nodes readback across all 6 shell ecosystems
            nodes = query_canonical_node_records(
                postgres.psql_args, root_path=root_path, psql_command=postgres.psql_command
            )
            self.assertGreater(len(nodes), 20)
            node_map = {n.canonical_key: n for n in nodes}
            expected_node_keys = {
                "file:scripts/deploy.sh", "file:scripts/common.sh", "file:scripts/parse.awk",
                "file:scripts/env.zsh", "file:scripts/provision.ps1", "file:tests/suite.bats",
                "file:tests/runner.zunit", "bash.script:file%3Ascripts%2Fdeploy.sh",
                "bash.script:file%3Ascripts%2Fcommon.sh", "awk.program:file%3Ascripts%2Fparse.awk",
                "zsh.script:file%3Ascripts%2Fenv.zsh",
                "powershell.script:file%3Ascripts%2Fprovision.ps1",
                "bats.file:file%3Atests%2Fsuite.bats", "zunit.file:file%3Atests%2Frunner.zunit",
                "bash.function:file%3Ascripts%2Fdeploy.sh:deploy_app",
                "awk.function:file%3Ascripts%2Fparse.awk:calculate_metric",
                "zsh.function:file%3Ascripts%2Fenv.zsh:setup_shell",
                "powershell.function:file%3Ascripts%2Fprovision.ps1:Configure-Nodes",
                "bats.test_case:file%3Atests%2Fsuite.bats:verify%20deployment%20environment",
                "zunit.test_case:file%3Atests%2Frunner.zunit:zsh%20configuration%20loads",
                "env:DEPLOY_ENV", "env:LOG_LEVEL", "env:ZSH_PROFILE", "env:INFRA_STAGE",
                "tool:echo", "tool:compinit",
            }
            self.assertTrue(expected_node_keys.issubset(node_map))
            self.assertTrue(all(n.first_seen_run_id == summary.run_id for n in nodes))
            self.assertTrue(all(n.last_seen_run_id == summary.run_id for n in nodes))
            self.assertTrue(
                all(n.confidence in ("manual", "extracted", "heuristic") for n in nodes)
            )
            self.assertTrue(all(not n.conflict for n in nodes))

            # 6. Canonical edges readback & semantic relationship verification
            edges = query_canonical_edge_records(
                postgres.psql_args, root_path=root_path, psql_command=postgres.psql_command
            )
            self.assertGreater(len(edges), 10)
            edge_triples = {(e.source_key, e.edge_kind, e.target_key) for e in edges}
            expected_edge_triples = {
                ("file:scripts/deploy.sh", "defines", "bash.script:file%3Ascripts%2Fdeploy.sh"),
                (
                    "bash.script:file%3Ascripts%2Fdeploy.sh",
                    "defines",
                    "bash.function:file%3Ascripts%2Fdeploy.sh:deploy_app",
                ),
                ("file:scripts/common.sh", "defines", "bash.script:file%3Ascripts%2Fcommon.sh"),
                ("file:scripts/parse.awk", "defines", "awk.program:file%3Ascripts%2Fparse.awk"),
                (
                    "awk.program:file%3Ascripts%2Fparse.awk",
                    "defines",
                    "awk.function:file%3Ascripts%2Fparse.awk:calculate_metric",
                ),
                ("file:scripts/env.zsh", "defines", "zsh.script:file%3Ascripts%2Fenv.zsh"),
                (
                    "zsh.script:file%3Ascripts%2Fenv.zsh",
                    "defines",
                    "zsh.function:file%3Ascripts%2Fenv.zsh:setup_shell",
                ),
                (
                    "file:scripts/provision.ps1",
                    "defines",
                    "powershell.script:file%3Ascripts%2Fprovision.ps1",
                ),
                (
                    "powershell.script:file%3Ascripts%2Fprovision.ps1",
                    "defines",
                    "powershell.function:file%3Ascripts%2Fprovision.ps1:Configure-Nodes",
                ),
                ("file:tests/suite.bats", "defines", "bats.file:file%3Atests%2Fsuite.bats"),
                (
                    "bats.file:file%3Atests%2Fsuite.bats",
                    "contains",
                    "bats.test_case:file%3Atests%2Fsuite.bats:verify%20deployment%20environment",
                ),
                ("file:tests/runner.zunit", "defines", "zunit.file:file%3Atests%2Frunner.zunit"),
                (
                    "zunit.file:file%3Atests%2Frunner.zunit",
                    "contains",
                    "zunit.test_case:file%3Atests%2Frunner.zunit:zsh%20configuration%20loads",
                ),
                ("file:scripts/deploy.sh", "writes_env", "env:DEPLOY_ENV"),
                ("file:scripts/common.sh", "writes_env", "env:LOG_LEVEL"),
                ("zsh.script:file%3Ascripts%2Fenv.zsh", "writes_env", "env:ZSH_PROFILE"),
                ("file:scripts/provision.ps1", "writes_env", "env:INFRA_STAGE"),
                ("bash.script:file%3Ascripts%2Fdeploy.sh", "sources", "file:scripts/common.sh"),
                ("file:scripts/deploy.sh", "executes", "tool:echo"),
            }
            self.assertTrue(expected_edge_triples.issubset(edge_triples))
            self.assertFalse(any("escaping_target.sh" in e.target_key for e in edges))

            # 7. Canonical edge explanation with evidence link
            sources_edge = next(
                e for e in edges
                if e.edge_kind == "sources" and e.target_key == "file:scripts/common.sh"
            )
            explanation = query_canonical_edge_explanation(
                postgres.psql_args,
                root_path=root_path,
                source_key=sources_edge.source_key,
                kind=sources_edge.edge_kind,
                target_key=sources_edge.target_key,
                identity_metadata_hash=sources_edge.identity_metadata_hash,
                psql_command=postgres.psql_command,
            )
            assert explanation.edge is not None
            self.assertEqual(explanation.edge.source_key, sources_edge.source_key)
            self.assertGreaterEqual(len(explanation.evidence), 1)
            self.assertEqual(explanation.evidence[0].path, "scripts/deploy.sh")
            self.assertEqual(explanation.evidence[0].extractor, "repo-bash")

            # 8. Canonical neighborhood query
            center_key = "bash.script:file%3Ascripts%2Fdeploy.sh"
            neighborhood = query_canonical_neighborhood(
                postgres.psql_args, root_path=root_path, node=center_key,
                psql_command=postgres.psql_command,
            )
            assert neighborhood.center is not None
            self.assertEqual(neighborhood.center.canonical_key, center_key)
            neighbor_node_keys = {n.canonical_key for n in neighborhood.nodes}
            self.assertIn("file:scripts/deploy.sh", neighbor_node_keys)
            self.assertIn("bash.function:file%3Ascripts%2Fdeploy.sh:deploy_app", neighbor_node_keys)
            self.assertIn("file:scripts/common.sh", neighbor_node_keys)

            # 9. Relational integrity & durable table checks via psycopg
            params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
            with psycopg.connect(make_conninfo(**params)) as conn:
                run_row = conn.execute(
                    "SELECT status, git_commit FROM runs WHERE id = %s", (summary.run_id,)
                ).fetchone()
                assert run_row is not None
                self.assertEqual(run_row[0], "complete")

                stage_id = stage_id_for_authority(authority)
                stage_row = conn.execute(
                    "SELECT state, merge_status, publication_reconciliation_state, "
                    "cleanup_eligibility FROM ingestion_stages WHERE stage_id = %s",
                    (stage_id,),
                ).fetchone()
                self.assertEqual(stage_row, ("published", "committed", "reconciled", "eligible"))

                auth_row = conn.execute(
                    "SELECT last_run_id, singleton_fencing_epoch, graph_lease_fencing_epoch "
                    "FROM graph_publication_authority WHERE repository_id = %s",
                    (summary.repository_id,),
                ).fetchone()
                self.assertIsNone(auth_row)  # Direct publication does not claim coordinator fencing.

            # Direct runs carry an operation receipt without coordinator fencing.
            latest_pub = read_latest_receipt_bearing_publication(
                postgres.psql_args, psql_command=postgres.psql_command
            )
            assert latest_pub is not None
            self.assertEqual(latest_pub.run_id, summary.run_id)
            self.assertEqual(latest_pub.receipt, authority.receipt())

            run_pub = read_run_publication(
                postgres.psql_args,
                job_id=str(authority.operation_id),
                attempt=int(authority.attempt),
                psql_command=postgres.psql_command,
            )
            assert run_pub is not None
            self.assertEqual(run_pub, latest_pub)

            # 11. Deterministic idempotent replay
            replay_summary = run_staged_full_refresh(
                postgres.psql_args, all_observations, repository_name=repo_name,
                root_path=root_path, authority=authority,
            )
            self.assertEqual(replay_summary.run_id, summary.run_id)
            self.assertEqual(replay_summary.repository_id, summary.repository_id)

            # 12. Multi-run attempt advancement and run identity tracking
            authority_attempt2 = replace(authority, attempt=AttemptNumber(2))
            summary2 = run_staged_full_refresh(
                postgres.psql_args, all_observations, repository_name=repo_name,
                root_path=root_path, authority=authority_attempt2,
            )
            self.assertGreater(summary2.run_id, summary.run_id)

            updated_nodes = query_canonical_node_records(
                postgres.psql_args, root_path=root_path, psql_command=postgres.psql_command
            )
            self.assertTrue(all(n.first_seen_run_id == summary.run_id for n in updated_nodes))
            self.assertTrue(all(n.last_seen_run_id == summary2.run_id for n in updated_nodes))

            summary2_storage = query_canonical_storage_summary(
                postgres.psql_args, root_path=root_path, psql_command=postgres.psql_command
            )
            self.assertEqual(summary2_storage.runs, 2)
            self.assertEqual(summary2_storage.latest_run_id, summary2.run_id)



if __name__ == "__main__":
    import sys

    sys.exit(
        "Direct execution unsupported: "
        "RepoMap integration tests require container sandbox admission via pytest"
    )
