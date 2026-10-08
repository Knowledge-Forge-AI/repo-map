"""Disk-backed cross-family semantic link validation for publication bundles."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Mapping


class DiskFamilyLinkValidator:
    """Validate referential integrity across bundle families with bounded memory."""

    def __init__(self, *, spool_dir: Path | str | None = None) -> None:
        import sqlite3

        self._spool_dir = Path(spool_dir) if spool_dir is not None else None
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = tempfile.TemporaryDirectory(
            prefix="repomap_links_",
            dir=str(self._spool_dir) if self._spool_dir is not None else None,
        )
        self._db_path = Path(self._temp_dir.name) / "links.db"
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA synchronous = OFF")
        self._conn.execute("PRAGMA journal_mode = OFF")
        self._conn.execute("PRAGMA temp_store = MEMORY")
        self._conn.execute("CREATE TABLE raw_ordinals (ordinal TEXT PRIMARY KEY)")
        self._conn.execute("CREATE TABLE node_keys (key TEXT PRIMARY KEY)")
        self._conn.execute(
            "CREATE TABLE edge_keys (src TEXT, kind TEXT, tgt TEXT, hash TEXT, "
            "PRIMARY KEY (src, kind, tgt, hash))"
        )
        self._conn.execute("CREATE TABLE evidence_keys (key TEXT PRIMARY KEY)")

        self._pending_raw_ordinals: list[tuple[str]] = []
        self._pending_node_keys: list[tuple[str]] = []
        self._pending_edge_keys: list[tuple[str, str, str, str]] = []
        self._pending_evidence_keys: list[tuple[str]] = []
        self._batch_size = 5000

    def record_raw_observation(self, record: Mapping[str, object]) -> None:
        key = json.dumps(record.get("source_ordinal"), separators=(",", ":"))
        self._pending_raw_ordinals.append((key,))
        if len(self._pending_raw_ordinals) >= self._batch_size:
            self._flush_raw_ordinals()

    def record_canonical_node(self, record: Mapping[str, object]) -> None:
        key = json.dumps(record.get("canonical_key"), separators=(",", ":"))
        self._pending_node_keys.append((key,))
        if len(self._pending_node_keys) >= self._batch_size:
            self._flush_node_keys()

    def record_canonical_edge(self, record: Mapping[str, object]) -> None:
        src = json.dumps(record.get("source_canonical_key"), separators=(",", ":"))
        kind = json.dumps(record.get("edge_kind"), separators=(",", ":"))
        tgt = json.dumps(record.get("target_canonical_key"), separators=(",", ":"))
        hash_val = json.dumps(record.get("identity_metadata_hash"), separators=(",", ":"))
        self._pending_edge_keys.append((src, kind, tgt, hash_val))
        if len(self._pending_edge_keys) >= self._batch_size:
            self._flush_edge_keys()

    def record_and_validate_evidence(self, record: Mapping[str, object]) -> None:
        self._flush_raw_ordinals()
        raw_ord = json.dumps(record.get("raw_observation_ordinal"), separators=(",", ":"))
        cursor = self._conn.execute(
            "SELECT 1 FROM raw_ordinals WHERE ordinal = ? LIMIT 1", (raw_ord,)
        )
        if cursor.fetchone() is None:
            raise ValueError("bundle semantic evidence reference is invalid")
        ev_key = json.dumps(record.get("evidence_key"), separators=(",", ":"))
        self._pending_evidence_keys.append((ev_key,))
        if len(self._pending_evidence_keys) >= self._batch_size:
            self._flush_evidence_keys()

    def validate_node_evidence(self, record: Mapping[str, object]) -> None:
        self._flush_node_keys()
        self._flush_evidence_keys()
        node_key = json.dumps(record.get("canonical_key"), separators=(",", ":"))
        ev_key = json.dumps(record.get("evidence_key"), separators=(",", ":"))
        cursor = self._conn.execute(
            "SELECT 1 FROM node_keys WHERE key = ? LIMIT 1", (node_key,)
        )
        if cursor.fetchone() is None:
            raise ValueError("bundle semantic node evidence reference is invalid")
        cursor = self._conn.execute(
            "SELECT 1 FROM evidence_keys WHERE key = ? LIMIT 1", (ev_key,)
        )
        if cursor.fetchone() is None:
            raise ValueError("bundle semantic node evidence reference is invalid")

    def validate_edge_evidence(self, record: Mapping[str, object]) -> None:
        self._flush_edge_keys()
        self._flush_evidence_keys()
        src = json.dumps(record.get("source_canonical_key"), separators=(",", ":"))
        kind = json.dumps(record.get("edge_kind"), separators=(",", ":"))
        tgt = json.dumps(record.get("target_canonical_key"), separators=(",", ":"))
        hash_val = json.dumps(record.get("identity_metadata_hash"), separators=(",", ":"))
        ev_key = json.dumps(record.get("evidence_key"), separators=(",", ":"))
        cursor = self._conn.execute(
            "SELECT 1 FROM edge_keys WHERE src = ? AND kind = ? AND tgt = ? AND hash = ? LIMIT 1",
            (src, kind, tgt, hash_val),
        )
        if cursor.fetchone() is None:
            raise ValueError("bundle semantic edge evidence reference is invalid")
        cursor = self._conn.execute(
            "SELECT 1 FROM evidence_keys WHERE key = ? LIMIT 1", (ev_key,)
        )
        if cursor.fetchone() is None:
            raise ValueError("bundle semantic edge evidence reference is invalid")

    def finish_family(self, family: str) -> None:
        """Flush buffers and drop tables that are no longer needed."""
        if family == "raw_observations":
            self._flush_raw_ordinals()
        elif family == "canonical_nodes":
            self._flush_node_keys()
        elif family == "canonical_edges":
            self._flush_edge_keys()
        elif family == "canonical_evidence":
            self._flush_evidence_keys()
            self._conn.execute("DROP TABLE IF EXISTS raw_ordinals")
        elif family == "canonical_node_evidence":
            self._conn.execute("DROP TABLE IF EXISTS node_keys")
        elif family == "canonical_edge_evidence":
            self._conn.execute("DROP TABLE IF EXISTS edge_keys")
            self._conn.execute("DROP TABLE IF EXISTS evidence_keys")

    def _flush_raw_ordinals(self) -> None:
        if self._pending_raw_ordinals:
            self._conn.executemany(
                "INSERT OR IGNORE INTO raw_ordinals VALUES (?)", self._pending_raw_ordinals
            )
            self._conn.commit()
            self._pending_raw_ordinals.clear()

    def _flush_node_keys(self) -> None:
        if self._pending_node_keys:
            self._conn.executemany(
                "INSERT OR IGNORE INTO node_keys VALUES (?)", self._pending_node_keys
            )
            self._conn.commit()
            self._pending_node_keys.clear()

    def _flush_edge_keys(self) -> None:
        if self._pending_edge_keys:
            self._conn.executemany(
                "INSERT OR IGNORE INTO edge_keys VALUES (?, ?, ?, ?)", self._pending_edge_keys
            )
            self._conn.commit()
            self._pending_edge_keys.clear()

    def _flush_evidence_keys(self) -> None:
        if self._pending_evidence_keys:
            self._conn.executemany(
                "INSERT OR IGNORE INTO evidence_keys VALUES (?)", self._pending_evidence_keys
            )
            self._conn.commit()
            self._pending_evidence_keys.clear()

    def close(self) -> None:
        """Close database connection and clean up temp files."""
        try:
            self._conn.close()
        except Exception:
            pass
        if self._temp_dir is not None:
            try:
                self._temp_dir.cleanup()
            finally:
                self._temp_dir = None

    def __enter__(self) -> DiskFamilyLinkValidator:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
