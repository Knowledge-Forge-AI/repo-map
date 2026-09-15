import tempfile
import unittest
from pathlib import Path

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.schema_history import pre_arch5d_rdbms_root


class Scale1StagingMigrationIntegrationTests(unittest.TestCase):
    def test_staging_schema_is_additive_and_rollback_guard_refuses_live_stage(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as migration_tmpdir, temporary_postgres() as postgres:
            apply_migrations(
                pre_arch5d_rdbms_root(Path(migration_tmpdir)),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            new_tables = postgres.psql_scalar(
                """
SELECT string_agg(table_name, ',' ORDER BY table_name)
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'ingestion_stages',
    'stage_files',
    'stage_legacy_nodes',
    'stage_legacy_evidence',
    'stage_legacy_edges',
    'stage_raw_observations',
    'stage_canonical_nodes',
    'stage_canonical_edges',
    'stage_canonical_evidence',
    'stage_canonical_node_evidence',
    'stage_canonical_edge_evidence',
    'graph_publication_authority'
  );
"""
            )
            self.assertEqual(
                new_tables,
                "graph_publication_authority,ingestion_stages,"
                "stage_canonical_edge_evidence,stage_canonical_edges,"
                "stage_canonical_evidence,stage_canonical_node_evidence,"
                "stage_canonical_nodes,stage_files,stage_legacy_edges,"
                "stage_legacy_evidence,stage_legacy_nodes,"
                "stage_raw_observations",
            )

            stage_columns = postgres.psql_scalar(
                """
SELECT string_agg(column_name, ',' ORDER BY ordinal_position)
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'ingestion_stages';
"""
            )
            self.assertEqual(
                stage_columns,
                "stage_id,repository_id,operation_id,job_id,attempt,"
                "execution_mode,coordinator_instance_id,"
                "singleton_fencing_epoch,graph_lease_fencing_epoch,"
                "source_generation,config_generation,extractor_generation,"
                "canonicalizer_generation,state,created_at,updated_at,expires_at,"
                "expected_family_manifest,expected_row_counts,observed_row_counts,"
                "family_checksums,normalized_byte_counts,validation_status,"
                "merge_status,publication_reconciliation_state,cleanup_eligibility,"
                "cleanup_eligible_at",
            )

            repository_id = postgres.psql_scalar(
                """
INSERT INTO repositories(name, root_path)
VALUES ('fixture', 'fixture-root');
SELECT id FROM repositories WHERE root_path = 'fixture-root';
"""
            )
            postgres.psql_scalar(
                f"""
INSERT INTO files(repository_id, path, language, role)
VALUES ({repository_id}, 'README.md', 'markdown', 'documentation');
INSERT INTO ingestion_stages(
    stage_id, repository_id, operation_id, attempt, execution_mode,
    source_generation, config_generation, extractor_generation,
    canonicalizer_generation, expires_at
)
VALUES (
    'stage-001', {repository_id}, 'direct-001', 1, 'direct',
    'sg1:source', 'cg1:config', 'eg1:extractor', 'kg1:canonicalizer',
    now() + interval '1 hour'
);
INSERT INTO stage_files(
    stage_id, family_ordinal, path, language, role, confidence
)
VALUES ('stage-001', 0, 'README.md', 'markdown', 'documentation', 'extracted');
"""
            )

            self.assertEqual(
                postgres.psql_scalar("SELECT count(*) FROM files;"),
                "1",
            )
            self.assertEqual(
                postgres.psql_scalar("SELECT count(*) FROM stage_files;"),
                "1",
            )
            self.assertEqual(
                postgres.psql_scalar(
                    """
SELECT NOT EXISTS (
    SELECT 1 FROM ingestion_stages
    WHERE state <> 'cleaned'
       OR publication_reconciliation_state IN ('required', 'conflicting')
);
"""
                ),
                "f",
            )

            postgres.psql_scalar(
                """
UPDATE ingestion_stages
SET state = 'cleaned', cleanup_eligibility = 'cleaned';
"""
            )
            self.assertEqual(
                postgres.psql_scalar(
                    """
SELECT NOT EXISTS (
    SELECT 1 FROM ingestion_stages
    WHERE state <> 'cleaned'
       OR publication_reconciliation_state IN ('required', 'conflicting')
);
"""
                ),
                "t",
            )

            postgres.psql_scalar(
                "DELETE FROM ingestion_stages WHERE stage_id = 'stage-001';"
            )
            self.assertEqual(
                postgres.psql_scalar("SELECT count(*) FROM stage_files;"),
                "0",
            )
            self.assertEqual(
                postgres.psql_scalar("SELECT count(*) FROM files;"),
                "1",
            )

    def test_graph_publication_authority_projection_is_additive(self):
        require_postgres_binaries()

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            repository_id = postgres.psql_scalar(
                """
INSERT INTO repositories(name, root_path)
VALUES ('fixture', 'fixture-root');
SELECT id FROM repositories WHERE root_path = 'fixture-root';
"""
            )
            postgres.psql_scalar(
                f"""
INSERT INTO graph_publication_authority(
    repository_id, singleton_fencing_epoch, graph_lease_fencing_epoch,
    job_id, attempt, coordinator_instance_id,
    source_generation, config_generation, extractor_generation,
    canonicalizer_generation, last_stage_id
)
VALUES (
    {repository_id}, 4, 4, 'job-001', 2, 'coord-001',
    'sg1:source', 'cg1:config', 'eg1:extractor', 'kg1:canonicalizer',
    'stage-001'
);
"""
            )
            self.assertEqual(
                postgres.psql_scalar(
                    "SELECT singleton_fencing_epoch FROM graph_publication_authority;"
                ),
                "4",
            )
