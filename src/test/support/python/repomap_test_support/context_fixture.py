"""Deterministic polyglot SQLite Local and PostgreSQL fixture builders for W4 context tests."""

from __future__ import annotations

from collections.abc import Sequence
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from common_lore_index.graph.multi_source import (
    SourceKind, graph_source_binding_id, source_selection_policy_id,
)
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_local import (
    LocalSqliteConfig, local_graph_binding, sqlite_graph_database_path,
)
from common_lore_index.ops.config_records import (
    OpsGraphConfig, OpsServerMemoryConfig, OpsServiceConfig, OpsSourcesConfig,
)
from common_lore_index.server.context_read_sqlite import SqliteContextReadAdapter
from common_lore_index.storage.row_helpers import identity_metadata_hash
from common_lore_index.storage.sqlite_local.connection import initialize_graph_database
from common_lore_index.storage.sqlite_local.schema import LocalGraphBinding

CTX_GRAPH_ID = "polyglot-ctx"
BINDING_CORE = graph_source_binding_id(CTX_GRAPH_ID, "core")
BINDING_DOCS = graph_source_binding_id(CTX_GRAPH_ID, "docs")
BINDING_PRIV = graph_source_binding_id(CTX_GRAPH_ID, "priv")
DEFAULT_SELPOL = source_selection_policy_id((), ())
SNAP_CORE = "snap1:1111111111111111111111111111111111111111111111111111111111111111"
SNAP_DOCS = "snap1:2222222222222222222222222222222222222222222222222222222222222222"
SNAP_PRIV = "snap1:3333333333333333333333333333333333333333333333333333333333333333"

DEFAULT_VECTOR: list[list[Any]] = [
    [BINDING_CORE, 1, SNAP_CORE],
    [BINDING_DOCS, 1, SNAP_DOCS],
]


def _subj(
    ck: str, kind: str, dn: str, raw_kind: str, bid: str, snap: str,
    path: str, start: int | None, end: int | None, *, link_kind: str = "observed",
) -> dict[str, Any]:
    return {
        "canonical_key": ck, "kind": kind, "display_name": dn, "raw_kind": raw_kind,
        "link_kind": link_kind, "binding_id": bid, "snapshot_id": snap,
        "path": path, "start_line": start, "end_line": end,
    }


