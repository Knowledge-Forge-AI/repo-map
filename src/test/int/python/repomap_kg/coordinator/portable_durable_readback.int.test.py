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
import re

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
from repomap_test_support.portable_worker_scenarios import (
    PORTABLE_SUCCESS_CORPORA, coordinator_test_limits, portable_corpus_dependencies,
)
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres


@pytest.mark.parametrize("corpus,curated_fixture_paths,expected_kinds", PORTABLE_SUCCESS_CORPORA,
                         ids=[case[0] for case in PORTABLE_SUCCESS_CORPORA])
def test_worker_produced_portable_bundle_durable_publication_readback_and_reconciliation(
    corpus: str, curated_fixture_paths: tuple[str, ...], expected_kinds: tuple[str, ...],
) -> None:
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
        for relative_path in curated_fixture_paths:
            destination = src_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fixtures / relative_path, destination)

        # Resolve valid local dependencies explicitly for AWK and PowerShell fixtures
        local_deps = portable_corpus_dependencies(corpus)
        for rel_dep, content in local_deps.items():
            dep_path = src_dir / rel_dep
            dep_path.parent.mkdir(parents=True, exist_ok=True)
            dep_path.write_text(content, encoding="utf-8")

        expected_source_paths = tuple(sorted(("service.py", *curated_fixture_paths, *local_deps)))
        actual_source_paths = tuple(
            sorted(path.relative_to(src_dir).as_posix() for path in src_dir.rglob("*") if path.is_file())
        )
        assert actual_source_paths == expected_source_paths

        store_root = root / "artifact_store"
        store_root.mkdir(mode=0o700)
        store = FileSystemArtifactStore(store_root)

        config = create_single_source_graph_config(
            src_dir, graph_id="portable-durable", repository_name="repo-portable-durable",
        )
        manifest, manifest_ref, candidate_id = seal_configured_sources(
            config, store, extractor_generation="eg1:portable", canonicalizer_generation="kg1:portable",
        )
        assert store.verify(manifest_ref)

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
        evidence = repr({
            "corpus": corpus, "terminal": worker_result.terminal,
            "protocol_error": worker_result.protocol_error, "stderr": worker_result.stderr,
            "returncode": worker_result.returncode, "cleanup": worker_result.cleanup_error,
            "timeouts": (worker_result.process_timed_out, worker_result.heartbeat_timed_out,
                         worker_result.hello_timed_out),
        }).replace(str(root), "<test-root>")
        evidence = re.sub(r"FAKE_[A-Z0-9_]+", "<redacted-sentinel>", evidence)[:4000]
        assert worker_result.terminal.get("status") == "succeeded", evidence
        assert worker_result.terminal.get("error_category") is None, evidence
        assert worker_result.terminal.get("publication_state") == "not_started", evidence
        assert worker_result.terminal.get("latest_run_identity") is None, evidence
        assert worker_result.protocol_error is None, evidence
        assert worker_result.returncode == 0, evidence
        assert worker_result.cleanup_error is None, evidence
        assert not cap_path.exists(), evidence

        snapshot = worker_result.terminal.get("portable_snapshot")
        assert isinstance(snapshot, dict) and snapshot.get("outcome") == "completed", evidence

        bundle_ref = ArtifactReference.from_mapping(snapshot["bundle"])
        receipt_ref = ArtifactReference.from_mapping(snapshot["receipt"])
        assert store.verify(bundle_ref) and store.verify(receipt_ref), evidence

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
        assert receipt.bundle_id == bundle.bundle_id and receipt.snapshot_manifest_id == manifest.manifest_id
        assert bundle.candidate_id == candidate_id
        source_alias = config.effective_source_bindings[0].alias
        expected_published_file_paths = tuple(
            f"{source_alias}/{relative_path}" for relative_path in expected_source_paths
        )
        published_file_paths = tuple(sorted(str(row["path"]) for row in bundle.families["files"]))
        assert published_file_paths == expected_published_file_paths
        assert bundle.family_counts["files"] == len(expected_published_file_paths)
        assert bundle.family_counts["canonical_nodes"] > 0
        observation_kinds = {row["kind"] for row in bundle.families["raw_observations"]}
        assert set(expected_kinds) <= observation_kinds, (corpus, observation_kinds)

        serialized = repr(bundle.families)
        for relative in curated_fixture_paths:
            if "redaction" in relative or "commands-and-pipelines" in relative:
                sentinels = re.findall(r"FAKE_[A-Z0-9_]+", (fixtures / relative).read_text())
                assert sentinels and all(value not in serialized for value in sentinels), corpus
        if corpus == "false-positives":
            forbidden = {"awk.system_call", "awk.file_write", "awk.pipe_write", "zunit.test_case",
                         "zunit.mock", "bats.test_case", "shell.host_mutation"}
            assert not forbidden.intersection(observation_kinds), observation_kinds

        family_nodes = {"bash": "bash.script", "zsh": "zsh.script", "awk": "awk.program",
                        "bats": "bats.file", "zunit": "zunit.file"}
        powershell_nodes = {".ps1": "powershell.script", ".psm1": "powershell.module", ".psd1": "powershell.manifest"}
        representative_node_kinds = {
            f"{source_alias}/{path}": (powershell_nodes[Path(path).suffix] if path.startswith("powershell/")
                                     else family_nodes[path.split("/")[1]])
            for path in curated_fixture_paths
        }
        for fixture_path, expected_kind in representative_node_kinds.items():
            matching_nodes = [
                row for row in bundle.families["canonical_nodes"]
                if row["display_name"] == fixture_path and row["kind"] == expected_kind
            ]
            assert len(matching_nodes) == 1, (fixture_path, expected_kind)

        representative_edges = {
            (f"awk.program:file%3A{source_alias}%2Fshell%2Fawk%2Fincludes-and-extensions.awk", "includes", f"file:{source_alias}/shell/awk/lib/common.awk"),
            (f"awk.program:file%3A{source_alias}%2Fshell%2Fawk%2Fincludes-and-extensions.awk", "depends_on", "external:awk.extension:ordchr"),
            (f"powershell.manifest:file%3A{source_alias}%2Fpowershell%2FExample.Module.psd1", "references", f"file:{source_alias}/powershell/Example.Module.psm1"),
            (f"powershell.module:file%3A{source_alias}%2Fpowershell%2FExample.Module.psm1", "imports", f"file:{source_alias}/powershell/Example.Shared.psm1"),
            (f"powershell.script:file%3A{source_alias}%2Fpowershell%2Fbasic-script.ps1", "imports", f"file:{source_alias}/powershell/Example.Module.psm1"),
            (f"powershell.script:file%3A{source_alias}%2Fpowershell%2Fbasic-script.ps1", "sources", f"file:{source_alias}/powershell/helpers/Example.Shared.ps1"),
        }
        published_edges = {(r["source_canonical_key"], r["edge_kind"], r["target_canonical_key"]) for r in bundle.families["canonical_edges"]}
        if corpus == "core":
            assert representative_edges.issubset(published_edges)
        assert list(ws.iterdir()) == [], evidence
        assert list(priv_dir.iterdir()) == [], evidence

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
            p_rec = published.receipt.portable
            assert p_rec is not None and p_rec.publication_bundle_id == bundle.bundle_id
            assert p_rec.extraction_receipt_id == receipt.receipt_id and p_rec.candidate_id == bundle.candidate_id
            assert p_rec.snapshot_manifest_id == bundle.snapshot_manifest_id

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
                assert _row(
                    connection,
                    "SELECT job_id, attempt, last_run_id, singleton_fencing_epoch, graph_lease_fencing_epoch "
                    "FROM graph_publication_authority WHERE repository_id = %s",
                    (summary.repository_id,),
                ) == (job_id, attempt, summary.run_id, 1, 1)
                assert _row(
                    connection,
                    "SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility "
                    "FROM ingestion_stages WHERE stage_id = %s",
                    (stage_id_for_authority(authority),),
                ) == ("published", "committed", "reconciled", "eligible")

                for family in PUBLICATION_FAMILIES:
                    if family in ("canonical_evidence", "raw_observations"):
                        query = f"SELECT count(*) FROM {family} WHERE run_id = %s"
                    elif family in ("canonical_node_evidence", "canonical_edge_evidence"):
                        query = f"SELECT count(*) FROM {family} l JOIN canonical_evidence e ON e.id = l.canonical_evidence_id WHERE e.run_id = %s"
                    else:
                        query = f"SELECT count(*) FROM {family} WHERE last_seen_run_id = %s"
                    assert _row(connection, query, (summary.run_id,))[0] == bundle.family_counts[family]

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

            # 10. Commit-unknown reconciliation: matching transitions to published, conflict to quarantined
            stage_id = stage_id_for_authority(authority)
            owner = authority.owner(summary.repository_id)
            handoff_receipt = RunPublicationReceipt(authority.receipt().attempt, authority.receipt().generations, binding)

            def _set_stage_commit_unknown() -> None:
                with psycopg.connect(make_conninfo(**params)) as conn:
                    conn.execute(
                        "UPDATE ingestion_stages SET state = 'commit_unknown', merge_status = 'unknown', "
                        "publication_reconciliation_state = 'required', cleanup_eligibility = 'blocked' "
                        "WHERE stage_id = %s",
                        (stage_id,),
                    )
                    conn.commit()

            def _stage_state(conn: psycopg.Connection) -> tuple[object, ...]:
                return _row(
                    conn,
                    "SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility "
                    "FROM ingestion_stages WHERE stage_id = %s",
                    (stage_id,),
                )

            _set_stage_commit_unknown()
            matching_handoff = PublicationHandoff(MergeContext(stage_id, owner, summary.run_id), handoff_receipt).validate()
            assert reconcile_commit_unknown(psycopg.connect, params, matching_handoff, summary.repository_id) is True
            with psycopg.connect(make_conninfo(**params)) as conn:
                assert _stage_state(conn) == ("published", "committed", "reconciled", "eligible")

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
            with psycopg.connect(make_conninfo(**params)) as conn:
                assert _stage_state(conn) == ("quarantined", "unknown", "conflicting", "quarantined")


if __name__ == "__main__":
    import sys

    sys.exit("Direct execution unsupported: RepoMap integration tests require container sandbox admission via pytest")
