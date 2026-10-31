"""Containerized proof that an original D9-B backup restores onto a later qualified target.

The source is a core-image cluster and the target an independent optional-image cluster
with a different Engine image ID, carrying the same exact synthetic SQL extension files.
The original archive and manifest are never rewritten or re-dumped. Both admitted images
run the same PostgreSQL 16.14 server and clients, so no server/client version mismatch
is exercised or claimed here.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import hashlib
from pathlib import Path
import shutil
from typing import Any

import pytest

from common_lore_index.runtime._extension_restore_qualification import TrustedArtifactQualification
from common_lore_index.runtime.backup import dump_database, init_database_from_dump
from common_lore_index.runtime.backup_records import LocalDbBackupError
from repomap_test_support.d9_extension_policies import (
    installed_synthetic_extensions, probe_live_container_qualification, synthetic_multilevel_extension_policy,
)
from repomap_test_support.d9_extension_restore import (
    clean_template_reference, database_names, engine_container_id, owned_d9_postgres_cluster, seed_synthetic_graph,
)
from repomap_test_support.local_db_backup import connect_real_postgres as _connect
from repomap_test_support.postgres_harness import require_postgres_binaries
from repomap_test_support.test_scratch import short_test_directory

GRAPH = "d9b_rq_graph"


def _union(first: TrustedArtifactQualification, second: TrustedArtifactQualification) -> TrustedArtifactQualification:
    """A later, independently supplied qualification that also admits the second target."""
    return replace(
        first,
        allowed_server_versions=tuple(sorted({*first.allowed_server_versions, *second.allowed_server_versions})),
        allowed_client_majors=tuple(sorted({*first.allowed_client_majors, *second.allowed_client_majors})),
        allowed_client_versions=tuple(sorted({*first.allowed_client_versions, *second.allowed_client_versions})),
        allowed_os_arch_abis=tuple(sorted({*first.allowed_os_arch_abis, *second.allowed_os_arch_abis})),
        allowed_engine_image_ids=tuple(sorted({*first.allowed_engine_image_ids, *second.allowed_engine_image_ids})),
        template_baselines=tuple(sorted({*first.template_baselines, *second.template_baselines})),
    )


def _digests(directory: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.iterdir()) if p.is_file()}


def _refused(
    code: str, home: Path, backup: Path, runner: Any, policy: Any, postgres: Any, before: list[str], *, blocker: str | None = None
) -> None:
    with pytest.raises(LocalDbBackupError) as exc:
        init_database_from_dump(home, database=GRAPH, backup=backup, command_runner=runner, extension_restore_policy=policy)
    codes = [d.code for d in exc.value.diagnostics]
    assert codes and codes[0] == code, f"expected {code}, got {codes}"
    if blocker is not None:
        assert f"({blocker})" in exc.value.diagnostics[0].message, f"the refusal names exactly {blocker}: {exc.value.diagnostics}"
    assert database_names(postgres) == before, "refusal happens before any CREATE DATABASE"


@pytest.mark.requires_pgvector
def test_original_backup_restores_on_later_qualified_independent_engine_image(monkeypatch: pytest.MonkeyPatch) -> None:
    require_postgres_binaries()
    with short_test_directory("d9b-rq-", "home/repomap.rpl.toml") as directory:
        root = Path(directory)
        home, target_home = root / "home", root / "target_home"
        core_reference = clean_template_reference(root, profile="core")
        optional_reference = clean_template_reference(root)
        with owned_d9_postgres_cluster(home, graph_db=GRAPH, profile="core") as (identity, postgres, runner):
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", str(postgres.password))
            monkeypatch.setenv("POSTGRES_PASSWORD", str(postgres.password))
            with installed_synthetic_extensions("docker", identity.postgres_container, runner=runner):
                source_qual = probe_live_container_qualification(identity.postgres_container, user=postgres.user, template_baseline_sha256=core_reference)
                policy = synthetic_multilevel_extension_policy(owner=postgres.user, artifact_qualification=source_qual)
                seed_synthetic_graph(postgres, GRAPH)
                dump = dump_database(home, database=GRAPH, timestamp="20261021T070000Z", command_runner=runner, extension_restore_policy=policy)
                assert dump.restore_supported is True and dump.restore_blockers == (), f"blockers: {dump.restore_blockers}"
            source_container_id = engine_container_id(identity.postgres_container)
            with closing(_connect(postgres)) as s_adm:
                source_sysid = s_adm.execute("SELECT system_identifier::text FROM pg_control_system()").fetchone()

            with owned_d9_postgres_cluster(target_home, graph_db=GRAPH, password=str(postgres.password)) as (target_id, target_pg, target_runner):
                with installed_synthetic_extensions("docker", target_id.postgres_container, runner=target_runner):
                    target_qual = probe_live_container_qualification(target_id.postgres_container, user=target_pg.user, template_baseline_sha256=optional_reference)
                    assert set(target_qual.allowed_engine_image_ids).isdisjoint(source_qual.allowed_engine_image_ids), "independent Engine image IDs"
                    assert target_qual.allowed_server_versions == source_qual.allowed_server_versions, "identical bounded server versions; no mismatch is claimed"
                    assert engine_container_id(target_id.postgres_container) != source_container_id
                    with closing(_connect(target_pg)) as t_adm:
                        assert t_adm.execute("SELECT system_identifier::text FROM pg_control_system()").fetchone() != source_sysid
                    backup = target_home / "backups" / "imported" / dump.plan.backup_path.name
                    backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    shutil.copytree(dump.plan.backup_path, backup)
                    original = _digests(backup)
                    assert original == _digests(dump.plan.backup_path), "the imported backup is the unchanged original"
                    before = database_names(target_pg)

                    _refused("restore-target-artifact-unqualified", target_home, backup, target_runner, policy, target_pg, before)
                    later = replace(policy, artifact_qualification=_union(source_qual, target_qual))
                    assert later.policy_binding_record() == policy.policy_binding_record(), "target qualification is outside the declaration"
                    [alpha, *rest] = later.extensions
                    changed = replace(later, extensions=(replace(alpha, readiness_probe_sql="SELECT ext_alpha_s.alpha_version() || '';"), *rest))
                    _refused(
                        "backup-extension-restore-unsupported", target_home, backup, target_runner, changed, target_pg, before,
                        blocker="extension-policy-binding-mismatch",
                    )

                    result = init_database_from_dump(target_home, database=GRAPH, backup=backup, command_runner=target_runner, extension_restore_policy=later)
                    assert result.result == "success" and result.dump_restored is True
                    assert _digests(backup) == original, "the original archive and manifest are unchanged after restore"
                    assert not list((target_home / "runtime").glob(".restore-intents-*"))
                    with closing(_connect(target_pg, GRAPH)) as tg:
                        assert tg.execute("SELECT ext_gamma_s.gamma_probe()").fetchone() == ("1.0:beta-1.0:gamma-1.0",)
                        assert tg.execute("SELECT extversion FROM pg_extension WHERE extname = 'ext_alpha'").fetchone() == ("1.0",)
                        assert tg.execute("SELECT id, tag FROM app_ext.items").fetchall() == [(1, "alpha-beta-gamma")]
