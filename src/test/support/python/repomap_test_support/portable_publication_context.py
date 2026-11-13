"""Real mixed-source Local/Server setup and accepted-publication readback."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import json
from pathlib import Path
import pytest
from common_lore_index.cli.main import main as cli_main
from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from common_lore_index.ops.local_refresh import refresh_local_graph
from common_lore_index.ops.refresh import refresh_graph
from common_lore_index.storage import apply_migrations, default_rdbms_root
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID, binding_id_for_alias, materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home, write_mixed_v1_sqlite_home,
)
from repomap_test_support.sqlite_local_harness import LocalHarness

@contextmanager
def publication_backend(root: Path, backend: str) -> Iterator[tuple[Path, Path, Callable[[], object]]]:
    source = root / "source"
    materialize_mixed_v1_working_copy(source, generation=1)
    bulk = source / "core" / "pkg" / "bulk.py"
    bulk.write_text("".join(f"def function_{i}():\n    return {i}\n\n" for i in range(4201)), encoding="utf-8")
    home = root / "home"
    if backend == "sqlite":
        write_mixed_v1_sqlite_home(home, source)
        initialized = LocalHarness(root / "guarded", block_psycopg=True).run(
            "ops", "sqlite-init", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID, "--json",
        )
        assert initialized.returncode == 0, initialized.stderr
        local = load_graph_registry_config_home(home)
        assert isinstance(local, LocalSqliteConfig)
        yield home, bulk, lambda: refresh_local_graph(local, MIXED_V1_GRAPH_ID)
        return
    with temporary_postgres() as postgres:
        write_mixed_v1_postgres_home(
            home, source, host=postgres.host, port=postgres.port, database=postgres.database,
            user=postgres.user, password=postgres.password, declared_aliases=("core", "companion"),
        )
        server = load_graph_registry_config_home(home)
        assert isinstance(server, OpsConfig)
        apply_migrations(
            default_rdbms_root(), server.postgres.psql_args_for_database(postgres.database),
            psql_command=postgres.psql_command,
        )
        yield home, bulk, lambda: refresh_graph(server, MIXED_V1_GRAPH_ID, psql_command=postgres.psql_command)


def accepted_pin(home: Path, output: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    result = cli_main([
        "ops", "context-select", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
        "--binding", binding_id_for_alias("core"), "--binding", binding_id_for_alias("companion"),
        "--pin-publication", "--output", str(output),
    ])
    captured = capsys.readouterr()
    assert result == 0 and captured.err == "", captured.err
    record = json.loads(captured.out)
    pin = record["expected_publication"]
    assert isinstance(pin, dict) and type(pin["generation"]) is int
    return pin
