"""Integration tests for worker-produced bundle durable publication and readback.

Composes:
1. Source sealing of a real language fixture into FileSystemArtifactStore.
2. Supervised portable semantic worker execution producing candidate bundle and receipt.
3. Conformance validation through PublisherBundleValidator.
4. Bound durable publication via run_staged_portable_refresh into PostgreSQL migrations.
5. Exact semantic graph key/relationship readback and receipt verification.
6. Idempotent publication replay, authority epoch fencing refusal, and
   commit_unknown reconciliation (matching admission and conflicting quarantine).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import shutil

import psycopg
from psycopg.conninfo import make_conninfo
import pytest

from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.artifacts.source_sealer import seal_configured_sources
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.artifacts.validator import PublicationExpectation, PublisherBundleValidator
from repomap_kg.coordinator._portable_capability import (
    PortableExecutionCapability,
    create_portable_capability,
)
from repomap_kg.coordinator._portable_worker_launch import run_portable_worker
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.main import apply_migrations, default_rdbms_root
from repomap_kg.storage.publication import PortablePublicationBinding, RunPublicationReceipt
from repomap_kg.storage.publication_fencing import MergeContext, PublicationHandoff
from repomap_kg.storage.publication_readback import (
    read_latest_receipt_bearing_publication,
    read_run_publication,
)
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    _psycopg_connection_params_from_psql_args,
    run_staged_portable_refresh,
    stage_id_for_authority,
)
from repomap_kg.storage.staged_publication import reconcile_commit_unknown
from repomap_test_support.portable_publication_fixtures import (
    create_single_source_graph_config,
    row as _row,
)
from repomap_test_support.portable_worker_scenarios import coordinator_test_limits
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres


def test_worker_produced_portable_bundle_durable_publication_readback_and_reconciliation() -> None:
    require_postgres_binaries()
    with tempfile.TemporaryDirectory(prefix="repomap-durable-worker-") as temporary:
        root = Path(temporary).resolve()
        src_dir = root / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "service.py").write_text(
            "class WorkerService:\n"
            "    def handle_payload(self, item: str) -> str:\n"
            "        return f'processed:{item}'\n",
            encoding="utf-8",
        )

        fixtures = Path(__file__).parents[4] / "fixtures"
        shutil.copytree(fixtures / "shell", src_dir / "shell")
        shutil.copytree(fixtures / "powershell", src_dir / "powershell")
        selected_fixture_paths = tuple(
            sorted(
                path.relative_to(fixtures).as_posix()
                for folder in ("shell", "powershell")
                for path in (fixtures / folder).rglob("*")
                if path.is_file()
            )
        )
        expected_source_paths = tuple(sorted(("service.py", *selected_fixture_paths)))
        actual_source_paths = tuple(
            sorted(
                path.relative_to(src_dir).as_posix()
                for path in src_dir.rglob("*")
                if path.is_file()
            )
        )
        assert actual_source_paths == expected_source_paths

        store_root = root / "artifact_store"
        store_root.mkdir(mode=0o700)
        store = FileSystemArtifactStore(store_root)

        # 1. Authoritative source sealing
        config = create_single_source_graph_config(
            src_dir, graph_id="portable-durable", repository_name="repo-portable-durable",
        )
        manifest, manifest_ref, candidate_id = seal_configured_sources(
            config, store, extractor_generation="eg1:portable", canonicalizer_generation="kg1:portable",
        )
        assert store.verify(manifest_ref)

        # 2. Supervised portable worker launch producing candidate bundle
        ws = root / "worker_ws"
        ws.mkdir(mode=0o700, exist_ok=True)
        job_id, attempt = "job-portable-durable-1", 1
        capability = PortableExecutionCapability(
            schema_version=1, job_id=job_id, attempt=attempt, graph_id=manifest.graph_id,
            store_root=store_root, workspace_root=ws, manifest_reference=manifest_ref,
            source_generation=manifest.source_generation, config_generation=manifest.config_generation,
            extractor_generation=manifest.extractor_generation,
            canonicalizer_generation=manifest.canonicalizer_generation,
            max_artifact_bytes=10 * 1024 * 1024, max_bundle_bytes=10 * 1024 * 1024,
        )
        priv_dir = root / "worker_priv"
        priv_dir.mkdir(mode=0o700, exist_ok=True)
        cap_path = create_portable_capability(priv_dir, capability)
        worker_result = run_portable_worker(
            cap_path, {"job_id": job_id, "attempt": attempt}, coordinator_test_limits(),
        )
        assert worker_result.terminal.get("status") == "succeeded"
        assert worker_result.cleanup_error is None
        assert not cap_path.exists()

        snapshot = worker_result.terminal.get("portable_snapshot")
        assert isinstance(snapshot, dict) and snapshot.get("outcome") == "completed"

        bundle_ref = ArtifactReference.from_mapping(snapshot["bundle"])
        receipt_ref = ArtifactReference.from_mapping(snapshot["receipt"])
        assert store.verify(bundle_ref) and store.verify(receipt_ref)

        # 3. PublisherBundleValidator validation
        validator = PublisherBundleValidator()
        expectation = PublicationExpectation(
            request_id=job_id, job_id=job_id, attempt=attempt, graph_id=config.id,
            candidate_id=candidate_id, snapshot_manifest_id=manifest.manifest_id,
            snapshot_vector=manifest.snapshot_vector, source_generation=manifest.source_generation,
            config_generation=manifest.config_generation, extractor_generation=manifest.extractor_generation,
            canonicalizer_generation=manifest.canonicalizer_generation,
            extractor_capability_identity=manifest.extractor_capability_identity,
            resolver_identity=manifest.resolver_identity, canonicalizer_identity=manifest.canonicalizer_identity,
            semantic_contract_identity=manifest.semantic_contract_identity,
            quality_rule_identity=manifest.quality_rule_identity, mutating_owner_count=1,
            worker_capability_identity="cap1:portable-python-worker-v1",
            expected_privacy=manifest.effective_privacy.value,
        )
        validation = validator.validate_bundle(
            store=store, bundle_reference=bundle_ref, receipt_reference=receipt_ref, expectation=expectation,
        )
        assert validation.byte_integrity_valid and validation.semantic_authority_valid

        bundle = PublicationBundle.from_bytes(store.read(bundle_ref))
        receipt = ExtractionReceipt.from_bytes(store.read(receipt_ref))
        assert receipt.bundle_id == bundle.bundle_id
        assert receipt.snapshot_manifest_id == manifest.manifest_id
        assert bundle.candidate_id == candidate_id
        source_alias = config.effective_source_bindings[0].alias
        expected_published_file_paths = tuple(
            f"{source_alias}/{relative_path}" for relative_path in expected_source_paths
        )
        published_file_paths = tuple(
            sorted(str(row["path"]) for row in bundle.families["files"])
        )
        assert published_file_paths == expected_published_file_paths
        assert bundle.family_counts["files"] == len(expected_published_file_paths)
        assert bundle.family_counts["canonical_nodes"] > 0

        representative_node_kinds = {
            f"{source_alias}/shell/bash/basic.bash": "bash.script",
            f"{source_alias}/shell/zsh/basic.zsh": "zsh.script",
            f"{source_alias}/shell/awk/basic.awk": "awk.program",
            f"{source_alias}/powershell/Advanced.Module.psd1": "powershell.manifest",
            f"{source_alias}/shell/bats/basic.bats": "bats.file",
            f"{source_alias}/shell/zunit/basic.zunit": "zunit.file",
        }
        for fixture_path, expected_kind in representative_node_kinds.items():
            matching_nodes = [
                row
                for row in bundle.families["canonical_nodes"]
                if row["display_name"] == fixture_path and row["kind"] == expected_kind
            ]
            assert len(matching_nodes) == 1, (fixture_path, expected_kind)
        assert list(ws.iterdir()) == []
        assert list(priv_dir.iterdir()) == []

        # 4. Bound authority and portable binding matching worker outputs
        authority = IngestionAuthority(
            operation_id=OperationId(bundle.job_id), attempt=AttemptNumber(bundle.attempt),
            execution_mode="coordinator", source_generation=bundle.source_generation,
            config_generation=bundle.config_generation, extractor_generation=bundle.extractor_generation,
            canonicalizer_generation=bundle.canonicalizer_generation, job_id=JobId(bundle.job_id),
            coordinator_instance_id="coord-durable-readback",
            singleton_fencing_epoch=1, graph_lease_fencing_epoch=1,
        )
        binding = PortablePublicationBinding(
            route="portable-worker-v1", snapshot_manifest_id=bundle.snapshot_manifest_id,
            snapshot_vector=bundle.snapshot_vector, extraction_receipt_id=receipt.receipt_id,
            publication_bundle_id=bundle.bundle_id, candidate_id=bundle.candidate_id,
            resolver_identity=bundle.resolver_identity, canonicalizer_identity=bundle.canonicalizer_identity,
            semantic_contract_identity=bundle.semantic_contract_identity,
            quality_rule_identity=bundle.quality_rule_identity, protocol_version="1.0",
            worker_capability_identity=receipt.worker_capability_identity,
            stage_id=stage_id_for_authority(authority), execution_mode=authority.execution_mode,
            singleton_fencing_epoch=authority.singleton_fencing_epoch,
            graph_lease_fencing_epoch=authority.graph_lease_fencing_epoch,
            family_receipts={
                item.family: {"count": item.record_count, "byte_length": item.byte_length, "digest": item.content_digest}
                for item in bundle.family_summaries
            },
        ).validate()

        # 5. Staged publication into disposable PostgreSQL
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            summary = run_staged_portable_refresh(
                postgres.psql_args, bundle, repository_name=config.repository_name,
                root_path=f"graph:{config.id}", authority=authority, portable_binding=binding,
            )
            assert summary.run_id > 0 and summary.repository_id > 0

            # 6. Authoritative publication receipt readback
            published = read_run_publication(
                postgres.psql_args, job_id=job_id, attempt=attempt, psql_command=postgres.psql_command,
            )
            assert published is not None and published.run_id == summary.run_id
            assert published.receipt.portable is not None
            assert published.receipt.portable.publication_bundle_id == bundle.bundle_id
            assert published.receipt.portable.extraction_receipt_id == receipt.receipt_id
            assert published.receipt.portable.candidate_id == bundle.candidate_id
            assert published.receipt.portable.snapshot_manifest_id == bundle.snapshot_manifest_id

            latest = read_latest_receipt_bearing_publication(postgres.psql_args, psql_command=postgres.psql_command)
            assert latest is not None and latest.run_id == summary.run_id

            # 7. Exact durable relational checks across runs, authority, stages, and families
            params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
            with psycopg.connect(make_conninfo(**params)) as connection:
                run_row = _row(
                    connection,
                    "SELECT status, execution_route, snapshot_manifest_id, "
                    "extraction_receipt_id, publication_bundle_id, graph_candidate_id, "
                    "portable_stage_id FROM runs WHERE id = %s",
                    (summary.run_id,),
                )
                assert run_row == (
                    "complete", "portable-worker-v1", bundle.snapshot_manifest_id,
                    receipt.receipt_id, bundle.bundle_id, bundle.candidate_id, stage_id_for_authority(authority),
                )
                auth_row = _row(
                    connection,
                    "SELECT job_id, attempt, last_run_id, singleton_fencing_epoch, graph_lease_fencing_epoch "
                    "FROM graph_publication_authority WHERE repository_id = %s",
                    (summary.repository_id,),
                )
                assert auth_row == (job_id, attempt, summary.run_id, 1, 1)

                stage_row = _row(
                    connection,
                    "SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility "
                    "FROM ingestion_stages WHERE stage_id = %s",
                    (stage_id_for_authority(authority),),
                )
                assert stage_row == ("published", "committed", "reconciled", "eligible")

                for family in PUBLICATION_FAMILIES:
                    expected_count = bundle.family_counts[family]
                    if family in ("canonical_evidence", "raw_observations"):
                        query = f"SELECT count(*) FROM {family} WHERE run_id = %s"
                    elif family in ("canonical_node_evidence", "canonical_edge_evidence"):
                        query = (
                            f"SELECT count(*) FROM {family} l "
                            "JOIN canonical_evidence e ON e.id = l.canonical_evidence_id WHERE e.run_id = %s"
                        )
                    else:
                        query = f"SELECT count(*) FROM {family} WHERE last_seen_run_id = %s"
                    assert _row(connection, query, (summary.run_id,))[0] == expected_count

                actual_nodes = connection.execute(
                    "SELECT canonical_key, kind FROM canonical_nodes "
                    "WHERE last_seen_run_id = %s ORDER BY canonical_key",
                    (summary.run_id,),
                ).fetchall()
                expected_nodes = sorted(
                    (r["canonical_key"], r["kind"]) for r in bundle.families["canonical_nodes"]
                )
                assert actual_nodes == expected_nodes

                actual_edges = connection.execute(
                    "SELECT source_canonical_key, edge_kind, target_canonical_key FROM canonical_edges "
                    "WHERE last_seen_run_id = %s ORDER BY source_canonical_key, edge_kind, target_canonical_key",
                    (summary.run_id,),
                ).fetchall()
                expected_edges = sorted(
                    (r["source_canonical_key"], r["edge_kind"], r["target_canonical_key"])
                    for r in bundle.families["canonical_edges"]
                )
                assert actual_edges == expected_edges

            # 8. Idempotent replay preserves run identity
            replay_summary = run_staged_portable_refresh(
                postgres.psql_args, bundle, repository_name=config.repository_name,
                root_path=f"graph:{config.id}", authority=authority, portable_binding=binding,
            )
            assert replay_summary.run_id == summary.run_id and replay_summary.repository_id == summary.repository_id

            # 9. Authority/binding fencing epoch mismatch refusal
            mismatched_authority = replace(authority, singleton_fencing_epoch=999)
            with pytest.raises(StorageSchemaError, match="portable publication authority mismatch"):
                run_staged_portable_refresh(
                    postgres.psql_args, bundle, repository_name=config.repository_name,
                    root_path=f"graph:{config.id}", authority=mismatched_authority, portable_binding=binding,
                )

            # 10. Commit-unknown reconciliation: matching receipt transitions to published/eligible
            stage_id = stage_id_for_authority(authority)
            owner = authority.owner(summary.repository_id)
            handoff_receipt = RunPublicationReceipt(authority.receipt().attempt, authority.receipt().generations, binding)

            def _set_stage_commit_unknown() -> None:
                with psycopg.connect(make_conninfo(**params)) as conn:
                    conn.execute(
                        "UPDATE ingestion_stages SET state = 'commit_unknown', "
                        "merge_status = 'unknown', "
                        "publication_reconciliation_state = 'required', "
                        "cleanup_eligibility = 'blocked' WHERE stage_id = %s",
                        (stage_id,),
                    )
                    conn.commit()

            _set_stage_commit_unknown()
            matching_handoff = PublicationHandoff(MergeContext(stage_id, owner, summary.run_id), handoff_receipt).validate()
            assert reconcile_commit_unknown(psycopg.connect, params, matching_handoff, summary.repository_id) is True

            with psycopg.connect(make_conninfo(**params)) as connection:
                reconciled_row = _row(
                    connection,
                    "SELECT state, publication_reconciliation_state, cleanup_eligibility "
                    "FROM ingestion_stages WHERE stage_id = %s",
                    (stage_id,),
                )
                assert reconciled_row == ("published", "reconciled", "eligible")

            # 11. Commit-unknown reconciliation: conflicting candidate receipt quarantines stage
            _set_stage_commit_unknown()
            conflicting_binding = replace(binding, candidate_id="cand1:" + "0" * 64)
            conflicting_receipt = RunPublicationReceipt(
                authority.receipt().attempt, authority.receipt().generations, conflicting_binding,
            )
            conflicting_handoff = PublicationHandoff(
                MergeContext(stage_id, owner, summary.run_id), conflicting_receipt,
            ).validate()
            with pytest.raises(StorageSchemaError, match="staged publication receipt conflicts"):
                reconcile_commit_unknown(psycopg.connect, params, conflicting_handoff, summary.repository_id)

            with psycopg.connect(make_conninfo(**params)) as connection:
                quarantined_row = _row(
                    connection,
                    "SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility "
                    "FROM ingestion_stages WHERE stage_id = %s",
                    (stage_id,),
                )
                assert quarantined_row == ("quarantined", "unknown", "conflicting", "quarantined")


if __name__ == "__main__":
    import sys

    sys.exit("Direct execution unsupported: RepoMap integration tests require container sandbox admission via pytest")
