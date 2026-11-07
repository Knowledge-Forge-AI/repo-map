"""Public pushdown corpus: real extraction/publication; explicit synthetic mutations."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from common_lore_index.storage.sqlite_local.publisher import publish_generation
from repomap_test_support.navigation_search_fixtures import GRAPH, navigation_bundle, navigation_home
from repomap_test_support.sqlite_local_fixtures import publication_for


def pushdown_home(tmp_path: Path, noise: int = 2105, other_noise: int = 0) -> tuple[Path, Path]:
    """Earlier-sorted same-binding headings precede the two target sections.

    Markdown/Python extraction, canonicalization and publication are real.
    File observations/snapshot manifests use the established synthetic fixture.
    """
    home, database = navigation_home(tmp_path)
    outside = "# Outside\n" + "\n".join(f"## Needle Outside {i:05d}\n" for i in range(noise))
    bundle = navigation_bundle(
        generation=2,
        markdown_sources={"docs/aaa.md": outside,
                          "docs/zzz/target.md": "# Target\n## Needle One\n## Needle Two\n"},
        python_sources={"src/zzz/sample.py": "def needle_target():\n    return 1\n"},
        additional_markdown={"other": {"docs/aaa.md": "# Outside\n" + "\n".join(
            f"## Needle Other {i:05d}\n" for i in range(other_noise))}} if other_noise else None,
    )
    publish_generation(database, publication_for(bundle, GRAPH), bundle.families, expected_generation=1)
    return home, database


def add_alternatives(database: Path, key: str, count: int, *, path: str | None = None,
                     metadata: dict[str, Any] | None = None) -> None:
    """Synthetic evidence multiplicity/corruption, never represented as extraction."""
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        columns = [row[1] for row in connection.execute("PRAGMA table_info(canonical_evidence)") if row[1] != "id"]
        original = connection.execute(
            "SELECT e.* FROM canonical_evidence e JOIN canonical_node_evidence l ON l.canonical_evidence_id=e.id "
            "JOIN canonical_nodes n ON n.id=l.canonical_node_id WHERE n.canonical_key=? "
            "ORDER BY e.run_id DESC, e.evidence_key LIMIT 1", (key,),
        ).fetchone()
        assert original is not None
        node_id = connection.execute("SELECT id FROM canonical_nodes WHERE canonical_key=?", (key,)).fetchone()[0]
        start = connection.execute("SELECT count(*) FROM canonical_evidence WHERE run_id=? AND evidence_key LIKE ?",
                                   (original[1], original[3] + ":alternative:%")).fetchone()[0]
        for i in range(count):
            values = dict(zip(columns, original[1:]))
            values["evidence_key"] += f":alternative:{start + i:05d}"
            if path is not None:
                values["path"] = path
            if metadata is not None:
                values["metadata_json"] = json.dumps(metadata)
            inserted = connection.execute(
                "INSERT INTO canonical_evidence (" + ",".join(columns) + ") VALUES ("
                + ",".join("?" for _ in columns) + ")", tuple(values.values()),
            )
            connection.execute("INSERT INTO canonical_node_evidence VALUES (?, ?, 'observed')",
                               (node_id, inserted.lastrowid))


def fixture_oracle(database: Path, binding: str, prefix: str | None = None) -> dict[str, tuple[Any, ...] | None]:
    """Independent full, uncapped fixture oracle; no production predicate calls.

    Covers the generic safe corpus and explicit fixture mutations, not arbitrary
    sanitizer policy. All rows may be materialized here ONLY inside tests.
    """
    with sqlite3.connect(database) as connection:
        accepted = connection.execute("SELECT run_id FROM accepted_publication").fetchone()[0]
        rows = connection.execute(
            "SELECT n.canonical_key,n.kind,n.display_name,e.run_id,l.link_kind,e.raw_kind,e.path,"
            "e.metadata_json,r.snapshot_vector_json FROM canonical_nodes n "
            "JOIN canonical_node_evidence l ON l.canonical_node_id=n.id "
            "JOIN canonical_evidence e ON e.id=l.canonical_evidence_id "
            "JOIN runs r ON r.id=e.run_id WHERE n.graph_key_version=1 AND e.graph_key_version=1"
        ).fetchall()
    subjects: dict[str, list[Any]] = {}
    for row in rows:
        if row[1].startswith("doc.") and any("needle" in str(value).lower() for value in row[:3]):
            subjects.setdefault(row[0], []).append(row)
    result = {}
    role_kinds = {"doc.page": "markdown.document", "doc.section": "markdown.heading",
                  "doc.adr": "markdown.adr_metadata", "doc.skill": "markdown.skill_metadata"}

    def safe(value: Any) -> bool:
        return (isinstance(value, str) and bool(value) and len(value) <= 500
                and not value.startswith(("/", "~")) and ":" not in value and "\\" not in value
                and all(part not in {"", ".", ".."} for part in value.split("/"))
                and not any(ord(char) < 32 or ord(char) == 127 for char in value)
                and not any(mark in value for mark in ("[REDACTED]", "[private-", "...[truncated]")))

    for key, alternatives in subjects.items():
        selected = accepted if any(r[3] == accepted for r in alternatives) else max(r[3] for r in alternatives)
        destinations = []
        admitted = False
        for _, kind, _, run, link, raw_kind, graph_path, metadata, vector in alternatives:
            if run != selected or link != "observed" or raw_kind != role_kinds.get(kind, kind):
                continue
            source = json.loads(metadata)
            entries = [v for v in json.loads(vector) if v[0] == source.get("binding_id")]
            path = source.get("source_relative_path")
            valid = (safe(path) and safe(graph_path) and len(entries) == 1
                     and entries[0][2] == source.get("snapshot_id")
                     and entries[0][1] == source.get("binding_revision", entries[0][1]))
            destination = (source["binding_id"], path, selected) if valid else None
            destinations.append(destination)
            if valid and source["binding_id"] == binding:
                clean_prefix = None if prefix is None else prefix.rstrip("/")
                admitted |= clean_prefix is None or path == clean_prefix or path.startswith(clean_prefix + "/")
        if admitted:
            result[key] = destinations[0] if destinations and all(d == destinations[0] for d in destinations) else None
    return dict(sorted(result.items()))
