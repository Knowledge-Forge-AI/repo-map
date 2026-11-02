"""Reusable contract assertions for cloe-compact-context-v1 and cloe-source-selection-v1."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from common_lore_index.retrieval.context_budget import serialize_compact_json
from common_lore_index.retrieval.context_contracts import (
    CONTEXT_FRESHNESS_OBS_KEYS,
    CONTEXT_ITEM_KEYS,
    CONTEXT_LOCATION_KEYS,
    CONTEXT_RELATION_KEYS,
    OMISSION_COUNT_KEYS,
    PACKET_STATUSES,
    PACKET_TOP_LEVEL_KEYS,
)
from common_lore_index.retrieval.context_work import WORK_LEDGER_KEYS

FORBIDDEN_PACKET_BODY_MARKERS: tuple[str, ...] = (
    "Billing invoice service.",
    "raise ValueError('invalid')",
    "pkgs.hello",
    "Operate InvoiceService safely.",
    "def secret_fn",
)


def assert_valid_context_packet(
    packet: dict[str, Any],
    *,
    forbidden_substrings: Sequence[str] = (),
) -> bytes:
    """Assert that a cloe-compact-context-v1 packet satisfies key ordering and byte bounds."""
    base_keys = tuple(k for k in packet.keys() if k not in {"reason", "refusal_code", "unavailable_reason"})
    assert base_keys == PACKET_TOP_LEVEL_KEYS
    assert packet["schema"] == "cloe-compact-context-v1"
    assert packet["status"] in PACKET_STATUSES
    assert tuple(packet["omission_counts"].keys()) == OMISSION_COUNT_KEYS
    assert tuple(packet["work_ledger"].keys()) == WORK_LEDGER_KEYS

    for item in packet["items"]:
        assert tuple(item.keys()) == CONTEXT_ITEM_KEYS
        assert item["item_role"] == "seed"
        assert isinstance(item["rank"], int) and item["rank"] >= 1
        assert isinstance(item["rank_tiers"], dict)
        assert isinstance(item["rank_reasons"], list) and len(item["rank_reasons"]) >= 1
        for loc in item["locations"]:
            assert tuple(loc.keys()) == CONTEXT_LOCATION_KEYS
            fresh = loc["freshness"]
            if fresh is not None:
                assert tuple(fresh.keys()) == CONTEXT_FRESHNESS_OBS_KEYS

    for nbr in packet["neighbors"]:
        assert tuple(nbr.keys()) == CONTEXT_ITEM_KEYS
        assert nbr["item_role"] == "neighbor"
        assert nbr["rank"] is None
        assert nbr["match_class"] is None
        assert nbr["rank_tiers"] is None
        assert nbr["rank_reasons"] == []
        assert nbr["match_surface"] == "graph_topology"
        for loc in nbr["locations"]:
            assert tuple(loc.keys()) == CONTEXT_LOCATION_KEYS
            fresh = loc["freshness"]
            if fresh is not None:
                assert tuple(fresh.keys()) == CONTEXT_FRESHNESS_OBS_KEYS

    for rel in packet["relations"]:
        assert tuple(rel.keys()) == CONTEXT_RELATION_KEYS
        assert rel["match_surface"] == "graph_topology"

    raw = serialize_compact_json(packet)
    actual_bytes = packet["work_ledger"]["actual_bytes"]
    budget_bytes = packet["request"]["budget_bytes"]
    assert actual_bytes == len(raw), f"actual_bytes={actual_bytes} != len(raw)={len(raw)}"
    assert actual_bytes <= budget_bytes, f"actual_bytes={actual_bytes} > budget={budget_bytes}"

    text = raw.decode("utf-8")
    for marker in (*FORBIDDEN_PACKET_BODY_MARKERS, *forbidden_substrings):
        if marker:
            assert marker not in text, f"Forbidden marker {marker!r} leaked in packet"
    return raw


def assert_valid_budget_error(envelope: dict[str, Any]) -> bytes:
    """Assert that a budget_error envelope satisfies its compact 512-byte contract."""
    assert tuple(envelope.keys()) == (
        "schema",
        "status",
        "reason",
        "budget_bytes",
        "min_budget_bytes",
        "max_budget_bytes",
        "required_min_bytes",
    )
    assert envelope["schema"] == "cloe-compact-context-v1"
    assert envelope["status"] == "budget_error"
    raw = serialize_compact_json(envelope)
    assert len(raw) <= 512, f"budget_error envelope {len(raw)} bytes > 512"
    return raw


def build_postgres_context_fixture(
    tmp_path: Any,
    postgres: Any,
    *,
    graph_id: str = "polyglot-ctx",
    extra_subjects: Sequence[dict[str, Any]] = (),
    extra_edges: Sequence[tuple[str, str, str]] = (),
    include_private_binding: bool = False,
    apply_schema: bool = True,
) -> tuple[Any, Any]:
    """Seed POLYGLOT_SUBJECTS into a disposable PostgreSQL database and return (home_dir, PostgresContextReadAdapter)."""
    import json
    import os
    from pathlib import Path
    import psycopg
    from common_lore_index.graph.multi_source import graph_source_binding_id
    from common_lore_index.server.context_read_postgres import PostgresContextReadAdapter
    from common_lore_index.storage import apply_migrations, default_rdbms_root
    from repomap_test_support.context_fixture import (
        BINDING_CORE,
        BINDING_DOCS,
        BINDING_PRIV,
        POLYGLOT_EDGES,
        POLYGLOT_SUBJECTS,
        SNAP_CORE,
        SNAP_DOCS,
        SNAP_PRIV,
        _prepare_polyglot_bindings,
    )

    home = Path(tmp_path)
    if apply_schema:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
    _, _bindings, markers, cfg_bindings, toml_bindings = _prepare_polyglot_bindings(
        home, graph_id, include_private_binding
    )
    b_core, b_docs, b_priv = (
        graph_source_binding_id(graph_id, "core"),
        graph_source_binding_id(graph_id, "docs"),
        graph_source_binding_id(graph_id, "priv"),
    )
    os.chmod(home, 0o700)
    state_dir = home / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(state_dir, 0o700)
    mem_dir = home / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    pw_line = ""
    if getattr(postgres, "password", None):
        pw_file = home / "pgpass.secret"
        pw_file.write_text(str(postgres.password), encoding="utf-8")
        os.chmod(pw_file, 0o600)
        pw_line = f'password_file = "{pw_file.resolve().as_posix()}"\n'
    (home / "repomap.rpl.toml").write_text(
        f'schema_version = 1\n\n[storage]\nbackend = "postgresql"\n\n'
        f'[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n\n'
        f'[postgres]\nhost = "{postgres.host}"\nport = {postgres.port}\n'
        f'database = "{postgres.database}"\nuser = "{postgres.user}"\n{pw_line}\n'
        f'[runtime]\ncoordinator_mode = "native"\nbind_host = "127.0.0.1"\n\n'
        f'[runtime.postgres]\ndirect_host_port_enabled = true\n'
        f'host_port = {postgres.port}\nbind_host = "{postgres.host}"\n\n'
        f'[server_memory]\nenabled = false\npath = "{mem_dir.resolve().as_posix()}"\nmode = "read_only"\n\n'
        f'[[graphs]]\nid = "{graph_id}"\nname = "{graph_id}"\ndatabase = "{postgres.database}"\n'
        f'enabled = true\nmcp_visible = true\nrefresh_policy = "manual"\n\n{toml_bindings}',
        encoding="utf-8",
    )
    vector = [[b_core, 1, SNAP_CORE], [b_docs, 1, SNAP_DOCS]] + (
        [[b_priv, 1, SNAP_PRIV]] if include_private_binding else []
    )
    fams = {
        k: {"count": 1, "byte_length": 1, "digest": "sha256:" + "0" * 64}
        for k in (
            "files", "raw_observations", "canonical_nodes", "canonical_edges",
            "canonical_evidence", "canonical_node_evidence", "canonical_edge_evidence",
        )
    }
    repo_identity = f"repo1:{graph_id}"
    root_path = f"graph:{graph_id}"
    all_subjects = list(POLYGLOT_SUBJECTS) + list(extra_subjects)
    all_edges = list(POLYGLOT_EDGES) + list(extra_edges)
    with psycopg.connect(
        host=postgres.host, port=postgres.port, dbname=postgres.database,
        user=postgres.user, password=postgres.password,
    ) as conn:
        repo_row = conn.execute(
            "INSERT INTO repositories (name, root_path, repository_identity) VALUES (%s, %s, %s) RETURNING id",
            (graph_id, root_path, repo_identity),
        ).fetchone()
        assert repo_row is not None
        repo_id = int(repo_row[0])
        run_row = conn.execute(
            "INSERT INTO runs (repository_id, status, execution_route, portable_protocol_version, "
            "snapshot_manifest_id, snapshot_vector_json, extraction_receipt_id, publication_bundle_id, "
            "graph_candidate_id, resolver_identity, portable_canonicalizer_identity, "
            "semantic_contract_identity, quality_rule_identity, worker_capability_identity, "
            "portable_stage_id, portable_execution_mode, portable_singleton_fencing_epoch, "
            "portable_graph_lease_fencing_epoch, source_generation, config_generation, "
            "extractor_generation, canonicalizer_generation, publication_job_id, publication_attempt, "
            "family_receipts_json) VALUES (%s, 'complete', 'portable-worker-v1', '1.0', %s, %s, %s, %s, "
            "%s, 'resolver1:nix-static-v2', 'canon1:graph-key-v1-binding-path', "
            "'semantic1:multi-source-v1', 'quality1:default', 'cap1:portable-python-worker-v1', "
            "%s, 'direct', 0, 0, %s, %s, %s, %s, %s, 1, %s) RETURNING id",
            (
                repo_id, "snapmanifest1:" + "a1" * 32, json.dumps(vector, separators=(",", ":")),
                "receipt1:" + "b2" * 32, "bundle1:" + "c3" * 32, "cand1:" + "d4" * 32,
                f"stage-{graph_id}-1",
                "sg1:" + "11" * 32, "cg1:" + "22" * 32, "eg1:" + "33" * 32, "kg1:" + "44" * 32,
                f"job-{graph_id}-1",
                json.dumps(fams, separators=(",", ":")),
            ),
        ).fetchone()
        assert run_row is not None
        run_id = int(run_row[0])
        node_id_by_key: dict[str, int] = {}
        bid_map = {BINDING_CORE: b_core, BINDING_DOCS: b_docs, BINDING_PRIV: b_priv}
        for idx, subj in enumerate(all_subjects, start=1):
            disp = subj.get("display_name") or subj["canonical_key"]
            n_row = conn.execute(
                "INSERT INTO canonical_nodes (repository_id, graph_key_version, canonical_key, kind, "
                "display_name, metadata_json, confidence, conflict, first_seen_run_id, last_seen_run_id) "
                "VALUES (%s, 1, %s, %s, %s, '{}'::jsonb, 'extracted', false, %s, %s) RETURNING id",
                (repo_id, subj["canonical_key"], subj["kind"], disp, run_id, run_id),
            ).fetchone()
            assert n_row is not None
            nid = int(n_row[0])
            node_id_by_key[subj["canonical_key"]] = nid
            obs_row = conn.execute(
                "INSERT INTO raw_observations (repository_id, run_id, ordinal, schema_version, kind, "
                "source_id, path, payload_json, payload_hash) VALUES (%s, %s, %s, 1, %s, %s, %s, '{}'::jsonb, %s) RETURNING id",
                (repo_id, run_id, idx, subj["raw_kind"], f"src-{idx}", subj["path"], f"{idx:064x}"),
            ).fetchone()
            assert obs_row is not None
            eff_bid = bid_map.get(subj["binding_id"], subj["binding_id"])
            meta = json.dumps(
                {
                    "binding_id": eff_bid, "binding_revision": int(subj.get("binding_revision", 1)),
                    "snapshot_id": subj["snapshot_id"], "source_relative_path": subj["path"],
                },
                separators=(",", ":"),
            )
            ev_row = conn.execute(
                "INSERT INTO canonical_evidence (repository_id, run_id, graph_key_version, raw_observation_id, "
                "evidence_key, raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id, path, "
                "start_line, end_line, extractor, extractor_version, confidence, metadata_json) "
                "VALUES (%s, %s, 1, %s, %s, %s, 1, %s, %s, %s, %s, %s, 'polyglot', '1.0', 'extracted', %s::jsonb) RETURNING id",
                (repo_id, run_id, int(obs_row[0]), f"ev:{idx}", idx, subj["raw_kind"], f"src-{idx}", subj["path"], subj["start_line"], subj["end_line"], meta),
            ).fetchone()
            assert ev_row is not None
            conn.execute(
                "INSERT INTO canonical_node_evidence (canonical_node_id, canonical_evidence_id, link_kind) VALUES (%s, %s, %s)",
                (nid, int(ev_row[0]), subj.get("link_kind", "observed")),
            )
        for e_idx, (ekind, src_ck, tgt_ck) in enumerate(all_edges, start=1):
            if src_ck in node_id_by_key and tgt_ck in node_id_by_key:
                conn.execute(
                    "INSERT INTO canonical_edges (repository_id, graph_key_version, source_canonical_key, edge_kind, "
                    "target_canonical_key, identity_metadata_json, identity_metadata_hash, metadata_json, "
                    "confidence, conflict, first_seen_run_id, last_seen_run_id) "
                    "VALUES (%s, 1, %s, %s, %s, '{}'::jsonb, %s, '{}'::jsonb, 'extracted', false, %s, %s)",
                    (repo_id, src_ck, ekind, tgt_ck, f"{e_idx:064x}", run_id, run_id),
                )
    adapter = PostgresContextReadAdapter(
        graph_id=graph_id, repository_id=repo_identity, root_path=root_path,
        psql_args=postgres.psql_args, psql_command=postgres.psql_command,
        password=postgres.password, configured_bindings=cfg_bindings,
        private_markers=tuple(markers),
    )
    return home, adapter
