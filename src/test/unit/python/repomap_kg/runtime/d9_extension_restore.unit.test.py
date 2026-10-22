"""Unit tests for D9-B extension_v2 policy, qualification, blocker evaluation, derived TOC, and creation SQL."""

from __future__ import annotations

from copy import deepcopy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.runtime._backup_observation import _normalize_database_catalog
from repomap_kg.runtime._backup_provenance import parse_toc_entries
from repomap_kg.runtime._backup_support import (
    derive_manifest_support, evaluate_backup_restore_support,
    require_backup_restore_supported, sanitize_public_manifest,
)
from repomap_kg.runtime._backup_provenance import catalog_observation_sql
from repomap_kg.runtime._extension_restore_policy import (
    CORE_ONLY_EXTENSION_RESTORE_POLICY, ExtensionReplayBounds, TrustedArtifactQualification, TrustedExtensionRestorePolicy,
    TrustedExtensionRule, TrustedOptionalCapabilityContract, project_policy_for_observation,
)
from repomap_kg.runtime._extension_restore_qualification import engine_image_content_id, registry_manifest_digest
from repomap_kg.runtime._extension_restore_grants import _privilege_sql, canonical_grant_projection, canonical_grant_statements
from repomap_kg.runtime._extension_restore_template import (
    BASELINE_CATALOGS, BASELINE_INDIRECT_CATALOGS, build_create_database_sql, parse_template_baseline, template_baseline_sql,
)
from repomap_kg.storage.semantic_candidate_import import candidate_schema_sql
from repomap_kg.runtime._extension_restore_toc import build_derived_toc_plan
from repomap_kg.runtime.backup_commands import planned_pg_restore_command
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.release_cluster import initialize_release_cluster
from repomap_test_support.d9_extension_policies import (
    DEFAULT_ARTIFACT_QUALIFICATION, DEFAULT_REPLAY_BOUNDS, DEFAULT_TEST_ENGINE_IMAGE_ID, UNIT_TEMPLATE_BASELINE,
    UNIT_VECTOR_CONTROL_SHA256, UNIT_VECTOR_SCRIPT_SHA256,
    adr0077_pgvector_extension_policy, synthetic_multilevel_extension_policy,
)


def _sample_server_provenance() -> dict[str, Any]:
    return {
        "client_identities": {
            "pg_dump_version": "pg_dump (PostgreSQL) 16.4",
            "pg_restore_version": "pg_restore (PostgreSQL) 16.4",
            "psql_version": "psql (PostgreSQL) 16.4",
        },
        "compile_abi": {
            "CatalogVersionNo": 202307071, "block_size": 8192, "float8_pass_by_value": True,
            "max_identifier_length": 63, "max_index_keys": 32, "segment_size": 131072,
            "toast_max_chunk_size": 1996, "wal_block_size": 8192,
        },
        "os_arch_abi": "x86_64-pc-linux-musl", "server_version": "16.4",
        "server_version_num": 160004, "shared_preload_libraries": [],
        "version_string": "PostgreSQL 16.4 on x86_64-pc-linux-musl",
    }