POLYGLOT_SUBJECTS: tuple[dict[str, Any], ...] = (
    _subj("py:pkg.billing.InvoiceService", "python.class", "InvoiceService", "python.class", BINDING_CORE, SNAP_CORE, "src/billing/invoice.py", 1, 6),
    _subj("py:pkg.billing.InvoiceService.compute_total", "python.method", "compute_total", "python.method", BINDING_CORE, SNAP_CORE, "src/billing/invoice.py", 3, 6),
    _subj("py:pkg.billing.validate_invoice", "python.function", "validate_invoice", "python.function", BINDING_CORE, SNAP_CORE, "src/billing/invoice.py", 8, 10),
    _subj("py:pkg.billing", "python.module", "pkg.billing", "python.module", BINDING_CORE, SNAP_CORE, "src/billing/invoice.py", 1, 10),
    _subj("py:tests.test_invoice.test_invoice_service", "python.function", "test_invoice_service", "python.function", BINDING_CORE, SNAP_CORE, "tests/test_invoice.py", 1, 5),
    _subj("bats.file:tests/cli.bats", "bats.file", "cli.bats", "bats.file", BINDING_CORE, SNAP_CORE, "tests/cli.bats", 1, 6),
    _subj("bats.test_case:tests/cli.bats#invokes%20InvoiceService", "bats.test_case", "invokes InvoiceService", "bats.test_case", BINDING_CORE, SNAP_CORE, "tests/cli.bats", 2, 5, link_kind="inferred_from_edge"),
    _subj("zunit.test_case:tests/billing.zunit#InvoiceService", "zunit.test_case", "InvoiceService zsh test", "zunit.test_case", BINDING_CORE, SNAP_CORE, "tests/billing.zunit", 1, 4),
    _subj("nix.check:checks.x86_64-linux.billing", "nix.check", "billing check", "nix.check", BINDING_CORE, SNAP_CORE, "nix/default.nix", 1, 4, link_kind="inferred_from_edge"),
    _subj("doc:adr/0010-billing-architecture", "doc.adr", "ADR 0010 Billing Architecture", "markdown.adr_metadata", BINDING_DOCS, SNAP_DOCS, "adr/0010-billing.md", 1, 6),
    _subj("doc:skill/billing-ops", "doc.skill", "Billing Ops Skill", "markdown.skill_metadata", BINDING_DOCS, SNAP_DOCS, "skills/billing-ops.md", 1, 5),
    _subj("doc:page/billing-guide", "doc.page", "Billing Guide", "markdown.document", BINDING_DOCS, SNAP_DOCS, "guides/billing.md", 1, 8),
    _subj("doc:section/billing-guide#invoicing", "doc.section", "InvoiceService Overview", "markdown.heading", BINDING_DOCS, SNAP_DOCS, "guides/billing.md", 3, 7),
    _subj("email.message:msg-billing-alert", "email.message", "InvoiceService rollout notice", "email.message", BINDING_DOCS, SNAP_DOCS, "messages/rollout.eml", 1, 5),
    _subj("feed.item:feed-billing-release", "feed.item", "InvoiceService v1 release", "feed.item", BINDING_DOCS, SNAP_DOCS, "messages/releases.xml", 1, 5),
    _subj("tool:pytest", "tool", "pytest", "file", BINDING_CORE, SNAP_CORE, "src/billing/invoice.py", 1, 2, link_kind="inferred_from_edge"),
    _subj("py:pkg.ambig.AlphaHandler", "python.class", "AlphaHandler", "python.class", BINDING_CORE, SNAP_CORE, "src/billing/invoice.py", 1, 3),
    _subj("py:pkg.ambig2.AlphaHandler", "python.class", "AlphaHandler", "python.class", BINDING_CORE, SNAP_CORE, "src/billing/invoice.py", 4, 6),
    _subj("doc:shared/readme-core", "doc.page", "SharedReadme Core", "markdown.document", BINDING_CORE, SNAP_CORE, "shared/README.md", 1, 3),
    _subj("doc:shared/readme-docs", "doc.page", "SharedReadme Docs", "markdown.document", BINDING_DOCS, SNAP_DOCS, "shared/README.md", 1, 3),
    _subj("doc:page/multibyte-Δ-guide", "doc.page", "Δ-quorum-λ guide", "markdown.document", BINDING_DOCS, SNAP_DOCS, "guides/billing.md", 1, 4),
)

POLYGLOT_EDGES: tuple[tuple[str, str, str], ...] = (
    ("defines", "py:pkg.billing", "py:pkg.billing.InvoiceService"),
    ("contains", "py:pkg.billing.InvoiceService", "py:pkg.billing.InvoiceService.compute_total"),
    ("calls", "py:pkg.billing.InvoiceService.compute_total", "py:pkg.billing.validate_invoice"),
    ("references", "py:tests.test_invoice.test_invoice_service", "py:pkg.billing.InvoiceService"),
    ("contains", "bats.file:tests/cli.bats", "bats.test_case:tests/cli.bats#invokes%20InvoiceService"),
    ("links_to", "doc:adr/0010-billing-architecture", "py:pkg.billing.InvoiceService"),
    ("links_to", "doc:section/billing-guide#invoicing", "py:pkg.billing.InvoiceService"),
    ("links_to", "doc:page/billing-guide", "doc:adr/0010-billing-architecture"),
    ("references", "email.message:msg-billing-alert", "feed.item:feed-billing-release"),
)


