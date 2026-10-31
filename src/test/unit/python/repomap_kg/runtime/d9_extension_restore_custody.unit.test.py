"""Unit tests for D9-B held lifecycle custody orchestration and whole-set target preflight refusals."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from common_lore_index.runtime import _extension_restore_custody as custody_mod
from common_lore_index.runtime import _extension_restore_preflight as preflight_mod
from common_lore_index.runtime._backup_provenance import parse_toc_entries
from common_lore_index.runtime._backup_support import derive_manifest_support
from common_lore_index.runtime._extension_restore_custody import DatabaseCreationIntent, RestoreLifecycleAuthority, canonical_restore_authority
from common_lore_index.runtime._extension_restore_exec import ExecOutcome, active_exec_custody
from common_lore_index.runtime._extension_restore_preflight import (
    preflight_extension_v2_restore_set,
)
from common_lore_index.runtime._extension_restore_target import (
    observe_engine_identity,
)
from common_lore_index.runtime._extension_restore_template import BASELINE_CATALOGS, BASELINE_INDIRECT_CATALOGS
from common_lore_index.runtime.backup_records import LocalDbBackupError, RuntimeContainerMetadata
from common_lore_index.runtime.local import LocalRuntimeDiagnostic, build_local_runtime_plan, setup_local_runtime
from common_lore_index.runtime.maintenance import MAINTENANCE_LOCK_KEY, held_maintenance_custody_for
from repomap_test_support.d9_extension_policies import (
    DEFAULT_TEST_ENGINE_IMAGE_ID, DEFAULT_TEST_INSPECT_IMAGE, UNIT_TEMPLATE_BASELINE, UNIT_VECTOR_CONTROL_SHA256,
    UNIT_VECTOR_LIBRARY_SHA256, UNIT_VECTOR_SCRIPT_SHA256, adr0077_pgvector_extension_policy,
)
from repomap_test_support.local_db_backup import default_baseline_server_provenance

_CATALOGS = sorted(set(BASELINE_CATALOGS) | BASELINE_INDIRECT_CATALOGS)
_CONTAINER = RuntimeContainerMetadata("caller-supplied", "ignored", None, {}, None)


class _Result:
    def __init__(self, row: Any) -> None:
        self._row = row

    def fetchone(self) -> Any:
        return self._row


class _FakeConn:
    """Records statements; answers identity and baseline queries for one database."""

    def __init__(self, db: str, log: list[tuple[str, str]], state: dict[str, Any]) -> None:
        self.db, self.log, self.state, self.closed = db, log, state, False

    def execute(self, statement: Any, params: Any = None) -> _Result:
        text = statement if isinstance(statement, str) else statement.as_string(None) if hasattr(statement, "as_string") else str(statement)
        self.log.append((self.db, text if params is None else f"{text} % {params!r}"))
        if "pg_locks" in text:
            return _Result((self.state["oid"], self.state.get("stamp", ""), self.state["sysid"], self.state.get("locked", True)))
        if "repomap_d9b_template_baseline" in text:
            return _Result((json.dumps({"rows": 1, "sha256": self.state["baseline"], "catalogs": _CATALOGS}),))
        if text.startswith("COMMENT ON DATABASE") and "IS NULL" not in text:
            self.state["stamp"] = text.split(" IS ", 1)[1].strip("'")
        return _Result(None)

    @contextmanager
    def cursor(self) -> Iterator[Any]:
        conn = self

        class _Cur:
            def execute(self, sql: str, params: Any = None) -> None:
                conn.log.append((conn.db, f"{sql} % {params!r}"))

        yield _Cur()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.log.append((self.db, "BEGIN"))
        yield
        self.log.append((self.db, "COMMIT"))

    def close(self) -> None:
        self.closed = True


def _plan(tmp_path: Path) -> Any:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    setup_local_runtime(home)
    (home / "runtime").chmod(0o700)
    plan = build_local_runtime_plan(home)
    plan.env_file.chmod(0o600)
    return plan


def test_authority_holds_canonical_key_on_maintenance_and_each_created_target(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    log: list[tuple[str, str]] = []
    state: dict[str, Any] = {"oid": 16400, "sysid": "7001", "baseline": UNIT_TEMPLATE_BASELINE}
    conns: dict[str, _FakeConn] = {}

    def connect(db: str) -> _FakeConn:
        conns[db] = _FakeConn(db, log, state)
        return conns[db]

    intent = DatabaseCreationIntent("g1", "tok-0", "created_unheld", expected_system_identifier="7001")
    with RestoreLifecycleAuthority(plan, connect, namespace="runtime-endpoint:test") as authority:
        lock = f"SELECT pg_advisory_lock(%s) % ({MAINTENANCE_LOCK_KEY},)"
        assert (plan.maintenance_database, lock) in log, "the canonical key is held on the maintenance database"
        assert held_maintenance_custody_for("g1", authority_namespace="runtime-endpoint:test") is None, "no custody before the target is locked"
        authority.hold_target(intent, control=False)
        assert ("g1", lock) in log, "the canonical key is held on the created target itself"
        assert held_maintenance_custody_for("g1", authority_namespace="runtime-endpoint:test") is not None
        assert intent.expected_oid == 16400 and state["stamp"] == "repomap-restore-invocation:tok-0"
        authority.verify_baseline(intent, UNIT_TEMPLATE_BASELINE)
        assert authority.verify(intent) is True
        state["locked"] = False
        assert authority.verify(intent) is False, "a lost target lock voids custody"
        state["locked"] = True
        state["oid"] = 99999
        assert authority.verify(intent) is False, "a replaced OID voids custody"
        state["oid"] = 16400
        authority.finalize([intent])
        assert (plan.maintenance_database, 'COMMENT ON DATABASE "g1" IS NULL') in log
        with pytest.raises(LocalDbBackupError) as base_exc:
            authority.verify_baseline(intent, "0" * 64)
        assert base_exc.value.diagnostics[0].code == "restore-template-baseline-mismatch"
    assert conns["g1"].closed and conns[plan.maintenance_database].closed
    assert held_maintenance_custody_for("g1", authority_namespace="runtime-endpoint:test") is None

    stamped = {"oid": 5, "sysid": "7001", "stamp": "foreign", "baseline": UNIT_TEMPLATE_BASELINE}
    with RestoreLifecycleAuthority(plan, lambda db: _FakeConn(db, [], stamped), namespace="ns") as authority:
        with pytest.raises(LocalDbBackupError) as stamp_exc:
            authority.hold_target(DatabaseCreationIntent("g2", "tok", expected_system_identifier="7001"), control=False)
        assert stamp_exc.value.diagnostics[0].code == "restore-target-ownership-mismatch"


def test_authority_refuses_without_real_endpoint_or_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(tmp_path)

    def no_endpoint(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("endpoint unresolved")

    monkeypatch.setattr(custody_mod, "execution_postgres", no_endpoint)
    with pytest.raises(LocalDbBackupError) as ep_exc:
        canonical_restore_authority(plan)
    assert ep_exc.value.diagnostics[0].code == "backup-maintenance-window-unavailable"

    def refused(db: str) -> Any:
        raise OSError("connection refused")

    with pytest.raises(LocalDbBackupError) as conn_exc:
        with RestoreLifecycleAuthority(plan, refused, namespace="ns"):
            raise AssertionError("no window may be bound without a held lock")
    assert conn_exc.value.diagnostics[0].code == "backup-maintenance-window-unavailable"


def _vector_catalog() -> dict[str, Any]:
    ext = {"extcondition": [], "extconfig_tables": [], "prerequisite_extensions": [], "owner": "repomap"}
    return {
        "creation_semantics": {"datcollate": "C", "datcollversion": None, "datctype": "C", "daticulocale": None, "datlocprovider": "c", "encoding": "UTF8", "template": "unknown"},
        "database_role": "graph", "extension_config_tables": [], "extension_dependency_summary": {"by_class": {}, "edge_count": 0, "edges": []},
        "installed_extensions": [
            {**ext, "baseline_origin": "template_baseline", "declaration_identity": "d1:baseline:plpgsql", "experimental_context": "none", "is_baseline": True,
             "name": "plpgsql", "ownership_classification": "required", "relocatable": False, "schema": "pg_catalog", "trusted": True, "version": "1.0"},
            {**ext, "baseline_origin": "non_baseline", "declaration_identity": "adr0077:vector", "experimental_context": "adr0077-disposable-pgvector",
             "is_baseline": False, "name": "vector", "ownership_classification": "unclassified", "relocatable": True, "schema": "repomap_vector", "trusted": True, "version": "0.8.7"},
        ],
        "non_system_schemas": [{"name": "public", "owner": "repomap"}, {"name": "repomap_vector", "owner": "repomap"}],
    }


def _role(name: str, **overrides: Any) -> dict[str, Any]:
    base = {"rolname": name, "rolcanlogin": True, "rolsuper": False, "rolcreatedb": False, "rolcreaterole": False, "rolinherit": False,
            "rolreplication": False, "rolbypassrls": False, "owned_objects_count": 0, "member_of_count": 0, "members_count": 0}
    return {**base, **overrides}


def test_preflight_refuses_before_any_creation(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    policy = adr0077_pgvector_extension_policy()
    raw_toc = b";\n6; 2615 16385 SCHEMA - repomap_vector repomap\n2; 3079 16387 EXTENSION - vector \n215; 1259 16500 TABLE public items repomap\n"
    dump_path, dump_bytes = tmp_path / "dump.pgcustom", b"PGDMP-fake-custom-archive"
    dump_path.write_bytes(dump_bytes)
    srv: dict[str, Any] = default_baseline_server_provenance()
    srv["client_identities"] = {"pg_dump_version": "pg_dump (PostgreSQL) 16.4", "pg_restore_version": "pg_restore (PostgreSQL) 16.4", "psql_version": "unused"}
    cat = _vector_catalog()
    support = derive_manifest_support({"repomap": cat}, before_after_fingerprint_matched=True, extension_restore_policy=policy, server_provenance=srv)
    assert support.restore_supported is True, f"an unknown source template is an observation, not a blocker: {support.restore_blockers}"
    sha = hashlib.sha256(dump_bytes).hexdigest()
    manifest: dict[str, Any] = {
        "artifact_provenance": {
            "archive_bindings": [{"database": "repomap", "dump_file": "dump.pgcustom", "sha256": sha, "size_bytes": len(dump_bytes), "toc_sha256": parse_toc_entries(raw_toc, database="repomap").toc_sha256}],
            "container_image": DEFAULT_TEST_INSPECT_IMAGE, "container_image_id": DEFAULT_TEST_ENGINE_IMAGE_ID, "policy_binding": policy.policy_binding_record(),
        },
        "backup_format_version": 2, "database": "repomap", "database_catalogs": {"repomap": cat}, "databases": ["repomap"],
        "dump_files": [{"name": "dump.pgcustom", "sha256": sha, "size_bytes": len(dump_bytes)}],
        "quiescence": {"before_after_fingerprint_matched": True, "maintenance_window_held": True, "maintenance_window_mode": "advisory"},
        "restore_blockers": [], "restore_protocol": support.restore_protocol, "restore_supported": True, "server_provenance": srv,
    }
    target_srv = {**deepcopy(srv), "system_identifier": "7002"}
    target_srv.pop("client_identities")
    live: dict[str, Any] = {
        "available_extension_versions": [{"name": "vector", "relocatable": True, "requires": [], "schema": None, "superuser": True, "trusted": False, "version": "0.8.7"}],
        "current_role": {"name": "repomap", "rolcreatedb": True, "rolsuper": True}, "existing_databases": ["postgres"],
        "roles": [_role("repomap", rolsuper=True, rolcreatedb=True, rolcreaterole=True, rolinherit=True), _role("candidate_fixture_reader"), _role("candidate_fixture_enrichment")],
        "server_provenance": target_srv,
    }
    env: dict[str, Any] = {
        "inspect": {"Id": "cid123", "Image": DEFAULT_TEST_ENGINE_IMAGE_ID, "Config": {"Image": DEFAULT_TEST_INSPECT_IMAGE, "Labels": plan.identity.labels("postgres")}, "State": {"Running": True}},
        "template": {"datname": "template1", "encoding": "UTF8", "datcollate": "C", "datctype": "C", "datlocprovider": "c", "daticulocale": None, "datcollversion": None, "datistemplate": True, "datallowconn": True},
        "baseline": UNIT_TEMPLATE_BASELINE, "artifact": f"{UNIT_VECTOR_CONTROL_SHA256}:{UNIT_VECTOR_SCRIPT_SHA256}:{UNIT_VECTOR_LIBRARY_SHA256}", "psql": "psql (PostgreSQL) 16.4",
    }
    creates: list[str] = []

    def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        joined = " ".join(str(c) for c in cmd)
        creates.extend(c for c in cmd if "CREATE DATABASE" in str(c))
        if cmd[1:2] == ["inspect"]:
            out: Any = json.dumps([env["inspect"]])
        elif "--version" in joined:
            out = (env["psql"] if "psql" in joined else "pg_restore (PostgreSQL) 16.4" if "pg_restore" in joined else "pg_dump (PostgreSQL) 16.4") + "\n"
        elif "repomap_d9b_target_preflight" in joined:
            out = json.dumps(live)
        elif "'datistemplate', d.datistemplate" in joined:
            out = json.dumps(env["template"])
        elif "repomap_d9b_template_baseline" in joined:
            out = json.dumps({"rows": 1, "sha256": env["baseline"], "catalogs": _CATALOGS})
        elif "pg_config --sharedir" in joined:
            out = env["artifact"] + "\n"
        elif "pg_restore" in joined and "-l" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=raw_toc, stderr=b"")
        else:
            out = ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out if kwargs.get("text") else out.encode("utf-8"), stderr=b"" if not kwargs.get("text") else "")

    def refused(code: str) -> None:
        with pytest.raises(LocalDbBackupError) as exc:
            preflight_extension_v2_restore_set(plan, manifest, databases=("repomap",), dumps={"repomap": dump_path}, container=_CONTAINER, command_runner=runner,
                                               policy=policy, require_quiescence=False, coordinated=False)
        assert exc.value.diagnostics[0].code == code, f"expected {code}, got {[d.code for d in exc.value.diagnostics]}"
        assert creates == [], "every refusal happens before any CREATE DATABASE"

    ok = preflight_extension_v2_restore_set(plan, manifest, databases=("repomap",), dumps={"repomap": dump_path}, container=_CONTAINER, command_runner=runner,
                                            policy=policy, require_quiescence=False, coordinated=False)
    assert ok.engine_image_id == DEFAULT_TEST_ENGINE_IMAGE_ID and ok.template_baseline_sha256 == UNIT_TEMPLATE_BASELINE
    assert ok.databases["repomap"].create_database_sql.startswith('CREATE DATABASE "repomap" WITH TEMPLATE template1 ')

    env["baseline"] = "f" * 64
    refused("restore-template-baseline-mismatch")
    env["baseline"] = UNIT_TEMPLATE_BASELINE
    env["template"]["datcollate"] = "en_US.utf8"
    refused("restore-creation-semantics-incompatible")
    env["template"]["datcollate"] = "C"
    env["inspect"]["Image"] = None
    refused("restore-target-artifact-unqualified")
    env["inspect"]["Image"] = "sha256:" + "0" * 64
    refused("restore-target-artifact-unqualified")
    env["inspect"]["Image"] = DEFAULT_TEST_ENGINE_IMAGE_ID
    env["psql"] = "unavailable"
    refused("restore-target-incompatible")
    env["psql"] = "psql (PostgreSQL) 16.5"
    refused("restore-target-incompatible")
    env["psql"] = "psql (PostgreSQL) 16.4"
    env["artifact"] = f"{UNIT_VECTOR_CONTROL_SHA256}:{'e' * 64}:{UNIT_VECTOR_LIBRARY_SHA256}"
    refused("restore-target-artifact-unqualified")
    env["artifact"] = f"{UNIT_VECTOR_CONTROL_SHA256}:{UNIT_VECTOR_SCRIPT_SHA256}:{UNIT_VECTOR_LIBRARY_SHA256}"
    for field, value in (("members_count", 1), ("member_of_count", 1), ("owned_objects_count", None), ("rolinherit", True)):
        live["roles"][2] = _role("candidate_fixture_enrichment", **{field: value})
        refused("restore-principal-privilege-invalid")
    del live["roles"][2]["members_count"]
    refused("restore-principal-privilege-invalid")
    live["roles"].pop()
    refused("restore-custom-principal-missing")
    live["roles"].append(_role("candidate_fixture_enrichment"))
    (plan.runtime_dir / ".restore-intents-stale").mkdir(mode=0o700)
    refused("restore-target-ownership-unknown")


def test_engine_identity_uses_content_id_and_observed_repo_digests_only(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    manifest_digest = "sha256:" + "d" * 64
    base = adr0077_pgvector_extension_policy()
    policy = replace(base, artifact_qualification=replace(base.artifact_qualification, allowed_registry_manifest_digests=(manifest_digest,)))
    state: dict[str, Any] = {"repo_digests": [f"postgres@{manifest_digest}"], "config_image": f"postgres@{manifest_digest}", "image": DEFAULT_TEST_ENGINE_IMAGE_ID}
    seen: list[list[str]] = []

    def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        seen.append(cmd)
        if cmd[1:3] == ["image", "inspect"]:
            assert cmd[-1] == DEFAULT_TEST_ENGINE_IMAGE_ID, "RepoDigests are read from the exact Engine content ID"
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(state["repo_digests"]).encode("utf-8"), stderr=b"")
        item = {"Id": "cid", "Image": state["image"], "Config": {"Image": state["config_image"], "Labels": plan.identity.labels("postgres")}, "State": {"Running": True}}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps([item]), stderr="")

    assert observe_engine_identity(plan, runner, policy, field="t").image_id == DEFAULT_TEST_ENGINE_IMAGE_ID
    for repo_digests in ([], ["postgres@sha256:" + "e" * 64], None):
        state["repo_digests"] = repo_digests
        with pytest.raises(LocalDbBackupError) as exc:
            observe_engine_identity(plan, runner, policy, field="t")
        assert exc.value.diagnostics[0].code == "restore-target-artifact-unqualified", "Config.Image text never substitutes for an observed RepoDigest"
    state.update(repo_digests=[f"postgres@{manifest_digest}"], image=None)
    with pytest.raises(LocalDbBackupError) as missing:
        observe_engine_identity(plan, runner, policy, field="t")
    assert missing.value.diagnostics[0].code == "restore-target-artifact-unqualified", "a missing Engine Image refuses; no Config.Image fallback"


def test_preflight_unknown_outcome_gets_a_durable_typed_record_that_refuses_later_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Orchestration seams only: the unknown outcome is injected into the bound preflight custody."""
    plan = _plan(tmp_path)
    policy = adr0077_pgvector_extension_policy()
    observed: list[str] = []
    swallowed = {"value": False}
    primary = LocalDbBackupError((LocalRuntimeDiagnostic("error", "backup-toc-inconsistent", "dump.pgcustom", "listing failed"),))

    def engine(*args: Any, **kwargs: Any) -> Any:
        observed.append("engine")
        return SimpleNamespace(container_id="e" * 64, image_id=DEFAULT_TEST_ENGINE_IMAGE_ID)

    def unsettled_listing(*args: Any, **kwargs: Any) -> Any:
        custody = active_exec_custody()
        assert custody is not None and custody.container_id == "e" * 64
        outcome = ExecOutcome("dump.pgcustom", "f" * 32, "retired", "mismatch", "none", "retained")
        outcome.descendants, outcome.control_path = "unknown", f"/tmp/repomap-ext-exec-{plan.identity.home_hash}-{'f' * 32}"
        custody.outcomes.append(outcome)
        if swallowed["value"]:
            return "a caller swallowed the failure"
        raise primary

    for name, value in (("require_backup_restore_supported", lambda *a, **k: None), ("read_role_secrets", lambda *a, **k: None),
                        ("observe_engine_identity", engine), ("_preflight_observed_target", unsettled_listing)):
        monkeypatch.setattr(preflight_mod, name, value)

    def preflight() -> Any:
        return preflight_extension_v2_restore_set(plan, {}, databases=("repomap",), dumps={}, container=_CONTAINER, command_runner=subprocess.run,
                                                  policy=policy, require_quiescence=False, coordinated=False)

    with pytest.raises(LocalDbBackupError) as first:
        preflight()
    assert first.value is primary, "the initiating error is preserved when the record is written"
    [record_dir] = [p for p in plan.runtime_dir.iterdir() if p.name.startswith(".restore-")]
    assert record_dir.name.startswith(".restore-exec-record-") and stat.S_IMODE(record_dir.stat().st_mode) == 0o700
    record_file = record_dir / "record.json"
    assert stat.S_IMODE(record_file.stat().st_mode) == 0o600
    record = json.loads(record_file.read_text(encoding="utf-8"))
    assert {k: record[k] for k in ("record_type", "phase", "container_id", "owned_targets")} == {
        "record_type": "repomap-extension-exec-record-v1", "phase": "preflight", "container_id": "e" * 64, "owned_targets": [],
    }, "command state is recorded without representing the maintenance database as an owned target"
    assert len(record["invocation"]) == 32 and [(c["label"], c["remote"], c["control_path"]) for c in record["exec_unknown"]] == [
        ("dump.pgcustom", "mismatch", f"/tmp/repomap-ext-exec-{plan.identity.home_hash}-{'f' * 32}")
    ]
    with pytest.raises(LocalDbBackupError) as refused:
        preflight()
    assert refused.value.diagnostics[0].code == "restore-exec-outcome-unknown" and observed == ["engine"], "refused before any container command"
    shutil.rmtree(record_dir)  # operator inspection and removal
    swallowed["value"] = True
    with pytest.raises(LocalDbBackupError) as unsettled:
        preflight()
    assert [d.code for d in unsettled.value.diagnostics] == ["restore-exec-outcome-unknown"], "an unsettled outcome never yields a preflight result"
    assert len([p for p in plan.runtime_dir.iterdir() if p.name.startswith(".restore-exec-record-")]) == 1