def _sample_vector_catalog() -> dict[str, Any]:
    return {
        "creation_semantics": {
            "datcollate": "C", "datcollversion": None, "datctype": "C",
            "daticulocale": None, "datlocprovider": "c", "encoding": "UTF8", "template": "unknown",
        },
        "database_role": "graph",
        "extension_config_tables": [],
        "extension_dependency_summary": {
            "by_class": {"pg_class": 1, "pg_type": 1}, "edge_count": 2,
            "edges": [
                {
                    "deptype": "n", "extension": "vector", "identity_portable": True,
                    "object_class": "pg_type", "object_identity": "repomap_enrichment.embeddings",
                    "object_schema": "repomap_enrichment",
                },
                {
                    "deptype": "n", "extension": "vector", "identity_portable": True,
                    "object_class": "pg_class", "object_identity": "repomap_enrichment.embeddings_hnsw_idx",
                    "object_schema": "repomap_enrichment",
                },
            ],
        },
        "installed_extensions": [
            {
                "baseline_origin": "template_baseline", "declaration_identity": "d1:baseline:plpgsql",
                "experimental_context": "none", "extcondition": [], "extconfig_tables": [],
                "is_baseline": True, "name": "plpgsql", "owner": "repomap",
                "ownership_classification": "required", "prerequisite_extensions": [],
                "relocatable": False, "schema": "pg_catalog", "trusted": True, "version": "1.0",
            },
            {
                "baseline_origin": "non_baseline", "declaration_identity": "adr0077:vector",
                "experimental_context": "adr0077-disposable-pgvector", "extcondition": [], "extconfig_tables": [],
                "is_baseline": False, "name": "vector", "owner": "repomap",
                "ownership_classification": "unclassified", "prerequisite_extensions": [],
                "relocatable": True, "schema": "repomap_vector", "trusted": True, "version": "0.8.7",
            },
        ],
        "non_system_schemas": [
            {"name": "public", "owner": "repomap"},
            {"name": "repomap_enrichment", "owner": "repomap"},
            {"name": "repomap_vector", "owner": "repomap"},
        ],
    }


def _sample_vector_manifest(policy: TrustedExtensionRestorePolicy) -> dict[str, Any]:
    cat, srv = _sample_vector_catalog(), _sample_server_provenance()
    quiescence = {"before_after_fingerprint_matched": True, "maintenance_window_held": True, "maintenance_window_mode": "advisory"}
    support = derive_manifest_support(
        {"repomap": cat}, before_after_fingerprint_matched=True, require_quiescence=True,
        quiescence=quiescence, extension_restore_policy=policy, server_provenance=srv,
    )
    return {
        "artifact_provenance": {
            "archive_bindings": [{
                "database": "repomap", "dump_file": "repomap.pgcustom",
                "sha256": "a" * 64, "size_bytes": 1024, "toc_sha256": "b" * 64,
            }],
            "container_image": "postgres:16-alpine",
            "container_image_id": DEFAULT_TEST_ENGINE_IMAGE_ID,
            "policy_binding": policy.policy_binding_record(),
        },
        "backup_format_version": 2, "backup_id": "test--all--20261021T000000Z",
        "database": None, "database_catalogs": {"repomap": cat}, "databases": ["repomap"],
        "dump_files": [{"name": "repomap.pgcustom", "sha256": "a" * 64, "size_bytes": 1024}],
        "quiescence": quiescence, "restore_blockers": list(support.restore_blockers),
        "restore_protocol": support.restore_protocol, "restore_supported": support.restore_supported,
        "server_provenance": srv,
    }


