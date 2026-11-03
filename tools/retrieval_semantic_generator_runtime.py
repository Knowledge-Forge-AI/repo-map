"""Typed execution boundary for the optional fixed BGE runtime."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence, cast

from retrieval_semantic_generator_kernel_runtime_validation import validate_embed_batch
from retrieval_semantic_generator_kernel_runtime_types import (
    NativeRuntimeModules,
    _Array,
    _Floatable,
)


class RuntimeAdapterError(ValueError):
    """Bounded runtime refusal converted to the kernel error contract."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


class RuntimeProfile(Protocol):
    @property
    def numpy_version(self) -> str: ...

    @property
    def onnxruntime_version(self) -> str: ...

    @property
    def tokenizers_version(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    @property
    def max_tokens(self) -> int: ...

    @property
    def provider(self) -> str: ...


@dataclass(frozen=True, slots=True)
class TokenizedRecord:
    """Immutable token arrays and accounting for one accepted text."""

    ids: tuple[int, ...]
    attention_mask: tuple[int, ...]
    type_ids: tuple[int, ...]
    token_count_before_limit: int
    token_count_used: int
    overflow_chunks: int
    truncated: bool


class RuntimeAdapter(Protocol):
    """Internal seam; production factories come from a trusted controller."""

    @property
    def load_seconds(self) -> float: ...

    def tokenize(
        self, texts: tuple[str, ...], *, max_tokens: int
    ) -> tuple[TokenizedRecord, ...]: ...

    def embed(
        self, batch: tuple[TokenizedRecord, ...]
    ) -> tuple[tuple[float, ...], ...]: ...


class RuntimeFactory(Protocol):
    """Trusted composition-root callback after artifact admission."""

    def __call__(
        self, profile: RuntimeProfile, model_path: Path, tokenizer_path: Path
    ) -> RuntimeAdapter: ...


class NativeRuntimeAdapter:
    """The sole production adapter for an injected fixed runtime bundle."""

    _MAX_BATCH_SIZE = 500

    def __init__(
        self,
        profile: RuntimeProfile,
        model_path: Path,
        tokenizer_path: Path,
        modules: NativeRuntimeModules,
    ) -> None:
        np = modules.numpy
        ort = modules.onnxruntime
        tokenizers = modules.tokenizers
        tokenizers_version = modules.tokenizers_version
        if (
            np.__version__ != profile.numpy_version
            or ort.__version__ != profile.onnxruntime_version
            or tokenizers_version != profile.tokenizers_version
        ):
            raise RuntimeAdapterError(
                "runtime_mismatch", "approved runtime versions are required"
            )

        self._np = np
        self._profile = profile
        try:
            raw_config: object = json.loads(
                (tokenizer_path.parent / "tokenizer_config.json").read_text(
                    encoding="utf-8"
                )
            )
            tokenizer = tokenizers.Tokenizer.from_file(str(tokenizer_path))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeAdapterError(
                "tokenizer_refused", "pinned tokenizer could not be loaded"
            ) from exc
        if not isinstance(raw_config, dict):
            raise RuntimeAdapterError(
                "tokenizer_refused", "pinned tokenizer metadata is not an object"
            )
        pad_token: object = raw_config.get("pad_token")
        if type(pad_token) is not str or tokenizer.token_to_id(pad_token) != 0:
            raise RuntimeAdapterError(
                "tokenizer_refused", "pinned padding metadata does not match"
            )

        options = ort.SessionOptions()
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.enable_profiling = False
        started = time.monotonic()
        try:
            session = ort.InferenceSession(
                model_path.read_bytes(),
                sess_options=options,
                providers=[profile.provider],
            )
        except (OSError, ValueError, RuntimeError) as exc:
            raise RuntimeAdapterError(
                "runtime_load_failed", "pinned ONNX session could not be loaded"
            ) from exc
        self._load_seconds = time.monotonic() - started

        if tuple(session.get_providers()) != (profile.provider,):
            raise RuntimeAdapterError(
                "runtime_provider", "CPU-only execution provider was not selected"
            )
        inputs = session.get_inputs()
        expected_inputs = {"input_ids", "attention_mask", "token_type_ids"}
        if {item.name for item in inputs} != expected_inputs or any(
            item.type != "tensor(int64)" or len(item.shape) != 2 for item in inputs
        ):
            raise RuntimeAdapterError(
                "runtime_graph", "ONNX input contract differs from the observed profile"
            )
        outputs = session.get_outputs()
        if (
            len(outputs) != 1
            or outputs[0].name != "last_hidden_state"
            or outputs[0].type != "tensor(float)"
            or len(outputs[0].shape) != 3
            or outputs[0].shape[2] != profile.dimensions
        ):
            raise RuntimeAdapterError(
                "runtime_graph",
                "ONNX output contract differs from the observed profile",
            )
        self._tokenizer = tokenizer
        self._session = session
        self._output_name = outputs[0].name

    @property
    def load_seconds(self) -> float:
        return self._load_seconds

    def tokenize(
        self, texts: tuple[str, ...], *, max_tokens: int
    ) -> tuple[TokenizedRecord, ...]:
        try:
            self._tokenizer.no_padding()
            self._tokenizer.no_truncation()
            full = self._tokenizer.encode_batch(
                list(texts), add_special_tokens=True
            )
            self._tokenizer.enable_truncation(
                max_length=max_tokens,
                stride=0,
                strategy="longest_first",
                direction="right",
            )
            self._tokenizer.enable_padding(
                length=max_tokens,
                direction="right",
                pad_id=0,
                pad_token="[PAD]",
            )
            encoded = self._tokenizer.encode_batch(
                list(texts), add_special_tokens=True
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            raise RuntimeAdapterError(
                "tokenization_failed", "pinned tokenizer rejected the input"
            ) from exc

        result: list[TokenizedRecord] = []
        for before, item in zip(full, encoded, strict=True):
            result.append(
                TokenizedRecord(
                    ids=tuple(item.ids),
                    attention_mask=tuple(item.attention_mask),
                    type_ids=tuple(item.type_ids),
                    token_count_before_limit=len(before.ids),
                    token_count_used=sum(item.attention_mask),
                    overflow_chunks=len(item.overflowing),
                    truncated=len(before.ids) > max_tokens,
                )
            )
        return tuple(result)

    def embed(
        self, batch: tuple[TokenizedRecord, ...]
    ) -> tuple[tuple[float, ...], ...]:
        validate_embed_batch(
            batch,
            max_tokens=self._profile.max_tokens,
            max_batch_size=self._MAX_BATCH_SIZE,
            token_record_type=TokenizedRecord,
            error_type=RuntimeAdapterError,
        )
        np = self._np
        result: list[tuple[float, ...]] = []
        for item in batch:
            try:
                feed = {
                    "input_ids": np.asarray([item.ids], dtype=np.int64),
                    "attention_mask": np.asarray([item.attention_mask], dtype=np.int64),
                    "token_type_ids": np.asarray([item.type_ids], dtype=np.int64),
                }
                outputs = self._session.run([self._output_name], feed)
            except (TypeError, ValueError, RuntimeError) as exc:
                raise RuntimeAdapterError(
                    "runtime_inference_failed", "ONNX inference failed"
                ) from exc
            if len(outputs) != 1:
                raise RuntimeAdapterError(
                    "runtime_shape", "ONNX returned an unexpected output count"
                )

            raw = cast(_Array, outputs[0])
            if (
                tuple(raw.shape)
                != (1, self._profile.max_tokens, self._profile.dimensions)
                or str(raw.dtype) != "float32"
                or not np.isfinite(raw).all()
            ):
                raise RuntimeAdapterError(
                    "runtime_shape",
                    "ONNX output shape or finiteness differs from profile",
                )
            try:
                cls = raw[:, 0, :].astype(np.float64)
                norms = np.linalg.norm(cls, axis=1, keepdims=True)
            except (TypeError, ValueError, RuntimeError) as exc:
                raise RuntimeAdapterError(
                    "runtime_numeric", "CLS output cannot be normalized"
                ) from exc
            if not np.isfinite(norms).all() or (norms <= 0).any():
                raise RuntimeAdapterError(
                    "runtime_numeric", "CLS output cannot be normalized"
                )
            normalized = cls / norms
            try:
                for row in normalized:
                    values = cast(Sequence[object], row)
                    converted: list[float] = []
                    for value in values:
                        if isinstance(value, bool) or not isinstance(value, _Floatable):
                            raise TypeError("normalized output is not numeric")
                        numeric = float(value)
                        if not math.isfinite(numeric):
                            raise ValueError("normalized output is not finite")
                        converted.append(numeric)
                    result.append(tuple(converted))
            except (TypeError, ValueError, OverflowError) as exc:
                raise RuntimeAdapterError(
                    "runtime_numeric", "normalized output is not numeric"
                ) from exc
        return tuple(result)
