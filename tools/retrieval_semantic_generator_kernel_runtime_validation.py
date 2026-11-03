"""Fixed token-batch validation before native embedding calls."""

from __future__ import annotations

from typing import Protocol, cast


class _TokenRecordLike(Protocol):
    ids: tuple[int, ...]
    attention_mask: tuple[int, ...]
    type_ids: tuple[int, ...]
    token_count_before_limit: int
    token_count_used: int
    overflow_chunks: int
    truncated: bool


def validate_embed_batch(
    batch: tuple[object, ...],
    *,
    max_tokens: int,
    max_batch_size: int,
    token_record_type: type[object],
    error_type: type[ValueError],
) -> None:
    """Validate the complete batch before any session call is made."""

    if type(batch) is not tuple or not 1 <= len(batch) <= max_batch_size:
        raise error_type(
            "runtime_input", "runtime batch size is outside the fixed bound"
        )
    for item in batch:
        if not isinstance(item, token_record_type):
            raise error_type(
                "runtime_input", "runtime token record is invalid"
            )
        record = cast(_TokenRecordLike, item)
        if not (
            type(record.ids) is tuple
            and type(record.attention_mask) is tuple
            and type(record.type_ids) is tuple
            and len(record.ids)
            == len(record.attention_mask)
            == len(record.type_ids)
            == max_tokens
            and type(record.token_count_before_limit) is int
            and record.token_count_before_limit > 0
            and type(record.token_count_used) is int
            and type(record.overflow_chunks) is int
            and record.overflow_chunks >= 0
            and type(record.truncated) is bool
        ):
            raise error_type(
                "runtime_input", "runtime token record shape is invalid"
            )
        expected_used = min(record.token_count_before_limit, max_tokens)
        if record.token_count_used != expected_used or record.truncated is not (
            record.token_count_before_limit > max_tokens
        ):
            raise error_type(
                "runtime_input", "runtime token accounting is invalid"
            )
        if not record.truncated and record.overflow_chunks != 0:
            raise error_type(
                "runtime_input", "runtime overflow accounting is invalid"
            )
        if any(
            type(value) is not int or value < 0
            for value in (*record.ids, *record.type_ids)
        ):
            raise error_type(
                "runtime_input", "runtime token IDs are invalid"
            )
        if any(
            type(value) is not int or value not in {0, 1}
            for value in record.attention_mask
        ) or sum(record.attention_mask) != record.token_count_used:
            raise error_type(
                "runtime_input", "runtime attention accounting is invalid"
            )