def test_policy_validation_and_projection_invariants() -> None:
    policy = adr0077_pgvector_extension_policy()
    assert policy.allow_extension_v2 is True and len(policy.declaration_digest()) == 64
    proj = project_policy_for_observation(policy, database_role="graph")
    assert proj is not None
    assert proj["vector"]["declaration_identity"] == "adr0077:vector"
    assert proj["vector"]["exact_versions"] == ("0.8.7",)
    assert project_policy_for_observation(policy, database_role="control") == {}
    assert project_policy_for_observation(CORE_ONLY_EXTENSION_RESTORE_POLICY, database_role="graph") is None

    with pytest.raises(ValueError, match="distinct reader and writer roles"):
        TrustedOptionalCapabilityContract(
            capability_id="bad", experimental_context="adr0077-disposable-pgvector",
            extension_schema="repomap_vector", enrichment_reader_role="same_role", enrichment_writer_role="same_role",
        )
    with pytest.raises(ValueError, match="invalid extension classification"):
        TrustedExtensionRule(
            name="vector", allowed_database_roles=("graph",), exact_versions=("0.8.7",),
            required_schema="repomap_vector", allowed_owners=("repomap",), declaration_identity="adr0077:vector",
            ownership_classification="required", experimental_context="adr0077-disposable-pgvector",
            allowed_dependent_schemas=("repomap_enrichment",),
            control_sha256=UNIT_VECTOR_CONTROL_SHA256, script_sha256=UNIT_VECTOR_SCRIPT_SHA256,
        )
    with pytest.raises(ValueError, match="control_sha256, script_sha256"):
        TrustedExtensionRule(
            name="vector", allowed_database_roles=("graph",), exact_versions=("0.8.7",),
            required_schema="repomap_vector", allowed_owners=("repomap",), declaration_identity="adr0077:vector",
            ownership_classification="unclassified", experimental_context="adr0077-disposable-pgvector",
            allowed_dependent_schemas=("repomap_enrichment",),
        )
    with pytest.raises(ValueError, match="explicit server versions, OS/arch ABIs, Engine image IDs, exact client versions"):
        TrustedExtensionRestorePolicy(
            policy_id="unqualified", allow_extension_v2=True, artifact_qualification=TrustedArtifactQualification(),
            extensions=policy.extensions, replay_bounds=DEFAULT_REPLAY_BOUNDS,
        )
    no_clients = TrustedArtifactQualification(
        allowed_server_versions=("16.4",), allowed_os_arch_abis=("x86_64-pc-linux-musl",), allowed_engine_image_ids=(DEFAULT_TEST_ENGINE_IMAGE_ID,),
        template_baselines=((DEFAULT_TEST_ENGINE_IMAGE_ID, UNIT_TEMPLATE_BASELINE),),
    )
    with pytest.raises(ValueError, match="exact client versions"):
        adr0077_pgvector_extension_policy(artifact_qualification=no_clients)
    with pytest.raises(ValueError, match="template1 baselines bound to admitted Engine image IDs"):
        adr0077_pgvector_extension_policy(artifact_qualification=replace(DEFAULT_ARTIFACT_QUALIFICATION, template_baselines=()))
    with pytest.raises(ValueError, match="explicit replay_bounds"):
        replace(policy, replay_bounds=None)
    with pytest.raises(ValueError, match="template0 cannot be logically observed"):
        replace(DEFAULT_ARTIFACT_QUALIFICATION, target_template="template0")
    with pytest.raises(ValueError, match="sha256:<64hex> digests"):
        replace(DEFAULT_ARTIFACT_QUALIFICATION, allowed_engine_image_ids=(f"postgres:16-alpine@{DEFAULT_TEST_ENGINE_IMAGE_ID}",))
    for bad_bounds in ((0.0, 1), (float("inf"), 1), (10.0, 0), (10.0, 65 * 1024 * 1024)):
        with pytest.raises(ValueError, match="replay"):
            ExtensionReplayBounds(*bad_bounds)
    assert replace(policy, replay_bounds=ExtensionReplayBounds(5.0, 10)).declaration_digest() == policy.declaration_digest(), "replay bounds are operational, not trust facts"
    assert engine_image_content_id(DEFAULT_TEST_ENGINE_IMAGE_ID) == DEFAULT_TEST_ENGINE_IMAGE_ID
    assert engine_image_content_id(f"postgres:16-alpine@{DEFAULT_TEST_ENGINE_IMAGE_ID}") is None, "a reference is never an Engine content ID"
    assert registry_manifest_digest(f"postgres@{DEFAULT_TEST_ENGINE_IMAGE_ID}") == DEFAULT_TEST_ENGINE_IMAGE_ID
    assert registry_manifest_digest(DEFAULT_TEST_ENGINE_IMAGE_ID) is None and registry_manifest_digest("postgres:16-alpine") is None
    with pytest.raises(ValueError, match="core-only policy cannot declare"):
        TrustedExtensionRestorePolicy(policy_id="bad-core", allow_extension_v2=False, extensions=policy.extensions)


