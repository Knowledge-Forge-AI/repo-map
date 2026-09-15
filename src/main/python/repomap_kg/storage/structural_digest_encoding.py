"""One canonical JSON encoding authority for structural digest rows."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import json


class CanonicalJsonEncodingError(ValueError):
    """Raised when a structural digest value cannot be encoded."""


CANONICAL_JSON_ENCODER = json.JSONEncoder(
    ensure_ascii=True,
    sort_keys=True,
    separators=(",", ":"),
)
ENCODE_TEXT_CHUNK_CHARACTERS = 16_384


def iter_canonical_json_chunks(
    value: object,
    cancellation_check: Callable[[], None] | None = None,
) -> Iterator[str]:
    """Yield bounded chunks from the canonical structural JSON encoder."""

    try:
        encoded_parts = iter(CANONICAL_JSON_ENCODER.iterencode(value))
    except (TypeError, ValueError, OverflowError) as error:
        raise _encoding_error() from error
    while True:
        try:
            encoded_text = next(encoded_parts)
        except StopIteration:
            break
        except (TypeError, ValueError, OverflowError) as error:
            raise _encoding_error() from error
        yield from iter_text_chunks(encoded_text, cancellation_check)
    _check_cancellation(cancellation_check)


def iter_text_chunks(
    encoded_text: str,
    cancellation_check: Callable[[], None] | None = None,
) -> Iterator[str]:
    """Yield bounded chunks from an already canonical JSON value."""

    for offset in range(
        0,
        len(encoded_text),
        ENCODE_TEXT_CHUNK_CHARACTERS,
    ):
        _check_cancellation(cancellation_check)
        yield encoded_text[
            offset : offset + ENCODE_TEXT_CHUNK_CHARACTERS
        ]


def _check_cancellation(
    cancellation_check: Callable[[], None] | None,
) -> None:
    if cancellation_check is not None:
        cancellation_check()


def _encoding_error() -> CanonicalJsonEncodingError:
    return CanonicalJsonEncodingError(
        "canonical structural digest value is invalid"
    )
