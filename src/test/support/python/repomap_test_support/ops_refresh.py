"""Shared support for ops refresh unit tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.config import load_ops_config, load_ops_config_home


VALID_REFRESH_CONFIG = """\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "admin"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "{repo_root}"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
database = "repomap_repo_map"

[[graphs]]
id = "codex-vc"
name = "Codex VC"
root_path = "{private_root}"
repository_name = "codex-vc"
privacy = "private-ops"
enabled = false
mcp_visible = false
extractor_profile = "private-ops"
refresh_policy = "watch"
database = "repomap_codex_vc"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
"""


class OpsRefreshUnitTestCase(unittest.TestCase):
    def write_config(self, content: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "repomap.local.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def config_for_roots(self, repo_root: Path, private_root: Path | None = None):
        private = private_root or repo_root / "private"
        return load_ops_config(
            self.write_config(
                VALID_REFRESH_CONFIG.format(repo_root=repo_root, private_root=private)
            )
        )

    def config_home_for_roots(
        self,
        home: Path,
        repo_root: Path,
        private_root: Path | None = None,
    ):
        private = private_root or repo_root / "private"
        home.mkdir(parents=True)
        (home / "repomap.rpl.toml").write_text(
            VALID_REFRESH_CONFIG.format(repo_root=repo_root, private_root=private)
            .replace('host = "127.0.0.1"', 'host = "postgres"'),
            encoding="utf-8",
        )
        return load_ops_config_home(home)

    def sample_observations(self) -> list[RawObservation]:
        return [
            RawObservation(
                kind="file",
                source_id="README.md",
                path="README.md",
                confidence="extracted",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={"language": "markdown", "role": "documentation"},
            )
        ]
