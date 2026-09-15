from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest

from repomap_kg.ops.config_records import OpsConfigError
from repomap_kg.graph.multi_source_pipeline import multi_source_config_generation
from repomap_kg.ops.resolved_config import resolve_ops_config
from repomap_kg.ops.config import load_ops_config
from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
from repomap_kg.runtime.plan import build_local_runtime_plan
from repomap_test_support.ops_refresh import (
    OpsRefreshUnitTestCase,
    VALID_REFRESH_CONFIG,
)


class Arch1BResolvedConfigUnitTests(OpsRefreshUnitTestCase):
    def test_resolves_distinct_graph_control_and_maintenance_targets(self) -> None:
        config = self.config_for_roots(Path("/public/repo"))
        resolved = resolve_ops_config(config)

        assert tuple(graph.database for graph in resolved.graphs) == (
            "repomap_repo_map",
            "repomap_codex_vc",
        )
        assert resolved.control_database == "repomap_control"
        assert resolved.maintenance_database == "postgres"
        assert resolved.owned_databases == (
            "repomap_codex_vc",
            "repomap_control",
            "repomap_repo_map",
        )

    def test_repository_identity_is_stable_across_root_relocation(self) -> None:
        first = self.config_for_roots(Path("/public/first"))
        second = self.config_for_roots(Path("/public/second"))

        assert (
            resolve_ops_config(first).graph("repo-map").repository_identity
            == resolve_ops_config(second).graph("repo-map").repository_identity
            == "repo1:repo-map"
        )

    def test_rejects_graph_maintenance_or_template_database(self) -> None:
        config = self.config_for_roots(Path("/public/repo"))
        for database in ("postgres", "template0", "template1"):
            with self.subTest(database=database):
                graph = replace(config.graphs[0], database=database)
                invalid = replace(config, graphs=(graph, *config.graphs[1:]))

                with pytest.raises(
                    OpsConfigError,
                    match="graph database target is reserved",
                ):
                    resolve_ops_config(invalid)

    def test_rejects_maintenance_database_as_global_graph_default(self) -> None:
        config = self.config_for_roots(Path("/public/repo"))

        with pytest.raises(OpsConfigError, match="global graph database target"):
            resolve_ops_config(
                replace(
                    config,
                    postgres=replace(config.postgres, database="postgres"),
                )
            )

    def test_rejects_duplicate_effective_graph_database(self) -> None:
        config = self.config_for_roots(Path("/public/repo"))
        duplicate = replace(
            config.graphs[1],
            database=config.graphs[0].database,
        )

        with pytest.raises(OpsConfigError, match="duplicate effective graph database"):
            resolve_ops_config(replace(config, graphs=(config.graphs[0], duplicate)))

    def test_rejects_explicit_database_that_collides_with_fallback(self) -> None:
        config = self.config_for_roots(Path("/public/repo"))
        fallback = replace(config.graphs[0], database=None)
        duplicate = replace(config.graphs[1], database=config.postgres.database)

        with pytest.raises(OpsConfigError, match="duplicate effective graph database"):
            resolve_ops_config(replace(config, graphs=(fallback, duplicate)))

    def test_fallback_database_is_resolved_explicitly(self) -> None:
        config = self.config_for_roots(Path("/public/repo"))
        fallback = replace(config.graphs[0], database=None)
        resolved = resolve_ops_config(
            replace(config, graphs=(fallback, config.graphs[1]))
        )

        assert resolved.graph("repo-map").database == "repomap"

    def test_config_loading_rejects_duplicate_effective_database(self) -> None:
        content = VALID_REFRESH_CONFIG.format(
            repo_root="/public/repo",
            private_root="/public/private",
        ).replace('database = "repomap_codex_vc"', 'database = "repomap_repo_map"')

        with pytest.raises(OpsConfigError, match="duplicate effective graph database"):
            load_ops_config(self.write_config(content))

    def test_rejects_control_database_collision_with_graph(self) -> None:
        config = self.config_for_roots(Path("/public/repo"))
        collision = replace(config.graphs[1], database="repomap_control")

        with pytest.raises(OpsConfigError, match="control database target"):
            resolve_ops_config(replace(config, graphs=(config.graphs[0], collision)))

    def test_rejects_invalid_control_derivation_without_echoing_target(self) -> None:
        config = self.config_for_roots(Path("/public/repo"))
        private_target = "a" * 63

        with pytest.raises(OpsConfigError, match="derived control database target") as error:
            resolve_ops_config(
                replace(
                    config,
                    postgres=replace(config.postgres, database=private_target),
                )
            )

        assert private_target not in str(error.value)

    def test_rejects_configured_repository_identity_collision(self) -> None:
        config = self.config_for_roots(Path("/public/repo"))
        collision = replace(config.graphs[1], id=config.graphs[0].id)

        with pytest.raises(OpsConfigError, match="repository identity collision"):
            resolve_ops_config(replace(config, graphs=(config.graphs[0], collision)))

    def test_runtime_and_lifecycle_projection_exposes_exact_owned_allowlist(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home = root / "home"
            repository = root / "repository"
            private = root / "private"
            repository.mkdir()
            private.mkdir()
            self.config_home_for_roots(home, repository, private)

            plan = build_local_runtime_plan(home)

        assert plan.database == "repomap"
        assert plan.owned_databases == (
            "repomap_codex_vc",
            "repomap_control",
            "repomap_repo_map",
        )
        assert plan.maintenance_database == "postgres"

    def test_direct_and_coordinator_use_equal_resolved_config_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home = root / "home"
            repository = root / "repository"
            private = root / "private"
            repository.mkdir()
            (repository / "README.md").write_text("# RepoMap\n", encoding="utf-8")
            private.mkdir()
            config = self.config_home_for_roots(home, repository, private)
            graph = config.graphs[0]
            resolver = ConfiguredRefreshResolver(
                home / "repomap.rpl.toml",
                root / "psql",
            )

            with patch.dict("os.environ", {"REPOMAP_PG_PASSWORD": "synthetic"}):
                coordinator = resolver.resolve_authority("repo-map")

        assert coordinator.config_generation == multi_source_config_generation(graph)
