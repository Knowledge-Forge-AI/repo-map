"""Reusable source selection contract, length-framed digest, and revalidation (W4 §5.1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from common_lore_index.retrieval.context_contracts import (
    ContextRequestError, ExpectedPublicationPin, MAX_BINDINGS,
    MAX_PREFIXES_PER_BINDING, MAX_SCAN_UNITS, SOURCE_SELECTION_SCHEMA_VERSION,
    valid_source_path_prefix,
)
from common_lore_index.retrieval.context_identity import (
    ContextIdentityError,
    normalize_accepted_publication,
)

SELECTION_FINGERPRINT_PREFIX = "select_ctx1:"
MAX_SELECTION_FILE_BYTES = 65536
SELECTION_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "schema", "graph_id", "backend", "scan_unit_count",
    "bindings", "expected_publication", "selection_fingerprint", "repository_id",
)
SELECTION_BINDING_KEYS: tuple[str, ...] = (
    "binding_id", "revision", "snapshot_id",
    "selection_policy_id", "source_definition_id", "path_prefixes",
)

def _frame_field(hasher: "hashlib._Hash", label: str, value: str | None) -> None:
    label_bytes = label.encode("utf-8")
    hasher.update(f"{len(label_bytes)}:".encode("ascii") + label_bytes + b"=")
    if value is None:
        hasher.update(b"null;")
    else:
        val_bytes = value.encode("utf-8")
        hasher.update(f"{len(val_bytes)}:".encode("ascii") + val_bytes + b";")

@dataclass(frozen=True, slots=True)
class SourceBindingSelection:
    """Single binding entry in cloe-source-selection-v1."""
    binding_id: str
    revision: int
    snapshot_id: str | None
    selection_policy_id: str
    source_definition_id: str
    path_prefixes: tuple[str, ...] = ()
    def validate(self) -> "SourceBindingSelection":
        if not isinstance(self.binding_id, str) or not self.binding_id.strip():
            raise ContextRequestError("invalid binding_id", refusal_reason="invalid_selection_record")
        if type(self.revision) is not int or self.revision < 1:
            raise ContextRequestError("revision must be int >= 1", refusal_reason="invalid_selection_record")
        if self.snapshot_id is not None and (
            not isinstance(self.snapshot_id, str) or not self.snapshot_id.strip()
        ):
            raise ContextRequestError("invalid snapshot_id", refusal_reason="invalid_selection_record")
        for sfield in (self.selection_policy_id, self.source_definition_id):
            if not isinstance(sfield, str) or not sfield.strip():
                raise ContextRequestError("invalid policy/definition id", refusal_reason="invalid_selection_record")
        if len(self.path_prefixes) > MAX_PREFIXES_PER_BINDING:
            raise ContextRequestError("prefix_limit_exceeded", refusal_reason="prefix_limit_exceeded")
        for pfx in self.path_prefixes:
            if not valid_source_path_prefix(pfx):
                raise ContextRequestError(f"invalid path_prefix: {pfx!r}", refusal_reason="invalid_selection_record")
        return self
    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id, "revision": self.revision,
            "snapshot_id": self.snapshot_id, "selection_policy_id": self.selection_policy_id,
            "source_definition_id": self.source_definition_id,
            "path_prefixes": list(self.path_prefixes),
        }


def compute_selection_fingerprint(
    *, schema: str = SOURCE_SELECTION_SCHEMA_VERSION, graph_id: str, repository_id: str,
    backend: str, scan_unit_count: int, bindings: Sequence[SourceBindingSelection],
    expected_publication: ExpectedPublicationPin | None,
) -> str:
    """Compute length-framed SHA-256 selection_fingerprint ('select_ctx1:<64-hex>')."""
    h = hashlib.sha256()
    val: str | None
    for lbl, val in (
        ("schema", schema), ("graph_id", graph_id), ("repository_id", repository_id),
        ("backend", backend), ("scan_unit_count", str(scan_unit_count)),
    ):
        _frame_field(h, lbl, val)
    sorted_bindings = sorted(bindings, key=lambda b: b.binding_id.encode("utf-8"))
    _frame_field(h, "bindings_count", str(len(sorted_bindings)))
    for idx, b in enumerate(sorted_bindings):
        for lbl, val in (
            (f"b[{idx}].binding_id", b.binding_id),
            (f"b[{idx}].revision", str(b.revision)),
            (f"b[{idx}].snapshot_id", b.snapshot_id),
            (f"b[{idx}].selection_policy_id", b.selection_policy_id),
            (f"b[{idx}].source_definition_id", b.source_definition_id),
            (f"b[{idx}].pfx_count", str(len(b.path_prefixes))),
        ):
            _frame_field(h, lbl, val)
        for p_idx, pfx in enumerate(b.path_prefixes):
            _frame_field(h, f"b[{idx}].pfx[{p_idx}]", pfx)
    if expected_publication is None:
        _frame_field(h, "expected_publication", None)
    else:
        for lbl, val in (
            ("pin.accepted_run_id", str(expected_publication.accepted_run_id)),
            ("pin.publication_bundle_id", expected_publication.publication_bundle_id),
            ("pin.snapshot_manifest_id", expected_publication.snapshot_manifest_id),
            ("pin.generation", str(expected_publication.generation)),
            ("pin.job_id", expected_publication.job_id),
            ("pin.attempt", str(expected_publication.attempt)),
            ("pin.extraction_receipt_id", expected_publication.extraction_receipt_id),
        ):
            _frame_field(h, lbl, val)
    return SELECTION_FINGERPRINT_PREFIX + h.hexdigest()

def compute_inline_scope_fingerprint(
    *, graph_id: str, repository_id: str, backend: str, selection_source: str,
    selected_binding_ids: Sequence[str], path_prefixes: Sequence[Mapping[str, str]],
) -> str:
    """Compute length-framed 'select_ctx1:<64-hex>' digest for inline/default scope."""
    h = hashlib.sha256()
    for lbl, val in (
        ("scope_kind", selection_source), ("graph_id", graph_id),
        ("repository_id", repository_id), ("backend", backend),
        ("binding_count", str(len(selected_binding_ids))),
    ):
        _frame_field(h, lbl, val)
    for idx, bid in enumerate(selected_binding_ids):
        _frame_field(h, f"bid[{idx}]", bid)
    _frame_field(h, "prefix_count", str(len(path_prefixes)))
    for idx, item in enumerate(path_prefixes):
        _frame_field(h, f"pfx[{idx}].binding_id", item["binding_id"])
        _frame_field(h, f"pfx[{idx}].prefix", item["prefix"])
    return SELECTION_FINGERPRINT_PREFIX + h.hexdigest()


@dataclass(frozen=True, slots=True)
class SourceSelectionRecord:
    """Validated cloe-source-selection-v1 record."""
    schema: str
    graph_id: str
    backend: str
    scan_unit_count: int
    bindings: tuple[SourceBindingSelection, ...]
    expected_publication: ExpectedPublicationPin | None
    selection_fingerprint: str
    repository_id: str
    @classmethod
    def build(
        cls, *, graph_id: str, repository_id: str, backend: str,
        bindings: Sequence[SourceBindingSelection],
        expected_publication: ExpectedPublicationPin | None = None,
    ) -> "SourceSelectionRecord":
        sorted_bindings = tuple(sorted(bindings, key=lambda b: b.binding_id.encode("utf-8")))
        scan_units = sum(max(1, len(b.path_prefixes)) for b in sorted_bindings)
        fp = compute_selection_fingerprint(
            graph_id=graph_id, repository_id=repository_id, backend=backend,
            scan_unit_count=scan_units, bindings=sorted_bindings,
            expected_publication=expected_publication,
        )
        return cls(
            schema=SOURCE_SELECTION_SCHEMA_VERSION, graph_id=graph_id, backend=backend,
            scan_unit_count=scan_units, bindings=sorted_bindings,
            expected_publication=expected_publication, selection_fingerprint=fp,
            repository_id=repository_id,
        ).validate()
    def validate(self) -> "SourceSelectionRecord":
        if (
            self.schema != SOURCE_SELECTION_SCHEMA_VERSION
            or not isinstance(self.graph_id, str) or not self.graph_id.strip()
            or self.backend not in {"sqlite", "postgresql"}
            or not isinstance(self.repository_id, str) or not self.repository_id.startswith("repo1:")
        ):
            raise ContextRequestError("invalid selection header", refusal_reason="invalid_selection_record")
        if not (1 <= len(self.bindings) <= MAX_BINDINGS):
            raise ContextRequestError("binding_limit_exceeded", refusal_reason="binding_limit_exceeded")
        seen_ids: set[str] = set()
        expected_units = 0
        for b in self.bindings:
            b.validate()
            if b.binding_id in seen_ids:
                raise ContextRequestError("duplicate binding_id", refusal_reason="invalid_selection_record")
            seen_ids.add(b.binding_id)
            if (self.expected_publication is not None) != (b.snapshot_id is not None):
                raise ContextRequestError("snapshot_id pin mismatch", refusal_reason="invalid_selection_record")
            expected_units += max(1, len(b.path_prefixes))
        if expected_units > MAX_SCAN_UNITS:
            raise ContextRequestError("scan_unit_limit_exceeded", refusal_reason="scan_unit_limit_exceeded")
        if type(self.scan_unit_count) is not int or self.scan_unit_count != expected_units:
            raise ContextRequestError("scan_unit_count mismatch", refusal_reason="invalid_selection_record")
        if self.expected_publication is not None:
            self.expected_publication.validate()
        expected_fp = compute_selection_fingerprint(
            schema=self.schema, graph_id=self.graph_id, repository_id=self.repository_id,
            backend=self.backend, scan_unit_count=self.scan_unit_count,
            bindings=self.bindings, expected_publication=self.expected_publication,
        )
        if self.selection_fingerprint != expected_fp:
            raise ContextRequestError("selection_fingerprint mismatch", refusal_reason="selection_fingerprint_mismatch")
        return self
    def to_dict(self) -> dict[str, Any]:
        pin_dict = self.expected_publication.to_dict() if self.expected_publication is not None else None
        return {
            "schema": self.schema, "graph_id": self.graph_id, "backend": self.backend,
            "scan_unit_count": self.scan_unit_count, "bindings": [b.to_dict() for b in self.bindings],
            "expected_publication": pin_dict, "selection_fingerprint": self.selection_fingerprint,
            "repository_id": self.repository_id,
        }

def write_selection_file(record: SourceSelectionRecord, output_path: Path) -> bytes:
    """Write cloe-source-selection-v1 with O_EXCL and mode 0o600."""
    record.validate()
    raw = (
        json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(output_path), flags, 0o600)
    except FileExistsError as exc:
        raise ContextRequestError(
            f"selection output already exists: {output_path.name}",
            refusal_reason="selection_output_exists",
        ) from exc
    except OSError as exc:
        raise ContextRequestError(
            f"cannot write selection output: {exc.strerror}",
            refusal_reason="invalid_selection_record",
        ) from exc
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            if written <= 0 or written > len(raw) - offset:
                raise OSError("selection output write made no progress")
            offset += written
    except OSError as exc:
        try:
            os.unlink(output_path)
        except OSError:
            pass
        raise ContextRequestError(f"cannot write selection output: {exc}", refusal_reason="invalid_selection_record") from exc
    finally:
        os.close(fd)
    return raw

def read_selection_file(path: Path) -> SourceSelectionRecord:
    """Read and validate cloe-source-selection-v1 (O_NOFOLLOW | O_NONBLOCK, regular <= 64 KiB)."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise ContextRequestError(
            f"cannot open selection file: {exc.strerror or errno.errorcode.get(exc.errno or 0, 'io_error')}",
            refusal_reason="invalid_selection_record",
        ) from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_SELECTION_FILE_BYTES:
            raise ContextRequestError("invalid or oversize selection file", refusal_reason="invalid_selection_record")
        expected_size = st.st_size
        chunks: list[bytes] = []
        total = 0
        while True:
            current = os.fstat(fd)
            if (
                not stat.S_ISREG(current.st_mode)
                or current.st_size != expected_size
                or current.st_size > MAX_SELECTION_FILE_BYTES
            ):
                raise ContextRequestError(
                    "selection file changed while reading",
                    refusal_reason="invalid_selection_record",
                )
            if total >= MAX_SELECTION_FILE_BYTES:
                break
            remaining = MAX_SELECTION_FILE_BYTES - total
            chunk = os.read(fd, min(16384, remaining))
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_SELECTION_FILE_BYTES:
                raise ContextRequestError("oversize selection file", refusal_reason="invalid_selection_record")
            chunks.append(chunk)
        final = os.fstat(fd)
        if final.st_size != expected_size or final.st_size != total:
            raise ContextRequestError(
                "selection file changed while reading", refusal_reason="invalid_selection_record"
            )
        raw = b"".join(chunks)
    finally:
        os.close(fd)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContextRequestError("malformed selection JSON", refusal_reason="invalid_selection_record") from exc
    if not isinstance(payload, dict) or set(payload.keys()) != set(SELECTION_TOP_LEVEL_KEYS):
        raise ContextRequestError("closed schema violation in selection file", refusal_reason="invalid_selection_record")
    raw_bindings = payload.get("bindings")
    if not isinstance(raw_bindings, list) or not raw_bindings:
        raise ContextRequestError("bindings must be non-empty list", refusal_reason="invalid_selection_record")
    parsed_bindings: list[SourceBindingSelection] = []
    for item in raw_bindings:
        if not isinstance(item, dict) or set(item.keys()) != set(SELECTION_BINDING_KEYS):
            raise ContextRequestError("invalid binding object", refusal_reason="invalid_selection_record")
        pfxs = item.get("path_prefixes")
        if not isinstance(pfxs, list) or not all(isinstance(p, str) for p in pfxs):
            raise ContextRequestError("invalid path_prefixes", refusal_reason="invalid_selection_record")
        parsed_bindings.append(
            SourceBindingSelection(
                binding_id=item["binding_id"], revision=item["revision"],
                snapshot_id=item["snapshot_id"], selection_policy_id=item["selection_policy_id"],
                source_definition_id=item["source_definition_id"], path_prefixes=tuple(pfxs),
            )
        )
    raw_pin = payload.get("expected_publication")
    pin: ExpectedPublicationPin | None = None
    if raw_pin is not None:
        expected_pin_keys = {
            "accepted_run_id", "publication_bundle_id", "snapshot_manifest_id",
            "generation", "job_id", "attempt", "extraction_receipt_id",
        }
        if not isinstance(raw_pin, dict) or set(raw_pin.keys()) != expected_pin_keys:
            raise ContextRequestError("invalid expected_publication", refusal_reason="invalid_selection_record")
        pin = ExpectedPublicationPin(
            accepted_run_id=raw_pin["accepted_run_id"],
            publication_bundle_id=raw_pin["publication_bundle_id"],
            snapshot_manifest_id=raw_pin["snapshot_manifest_id"],
            generation=raw_pin["generation"], job_id=raw_pin["job_id"],
            attempt=raw_pin["attempt"], extraction_receipt_id=raw_pin["extraction_receipt_id"],
        )
    return SourceSelectionRecord(
        schema=payload["schema"], graph_id=payload["graph_id"], backend=payload["backend"],
        scan_unit_count=payload["scan_unit_count"], bindings=tuple(parsed_bindings),
        expected_publication=pin, selection_fingerprint=payload["selection_fingerprint"],
        repository_id=payload["repository_id"],
    ).validate()