def write_polyglot_source_trees(base_dir: Path) -> tuple[Path, Path]:
    """Write deterministic source files for BINDING_CORE and BINDING_DOCS on disk."""
    core_root = base_dir / "src_core"
    docs_root = base_dir / "src_docs"
    for rel in ("src/billing", "tests", "nix", "shared"):
        (core_root / rel).mkdir(parents=True, exist_ok=True)
    for rel in ("adr", "skills", "guides", "messages", "shared"):
        (docs_root / rel).mkdir(parents=True, exist_ok=True)
    (core_root / "shared/README.md").write_text("# SharedReadme Core\nLine 2\nLine 3\n", encoding="utf-8")
    (docs_root / "shared/README.md").write_text("# SharedReadme Docs\nLine 2\nLine 3\n", encoding="utf-8")

    (core_root / "src/billing/invoice.py").write_text(
        "class InvoiceService:\n    \"\"\"Billing invoice service.\"\"\"\n"
        "    def compute_total(self, items):\n        validate_invoice(items)\n"
        "        return sum(items)\n\n\ndef validate_invoice(items):\n"
        "    if items is None:\n        raise ValueError('invalid')\n",
        encoding="utf-8",
    )
    (core_root / "tests/test_invoice.py").write_text(
        "def test_invoice_service():\n    assert True\n\n\n# end\n", encoding="utf-8"
    )
    (core_root / "tests/cli.bats").write_text(
        "#!/usr/bin/env bats\n@test 'invokes InvoiceService' {\n  run true\n"
        "  [ \"$status\" -eq 0 ]\n}\n# end\n",
        encoding="utf-8",
    )
    (core_root / "tests/billing.zunit").write_text(
        "#!/usr/bin/env zunit\n@test 'InvoiceService zsh test' {\n  assert 1 equals 1\n}\n",
        encoding="utf-8",
    )
    (core_root / "nix/default.nix").write_text(
        "{ pkgs }:\n{\n  checks.x86_64-linux.billing = pkgs.hello;\n}\n", encoding="utf-8"
    )
    (docs_root / "adr/0010-billing.md").write_text(
        "# ADR 0010: Billing Architecture\nStatus: Accepted\n"
        "InvoiceService owns invoice calculation.\nLine 4\nLine 5\nLine 6\n",
        encoding="utf-8",
    )
    (docs_root / "skills/billing-ops.md").write_text(
        "---\nname: billing-ops\n---\n# Billing Ops Skill\nOperate InvoiceService safely.\n",
        encoding="utf-8",
    )
    (docs_root / "guides/billing.md").write_text(
        "---\ntitle: Billing Guide\n---\n## InvoiceService Overview\n"
        "```python\nInvoiceService().compute_total([10])\n```\nEnd of guide.\n",
        encoding="utf-8",
    )
    (docs_root / "messages/rollout.eml").write_text(
        "Subject: InvoiceService rollout notice\nFrom: ops@example.test\n\nBody.\nEnd.\n",
        encoding="utf-8",
    )
    (docs_root / "messages/releases.xml").write_text(
        "<rss><channel><item><title>InvoiceService v1 release</title></item></channel></rss>\n"
        "<!-- 2 -->\n<!-- 3 -->\n<!-- 4 -->\n<!-- 5 -->\n",
        encoding="utf-8",
    )
    return core_root, docs_root


