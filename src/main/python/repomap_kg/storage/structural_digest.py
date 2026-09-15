"""Memory-bounded semantic digest for the seven final storage families."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
import hashlib
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from repomap_kg.storage.external_row_sort import (
    ExternalRowSortError,
    external_sort_encoded_rows,
)
from repomap_kg.storage.structural_digest_encoding import (
    CanonicalJsonEncodingError,
    iter_canonical_json_chunks,
    iter_text_chunks,
)

if TYPE_CHECKING:
    from repomap_kg.storage.staged_rows import PreparedStageRows


class StructuralDigestError(ValueError):
    """Raised when a semantic family stream violates the digest contract."""


class _DigestWriter(Protocol):
    def update(self, payload: bytes) -> None: ...


STRUCTURAL_DIGEST_FIELDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "files": (
            "path",
            "language",
            "role",
            "content_hash",
            "executable",
            "generated",
            "metadata_json",
        ),
        "raw_observations": (
            "source_ordinal",
            "schema_version",
            "kind",
            "source_id",
            "path",
            "payload_json",
            "payload_hash",
        ),
        "canonical_nodes": (
            "graph_key_version",
            "canonical_key",
            "kind",
            "display_name",
            "metadata_json",
            "confidence",
            "conflict",
        ),
        "canonical_edges": (
            "graph_key_version",
            "source_canonical_key",
            "edge_kind",
            "target_canonical_key",
            "identity_metadata_json",
            "identity_metadata_hash",
            "metadata_json",
            "confidence",
            "conflict",
        ),
        "canonical_evidence": (
            "graph_key_version",
            "evidence_key",
            "raw_observation_ordinal",
            "raw_schema_version",
            "raw_kind",
            "raw_source_id",
            "path",
            "start_line",
            "end_line",
            "extractor",
            "extractor_version",
            "confidence",
            "metadata_json",
        ),
        "canonical_node_evidence": (
            "canonical_key",
            "evidence_key",
            "link_kind",
        ),
        "canonical_edge_evidence": (
            "source_canonical_key",
            "edge_kind",
            "target_canonical_key",
            "identity_metadata_hash",
            "evidence_key",
            "link_kind",
        ),
    }
)

# The accepted whole-graph implementation used sort_keys=True at the top level.
STRUCTURAL_DIGEST_FAMILY_CODES = tuple(sorted(STRUCTURAL_DIGEST_FIELDS))

# These positions preserve the terminal readback queries' accepted ORDER BY
# clauses. Identity fields are non-null in the storage contract.
_STRUCTURAL_DIGEST_ORDER_INDEXES: Mapping[str, tuple[int, ...]] = (
    MappingProxyType(
        {
            "files": (0,),
            "raw_observations": (0,),
            "canonical_nodes": (0, 1),
            "canonical_edges": (0, 1, 2, 3, 5),
            "canonical_evidence": (0, 1),
            "canonical_node_evidence": (0, 1, 2),
            "canonical_edge_evidence": (0, 1, 2, 3, 4, 5),
        }
    )
)
_STRUCTURAL_DIGEST_ORDER_TYPES: Mapping[str, tuple[type, ...]] = (
    MappingProxyType(
        {
            "files": (str,),
            "raw_observations": (int,),
            "canonical_nodes": (int, str),
            "canonical_edges": (int, str, str, str, str),
            "canonical_evidence": (int, str),
            "canonical_node_evidence": (str, str, str),
            "canonical_edge_evidence": (str, str, str, str, str, str),
        }
    )
)

@dataclass(frozen=True)
class StructuralDigestFamily:
    """One exact semantic family and its already ordered row stream."""

    family_code: str
    ordered_rows: Iterable[Sequence[object] | _EncodedStructuralDigestRow]


@dataclass(frozen=True)
class _EncodedStructuralDigestRow:
    text: str


def structural_digest(
    families: Iterable[StructuralDigestFamily],
    *,
    cancellation_check: Callable[[], None] | None = None,
    chunk_observer: Callable[[int], None] | None = None,
) -> str:
    """Return the accepted SHA-256 digest without materializing the graph."""

    digest = hashlib.sha256()
    family_iterator = iter(families)
    try:
        _update(digest, b"{", cancellation_check, chunk_observer)
        for index, expected_family in enumerate(
            STRUCTURAL_DIGEST_FAMILY_CODES
        ):
            try:
                family = next(family_iterator)
            except StopIteration as error:
                raise StructuralDigestError(
                    "structural digest family is missing"
                ) from error
            if (
                not isinstance(family, StructuralDigestFamily)
                or family.family_code != expected_family
            ):
                raise StructuralDigestError(
                    "structural digest family order is invalid"
                )
            if index:
                _update(digest, b",", cancellation_check, chunk_observer)
            _encode_json(
                expected_family,
                digest,
                cancellation_check,
                chunk_observer,
            )
            _update(digest, b":[", cancellation_check, chunk_observer)
            _encode_rows(
                family,
                digest,
                cancellation_check,
                chunk_observer,
            )
            _update(digest, b"]", cancellation_check, chunk_observer)
        try:
            next(family_iterator)
        except StopIteration:
            pass
        else:
            raise StructuralDigestError(
                "structural digest family is unexpected"
            )
        _update(digest, b"}", cancellation_check, chunk_observer)
        _check_cancellation(cancellation_check)
        return digest.hexdigest()
    finally:
        _close_iterator(family_iterator)


def digest_prepared_stage_rows(
    prepared: PreparedStageRows,
    *,
    cancellation_check: Callable[[], None] | None = None,
    chunk_observer: Callable[[int], None] | None = None,
    artifact_observer: Callable[[int, int], None] | None = None,
) -> str:
    """Project prepared staging rows directly into the semantic digest."""

    family_codes = set(prepared.family_rows)
    expected = set(STRUCTURAL_DIGEST_FAMILY_CODES)
    if family_codes != expected:
        raise StructuralDigestError(
            "prepared structural digest families are invalid"
        )
    families = (
        StructuralDigestFamily(
            family,
            _ordered_prepared_rows(
                prepared.family_rows[family],
                family,
                STRUCTURAL_DIGEST_FIELDS[family],
                cancellation_check,
                artifact_observer,
            ),
        )
        for family in STRUCTURAL_DIGEST_FAMILY_CODES
    )
    return structural_digest(
        families,
        cancellation_check=cancellation_check,
        chunk_observer=chunk_observer,
    )


def _ordered_prepared_rows(
    rows: Iterable[Mapping[str, object]],
    family: str,
    fields: tuple[str, ...],
    cancellation_check: Callable[[], None] | None,
    artifact_observer: Callable[[int, int], None] | None,
) -> Iterator[_EncodedStructuralDigestRow]:
    try:
        for encoded in external_sort_encoded_rows(
            _project_prepared_rows(rows, fields),
            key_indexes=_STRUCTURAL_DIGEST_ORDER_INDEXES[family],
            field_count=len(fields),
            key_types=_STRUCTURAL_DIGEST_ORDER_TYPES[family],
            cancellation_check=cancellation_check,
            artifact_observer=artifact_observer,
        ):
            yield _EncodedStructuralDigestRow(encoded)
    except ExternalRowSortError as error:
        raise StructuralDigestError(
            "prepared structural digest ordering failed"
        ) from error


def _encode_rows(
    family: StructuralDigestFamily,
    digest: _DigestWriter,
    cancellation_check: Callable[[], None] | None,
    chunk_observer: Callable[[int], None] | None,
) -> None:
    row_iterator = iter(family.ordered_rows)
    expected_fields = len(STRUCTURAL_DIGEST_FIELDS[family.family_code])
    first = True
    try:
        for row in row_iterator:
            _check_cancellation(cancellation_check)
            if not first:
                _update(digest, b",", cancellation_check, chunk_observer)
            if isinstance(row, _EncodedStructuralDigestRow):
                _encode_canonical_row(
                    row.text,
                    digest,
                    cancellation_check,
                    chunk_observer,
                )
            else:
                if (
                    not isinstance(row, (tuple, list))
                    or len(row) != expected_fields
                ):
                    raise StructuralDigestError(
                        "structural digest row is invalid"
                    )
                _encode_json(
                    row,
                    digest,
                    cancellation_check,
                    chunk_observer,
                )
            first = False
    finally:
        _close_iterator(row_iterator)


def _encode_json(
    value: object,
    digest: _DigestWriter,
    cancellation_check: Callable[[], None] | None,
    chunk_observer: Callable[[int], None] | None,
) -> None:
    try:
        for encoded_text in iter_canonical_json_chunks(
            value,
            cancellation_check,
        ):
            _update(
                digest,
                encoded_text.encode("ascii"),
                cancellation_check,
                chunk_observer,
            )
    except CanonicalJsonEncodingError as error:
        raise StructuralDigestError(
            "structural digest row value is invalid"
        ) from error


def _encode_canonical_row(
    encoded: str,
    digest: _DigestWriter,
    cancellation_check: Callable[[], None] | None,
    chunk_observer: Callable[[int], None] | None,
) -> None:
    for encoded_text in iter_text_chunks(encoded, cancellation_check):
        _update(
            digest,
            encoded_text.encode("ascii"),
            cancellation_check,
            chunk_observer,
        )


def _project_prepared_rows(
    rows: Iterable[Mapping[str, object]],
    fields: tuple[str, ...],
) -> Iterator[tuple[object, ...]]:
    iterator = iter(rows)
    try:
        for row in iterator:
            if not isinstance(row, Mapping):
                raise StructuralDigestError(
                    "prepared structural digest row is invalid"
                )
            try:
                yield tuple(row[field] for field in fields)
            except KeyError as error:
                raise StructuralDigestError(
                    "prepared structural digest row is invalid"
                ) from error
    finally:
        _close_iterator(iterator)


def _update(
    digest: _DigestWriter,
    payload: bytes,
    cancellation_check: Callable[[], None] | None,
    chunk_observer: Callable[[int], None] | None,
) -> None:
    _check_cancellation(cancellation_check)
    digest.update(payload)
    if chunk_observer is not None:
        chunk_observer(len(payload))


def _check_cancellation(
    cancellation_check: Callable[[], None] | None,
) -> None:
    if cancellation_check is not None:
        cancellation_check()


def _close_iterator(iterator: object) -> None:
    close = getattr(iterator, "close", None)
    if callable(close):
        close()


__all__ = (
    "STRUCTURAL_DIGEST_FAMILY_CODES",
    "STRUCTURAL_DIGEST_FIELDS",
    "StructuralDigestError",
    "StructuralDigestFamily",
    "digest_prepared_stage_rows",
    "structural_digest",
)
