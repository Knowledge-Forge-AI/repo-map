from __future__ import annotations

import psycopg
import pytest

from repomap_kg.ops.direct_publication import publish_observation_generation
from repomap_kg.runtime.maintenance import (
    MaintenanceUnavailableError,
    maintenance_window,
)
from repomap_kg.storage import apply_migrations
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _connect_factory(postgres):
    def connect():
        return psycopg.connect(
            host=postgres.host,
            port=postgres.port,
            user=postgres.user,
            dbname=postgres.database,
            password=postgres.password,
        )

    return connect


def test_staged_import_refuses_graph_schema_maintenance() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            None,
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )

        with maintenance_window(_connect_factory(postgres)):
            with pytest.raises(MaintenanceUnavailableError, match="maintenance"):
                publish_observation_generation(
                    postgres.psql_args,
                    (),
                    repository_name="synthetic-maintenance",
                    root_path="/synthetic/maintenance",
                    psql_command=postgres.psql_command,
                )