def test_observation_projection_does_not_self_authorize_noncompliant_extension() -> None:
    policy = adr0077_pgvector_extension_policy()
    raw_cat = _sample_vector_catalog()
    raw_cat["creation_semantics"]["template"] = "unknown"
    raw_cat["installed_extensions"][1].update({
        "version": "0.7.0", "baseline_origin": "unavailable", "ownership_classification": "unclassified",
        "declaration_identity": "unavailable", "experimental_context": "unavailable",
    })
    proj = project_policy_for_observation(policy, database_role="graph")
    norm = _normalize_database_catalog(raw_cat, database="repomap", expected_role="graph", extension_policy=proj)
    creation = norm["creation_semantics"]
    assert isinstance(creation, dict) and creation["template"] == "unknown"
    installed_list = norm["installed_extensions"]
    assert isinstance(installed_list, list)
    vec_entry = next(e for e in installed_list if e["name"] == "vector")
    assert vec_entry["declaration_identity"] == "unavailable" and vec_entry["baseline_origin"] == "unavailable"


def test_manifest_support_core_only_vs_admitted_extension_v2() -> None:
    policy = adr0077_pgvector_extension_policy()
    manifest = _sample_vector_manifest(policy)
    assert manifest["restore_protocol"] == "extension_v2" and manifest["restore_supported"] is True

    core_eval = evaluate_backup_restore_support(manifest)
    assert core_eval.restore_supported is False
    assert "extension-restore-protocol-unimplemented" in core_eval.restore_blockers
    assert "extension-not-allowlisted" in core_eval.restore_blockers
    with pytest.raises(LocalDbBackupError) as exc_info:
        require_backup_restore_supported(manifest, database="repomap")
    codes = [d.code for d in exc_info.value.diagnostics]
    assert "backup-extension-restore-unsupported" in codes and "backup-restore-unsupported" in codes

    ext_eval = require_backup_restore_supported(
        manifest, database="repomap", require_quiescence=True, extension_restore_policy=policy
    )
    assert ext_eval.restore_protocol == "extension_v2" and ext_eval.restore_supported is True
    pub = sanitize_public_manifest(manifest, extension_restore_policy=policy)
    assert pub["restore_protocol"] == "extension_v2" and "database_catalogs" not in pub


