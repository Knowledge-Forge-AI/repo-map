"""Unit tests for the stable D9-B backup declaration versus current target qualification.

The stored policy binding identifies the source capability declaration only. Current
target qualification and replay bounds are independent restore inputs; the original,
unchanged manifest can be considered against a later qualified target.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from repomap_kg.runtime._backup_provenance import parse_toc_entries
from repomap_kg.runtime._backup_support import derive_manifest_support, evaluate_backup_restore_support
from repomap_kg.runtime._extension_restore_policy import DECLARATION_FORMAT, ExtensionReplayBounds, TrustedExtensionRestorePolicy
from repomap_kg.runtime._extension_restore_preflight import preflight_extension_v2_restore_set
from repomap_kg.runtime._extension_restore_qualification import TrustedArtifactQualification
from repomap_kg.runtime._extension_restore_template import BASELINE_CATALOGS, BASELINE_INDIRECT_CATALOGS
from repomap_kg.runtime.backup_records import LocalDbBackupError, RuntimeContainerMetadata
from repomap_kg.runtime.local import build_local_runtime_plan, setup_local_runtime
from repomap_test_support.d9_extension_policies import (
    DEFAULT_ARTIFACT_QUALIFICATION, DEFAULT_TEST_ENGINE_IMAGE_ID, DEFAULT_TEST_INSPECT_IMAGE,
    UNIT_VECTOR_CONTROL_SHA256, UNIT_VECTOR_LIBRARY_SHA256, UNIT_VECTOR_SCRIPT_SHA256, adr0077_pgvector_extension_policy,
)
from repomap_test_support.local_db_backup import default_baseline_server_provenance

LATER_IMAGE_ID = "sha256:" + "7" * 64
LATER_BASELINE = hashlib.sha256(b"later-target-template1").hexdigest()
RAW_TOC = b";\n6; 2615 16385 SCHEMA - repomap_vector repomap\n2; 3079 16387 EXTENSION - vector \n215; 1259 16500 TABLE public items repomap\n"


def _expanded(qual: TrustedArtifactQualification) -> TrustedArtifactQualification:
    """An independently supplied, later qualification admitting one more target."""
    return replace(
        qual,
        allowed_engine_image_ids=(*qual.allowed_engine_image_ids, LATER_IMAGE_ID),
        allowed_client_versions=(*qual.allowed_client_versions, "16.5"),
        allowed_server_versions=(*qual.allowed_server_versions, "16.5"),
        allowed_os_arch_abis=(*qual.allowed_os_arch_abis, "aarch64-unknown-linux-musl"),
        template_baselines=(*qual.template_baselines, (LATER_IMAGE_ID, LATER_BASELINE)),
    )


def test_declaration_binding_excludes_current_target_qualification_and_replay_bounds() -> None:
    policy = adr0077_pgvector_extension_policy()
    record = policy.policy_binding_record()
    assert set(record) == {"d1_baseline", "d3_policy", "policy_id", "declaration_format", "declaration_sha256"}
    assert record["declaration_format"] == DECLARATION_FORMAT and "policy_sha256" not in record
    canonical = json.dumps(policy.declaration_record(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert record["declaration_sha256"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert "artifact_qualification" not in policy.declaration_record() and "replay_bounds" not in policy.declaration_record()
    for operational in (
        replace(policy, artifact_qualification=_expanded(policy.artifact_qualification)),
        replace(policy, artifact_qualification=replace(DEFAULT_ARTIFACT_QUALIFICATION, template_baselines=((DEFAULT_TEST_ENGINE_IMAGE_ID, "0" * 64),))),
        replace(policy, artifact_qualification=replace(policy.artifact_qualification, allowed_registry_manifest_digests=("sha256:" + "8" * 64,))),
        replace(policy, replay_bounds=ExtensionReplayBounds(1.0, 1)),
    ):
        assert operational.policy_binding_record() == record, "target qualification and replay bounds are not declaration facts"
    [rule] = policy.extensions
    assert rule.optional_capability is not None
    semantic = [
        replace(policy, policy_id="adr0077-disposable-pgvector-v2"),
        replace(policy, extensions=(replace(rule, exact_versions=("0.8.7", "0.8.8")),)),
        replace(policy, extensions=(replace(rule, script_sha256="e" * 64),)),
        replace(policy, extensions=(replace(rule, library_sha256=None),)),
        replace(policy, extensions=(replace(rule, readiness_probe_sql="SELECT 2;"),)),
        replace(policy, extensions=(replace(rule, allowed_owners=("other_owner",)),)),
        replace(policy, extensions=(replace(rule, optional_capability=replace(rule.optional_capability, enrichment_reader_role="other_reader")),)),
    ]
    digests = {p.declaration_digest() for p in semantic}
    assert len(digests) == len(semantic) and policy.declaration_digest() not in digests, "every semantic rule change changes the declaration"


def _manifest(policy: TrustedExtensionRestorePolicy, dump_bytes: bytes = b"PGDMP-fake") -> dict[str, Any]:
    srv: dict[str, Any] = default_baseline_server_provenance()
    srv["client_identities"] = {"pg_dump_version": "pg_dump (PostgreSQL) 16.4", "pg_restore_version": "pg_restore (PostgreSQL) 16.4", "psql_version": "unused"}
    ext = {"extcondition": [], "extconfig_tables": [], "prerequisite_extensions": [], "owner": "repomap", "trusted": True}
    cat = {
        "creation_semantics": {"datcollate": "C", "datcollversion": None, "datctype": "C", "daticulocale": None, "datlocprovider": "c", "encoding": "UTF8", "template": "unknown"},
        "database_role": "graph", "extension_config_tables": [], "extension_dependency_summary": {"by_class": {}, "edge_count": 0, "edges": []},
        "installed_extensions": [
            {**ext, "baseline_origin": "template_baseline", "declaration_identity": "d1:baseline:plpgsql", "experimental_context": "none",
             "is_baseline": True, "name": "plpgsql", "ownership_classification": "required", "relocatable": False, "schema": "pg_catalog", "version": "1.0"},
            {**ext, "baseline_origin": "non_baseline", "declaration_identity": "adr0077:vector", "experimental_context": "adr0077-disposable-pgvector",
             "is_baseline": False, "name": "vector", "ownership_classification": "unclassified", "relocatable": True, "schema": "repomap_vector", "version": "0.8.7"},
        ],
        "non_system_schemas": [{"name": "public", "owner": "repomap"}, {"name": "repomap_vector", "owner": "repomap"}],
    }
    support = derive_manifest_support({"repomap": cat}, before_after_fingerprint_matched=True, extension_restore_policy=policy, server_provenance=srv)
    assert support.restore_supported is True, support.restore_blockers
    sha = hashlib.sha256(dump_bytes).hexdigest()
    return {
        "artifact_provenance": {
            "archive_bindings": [{"database": "repomap", "dump_file": "dump.pgcustom", "sha256": sha, "size_bytes": len(dump_bytes),
                                  "toc_sha256": parse_toc_entries(RAW_TOC, database="repomap").toc_sha256}],
            "container_image": DEFAULT_TEST_INSPECT_IMAGE, "container_image_id": DEFAULT_TEST_ENGINE_IMAGE_ID, "policy_binding": policy.policy_binding_record(),
        },
        "backup_format_version": 2, "database": "repomap", "database_catalogs": {"repomap": cat}, "databases": ["repomap"],
        "dump_files": [{"name": "dump.pgcustom", "sha256": sha, "size_bytes": len(dump_bytes)}],
        "quiescence": {"before_after_fingerprint_matched": True, "maintenance_window_held": True, "maintenance_window_mode": "advisory"},
        "restore_blockers": [], "restore_protocol": support.restore_protocol, "restore_supported": True, "server_provenance": srv,
    }


def test_original_manifest_is_evaluated_against_current_independent_qualification() -> None:
    policy = adr0077_pgvector_extension_policy()
    manifest = _manifest(policy)
    frozen = json.dumps(manifest, sort_keys=True)
    later = replace(policy, artifact_qualification=_expanded(policy.artifact_qualification))
    evaluation = evaluate_backup_restore_support(manifest, extension_restore_policy=later)
    assert evaluation.restore_supported is True and evaluation.restore_blockers == (), evaluation.restore_blockers
    assert json.dumps(manifest, sort_keys=True) == frozen, "the original manifest is neither rewritten nor migrated"

    [rule] = policy.extensions
    changed = replace(later, extensions=(replace(rule, exact_versions=("0.8.7", "0.8.8")),))
    assert "extension-policy-binding-mismatch" in evaluate_backup_restore_support(manifest, extension_restore_policy=changed).restore_blockers
    for binding in (
        {**policy.policy_binding_record(), "declaration_sha256": "0" * 64},
        {**policy.policy_binding_record(), "declaration_format": "repomap-extension-declaration-v0"},
        {**policy.policy_binding_record(), "artifact_qualification": "minted-from-manifest"},
        {k: v for k, v in policy.policy_binding_record().items() if k != "declaration_format"},
        {"d1_baseline": "plpgsql@pg_catalog", "d3_policy": "allowlist-required", "policy_id": policy.policy_id, "policy_sha256": "a" * 64},
    ):
        tampered = deepcopy(manifest)
        tampered["artifact_provenance"]["policy_binding"] = binding
        blockers = evaluate_backup_restore_support(tampered, extension_restore_policy=later).restore_blockers
        assert "extension-policy-binding-mismatch" in blockers, f"binding {binding!r} must refuse, never migrate"
    source_fact = deepcopy(manifest)
    source_fact["server_provenance"]["server_version"] = "16.9"
    assert "extension-target-incompatible" in evaluate_backup_restore_support(source_fact, extension_restore_policy=later).restore_blockers
    narrowed = replace(later, artifact_qualification=replace(later.artifact_qualification, allowed_client_versions=("16.5",)))
    assert "extension-target-incompatible" in evaluate_backup_restore_support(manifest, extension_restore_policy=narrowed).restore_blockers, \
        "source client facts are checked against current qualification"


def _role(name: str, **overrides: Any) -> dict[str, Any]:
    base = {"rolname": name, "rolcanlogin": True, "rolsuper": False, "rolcreatedb": False, "rolcreaterole": False, "rolinherit": False,
            "rolreplication": False, "rolbypassrls": False, "owned_objects_count": 0, "member_of_count": 0, "members_count": 0}
    return {**base, **overrides}


def test_preflight_admits_later_qualified_target_for_unchanged_backup_and_refuses_unqualified(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    setup_local_runtime(home)
    (home / "runtime").chmod(0o700)
    plan = build_local_runtime_plan(home)
    plan.env_file.chmod(0o600)
    policy = adr0077_pgvector_extension_policy()
    dump_path = tmp_path / "dump.pgcustom"
    dump_path.write_bytes(b"PGDMP-fake")
    manifest = _manifest(policy)
    target_srv = {**deepcopy(manifest["server_provenance"]), "system_identifier": "7002"}
    target_srv.pop("client_identities")
    live = {
        "available_extension_versions": [{"name": "vector", "relocatable": True, "requires": [], "schema": None, "superuser": True, "trusted": False, "version": "0.8.7"}],
        "current_role": {"name": "repomap", "rolcreatedb": True, "rolsuper": True}, "existing_databases": ["postgres"],
        "roles": [_role("repomap", rolsuper=True, rolcreatedb=True, rolinherit=True), _role("candidate_fixture_reader"), _role("candidate_fixture_enrichment")],
        "server_provenance": target_srv,
    }
    env: dict[str, Any] = {"image": LATER_IMAGE_ID, "baseline": LATER_BASELINE, "psql": "psql (PostgreSQL) 16.4"}
    catalogs = sorted(set(BASELINE_CATALOGS) | BASELINE_INDIRECT_CATALOGS)
    creates: list[str] = []

    def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        joined = " ".join(str(c) for c in cmd)
        creates.extend(c for c in cmd if "CREATE DATABASE" in str(c))
        if cmd[1:2] == ["inspect"]:
            item = {"Id": "cid-later", "Image": env["image"], "Config": {"Image": "later:tag", "Labels": plan.identity.labels("postgres")}, "State": {"Running": True}}
            out: Any = json.dumps([item])
        elif "--version" in joined:
            out = (env["psql"] if "psql" in joined else "pg_restore (PostgreSQL) 16.4" if "pg_restore" in joined else "pg_dump (PostgreSQL) 16.4") + "\n"
        elif "repomap_d9b_target_preflight" in joined:
            out = json.dumps(live)
        elif "'datistemplate', d.datistemplate" in joined:
            out = json.dumps({"datname": "template1", "encoding": "UTF8", "datcollate": "C", "datctype": "C", "datlocprovider": "c",
                              "daticulocale": None, "datcollversion": None, "datistemplate": True, "datallowconn": True})
        elif "repomap_d9b_template_baseline" in joined:
            out = json.dumps({"rows": 1, "sha256": env["baseline"], "catalogs": catalogs})
        elif "pg_config --sharedir" in joined:
            out = f"{UNIT_VECTOR_CONTROL_SHA256}:{UNIT_VECTOR_SCRIPT_SHA256}:{UNIT_VECTOR_LIBRARY_SHA256}\n"
        elif "pg_restore" in joined and "-l" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=RAW_TOC, stderr=b"")
        else:
            out = ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out if kwargs.get("text") else out.encode("utf-8"), stderr="" if kwargs.get("text") else b"")

    container = RuntimeContainerMetadata("caller-supplied", "ignored", None, {}, None)

    def preflight(current: TrustedExtensionRestorePolicy) -> Any:
        return preflight_extension_v2_restore_set(plan, manifest, databases=("repomap",), dumps={"repomap": dump_path}, container=container,
                                                  command_runner=runner, policy=current, require_quiescence=False, coordinated=False)

    def refused(current: TrustedExtensionRestorePolicy, code: str) -> None:
        with pytest.raises(LocalDbBackupError) as exc:
            preflight(current)
        assert exc.value.diagnostics[0].code == code, [d.code for d in exc.value.diagnostics]

    refused(policy, "restore-target-artifact-unqualified")
    later = replace(policy, artifact_qualification=_expanded(policy.artifact_qualification), replay_bounds=ExtensionReplayBounds(30.0, 4096))
    ok = preflight(later)
    assert ok.engine_image_id == LATER_IMAGE_ID and ok.template_baseline_sha256 == LATER_BASELINE and ok.container.container_id == "cid-later"
    no_baseline = replace(later, artifact_qualification=replace(later.artifact_qualification, template_baselines=policy.artifact_qualification.template_baselines))
    refused(no_baseline, "restore-template-baseline-unqualified")
    no_source = replace(later, artifact_qualification=replace(
        later.artifact_qualification, allowed_engine_image_ids=(LATER_IMAGE_ID,), template_baselines=((LATER_IMAGE_ID, LATER_BASELINE),)))
    refused(no_source, "restore-target-artifact-unqualified")
    [rule] = policy.extensions
    refused(replace(later, extensions=(replace(rule, declaration_identity="adr0077:vector-v2"),)), "backup-extension-restore-unsupported")
    env["psql"] = "psql (PostgreSQL) 16.6"
    refused(later, "restore-target-incompatible")
    env["psql"], env["baseline"] = "psql (PostgreSQL) 16.4", "f" * 64
    refused(later, "restore-template-baseline-mismatch")
    assert creates == [], "every refusal happens before any CREATE DATABASE"
