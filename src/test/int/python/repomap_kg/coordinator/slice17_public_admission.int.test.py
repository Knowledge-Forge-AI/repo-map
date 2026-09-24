"""Public CLI admission and preflight contrasts before worker launch."""
import json

import pytest

from repomap_test_support.cli_in_process import run_repo_map_in_process


@pytest.mark.parametrize(("options", "category"), [
    ([], "coordinator_requires_repo_map_home"),
    (["--repo-map-home", "HOME"], "coordinator_requires_idempotency_key"),
    (["--repo-map-home", "HOME", "--idempotency-key", "fixture", "--psql-command", "unused"],
     "coordinator_rejects_psql_command"),
    (["--repo-map-home", "HOME", "--idempotency-key", "fixture", "--backend-telemetry-fd", "17"],
     "coordinator_rejects_backend_telemetry"),
])
def test_coordinator_cli_refuses_incompatible_launch_authority(tmp_path, options, category):
    home = tmp_path / "absent-home"
    args = [str(home) if value == "HOME" else value for value in options]
    code, stdout, stderr = run_repo_map_in_process(
        "ops", "refresh-graph", "--mode", "coordinator", "--graph", "fixture", *args)
    assert code == 1 and stdout == ""
    assert category in stderr
    assert not home.exists()


def _config(path, root, excludes=(), enabled=True):
    path.write_text(f'''schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
[postgres]
host = "127.0.0.1"
port = 55433
database = "fixture"
user = "fixture"
password_env = "REPOMAP_PG_PASSWORD"
[[graphs]]
id = "fixture"
name = "Fixture"
root_path = {json.dumps(str(root))}
repository_name = "fixture"
privacy = "private-ops"
enabled = {str(enabled).lower()}
mcp_visible = false
extractor_profile = "private-ops"
refresh_policy = "manual"
exclude_paths = {json.dumps(list(excludes))}
[server_memory]
enabled = false
path = "unused"
mode = "read_only"
''')


@pytest.mark.parametrize("state", ["missing", "file", "disabled"])
def test_preflight_refuses_unusable_source_and_recovers_without_launch(tmp_path, state):
    config, root = tmp_path / "config.toml", tmp_path / "source"
    if state == "file":
        root.write_text("not a directory")
    _config(config, root, enabled=state != "disabled")
    code, stdout, stderr = run_repo_map_in_process(
        "ops", "refresh-preflight", "--config", str(config), "--graph", "fixture", "--json")
    assert code == 1 and stdout == ""
    assert {"missing": "does not exist", "file": "not a directory", "disabled": "disabled"}[state] in stderr
    if root.is_file():
        root.unlink()
    root.mkdir()
    (root / "main.py").write_text("VALUE = 1\n")
    _config(config, root)
    code, stdout, stderr = run_repo_map_in_process(
        "ops", "refresh-preflight", "--config", str(config), "--graph", "fixture", "--json")
    payload = json.loads(stdout)
    assert code == 0 and stderr == ""
    assert payload["graph"]["files_included"] == 1
    assert not payload["safety"]["storage_written"] and not payload["safety"]["source_acquisition"]


def test_preflight_counts_excluded_links_without_reading_outside_content(tmp_path):
    config, root, outside = tmp_path / "config.toml", tmp_path / "source", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    marker = "outside-content-must-not-appear"
    (outside / "data").write_text(marker)
    for name in ("build", "custom", "credentials"):
        (root / name).symlink_to(outside, target_is_directory=True)
    for name in ("dist", "custom-file"):
        (root / name).symlink_to(outside / "data")
    (root / "inside").mkdir()
    (root / "inside" / "main.py").write_text("VALUE = 1\n")
    (root / "alias.py").symlink_to(root / "inside" / "main.py")
    (root / "alias-dir").symlink_to(root / "inside", target_is_directory=True)
    (root / "skip.txt").write_text(marker)
    (root / "passwords").mkdir()
    (root / "passwords" / "empty.txt").write_text("")
    for name in ("requirements.txt", "Gemfile", "record.eml", "table.csv", "data.json", "odd.bin"):
        (root / name).write_text("")
    _config(config, root, ("build", "custom", "custom-file", "skip.txt"))
    code, stdout, stderr = run_repo_map_in_process(
        "ops", "refresh-preflight", "--config", str(config), "--graph", "fixture", "--json")
    assert code == 0 and stderr == ""
    payload = json.loads(stdout)
    graph = payload["graph"]
    assert graph["symlinks_skipped_outside_root"] == 5
    assert graph["symlink_count"] == 7
    assert graph["configured_exclude_hit_counts"] == {"build": 1, "custom": 1, "custom-file": 1, "skip.txt": 1}
    assert graph["generated_output_skips"] >= 2
    assert graph["secret_like_path_count"] >= 2
    assert graph["extractor_categories"]["email"] == 1
    assert graph["extractor_categories"]["config"] == 1
    assert graph["language_counts"]["ruby"] == 1
    assert marker not in stdout and str(outside) not in stdout
    assert graph["root_path_display"] == "[private-root]"
    assert not payload["safety"]["storage_written"]
    assert (outside / "data").read_text() == marker