def _prepare_polyglot_bindings(
    tmp_path: Path, graph_id: str, include_private_binding: bool
) -> tuple[Path, list[OpsGraphSourceBindingConfig], list[str], dict[str, dict[str, Any]], str]:
    core_root, docs_root = write_polyglot_source_trees(tmp_path)
    priv_root = tmp_path / "src_priv_secret_marker"
    priv_root.mkdir(parents=True, exist_ok=True)
    (priv_root / "secret.py").write_text("def secret_fn():\n    pass\n", encoding="utf-8")
    b_core, b_docs, b_priv = (
        graph_source_binding_id(graph_id, "core"),
        graph_source_binding_id(graph_id, "docs"),
        graph_source_binding_id(graph_id, "priv"),
    )
    bindings = [
        OpsGraphSourceBindingConfig(
            schema_version=1, binding_id=b_core, source_definition_id="src1:core",
            alias="core", revision=1, source_kind=SourceKind.FOLDER,
            root_path=str(core_root), root_path_expanded=str(core_root),
            repository_name="polyglot-core", logical_root="core", privacy="public-dev",
            evidence_retention="full-authorized", extractor_profile="default",
            include_paths=(), exclude_paths=(), selection_policy_id=DEFAULT_SELPOL,
            resolution_policy="allow-declared", enabled=True, role="source", input_name="core",
        ),
        OpsGraphSourceBindingConfig(
            schema_version=1, binding_id=b_docs, source_definition_id="src1:docs",
            alias="docs", revision=1, source_kind=SourceKind.FOLDER,
            root_path=str(docs_root), root_path_expanded=str(docs_root),
            repository_name="polyglot-docs", logical_root="docs", privacy="public-dev",
            evidence_retention="full-authorized", extractor_profile="default",
            include_paths=(), exclude_paths=(), selection_policy_id=DEFAULT_SELPOL,
            resolution_policy="allow-declared", enabled=True, role="companion", input_name="docs",
        ),
    ]
    markers: list[str] = []
    if include_private_binding:
        bindings.append(
            OpsGraphSourceBindingConfig(
                schema_version=1, binding_id=b_priv, source_definition_id="src1:priv",
                alias="priv", revision=1, source_kind=SourceKind.FOLDER,
                root_path=str(priv_root), root_path_expanded=str(priv_root),
                repository_name="polyglot-priv", logical_root="priv", privacy="private-memory",
                evidence_retention="metadata-only", extractor_profile="default",
                include_paths=(), exclude_paths=(), selection_policy_id=DEFAULT_SELPOL,
                resolution_policy="isolated", enabled=True, role="mailbox", input_name="priv",
            )
        )
        markers.extend((str(priv_root), "secret_priv_marker"))
    toml_bindings = "\n".join(
        f'[[graphs.source_bindings]]\nschema_version = 1\nbinding_id = "{b.binding_id}"\n'
        f'source_definition_id = "{b.source_definition_id}"\nalias = "{b.alias}"\nrevision = {b.revision}\n'
        f'kind = "folder"\nroot_path = "{Path(b.root_path).resolve().as_posix()}"\n'
        f'repository_name = "{b.repository_name}"\nlogical_root = "{b.logical_root}"\n'
        f'privacy = "{b.privacy}"\nevidence_retention = "{b.evidence_retention}"\n'
        f'extractor_profile = "{b.extractor_profile}"\nresolution_policy = "{b.resolution_policy}"\n'
        f'role = "{b.role}"\ninput_name = "{b.input_name}"\nenabled = true\n'
        for b in bindings
    )
    cfg_bindings = {
        b.binding_id: {
            "binding_id": b.binding_id, "revision": int(b.revision),
            "selection_policy_id": b.selection_policy_id, "source_definition_id": b.source_definition_id,
        }
        for b in bindings
    }
    return core_root, bindings, markers, cfg_bindings, toml_bindings