def test_manifest_support_refuses_stale_policy_binding_and_catalog_violations() -> None:
    policy = adr0077_pgvector_extension_policy()
    manifest = _sample_vector_manifest(policy)

    other_policy = adr0077_pgvector_extension_policy(exact_versions=("0.8.7", "0.8.8"))
    stale_eval = evaluate_backup_restore_support(manifest, extension_restore_policy=other_policy)
    assert "extension-policy-binding-mismatch" in stale_eval.restore_blockers

    bad_ver = deepcopy(manifest)
    bad_ver["database_catalogs"]["repomap"]["installed_extensions"][1]["version"] = "0.7.0"
    assert "extension-version-not-qualified" in evaluate_backup_restore_support(bad_ver, extension_restore_policy=policy).restore_blockers

    bad_own = deepcopy(manifest)
    bad_own["database_catalogs"]["repomap"]["installed_extensions"][1]["owner"] = "rogue_owner"
    assert "extension-owner-unapproved" in evaluate_backup_restore_support(bad_own, extension_restore_policy=policy).restore_blockers

    bad_edge = deepcopy(manifest)
    bad_edge["database_catalogs"]["repomap"]["extension_dependency_summary"]["edges"][0]["object_schema"] = ""
    assert "extension-dependency-unsupported" in evaluate_backup_restore_support(bad_edge, extension_restore_policy=policy).restore_blockers

    bad_cls = deepcopy(manifest)
    bad_cls["database_catalogs"]["repomap"]["extension_dependency_summary"]["edges"][0]["object_class"] = "pg_event_trigger"
    assert "extension-dependency-unsupported" in evaluate_backup_restore_support(bad_cls, extension_restore_policy=policy).restore_blockers

    bad_cfg = deepcopy(manifest)
    bad_cfg["database_catalogs"]["repomap"]["installed_extensions"][1]["extconfig_tables"] = ["repomap_vector.cfg"]
    bad_cfg["database_catalogs"]["repomap"]["extension_config_tables"] = [{"extension": "vector", "table": "cfg"}]
    with pytest.raises(LocalDbBackupError) as cfg_exc:
        require_backup_restore_supported(bad_cfg, database="repomap", extension_restore_policy=policy)
    assert any(d.code == "backup-extension-config-unsupported" for d in cfg_exc.value.diagnostics)

    bad_srv = deepcopy(manifest)
    bad_srv["server_provenance"]["server_version_num"] = 150007
    assert "extension-target-incompatible" in evaluate_backup_restore_support(bad_srv, extension_restore_policy=policy).restore_blockers

    bad_restore = deepcopy(manifest)
    bad_restore["server_provenance"]["client_identities"]["pg_restore_version"] = "pg_restore (PostgreSQL) 15.1"
    assert "extension-target-incompatible" in evaluate_backup_restore_support(bad_restore, extension_restore_policy=policy).restore_blockers
    unused_dump = deepcopy(manifest)
    unused_dump["server_provenance"]["client_identities"]["pg_dump_version"] = "unused"
    assert "extension-target-incompatible" in evaluate_backup_restore_support(unused_dump, extension_restore_policy=policy).restore_blockers
    exact_client_pol = adr0077_pgvector_extension_policy(artifact_qualification=replace(DEFAULT_ARTIFACT_QUALIFICATION, allowed_client_versions=("16.5",)))
    assert "extension-target-incompatible" in evaluate_backup_restore_support(manifest, extension_restore_policy=exact_client_pol).restore_blockers

    missing_srv = deepcopy(manifest)
    missing_srv["server_provenance"] = None
    assert "extension-target-incompatible" in evaluate_backup_restore_support(missing_srv, extension_restore_policy=policy).restore_blockers

    for observed_template in ("unknown", "template1", "template0"):
        any_tpl = deepcopy(manifest)
        any_tpl["database_catalogs"]["repomap"]["creation_semantics"]["template"] = observed_template
        assert "database-creation-semantics-mismatch" not in evaluate_backup_restore_support(any_tpl, extension_restore_policy=policy).restore_blockers, "the historical source template is an observation, never a policy requirement"
    bad_cs = deepcopy(manifest)
    bad_cs["database_catalogs"]["repomap"]["creation_semantics"]["datcollate"] = ""
    assert "database-creation-semantics-mismatch" in evaluate_backup_restore_support(bad_cs, extension_restore_policy=policy).restore_blockers
    with pytest.raises(LocalDbBackupError) as cs_exc:
        require_backup_restore_supported(bad_cs, database="repomap", extension_restore_policy=policy)
    assert "restore-creation-semantics-incompatible" in [d.code for d in cs_exc.value.diagnostics]
    assert "'template', 'unknown'" in catalog_observation_sql("graph") and "template0" not in catalog_observation_sql("graph")

    multi_pol = synthetic_multilevel_extension_policy()
    bad_dep = deepcopy(manifest)
    bad_dep["database_catalogs"]["repomap"]["installed_extensions"][1] = {
        "baseline_origin": "non_baseline", "declaration_identity": "test:ext_beta",
        "experimental_context": "none", "extcondition": [], "extconfig_tables": [],
        "is_baseline": False, "name": "ext_beta", "owner": "repomap",
        "ownership_classification": "required", "prerequisite_extensions": ["ext_alpha"],
        "relocatable": False, "schema": "ext_beta_s", "trusted": False, "version": "1.0",
    }
    assert "extension-dependency-unsupported" in evaluate_backup_restore_support(bad_dep, extension_restore_policy=multi_pol).restore_blockers


