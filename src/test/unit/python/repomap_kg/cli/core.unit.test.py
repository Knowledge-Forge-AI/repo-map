import io
import json
import os
import runpy
import sys
import tempfile
import unittest
import pytest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from repomap_kg import __version__
from repomap_kg import cli as cli_module
from repomap_kg.cli import dispatch as cli_dispatch
from repomap_kg.cli import parser as cli_parser
from repomap_kg.cli.main import main
from repomap_kg.cli.parser import build_parser

class CliCoreUnitTests(unittest.TestCase):
    def test_version_option_prints_distribution_name_and_version(self):
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = main(["--version"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), f"repomap-kg {__version__}")

    def test_identity_json_outputs_stable_project_metadata(self):
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = main(["identity", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["name"], "RepoMap")
        self.assertEqual(payload["distribution"], "repomap-kg")
        self.assertEqual(payload["package"], "repomap_kg")
        self.assertEqual(payload["cli"], "repomap-kg")
        self.assertEqual(payload["license"], "Apache-2.0")
        self.assertEqual(payload["database"], "Postgres")

    def test_identity_text_outputs_key_value_metadata(self):
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = main(["identity"])

        self.assertEqual(exit_code, 0)
        self.assertIn("name: RepoMap", stdout.getvalue())
        self.assertIn("distribution: repomap-kg", stdout.getvalue())

    def test_no_arguments_prints_help(self):
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        self.assertIn("usage: repomap-kg", stdout.getvalue())

    def test_ref3_keeps_cli_parser_and_dispatch_compatibility_exports(self):
        self.assertIs(getattr(cli_module, "build_parser"), cli_parser.build_parser)
        self.assertIs(getattr(cli_module, "dispatch_command"), cli_dispatch.dispatch_command)
        self.assertIs(cli_module.main, main)
        self.assertIs(getattr(cli_module, "build_parser"), build_parser)

    def test_parser_accepts_representative_ref3_command_groups(self):
        parser = build_parser()
        cases = (
            (("discover", "."), ("discover", None)),
            (
                ("storage", "host-mutators", "--root-path", "/tmp/repo"),
                ("storage", "host-mutators"),
            ),
            (("mcp", "serve"), ("mcp", "serve")),
            (("ops", "graph-summary", "--graph", "repo-map"), ("ops", "graph-summary")),
            (("local", "status"), ("local", "status")),
        )

        for argv, expected in cases:
            with self.subTest(argv=argv):
                args = parser.parse_args(list(argv))
                self.assertEqual(args.command, expected[0])
                if expected[0] == "storage":
                    self.assertEqual(args.storage_command, expected[1])
                elif expected[0] == "mcp":
                    self.assertEqual(args.mcp_command, expected[1])
                elif expected[0] == "ops":
                    self.assertEqual(args.ops_command, expected[1])
                elif expected[0] == "local":
                    self.assertEqual(args.local_command, expected[1])

    def test_help_mentions_identity_command_and_project_purpose(self):
        help_text = build_parser().format_help()

        self.assertIn("RepoMap", help_text)
        self.assertIn("identity", help_text)
        self.assertIn("deterministic knowledge graph", help_text)

    def test_module_entrypoint_returns_cli_exit_status(self):
        with patch("repomap_kg.cli.main", return_value=7):
            with self.assertRaises(SystemExit) as caught:
                runpy.run_module("repomap_kg", run_name="__main__")

        self.assertEqual(caught.exception.code, 7)

    def test_packaged_module_entrypoint_scrubs_environment_before_cli_main(self):
        observed: dict[str, str] = {}

        def record_environment():
            observed.update(os.environ)
            return 0

        argv = [
            "repomap-kg",
            "ops",
            "coordinator-serve",
            "--repo-map-home",
            "/placeholder/home",
            "--service-package-environment",
            "--json",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.dict(
                os.environ,
                {
                    "LANG": "C.UTF-8",
                    "HOME": "/placeholder/home",
                    "DATABASE_PASSWORD": "synthetic-secret",
                },
                clear=True,
            ),
            patch("repomap_kg.cli.main", side_effect=record_environment),
        ):
            with self.assertRaises(SystemExit):
                runpy.run_module("repomap_kg", run_name="__main__")

        self.assertEqual(observed, {"LANG": "C.UTF-8"})

    def test_cli_main_argument_helpers_cover_validation_and_error_branches(self):
        from repomap_kg.cli.main import (
            _read_json_file,
            canonical_edge_identity_metadata_from_args,
            canonical_file_neighborhood_node_from_args,
            canonical_host_mutator_filters_from_args,
            canonical_host_mutator_summary_target_from_args,
            filter_canonical_host_mutator_records,
            psql_args_from_args,
            read_observations_argument,
            GRAPH_KEY_VERSION,
        )
        from repomap_kg.graph.keys import file_key, host_category_key
        from repomap_kg.storage import StorageSchemaError

        with tempfile.TemporaryDirectory(prefix="repomap-cli-helpers-") as tmp:
            tmp_path = Path(tmp)
            # 1. _read_json_file
            bad_json = tmp_path / "bad.json"
            bad_json.write_text("{not-valid-json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not valid JSON"):
                _read_json_file(str(bad_json), "test")

            list_json = tmp_path / "list.json"
            list_json.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must contain a JSON object"):
                _read_json_file(str(list_json), "test")

            ok_json = tmp_path / "ok.json"
            ok_json.write_text('{"key": "val"}', encoding="utf-8")
            self.assertEqual(_read_json_file(str(ok_json), "test"), {"key": "val"})

            # 2. canonical_file_neighborhood_node_from_args
            args_bad_ver = SimpleNamespace(graph_key_version=999, depth=1, path="a.py")
            with self.assertRaisesRegex(StorageSchemaError, "unsupported graph key version"):
                canonical_file_neighborhood_node_from_args(args_bad_ver)

            args_bad_depth = SimpleNamespace(graph_key_version=GRAPH_KEY_VERSION, depth=2, path="a.py")
            with self.assertRaisesRegex(StorageSchemaError, "only supports depth 1"):
                canonical_file_neighborhood_node_from_args(args_bad_depth)

            args_bad_path = SimpleNamespace(graph_key_version=GRAPH_KEY_VERSION, depth=1, path="/abs/escaping")
            with self.assertRaisesRegex(StorageSchemaError, "invalid file path"):
                canonical_file_neighborhood_node_from_args(args_bad_path)

            args_ok_node = SimpleNamespace(graph_key_version=GRAPH_KEY_VERSION, depth=1, path="src/a.py")
            self.assertEqual(canonical_file_neighborhood_node_from_args(args_ok_node), file_key("src/a.py"))

            # 3. canonical_host_mutator_filters_from_args
            args_hm_bad_ver = SimpleNamespace(graph_key_version=999)
            with self.assertRaisesRegex(StorageSchemaError, "unsupported graph key version"):
                canonical_host_mutator_filters_from_args(args_hm_bad_ver)

            args_hm_bad_src = SimpleNamespace(
                graph_key_version=GRAPH_KEY_VERSION, source_key="invalid key with spaces", target_key=None, category=None
            )
            with self.assertRaisesRegex(StorageSchemaError, "invalid --source-key canonical key"):
                canonical_host_mutator_filters_from_args(args_hm_bad_src)

            args_hm_bad_cat = SimpleNamespace(
                graph_key_version=GRAPH_KEY_VERSION, source_key=None, target_key=None, category=""
            )
            with self.assertRaisesRegex(StorageSchemaError, "invalid host mutation category"):
                canonical_host_mutator_filters_from_args(args_hm_bad_cat)

            cat_key = host_category_key("container")
            diff_key = host_category_key("package")
            args_hm_mismatch = SimpleNamespace(
                graph_key_version=GRAPH_KEY_VERSION, source_key=None, target_key=diff_key, category="container"
            )
            with self.assertRaisesRegex(StorageSchemaError, "refer to different host categories"):
                canonical_host_mutator_filters_from_args(args_hm_mismatch)

            args_hm_ok = SimpleNamespace(
                graph_key_version=GRAPH_KEY_VERSION, source_key=None, target_key=cat_key, category="container"
            )
            self.assertEqual(canonical_host_mutator_filters_from_args(args_hm_ok), cat_key)

            # 4. canonical_host_mutator_summary_target_from_args
            self.assertIsNone(
                canonical_host_mutator_summary_target_from_args(
                    SimpleNamespace(graph_key_version=GRAPH_KEY_VERSION, category=None)
                )
            )
            with self.assertRaises(StorageSchemaError):
                canonical_host_mutator_summary_target_from_args(SimpleNamespace(graph_key_version=999, category=None))
            with self.assertRaises(StorageSchemaError):
                canonical_host_mutator_summary_target_from_args(
                    SimpleNamespace(graph_key_version=GRAPH_KEY_VERSION, category="")
                )
            self.assertEqual(
                canonical_host_mutator_summary_target_from_args(
                    SimpleNamespace(graph_key_version=GRAPH_KEY_VERSION, category="container")
                ),
                cat_key,
            )

            # 5. filter_canonical_host_mutator_records
            rec_tool = SimpleNamespace(metadata={"tool": "docker"}, identity_metadata={"tool": "docker"})
            rec_other = SimpleNamespace(metadata={"tool": "curl"}, identity_metadata={"tool": "curl"})
            self.assertEqual(filter_canonical_host_mutator_records((rec_tool, rec_other), tool=None), (rec_tool, rec_other))
            self.assertEqual(filter_canonical_host_mutator_records((rec_tool, rec_other), tool="docker"), (rec_tool,))

            # 6. canonical_edge_identity_metadata_from_args
            with self.assertRaises(StorageSchemaError):
                canonical_edge_identity_metadata_from_args(SimpleNamespace(identity_metadata_json="{bad"))
            with self.assertRaises(StorageSchemaError):
                canonical_edge_identity_metadata_from_args(SimpleNamespace(identity_metadata_json="[1, 2]"))
            self.assertEqual(
                canonical_edge_identity_metadata_from_args(SimpleNamespace(identity_metadata_json='{"rule": "v1"}')),
                {"rule": "v1"},
            )

            # 7. psql_args_from_args
            psql_empty = SimpleNamespace(pg_host=None, pg_port=None, pg_user=None, pg_database=None)
            self.assertEqual(psql_args_from_args(psql_empty), [])
            psql_full = SimpleNamespace(pg_host="h", pg_port="5432", pg_user="u", pg_database="d")
            self.assertEqual(psql_args_from_args(psql_full), ["-h", "h", "-p", "5432", "-U", "u", "-d", "d"])

            # 8. read_observations_argument from file and stdin
            obs_file = tmp_path / "obs.jsonl"
            valid_obs_json = json.dumps({
                "kind": "file",
                "source_id": "s1",
                "path": "a.py",
                "confidence": "extracted",
                "extractor": "e1",
                "extractor_version": "1.0",
            }) + "\n"
            obs_file.write_text(valid_obs_json, encoding="utf-8")
            from_file = read_observations_argument(str(obs_file))
            self.assertEqual(len(list(from_file)), 1)
            with patch("sys.stdin", io.StringIO(valid_obs_json)):
                from_stdin = read_observations_argument("-")
                self.assertEqual(len(list(from_stdin)), 1)


def test_integration_cli_module_boundary_preserves_child_inputs_and_patch_seams(tmp_path: Path) -> None:
    import subprocess
    from unittest.mock import MagicMock
    from repomap_test_support import cli_integration
    from runner_coverage_bootstrap import install_bootstrap_directory

    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("output\n", "error\n")
    mock_proc.returncode = 17
    mock_proc.pid = 4242
    session_dir = tmp_path / "session"
    session_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir = session_dir / "child_procs"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    bdir = session_dir / "bootstrap"
    install_bootstrap_directory(bdir)
    config_file = session_dir / "coverage.rc"
    config_file.write_text("[run]\n", encoding="utf-8")
    inherited = {
        "PYTHONPATH": str(bdir),
        "COVERAGE_PROCESS_START": str(config_file),
        "COVERAGE_CHILD_MANIFEST_DIR": str(manifest_dir),
        "COVERAGE_SESSION_INVOCATION_ID": "inv-test-cli-seam",
        "_REPOMAP_TEST_SANDBOX_ACTIVE": "1",
    }
    with patch.dict(os.environ, inherited), patch("subprocess.Popen", return_value=mock_proc) as popen_mock:
        completed = cli_integration.run_cli_module("identity", input_text="payload")
        assert completed.returncode == 17
        assert completed.stdout == "output\n"
        assert completed.stderr == "error\n"
    args, kwargs = popen_mock.call_args
    assert args == ([sys.executable, "-m", "repomap_kg", "identity"],)
    assert kwargs["cwd"] == str(cli_integration.REPO_ROOT) and kwargs["text"] is True
    assert (kwargs["stdin"], kwargs["stdout"], kwargs["stderr"]) == (subprocess.PIPE, subprocess.PIPE, subprocess.PIPE)
    mock_proc.communicate.assert_called_once_with(input="payload")
    assert all(kwargs["env"][key] == value for key, value in inherited.items() if key != "PYTHONPATH")
    assert str(bdir) in kwargs["env"]["PYTHONPATH"]

    completed_dummy = subprocess.CompletedProcess(["module"], 17, "output\n", "error\n")
    with patch.object(cli_integration, "run_cli_module", return_value=completed_dummy) as entry:
        assert cli_integration.run_module_entrypoint("identity") == (17, "output\n", "error\n")
    entry.assert_called_once_with("identity")
    with patch("subprocess.Popen", side_effect=OSError("launch refused")):
        with patch.dict(os.environ, inherited):
            with unittest.TestCase().assertRaisesRegex(OSError, "launch refused"):
                cli_integration.run_cli_module("identity")


def test_measured_launch_without_observer_authority_fails_closed() -> None:
    from runner_coverage_execution import launch_observed_process

    incomplete = {"COVERAGE_PROCESS_START": "dummy.rc", "COVERAGE_CHILD_MANIFEST_DIR": "dummy-manifests"}
    with patch.dict(os.environ, incomplete, clear=True):
        with pytest.raises(RuntimeError, match="requires an explicit observer"):
            launch_observed_process([sys.executable, "-c", "pass"], family="cli_module", pid_namespace_relation="shared")


def test_measured_launch_prepares_explicit_env_without_bypass(tmp_path: Path) -> None:
    from unittest.mock import MagicMock
    from runner_coverage_bootstrap import install_bootstrap_directory
    from runner_coverage_execution import launch_observed_process

    mock_proc = MagicMock(communicate=MagicMock(return_value=("", "")), returncode=0, pid=1234)
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    bdir = session_dir / "bootstrap"
    install_bootstrap_directory(bdir)
    manifest_dir = session_dir / "manifests"
    manifest_dir.mkdir()
    config_file = session_dir / "coverage.rc"
    config_file.write_text("[run]\n", encoding="utf-8")
    explicit_env = {
        "PATH": "/bin", "CUSTOM_VAR": "custom",
        "COVERAGE_PROCESS_START": str(config_file),
        "COVERAGE_CHILD_MANIFEST_DIR": str(manifest_dir),
        "COVERAGE_SESSION_INVOCATION_ID": "inv-test-bypass",
    }
    with patch.dict(os.environ, {}, clear=True), patch("subprocess.Popen", return_value=mock_proc) as popen_mock:
        launch_observed_process(
            [sys.executable, "-c", "pass"], family="cli_module", env=explicit_env,
            pid_namespace_relation="shared",
        )
    passed_env = popen_mock.call_args[1]["env"]
    assert passed_env["CUSTOM_VAR"] == "custom"
    assert str(bdir) in passed_env["PYTHONPATH"]


def test_integration_cli_module_boundary_executes_real_module_version() -> None:
    from repomap_test_support import cli_integration

    original_argv = sys.argv[:]
    code, stdout, stderr = cli_integration.run_module_entrypoint("--version")
    assert (code, stdout.strip(), stderr) == (0, f"repomap-kg {__version__}", "")
    assert sys.argv == original_argv


def test_integration_cli_subprocess_retains_runner_child_coverage_bootstrap(tmp_path: Path) -> None:
    from repomap_test_support import cli_integration
    from runner_coverage import ChildCoverageSession

    with ChildCoverageSession(scratch_dir=tmp_path / "coverage") as session:
        code, stdout, _stderr = cli_integration.run_module_entrypoint("--version")
    assert code == 0 and stdout.strip() == f"repomap-kg {__version__}"
    started = {path.stem for path in session.child_manifest_dir.glob("*.start")}
    exited = {path.stem for path in session.child_manifest_dir.glob("*.exit")}
    recorded = {path.stem for path in session.child_manifest_dir.glob("*.shard")}
    assert len(started) == 1
    assert started == exited == recorded
    assert list(session.data_dir.glob(".coverage.*"))
# REPOMAP-PUBLIC-V002-FIX10-R1 dynamic boundary re-attestation.
