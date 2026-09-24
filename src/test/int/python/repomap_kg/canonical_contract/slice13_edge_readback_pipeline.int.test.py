"""Integration tests for Slice 13 edge readback pipeline (Group S13-A).

Covers:
- S13-A01: Edge identity metadata disambiguation
- S13-A02: Evidence paging and stable cross-run ordering
- S13-A03: Evidence association excludes another repository
- S13-A04: Evidence raw-observation fallback
"""

from __future__ import annotations

import subprocess
import unittest

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.canonical import query_canonical_edge_explanation
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


class Slice13EdgeReadbackPipelineIntegrationTests(unittest.TestCase):
    """Slice 13 Group S13-A integration tests for canonical edge explanation readback."""


    def test_s13_a01_edge_identity_metadata_disambiguation(self) -> None:
        """Disambiguates edges sharing source, kind, and target by distinct identity metadata hash."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            h1 = "1" * 64
            h2 = "2" * 64
            subprocess.run(
                [
                    postgres.psql_command,
                    *postgres.psql_args,
                    "-c",
                    f"""
                    INSERT INTO repositories (id, name, root_path, repository_identity)
                    VALUES (1, 'slice13-repo', '/tmp/slice13-root', 'repo13:main');
                    INSERT INTO runs (id, repository_id, status) VALUES (1, 1, 'complete');
                    INSERT INTO canonical_nodes (id, repository_id, graph_key_version, canonical_key, kind, display_name, metadata_json, confidence)
                    VALUES
                    (1, 1, 1, 'file:src/source.py', 'file', 'source.py', '{{}}', 'extracted'),
                    (2, 1, 1, 'file:src/target.py', 'file', 'target.py', '{{}}', 'extracted');
                    INSERT INTO canonical_edges (id, repository_id, graph_key_version, source_canonical_key, edge_kind, target_canonical_key, identity_metadata_json, identity_metadata_hash, metadata_json, confidence)
                    VALUES
                    (1, 1, 1, 'file:src/source.py', 'references', 'file:src/target.py', '{{"order": 1}}', '{h1}', '{{"comment": "first"}}', 'extracted'),
                    (2, 1, 1, 'file:src/source.py', 'references', 'file:src/target.py', '{{"order": 2}}', '{h2}', '{{"comment": "second"}}', 'extracted');
                    INSERT INTO canonical_evidence (id, repository_id, run_id, graph_key_version, evidence_key, raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id, path, extractor, extractor_version, confidence, metadata_json)
                    VALUES
                    (1, 1, 1, 1, 'ev:order1', 1, 1, 'python.import', 'imp1', 'src/source.py', 'test', '1.0', 'extracted', '{{"pos": 1}}'),
                    (2, 1, 1, 1, 'ev:order2', 2, 1, 'python.import', 'imp2', 'src/source.py', 'test', '1.0', 'extracted', '{{"pos": 2}}');
                    INSERT INTO canonical_edge_evidence (canonical_edge_id, canonical_evidence_id, link_kind)
                    VALUES (1, 1, 'direct'), (2, 2, 'direct');
                    """,
                ],
                check=True,
                capture_output=True,
            )

            res1 = query_canonical_edge_explanation(
                postgres.psql_args,
                root_path="/tmp/slice13-root",
                source_key="file:src/source.py",
                kind="references",
                target_key="file:src/target.py",
                identity_metadata_hash=h1,
                psql_command=postgres.psql_command,
            )
            self.assertIsNotNone(res1.edge)
            assert res1.edge is not None
            self.assertEqual(res1.edge.identity_metadata_hash, h1)
            self.assertEqual(res1.edge.metadata.get("comment"), "first")
            self.assertEqual(len(res1.evidence), 1)
            self.assertEqual(res1.evidence[0].evidence_key, "ev:order1")

            res2 = query_canonical_edge_explanation(
                postgres.psql_args,
                root_path="/tmp/slice13-root",
                source_key="file:src/source.py",
                kind="references",
                target_key="file:src/target.py",
                identity_metadata_hash=h2,
                psql_command=postgres.psql_command,
            )
            self.assertIsNotNone(res2.edge)
            assert res2.edge is not None
            self.assertEqual(res2.edge.identity_metadata_hash, h2)
            self.assertEqual(res2.edge.metadata.get("comment"), "second")
            self.assertEqual(len(res2.evidence), 1)
            self.assertEqual(res2.evidence[0].evidence_key, "ev:order2")

    def test_s13_a02_evidence_paging_and_stable_ordering(self) -> None:
        """Paginates edge evidence stably across runs and ordinals."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            h_edge = "e" * 64
            subprocess.run(
                [
                    postgres.psql_command,
                    *postgres.psql_args,
                    "-c",
                    f"""
                    INSERT INTO repositories (id, name, root_path, repository_identity)
                    VALUES (1, 'slice13-repo', '/tmp/slice13-root', 'repo13:main');
                    INSERT INTO runs (id, repository_id, status) VALUES (1, 1, 'complete'), (2, 1, 'complete');
                    INSERT INTO canonical_nodes (id, repository_id, graph_key_version, canonical_key, kind, display_name, metadata_json, confidence)
                    VALUES
                    (1, 1, 1, 'file:src/a.py', 'file', 'a.py', '{{}}', 'extracted'),
                    (2, 1, 1, 'file:src/b.py', 'file', 'b.py', '{{}}', 'extracted');
                    INSERT INTO canonical_edges (id, repository_id, graph_key_version, source_canonical_key, edge_kind, target_canonical_key, identity_metadata_json, identity_metadata_hash, metadata_json, confidence)
                    VALUES (1, 1, 1, 'file:src/a.py', 'references', 'file:src/b.py', '{{}}', '{h_edge}', '{{}}', 'extracted');
                    INSERT INTO canonical_evidence (id, repository_id, run_id, graph_key_version, evidence_key, raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id, path, extractor, extractor_version, confidence, metadata_json)
                    VALUES
                    (1, 1, 1, 1, 'ev:run1-ord1', 1, 1, 'python.import', 'src1', 'src/a.py', 'test', '1.0', 'extracted', '{{}}'),
                    (2, 1, 1, 1, 'ev:run1-ord2', 2, 1, 'python.import', 'src2', 'src/a.py', 'test', '1.0', 'extracted', '{{}}'),
                    (3, 1, 2, 1, 'ev:run2-ord1', 1, 1, 'python.import', 'src3', 'src/a.py', 'test', '1.0', 'extracted', '{{}}');
                    INSERT INTO canonical_edge_evidence (canonical_edge_id, canonical_evidence_id, link_kind)
                    VALUES (1, 1, 'direct'), (1, 2, 'direct'), (1, 3, 'direct');
                    """,
                ],
                check=True,
                capture_output=True,
            )

            page1 = query_canonical_edge_explanation(
                postgres.psql_args,
                root_path="/tmp/slice13-root",
                source_key="file:src/a.py",
                kind="references",
                target_key="file:src/b.py",
                identity_metadata_hash=h_edge,
                evidence_limit=2,
                evidence_offset=0,
                psql_command=postgres.psql_command,
            )
            self.assertEqual(len(page1.evidence), 2)
            self.assertEqual(page1.evidence[0].evidence_key, "ev:run1-ord1")
            self.assertEqual(page1.evidence[1].evidence_key, "ev:run1-ord2")

            page2 = query_canonical_edge_explanation(
                postgres.psql_args,
                root_path="/tmp/slice13-root",
                source_key="file:src/a.py",
                kind="references",
                target_key="file:src/b.py",
                identity_metadata_hash=h_edge,
                evidence_limit=2,
                evidence_offset=2,
                psql_command=postgres.psql_command,
            )
            self.assertEqual(len(page2.evidence), 1)
            self.assertEqual(page2.evidence[0].evidence_key, "ev:run2-ord1")

            keys_p1 = {e.evidence_key for e in page1.evidence}
            keys_p2 = {e.evidence_key for e in page2.evidence}
            self.assertTrue(keys_p1.isdisjoint(keys_p2))

    def test_s13_a03_evidence_association_excludes_another_repository(self) -> None:
        """Edge explanation restricts evidence association strictly to the requested repository."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            h_edge = "3" * 64
            subprocess.run(
                [
                    postgres.psql_command,
                    *postgres.psql_args,
                    "-c",
                    f"""
                    INSERT INTO repositories (id, name, root_path, repository_identity)
                    VALUES
                    (1, 'repo-alpha', '/tmp/slice13-alpha', 'repo13:alpha'),
                    (2, 'repo-beta', '/tmp/slice13-beta', 'repo13:beta');
                    INSERT INTO runs (id, repository_id, status) VALUES (1, 1, 'complete'), (2, 2, 'complete');
                    INSERT INTO canonical_nodes (id, repository_id, graph_key_version, canonical_key, kind, display_name, metadata_json, confidence)
                    VALUES
                    (1, 1, 1, 'file:mod.py', 'file', 'mod.py', '{{}}', 'extracted'),
                    (2, 1, 1, 'file:dep.py', 'file', 'dep.py', '{{}}', 'extracted'),
                    (3, 2, 1, 'file:mod.py', 'file', 'mod.py', '{{}}', 'extracted'),
                    (4, 2, 1, 'file:dep.py', 'file', 'dep.py', '{{}}', 'extracted');
                    INSERT INTO canonical_edges (id, repository_id, graph_key_version, source_canonical_key, edge_kind, target_canonical_key, identity_metadata_json, identity_metadata_hash, metadata_json, confidence)
                    VALUES
                    (1, 1, 1, 'file:mod.py', 'references', 'file:dep.py', '{{}}', '{h_edge}', '{{}}', 'extracted'),
                    (2, 2, 1, 'file:mod.py', 'references', 'file:dep.py', '{{}}', '{h_edge}', '{{}}', 'extracted');
                    INSERT INTO canonical_evidence (id, repository_id, run_id, graph_key_version, evidence_key, raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id, path, extractor, extractor_version, confidence, metadata_json)
                    VALUES
                    (1, 1, 1, 1, 'ev:shared', 1, 1, 'python.import', 'src-a', 'src/alpha_mod.py', 'test', '1.0', 'extracted', '{{}}'),
                    (2, 2, 2, 1, 'ev:shared', 1, 1, 'python.import', 'src-b', 'src/beta_mod.py', 'test', '1.0', 'extracted', '{{}}');
                    INSERT INTO canonical_edge_evidence (canonical_edge_id, canonical_evidence_id, link_kind)
                    VALUES (1, 1, 'direct'), (2, 2, 'direct');
                    """,
                ],
                check=True,
                capture_output=True,
            )

            res_alpha = query_canonical_edge_explanation(
                postgres.psql_args,
                root_path="/tmp/slice13-alpha",
                source_key="file:mod.py",
                kind="references",
                target_key="file:dep.py",
                identity_metadata_hash=h_edge,
                psql_command=postgres.psql_command,
            )
            self.assertEqual(len(res_alpha.evidence), 1)
            self.assertEqual(res_alpha.evidence[0].path, "src/alpha_mod.py")

            res_beta = query_canonical_edge_explanation(
                postgres.psql_args,
                root_path="/tmp/slice13-beta",
                source_key="file:mod.py",
                kind="references",
                target_key="file:dep.py",
                identity_metadata_hash=h_edge,
                psql_command=postgres.psql_command,
            )
            self.assertEqual(len(res_beta.evidence), 1)
            self.assertEqual(res_beta.evidence[0].path, "src/beta_mod.py")

    def test_s13_a04_evidence_raw_observation_fallback(self) -> None:
        """Falls back to canonical evidence fields when raw observation reference is absent."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            h_edge = "4" * 64
            h_raw = "f" * 64
            subprocess.run(
                [
                    postgres.psql_command,
                    *postgres.psql_args,
                    "-c",
                    f"""
                    INSERT INTO repositories (id, name, root_path, repository_identity)
                    VALUES (1, 'slice13-repo', '/tmp/slice13-root', 'repo13:main');
                    INSERT INTO runs (id, repository_id, status) VALUES (1, 1, 'complete');
                    INSERT INTO canonical_nodes (id, repository_id, graph_key_version, canonical_key, kind, display_name, metadata_json, confidence)
                    VALUES
                    (1, 1, 1, 'file:m.py', 'file', 'm.py', '{{}}', 'extracted'),
                    (2, 1, 1, 'file:n.py', 'file', 'n.py', '{{}}', 'extracted');
                    INSERT INTO canonical_edges (id, repository_id, graph_key_version, source_canonical_key, edge_kind, target_canonical_key, identity_metadata_json, identity_metadata_hash, metadata_json, confidence)
                    VALUES (1, 1, 1, 'file:m.py', 'references', 'file:n.py', '{{}}', '{h_edge}', '{{}}', 'extracted');
                    INSERT INTO raw_observations (id, repository_id, run_id, ordinal, schema_version, kind, source_id, path, payload_json, payload_hash)
                    VALUES (1, 1, 1, 1, 1, 'raw.python.stmt', 'stmt-001', 'm.py', '{{"key": "val"}}'::jsonb, '{h_raw}');
                    INSERT INTO canonical_evidence (id, repository_id, run_id, graph_key_version, raw_observation_id, evidence_key, raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id, path, extractor, extractor_version, confidence, metadata_json)
                    VALUES
                    (1, 1, 1, 1, 1, 'ev:linked', 1, 1, 'fallback.kind', 'fallback.source', 'm.py', 'test', '1.0', 'extracted', '{{}}'),
                    (2, 1, 1, 1, NULL, 'ev:unlinked', 2, 1, 'fallback.kind', 'fallback.source', 'm.py', 'test', '1.0', 'extracted', '{{}}');
                    INSERT INTO canonical_edge_evidence (canonical_edge_id, canonical_evidence_id, link_kind)
                    VALUES (1, 1, 'direct'), (1, 2, 'direct');
                    """,
                ],
                check=True,
                capture_output=True,
            )

            res = query_canonical_edge_explanation(
                postgres.psql_args,
                root_path="/tmp/slice13-root",
                source_key="file:m.py",
                kind="references",
                target_key="file:n.py",
                identity_metadata_hash=h_edge,
                psql_command=postgres.psql_command,
            )
            self.assertEqual(len(res.evidence), 2)
            ev_linked = next(e for e in res.evidence if e.evidence_key == "ev:linked")
            ev_unlinked = next(e for e in res.evidence if e.evidence_key == "ev:unlinked")

            # Linked evidence resolves raw observation attributes from raw_observations
            self.assertEqual(ev_linked.raw_observation.get("payload_hash"), h_raw)
            self.assertEqual(ev_linked.raw_observation.get("kind"), "raw.python.stmt")
            self.assertEqual(ev_linked.raw_observation.get("source_id"), "stmt-001")

            # Unlinked evidence falls back to canonical_evidence raw_kind and raw_source_id
            self.assertIsNone(ev_unlinked.raw_observation.get("payload_hash"))
            self.assertEqual(ev_unlinked.raw_observation.get("kind"), "fallback.kind")
            self.assertEqual(ev_unlinked.raw_observation.get("source_id"), "fallback.source")


if __name__ == "__main__":
    import sys
    sys.exit(
        "Direct execution unsupported; use tools/run_tests.py for container sandbox admission."
    )