def revalidate_selection_record(
    record: SourceSelectionRecord,
    *,
    live_graph_id: str,
    live_repository_id: str,
    live_backend: str,
    live_bindings_by_id: Mapping[str, Mapping[str, Any]],
    live_accepted: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    """Revalidate selection record against live config and accepted publication.

    Returns (status_override, reason) or (None, None) when valid.
    """
    if (
        record.graph_id != live_graph_id
        or record.repository_id != live_repository_id
        or record.backend != live_backend
    ):
        return "refused", "selection_graph_mismatch"
    for b in record.bindings:
        live_b = live_bindings_by_id.get(b.binding_id)
        if live_b is None:
            return "refused", "selection_binding_missing"
        live_revision = live_b.get("revision")
        if (
            live_b.get("source_definition_id") != b.source_definition_id
            or live_b.get("selection_policy_id") != b.selection_policy_id
            or type(live_revision) is not int
            or live_revision < 1
            or live_revision != b.revision
        ):
            return "refused", "selection_binding_changed"
    if live_accepted is None:
        return "unavailable", "publication_absent"
    try:
        normalized = normalize_accepted_publication(
            live_accepted, require_pin=record.expected_publication is not None
        )
    except (ContextIdentityError, TypeError):
        return "unavailable", "accepted_publication_unverified"
    if record.expected_publication is not None and not record.expected_publication.matches_accepted(
        normalized
    ):
        return "stale", "selection_publication_advanced"
    vec_map = {binding_id: (revision, snapshot_id) for binding_id, revision, snapshot_id in normalized["snapshot_vector"]}
    for b in record.bindings:
        if b.binding_id not in vec_map:
            return "refused", "selection_binding_missing"
        live_rev, live_snap = vec_map[b.binding_id]
        if live_rev != b.revision:
            return "refused", "selection_binding_changed"
        if b.snapshot_id is not None and live_snap != b.snapshot_id:
            if record.expected_publication is not None:
                return "stale", "selection_publication_advanced"
            return "refused", "selection_binding_changed"
    return None, None