def build_sqlite_context_fixture(
    tmp_path: Path,
    *,
    graph_id: str = CTX_GRAPH_ID,
    extra_subjects: Sequence[dict[str, Any]] = (),
    extra_edges: Sequence[tuple[str, str, str]] = (),
    include_private_binding: bool = False,
) -> tuple[Path, LocalSqliteConfig, OpsGraphConfig, LocalGraphBinding, SqliteContextReadAdapter]:
    """Create a populated SQLite Local database, repomap.rpl.toml, and source roots for context tests."""
    core_root, bindings, markers, cfg_bindings, toml_bindings = _prepare_polyglot_bindings(
        tmp_path, graph_id, include_private_binding
    )
    b_core, b_docs, b_priv = (
        graph_source_binding_id(graph_id, "core"),
        graph_source_binding_id(graph_id, "docs"),
        graph_source_binding_id(graph_id, "priv"),
    )
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "repomap.rpl.toml").write_text(
        f'schema_version = 1\n\n[storage]\nbackend = "sqlite"\n\n'
        f'[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n\n'
        f'[server_memory]\nenabled = false\npath = "{mem_dir.resolve().as_posix()}"\nmode = "read_only"\n\n'
        f'[[graphs]]\nid = "{graph_id}"\nname = "{graph_id}"\n'
        f'enabled = true\nmcp_visible = true\nrefresh_policy = "manual"\n\n{toml_bindings}',
        encoding="utf-8",
    )
    graph = OpsGraphConfig(
        id=graph_id, name=graph_id, root_path=str(core_root),
        root_path_expanded=str(core_root), repository_name=graph_id, privacy="public-dev",
        enabled=True, mcp_visible=True, extractor_profile="default",
        refresh_policy="manual", database=None, source_bindings=tuple(bindings),
        explicit_source_bindings=True,
    )
    config = LocalSqliteConfig(
        config_path=str(tmp_path / "repomap.rpl.toml"), config_home=str(tmp_path),
        config_files=("repomap.rpl.toml",), schema_version=1,
        service=OpsServiceConfig(mode="local", mcp_transport="stdio", log_level="info"),
        graphs=(graph,),
        server_memory=OpsServerMemoryConfig(
            enabled=False, path="./server-memory", path_expanded=str(mem_dir), mode="read_only",
        ),
        sources=OpsSourcesConfig(),
    )
    sqlite_path = sqlite_graph_database_path(config, graph)
    sqlite_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(sqlite_path.parent, 0o700)
    binding = local_graph_binding(graph)
    initialize_graph_database(sqlite_path, binding, applied_at="2026-11-01T00:00:00Z")

    vector = [[b_core, 1, SNAP_CORE], [b_docs, 1, SNAP_DOCS]] + (
        [[b_priv, 1, SNAP_PRIV]] if include_private_binding else []
    )
    all_subjects = list(POLYGLOT_SUBJECTS) + list(extra_subjects)
    all_edges = list(POLYGLOT_EDGES) + list(extra_edges)
    empty_identity_hash = identity_metadata_hash({})

    conn = sqlite3.connect(sqlite_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO runs (id, previous_run_id, status, started_at, finished_at, "
                "publisher, execution_route, portable_protocol_version, snapshot_manifest_id, "
                "snapshot_vector_json, extraction_receipt_id, publication_bundle_id, "
                "graph_candidate_id, resolver_identity, portable_canonicalizer_identity, "
                "semantic_contract_identity, quality_rule_identity, worker_capability_identity, "
                "portable_stage_id, portable_execution_mode, source_generation, config_generation, "
                "extractor_generation, canonicalizer_generation, publication_job_id, "
                "publication_attempt, family_receipts_json, privacy) VALUES ("
                "1, NULL, 'complete', '2026-11-01T00:00:00Z', '2026-11-01T00:00:01Z', "
                "'sqlite-local-direct-v1', 'portable-worker-v1', '1.0', "
                "'snapmanifest1:' || replace(hex(zeroblob(32)), '00', 'a1'), ?, "
                "'receipt1:' || replace(hex(zeroblob(32)), '00', 'b2'), "
                "'bundle1:' || replace(hex(zeroblob(32)), '00', 'c3'), "
                "'cand1:' || replace(hex(zeroblob(32)), '00', 'd4'), "
                "'resolver1:nix-static-v2', 'canon1:graph-key-v1-binding-path', "
                "'semantic1:multi-source-v1', 'quality1:default', 'cap1:portable-python-worker-v1', "
                "'stage-ctx-1', 'direct', 'sg1:' || replace(hex(zeroblob(32)), '00', '11'), "
                "'cg1:' || replace(hex(zeroblob(32)), '00', '22'), "
                "'eg1:' || replace(hex(zeroblob(32)), '00', '33'), "
                "'kg1:' || replace(hex(zeroblob(32)), '00', '44'), 'job-ctx-1', 1, '{}', 'public')",
                (json.dumps(vector, separators=(",", ":")),),
            )
            conn.execute("INSERT INTO accepted_publication (singleton, generation, run_id) VALUES (1, 1, 1)")
            node_id_by_key: dict[str, int] = {}
            for idx, subj in enumerate(all_subjects, start=1):
                node_id_by_key[subj["canonical_key"]] = idx
                disp = subj.get("display_name") or subj["canonical_key"]
                conn.execute(
                    "INSERT INTO canonical_nodes (id, graph_key_version, canonical_key, kind, "
                    "display_name, metadata_json, confidence, conflict, first_seen_run_id, last_seen_run_id) "
                    "VALUES (?, 1, ?, ?, ?, '{}', 'extracted', 0, 1, 1)",
                    (idx, subj["canonical_key"], subj["kind"], disp),
                )
                conn.execute(
                    "INSERT INTO raw_observations (run_id, ordinal, schema_version, kind, source_id, "
                    "path, payload_json, payload_hash) VALUES (1, ?, 1, ?, ?, ?, '{}', ?)",
                    (idx, subj["raw_kind"], f"src-{idx}", subj["path"], f"hash-{idx:04d}"),
                )
                bid_map = {BINDING_CORE: b_core, BINDING_DOCS: b_docs, BINDING_PRIV: b_priv}
                eff_bid = bid_map.get(subj["binding_id"], subj["binding_id"])
                meta = json.dumps(
                    {
                        "binding_id": eff_bid, "binding_revision": int(subj.get("binding_revision", 1)),
                        "snapshot_id": subj["snapshot_id"], "source_relative_path": subj["path"],
                    },
                    separators=(",", ":"),
                )
                conn.execute(
                    "INSERT INTO canonical_evidence (id, run_id, graph_key_version, evidence_key, "
                    "raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id, path, "
                    "start_line, end_line, extractor, extractor_version, confidence, metadata_json) "
                    "VALUES (?, 1, 1, ?, ?, 1, ?, ?, ?, ?, ?, 'polyglot', '1.0', 'extracted', ?)",
                    (idx, f"ev:{idx}", idx, subj["raw_kind"], f"src-{idx}", subj["path"], subj["start_line"], subj["end_line"], meta),
                )
                conn.execute(
                    "INSERT INTO canonical_node_evidence (canonical_node_id, canonical_evidence_id, link_kind) VALUES (?, ?, ?)",
                    (idx, idx, subj.get("link_kind", "observed")),
                )
            for e_idx, (ekind, src_ck, tgt_ck) in enumerate(all_edges, start=1):
                if src_ck in node_id_by_key and tgt_ck in node_id_by_key:
                    conn.execute(
                        "INSERT INTO canonical_edges (id, graph_key_version, source_canonical_key, edge_kind, "
                        "target_canonical_key, identity_metadata_json, identity_metadata_hash, metadata_json, "
                        "confidence, conflict, first_seen_run_id, last_seen_run_id) "
                        "VALUES (?, 1, ?, ?, ?, '{}', ?, '{}', 'extracted', 0, 1, 1)",
                        (e_idx, src_ck, ekind, tgt_ck, empty_identity_hash),
                    )
    finally:
        conn.close()

    adapter = SqliteContextReadAdapter(
        graph_id=graph.id, db_path=sqlite_path,
        binding=binding,
        configured_bindings=cfg_bindings, private_markers=tuple(markers),
    )
    return sqlite_path, config, graph, binding, adapter