def test_derived_toc_plan_exclusions_and_shared_schema_preservation() -> None:
    raw_toc = (
        b";\n; Archive created at 2026-10-21\n;\n"
        b"6; 2615 16385 SCHEMA - repomap_vector repomap\n"
        b"7; 2615 16386 SCHEMA - repomap_enrichment repomap\n"
        b"2; 3079 16387 EXTENSION - vector \n"
        b"4888; 0 0 COMMENT - EXTENSION vector \n"
        b"215; 1259 16500 TABLE repomap_enrichment rebuilds repomap\n"
        b"216; 1259 16510 TABLE repomap_enrichment embeddings repomap\n"
        b"4880; 0 16500 TABLE DATA repomap_enrichment rebuilds repomap\n"
        b"4881; 0 16510 TABLE DATA repomap_enrichment embeddings repomap\n"
        b"4730; 1259 16520 INDEX repomap_enrichment embeddings_hnsw_idx repomap\n"
    )
    cat = _sample_vector_catalog()
    toc_obs = parse_toc_entries(raw_toc, database="repomap")
    plan = build_derived_toc_plan(raw_toc, database="repomap", database_catalog=cat, expected_toc_sha256=toc_obs.toc_sha256)
    assert plan.original_toc_sha256 == toc_obs.toc_sha256
    assert plan.extension_comments == ("vector",)
    assert plan.selected_dump_ids == (7, 4888, 215, 216, 4880, 4881, 4730)
    assert {e["dump_id"]: e["reason"] for e in plan.excluded_entries} == {
        6: "precreated-extension-schema", 2: "preinstalled-extension",
    }
    raw_toc_shared = raw_toc + b"299; 1259 16999 TABLE repomap_vector custom_app_tbl repomap\n"
    shared_obs = parse_toc_entries(raw_toc_shared, database="repomap")
    shared_plan = build_derived_toc_plan(raw_toc_shared, database="repomap", database_catalog=cat, expected_toc_sha256=shared_obs.toc_sha256)
    assert 299 in shared_plan.selected_dump_ids and 6 not in shared_plan.selected_dump_ids

    raw_toc_bad_comment = raw_toc + b"4899; 0 0 COMMENT - EXTENSION unknown_ext \n"
    bad_comment_obs = parse_toc_entries(raw_toc_bad_comment, database="repomap")
    with pytest.raises(LocalDbBackupError) as bad_c_exc:
        build_derived_toc_plan(raw_toc_bad_comment, database="repomap", database_catalog=cat, expected_toc_sha256=bad_comment_obs.toc_sha256)
    assert bad_c_exc.value.diagnostics[0].code == "backup-toc-inconsistent"


