"""Artifact, input, token-accounting, and vector validation for BGE."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from numbers import Real
from pathlib import Path
from typing import Sequence, cast

from retrieval_semantic_generator_kernel_contracts import (
    CONFIG_SHA256,
    KNOWN_MODES,
    MAX_BATCH_SIZE,
    MAX_RECORD_ID_BYTES,
    MAX_RECORD_TEXT_BYTES,
    MAX_TOTAL_TEXT_BYTES,
    MODEL_DIMENSIONS,
    MODEL_MAX_TOKENS,
    MODEL_REVISION,
    MODEL_SHA256,
    NUMPY_VERSION,
    ONNX_RUNTIME_VERSION,
    QUERY_PREFIX,
    SemanticKernelError,
    SemanticKernelProfile,
    SemanticMode,
    SemanticText,
    TOKENIZER_CONFIG_SHA256,
    TOKENIZER_SHA256,
    TOKENIZERS_VERSION,
)
from retrieval_semantic_generator_runtime import TokenizedRecord


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _has_symlink_component(path: Path) -> bool:
    """Reject a symlink anywhere in the model path, including its parents."""

    absolute = path if path.is_absolute() else Path.cwd() / path
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        if current.is_symlink():
            return True
    return False


def validate_profile(profile: SemanticKernelProfile) -> Path:
    if not isinstance(profile, SemanticKernelProfile):
        raise SemanticKernelError("invalid_profile", "SemanticKernelProfile required")

    exact_strings = (
        (profile.revision, MODEL_REVISION),
        (profile.model_sha256, MODEL_SHA256),
        (profile.tokenizer_sha256, TOKENIZER_SHA256),
        (profile.onnxruntime_version, ONNX_RUNTIME_VERSION),
        (profile.tokenizers_version, TOKENIZERS_VERSION),
        (profile.numpy_version, NUMPY_VERSION),
        (profile.provider, "CPUExecutionProvider"),
        (profile.execution_mode, "ORT_SEQUENTIAL"),
    )
    if any(
        type(actual) is not str or actual != expected
        for actual, expected in exact_strings
    ):
        raise SemanticKernelError(
            "profile_mismatch", "fixed BGE CPU profile required"
        )

    exact_ints = (
        (profile.dimensions, MODEL_DIMENSIONS),
        (profile.max_tokens, MODEL_MAX_TOKENS),
        (profile.intra_op_threads, 1),
        (profile.inter_op_threads, 1),
    )
    if any(
        type(actual) is not int or actual != expected
        for actual, expected in exact_ints
    ):
        raise SemanticKernelError(
            "profile_mismatch", "fixed dimensions and thread limits required"
        )

    try:
        model_dir = Path(profile.model_dir)
    except (TypeError, ValueError) as exc:
        raise SemanticKernelError(
            "invalid_profile", "model directory is not a path"
        ) from exc
    if not model_dir.is_dir() or _has_symlink_component(model_dir):
        raise SemanticKernelError("artifact_refused", "model directory is unavailable")
    return model_dir


def _require_artifact(path: Path, expected_sha256: str) -> None:
    if _has_symlink_component(path) or not path.is_file():
        raise SemanticKernelError(
            "artifact_refused", "pinned model artifact verification failed"
        )
    try:
        actual_sha256 = _sha256_file(path)
    except OSError as exc:
        raise SemanticKernelError(
            "artifact_refused", "pinned model artifact is unreadable"
        ) from exc
    if actual_sha256 != expected_sha256:
        raise SemanticKernelError(
            "artifact_refused", "pinned model artifact verification failed"
        )


def verify_artifacts(
    profile: SemanticKernelProfile, model_dir: Path
) -> tuple[Path, Path]:
    onnx_dir = model_dir / "onnx"
    if not onnx_dir.is_dir() or _has_symlink_component(onnx_dir):
        raise SemanticKernelError(
            "artifact_refused", "pinned ONNX directory is unavailable"
        )

    model_path = onnx_dir / "model.onnx"
    tokenizer_path = model_dir / "tokenizer.json"
    _require_artifact(model_path, profile.model_sha256)
    _require_artifact(tokenizer_path, profile.tokenizer_sha256)
    _require_artifact(model_dir / "config.json", CONFIG_SHA256)
    _require_artifact(model_dir / "tokenizer_config.json", TOKENIZER_CONFIG_SHA256)
    try:
        config: object = json.loads(
            (model_dir / "config.json").read_text(encoding="utf-8")
        )
        tokenizer_config: object = json.loads(
            (model_dir / "tokenizer_config.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SemanticKernelError(
            "artifact_refused", "pinned model metadata is unreadable"
        ) from exc
    if not isinstance(config, dict) or not isinstance(tokenizer_config, dict):
        raise SemanticKernelError(
            "artifact_refused", "pinned model metadata is not an object"
        )
    hidden_size: object = config.get("hidden_size")
    pad_token_id: object = config.get("pad_token_id")
    model_max_length: object = tokenizer_config.get("model_max_length")
    pad_token: object = tokenizer_config.get("pad_token")
    if (
        type(hidden_size) is not int
        or type(pad_token_id) is not int
        or type(model_max_length) is not int
        or hidden_size != MODEL_DIMENSIONS
        or pad_token_id != 0
        or model_max_length != MODEL_MAX_TOKENS
        or type(pad_token) is not str
    ):
        raise SemanticKernelError(
            "artifact_refused", "pinned model metadata does not match profile"
        )
    return model_path, tokenizer_path


def _validate_text(value: object, *, field: str, max_bytes: int) -> int:
    if type(value) is not str or not value.strip():
        raise SemanticKernelError("invalid_input", f"{field} must be non-empty text")
    if any(unicodedata.category(char) in {"Cc", "Cs"} for char in value):
        raise SemanticKernelError(
            "invalid_input", f"{field} contains a control character"
        )
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SemanticKernelError(
            "invalid_input", f"{field} is not strict UTF-8"
        ) from exc
    if len(encoded) > max_bytes:
        raise SemanticKernelError("input_oversized", f"{field} exceeds its byte limit")
    return len(encoded)


def validated_inputs(
    records: object,
) -> tuple[
    tuple[SemanticText, ...], tuple[str, ...], tuple[SemanticMode, ...], int, int
]:
    if isinstance(records, (str, bytes, bytearray)) or not isinstance(
        records, Sequence
    ):
        raise SemanticKernelError("invalid_input", "records must be a sequence")
    typed_records = cast(Sequence[object], records)
    if not 1 <= len(typed_records) <= MAX_BATCH_SIZE:
        raise SemanticKernelError(
            "batch_limit", "record count must be between one and five hundred"
        )

    seen: set[str] = set()
    snapshot: list[SemanticText] = []
    model_texts: list[str] = []
    modes: list[SemanticMode] = []
    source_bytes = 0
    model_bytes = 0
    for raw_record in typed_records:
        if not isinstance(raw_record, SemanticText):
            raise SemanticKernelError(
                "invalid_input", "records must contain SemanticText values"
            )
        record = raw_record
        id_bytes = _validate_text(
            record.record_id, field="record_id", max_bytes=MAX_RECORD_ID_BYTES
        )
        if record.record_id in seen:
            raise SemanticKernelError(
                "duplicate_record_id", "record IDs must be unique"
            )
        seen.add(record.record_id)
        text_bytes = _validate_text(
            record.text, field="text", max_bytes=MAX_RECORD_TEXT_BYTES
        )
        if isinstance(record.mode, SemanticMode):
            mode = record.mode
        elif type(record.mode) is str and record.mode in KNOWN_MODES:
            mode = SemanticMode(record.mode)
        else:
            raise SemanticKernelError(
                "invalid_mode", "mode must be exactly document or query"
            )
        model_text = (
            QUERY_PREFIX + record.text
            if mode is SemanticMode.QUERY
            else record.text
        )
        model_text_bytes = _validate_text(
            model_text, field="model text", max_bytes=MAX_RECORD_TEXT_BYTES
        )
        source_bytes += id_bytes + text_bytes
        model_bytes += model_text_bytes
        if source_bytes > MAX_TOTAL_TEXT_BYTES or model_bytes > MAX_TOTAL_TEXT_BYTES:
            raise SemanticKernelError(
                "input_oversized", "aggregate input bytes exceed the bounded limit"
            )
        snapshot.append(SemanticText(record.record_id, record.text, mode))
        model_texts.append(model_text)
        modes.append(mode)
    return tuple(snapshot), tuple(model_texts), tuple(modes), source_bytes, model_bytes


def validate_tokenized(
    batch: tuple[TokenizedRecord, ...], *, max_tokens: int, expected: int
) -> None:
    if type(batch) is not tuple or len(batch) != expected:
        raise SemanticKernelError(
            "runtime_drop", "runtime returned a different record count"
        )
    for item in batch:
        if not isinstance(item, TokenizedRecord):
            raise SemanticKernelError(
                "runtime_shape", "runtime returned an invalid token record"
            )
        if not (
            type(item.ids) is tuple
            and type(item.attention_mask) is tuple
            and type(item.type_ids) is tuple
            and len(item.ids)
            == len(item.attention_mask)
            == len(item.type_ids)
            == max_tokens
            and type(item.token_count_before_limit) is int
            and item.token_count_before_limit > 0
            and type(item.token_count_used) is int
            and type(item.overflow_chunks) is int
            and item.overflow_chunks >= 0
            and type(item.truncated) is bool
        ):
            raise SemanticKernelError(
                "runtime_shape", "runtime token accounting is invalid"
            )
        expected_used = min(item.token_count_before_limit, max_tokens)
        if item.token_count_used != expected_used or item.truncated is not (
            item.token_count_before_limit > max_tokens
        ):
            raise SemanticKernelError(
                "runtime_accounting", "runtime token limit accounting disagrees"
            )
        if not item.truncated and item.overflow_chunks != 0:
            raise SemanticKernelError(
                "runtime_accounting", "untruncated input cannot have overflow chunks"
            )
        if any(
            type(value) is not int or value < 0
            for value in (*item.ids, *item.type_ids)
        ):
            raise SemanticKernelError("runtime_shape", "runtime token IDs are invalid")
        if any(
            type(value) is not int or value not in {0, 1}
            for value in item.attention_mask
        ):
            raise SemanticKernelError(
                "runtime_shape", "runtime attention mask is invalid"
            )
        if sum(item.attention_mask) != item.token_count_used:
            raise SemanticKernelError(
                "runtime_accounting", "attention-mask token count disagrees"
            )


def validate_vectors(
    vectors: object, *, expected: int, dimensions: int
) -> None:
    if type(vectors) is not tuple:
        raise SemanticKernelError(
            "runtime_drop", "runtime returned a different vector count"
        )
    typed_vectors = cast(tuple[object, ...], vectors)
    if len(typed_vectors) != expected:
        raise SemanticKernelError(
            "runtime_drop", "runtime returned a different vector count"
        )
    for raw_vector in typed_vectors:
        if type(raw_vector) is not tuple:
            raise SemanticKernelError(
                "runtime_shape", "embedding dimension does not match profile"
            )
        vector = cast(tuple[object, ...], raw_vector)
        if len(vector) != dimensions:
            raise SemanticKernelError(
                "runtime_shape", "embedding dimension does not match profile"
            )
        normalized: list[float] = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, Real):
                raise SemanticKernelError(
                    "runtime_numeric", "embedding contains a non-finite value"
                )
            numeric = float(value)
            if not math.isfinite(numeric):
                raise SemanticKernelError(
                    "runtime_numeric", "embedding contains a non-finite value"
                )
            normalized.append(numeric)
        norm = math.sqrt(sum(value * value for value in normalized))
        if not math.isfinite(norm) or norm <= 0 or not math.isclose(
            norm, 1.0, abs_tol=1e-5, rel_tol=0.0
        ):
            raise SemanticKernelError(
                "runtime_numeric", "embedding is not unit-normalized"
            )


def validate_duration(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SemanticKernelError("runtime_accounting", f"{field} is invalid")
    duration = float(value)
    if not math.isfinite(duration) or duration < 0:
        raise SemanticKernelError("runtime_accounting", f"{field} is invalid")
    return duration
