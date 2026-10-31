"""Optional-row provenance and capability-role zero-ownership checks for D9-B.

Historical rebuild rows are data validated against their own run receipt; only rows
of the current accepted publication additionally need node/evidence binding.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from common_lore_index.runtime._extension_restore_native import run_bounded_ext_command
from common_lore_index.runtime.backup_commands import (
    CommandRunner,
    decode_process_output,
    planned_psql_command,
)
from common_lore_index.runtime.backup_records import LocalDbBackupError
from common_lore_index.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan
from common_lore_index.storage.authority import GraphRunId
from common_lore_index.storage.publication import (
    RunPublicationReceipt,
    publication_receipt_from_mapping,
)
from common_lore_index.storage.publication_readback import RunPublicationRecord
from common_lore_index.storage.semantic_candidates import (
    CandidatePublication,
    EmbeddingProfile,
)


def _err(code: str, field: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError((LocalRuntimeDiagnostic("error", code, field, message),))


def _lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _provenance_sql() -> str:
    receipt_cols = ", ".join(f"'{f}', g.{f}" for f in RunPublicationReceipt.field_names())
    return (
        "SELECT CASE WHEN to_regclass('repomap_enrichment.rebuilds') IS NULL OR to_regclass('repomap_enrichment.embeddings') IS NULL "
        "OR obj_description('repomap_enrichment'::regnamespace, 'pg_namespace') IS DISTINCT FROM 'repomap-enrichment-schema:1' THEN 'invalid' "
        "WHEN EXISTS (SELECT 1 FROM repomap_enrichment.embeddings e LEFT JOIN repomap_enrichment.rebuilds r ON r.rebuild_id = e.rebuild_id "
        "WHERE r.rebuild_id IS NULL) THEN 'invalid' ELSE coalesce((SELECT json_agg(json_build_object("
        "'rebuild', to_jsonb(r) - 'enrichment_principal', 'principal_ok', btrim(r.enrichment_principal) <> '', 'repository_known', repo.id IS NOT NULL, "
        f"'run', (SELECT json_build_object('run_id', g.id, 'status', g.status, 'repository_id', g.repository_id, {receipt_cols}) FROM public.runs g WHERE g.id = r.run_id), "
        "'repository_id', repo.id, 'current', r.run_id = (SELECT max(g2.id) FROM public.runs g2 WHERE g2.repository_id = repo.id AND g2.status = 'complete'), "
        "'embedding_count', (SELECT count(*) FROM repomap_enrichment.embeddings e WHERE e.rebuild_id = r.rebuild_id), "
        "'embeddings_consistent', NOT EXISTS (SELECT 1 FROM repomap_enrichment.embeddings e WHERE e.rebuild_id = r.rebuild_id AND (e.dimensions <> r.dimensions "
        "OR repomap_vector.vector_dims(e.embedding) <> r.dimensions OR e.input_digest !~ '^sha256:[0-9a-f]{64}$')), "
        "'evidence_bound', NOT EXISTS (SELECT 1 FROM repomap_enrichment.embeddings e WHERE e.rebuild_id = r.rebuild_id AND NOT EXISTS ("
        "SELECT 1 FROM public.canonical_nodes node JOIN public.canonical_node_evidence link ON link.canonical_node_id = node.id "
        "JOIN public.canonical_evidence ev ON ev.id = link.canonical_evidence_id WHERE node.repository_id = repo.id AND node.canonical_key = e.canonical_key "
        "AND node.graph_key_version = 1 AND node.last_seen_run_id = r.run_id AND ev.repository_id = repo.id AND ev.run_id = r.run_id "
        "AND ev.graph_key_version = 1 AND ev.metadata_json->>'binding_id' = e.source_binding_id AND ev.metadata_json->>'snapshot_id' = e.snapshot_id))"
        ") ORDER BY r.rebuild_id)::text FROM repomap_enrichment.rebuilds r LEFT JOIN public.repositories repo ON repo.repository_identity = r.repository_identity), '[]') END;"
    )


def _row_valid(row: Mapping[str, object]) -> bool:
    rebuild, run = row.get("rebuild"), row.get("run")
    if (
        not isinstance(rebuild, Mapping)
        or not isinstance(run, Mapping)
        or row.get("principal_ok") is not True
        or row.get("repository_known") is not True
    ):
        return False
    if (
        run.get("status") != "complete"
        or run.get("repository_id") != row.get("repository_id")
        or run.get("run_id") != rebuild.get("run_id")
    ):
        return False
    receipt = publication_receipt_from_mapping(run)
    if receipt is None or receipt.portable is None:
        return False
    publication = CandidatePublication(
        str(rebuild["repository_identity"]),
        RunPublicationRecord(GraphRunId(int(str(rebuild["run_id"]))), receipt),
    )
    profile = EmbeddingProfile(
        str(rebuild["model"]),
        str(rebuild["model_version"]),
        str(rebuild["generator"]),
        str(rebuild["generator_version"]),
        int(str(rebuild["dimensions"])),
        str(rebuild["representation_version"]),
        str(rebuild["normalization"]),
        str(rebuild["metric"]),
    )
    bound = dict(zip(receipt.generations.field_names(), receipt.generations.values(), strict=True))
    bound.update(
        publication_bundle_id=receipt.portable.publication_bundle_id,
        snapshot_manifest_id=receipt.portable.snapshot_manifest_id,
    )
    return (
        publication.receipt_identity == rebuild.get("receipt_identity")
        and profile.identity == rebuild.get("profile_identity")
        and all(str(value) == str(rebuild.get(key)) for key, value in bound.items())
        and rebuild.get("privacy_class") == "public"
        and row.get("embedding_count") == rebuild.get("row_count")
        and row.get("embeddings_consistent") is True
        and (row.get("current") is not True or row.get("evidence_bound") is True)
    )


def verify_optional_row_provenance(
    plan: LocalRuntimePlan, database: str, command_runner: CommandRunner
) -> int:
    """Validate every retained rebuild against its own canonical receipt; return the number of rows checked."""
    raw = decode_process_output(
        run_bounded_ext_command(
            plan,
            planned_psql_command(plan, database, "-X", "-tAc", _provenance_sql()),
            command_runner,
            field="optional row provenance check",
        )
    ).strip()
    try:
        rows = json.loads(raw) if raw != "invalid" else None
        if not isinstance(rows, list) or not all(
            isinstance(r, Mapping) and _row_valid(r) for r in rows
        ):
            raise ValueError("invalid optional row provenance")
    except (ValueError, KeyError, TypeError) as exc:
        raise _err(
            "restore-postcheck-provenance-invalid",
            database,
            "restored optional rows failed their own receipt, profile or publication binding",
        ) from exc
    return len(rows)


def verify_zero_ownership(
    plan: LocalRuntimePlan, database: str, roles: Sequence[str], command_runner: CommandRunner
) -> None:
    role_literals = ", ".join(_lit(r) for r in sorted(set(roles)))
    sql = f"SELECT count(*)::int FROM pg_shdepend s JOIN pg_roles r ON r.oid = s.refobjid WHERE s.refclassid = 'pg_authid'::regclass AND s.deptype = 'o' AND r.rolname IN ({role_literals});"
    out = decode_process_output(
        run_bounded_ext_command(
            plan,
            planned_psql_command(plan, database, "-X", "-tAc", sql),
            command_runner,
            field="capability role zero-ownership check",
        )
    ).strip()
    if out != "0":
        raise _err(
            "restore-principal-privilege-invalid",
            database,
            "capability role owns objects after restore",
        )