def test_create_database_sql_pg_restore_flags_and_release_cluster_policy_forwarding(tmp_path: Path) -> None:
    template_row = {"datname": "template1", "encoding": "UTF8", "datcollate": "C", "datctype": "C", "datlocprovider": "c", "daticulocale": None, "datcollversion": None}
    cs = _sample_vector_catalog()["creation_semantics"]
    sql = build_create_database_sql("repomap", cs, template_row=template_row)
    assert sql == 'CREATE DATABASE "repomap" WITH TEMPLATE template1 ENCODING \'UTF8\' LOCALE_PROVIDER libc LC_COLLATE \'C\' LC_CTYPE \'C\';'
    for field, value in (("datcollate", "en_US.utf8"), ("encoding", "LATIN1"), ("datlocprovider", "i"), ("datcollversion", "2.36")):
        with pytest.raises(LocalDbBackupError) as cs_exc:
            build_create_database_sql("repomap", cs, template_row={**template_row, field: value})
        assert cs_exc.value.diagnostics[0].code == "restore-creation-semantics-incompatible", f"template1 {field} mismatch must refuse"
    icu_cs = {**cs, "datlocprovider": "i", "daticulocale": "und-x-icu", "datcollversion": "153.112"}
    icu_sql = build_create_database_sql("repomap", icu_cs, template_row={**template_row, "datlocprovider": "i", "daticulocale": "und-x-icu", "datcollversion": "153.112"})
    assert icu_sql.endswith("LOCALE_PROVIDER icu LC_COLLATE 'C' LC_CTYPE 'C' ICU_LOCALE 'und-x-icu';")

    baseline_sql = template_baseline_sql()
    assert all(f"pg_catalog.{c} t" in baseline_sql for c in BASELINE_CATALOGS) and "aclexplode(t.relacl)" in baseline_sql and "'relpages'" in baseline_sql
    catalogs = sorted(set(BASELINE_CATALOGS) | BASELINE_INDIRECT_CATALOGS)
    assert parse_template_baseline(json.dumps({"rows": 3, "sha256": UNIT_TEMPLATE_BASELINE, "catalogs": catalogs}), field="t") == UNIT_TEMPLATE_BASELINE
    for bad in ({"sha256": UNIT_TEMPLATE_BASELINE, "catalogs": [*catalogs, "pg_future_catalog"]}, {"sha256": UNIT_TEMPLATE_BASELINE, "catalogs": catalogs[1:]}, {"sha256": "x", "catalogs": catalogs}):
        with pytest.raises(LocalDbBackupError) as base_exc:
            parse_template_baseline(json.dumps(bad), field="t")
        assert base_exc.value.diagnostics[0].code == "restore-template-baseline-unqualified"

    statements = canonical_grant_statements("reader_r", "writer_w")
    canonical = " ".join(candidate_schema_sql(read_principal="reader_r", enrichment_principal="writer_w").split())
    assert all(stmt[:-1] in canonical for stmt in statements) and len(statements) == 10, "grants are the exact canonical statements"
    insert_cols, read_tables = canonical_grant_projection()
    assert "enrichment_principal" not in insert_cols and len(insert_cols) == 21 and len(read_tables) == 5
    opt = adr0077_pgvector_extension_policy().extensions[0].optional_capability
    assert opt is not None
    _sql, expect = _privilege_sql(opt, has_enrichment=True)
    assert expect["candidate_fixture_enrichment:insert:rebuilds.enrichment_principal"] is False
    assert expect["candidate_fixture_enrichment:update:rebuilds"] is False and expect["candidate_fixture_reader:select:embeddings"] is True

    from repomap_kg.runtime.local import build_local_runtime_plan, setup_local_runtime
    setup_local_runtime(tmp_path)
    rt_plan = build_local_runtime_plan(tmp_path)
    ext_cmd = planned_pg_restore_command(rt_plan, "repomap", exit_on_error=True, use_list_path="/tmp/private/derived.toc")
    assert "--exit-on-error" in ext_cmd and "--use-list=/tmp/private/derived.toc" in ext_cmd

    received_policies: list[Any] = []

    class _DummyOp:
        databases: tuple[str, ...] = ()
        expected_count = 1
        def database_exists(self, db: str) -> bool: return True
        def create_database(self, db: str) -> None: pass
        def schema_state(self, db: str) -> tuple[str, int]: return ("current", 1)
        def initialize_schema(self, db: str) -> None: pass
        def upgrade_schema(self, db: str, c: int) -> None: pass
        def reconcile_roles(self, db: str) -> None: pass
        def drop_created_database(self, db: str) -> None: pass

    def _custom_ctrl(home: str | Path, *, extension_restore_policy: Any = None) -> dict[str, object]:
        received_policies.append(extension_restore_policy)
        return {"database_created": False}

    pol = adr0077_pgvector_extension_policy(artifact_qualification=DEFAULT_ARTIFACT_QUALIFICATION)
    initialize_release_cluster(tmp_path, operator_factory=lambda _h: _DummyOp(), control_initializer=_custom_ctrl, extension_restore_policy=pol)
    assert received_policies == [pol]
