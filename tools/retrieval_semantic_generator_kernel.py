"""Bounded offline BGE CPU embedding kernel.

The parent lifecycle owns artifact admission, public-input eligibility, and
publication. This module rechecks fixed model files before importing the
optional runtime and keeps the inference boundary deliberately narrow.
"""

from __future__ import annotations

import time
from typing import Sequence

from retrieval_semantic_generator_kernel_contracts import (
    CONFIG_SHA256,
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
    SemanticCost,
    SemanticEmbedding,
    SemanticGeneration,
    SemanticKernelError,
    SemanticKernelProfile,
    SemanticMode,
    SemanticText,
    TOKENIZER_CONFIG_SHA256,
    TOKENIZER_SHA256,
    TOKENIZERS_VERSION,
)
from retrieval_semantic_generator_kernel_validation import (
    validate_duration,
    validate_profile,
    validate_tokenized,
    validate_vectors,
    validated_inputs,
    verify_artifacts,
)
from retrieval_semantic_generator_runtime import (
    RuntimeAdapter,
    RuntimeAdapterError,
    RuntimeFactory,
    TokenizedRecord,
)


class SemanticGeneratorKernel:
    """Generate bounded embeddings through a trusted fixed-runtime seam."""

    def __init__(
        self,
        profile: SemanticKernelProfile,
        *,
        _runtime: RuntimeAdapter | None = None,
        runtime_factory: RuntimeFactory | None = None,
    ) -> None:
        """Keep runtime construction in the phase-private composition root."""
        if _runtime is not None and runtime_factory is not None:
            raise ValueError("runtime adapter and factory are mutually exclusive")
        self._profile = profile
        self._runtime = _runtime
        self._runtime_factory = runtime_factory

    def generate(self, records: Sequence[SemanticText]) -> SemanticGeneration:
        started = time.monotonic()
        profile = self._profile
        model_dir = validate_profile(profile)
        snapshot, model_texts, modes, source_bytes, model_bytes = validated_inputs(
            records
        )

        if self._runtime is None:
            model_path, tokenizer_path = verify_artifacts(profile, model_dir)
            if self._runtime_factory is None:
                raise SemanticKernelError(
                    "runtime_unavailable",
                    "trusted runtime factory is required for native execution",
                )
            try:
                runtime = self._runtime_factory(profile, model_path, tokenizer_path)
            except RuntimeAdapterError as exc:
                raise SemanticKernelError(
                    exc.code, "runtime boundary refused"
                ) from exc
        else:
            runtime = self._runtime

        try:
            tokenized = runtime.tokenize(model_texts, max_tokens=profile.max_tokens)
            validate_tokenized(
                tokenized, max_tokens=profile.max_tokens, expected=len(snapshot)
            )
            inference_started = time.monotonic()
            vectors = runtime.embed(tokenized)
            inference_seconds = time.monotonic() - inference_started
        except SemanticKernelError:
            raise
        except RuntimeAdapterError as exc:
            raise SemanticKernelError(
                exc.code, "runtime boundary refused"
            ) from exc
        except Exception as exc:
            raise SemanticKernelError(
                "runtime_failure", "semantic runtime failed"
            ) from exc

        validate_vectors(
            vectors, expected=len(snapshot), dimensions=profile.dimensions
        )
        embeddings = tuple(
            SemanticEmbedding(
                record.record_id,
                mode,
                tuple(float(value) for value in vector),
                item.token_count_before_limit,
                item.token_count_used,
                item.overflow_chunks,
                item.truncated,
            )
            for record, mode, item, vector in zip(
                snapshot, modes, tokenized, vectors, strict=True
            )
        )
        truncated_records = sum(item.truncated for item in tokenized)
        load_seconds = validate_duration(
            runtime.load_seconds, field="load duration"
        )
        inference_seconds = validate_duration(
            inference_seconds, field="inference duration"
        )
        total_seconds = validate_duration(
            time.monotonic() - started, field="total duration"
        )
        cost = SemanticCost(
            input_records=len(snapshot),
            input_bytes=source_bytes,
            model_input_bytes=model_bytes,
            token_count_before_limit=sum(
                item.token_count_before_limit for item in tokenized
            ),
            token_count_used=sum(item.token_count_used for item in tokenized),
            overflow_chunks=sum(item.overflow_chunks for item in tokenized),
            truncated_records=truncated_records,
            load_seconds=load_seconds,
            inference_seconds=inference_seconds,
            total_seconds=total_seconds,
        )
        partial = truncated_records > 0
        return SemanticGeneration(
            embeddings, cost, "partial" if partial else "complete", partial
        )


__all__ = [
    "CONFIG_SHA256",
    "MAX_BATCH_SIZE",
    "MAX_RECORD_ID_BYTES",
    "MAX_RECORD_TEXT_BYTES",
    "MAX_TOTAL_TEXT_BYTES",
    "MODEL_DIMENSIONS",
    "MODEL_MAX_TOKENS",
    "MODEL_REVISION",
    "MODEL_SHA256",
    "NUMPY_VERSION",
    "ONNX_RUNTIME_VERSION",
    "QUERY_PREFIX",
    "SemanticCost",
    "SemanticEmbedding",
    "SemanticGeneration",
    "SemanticGeneratorKernel",
    "SemanticKernelError",
    "SemanticKernelProfile",
    "SemanticMode",
    "SemanticText",
    "TOKENIZER_CONFIG_SHA256",
    "TOKENIZER_SHA256",
    "TOKENIZERS_VERSION",
    "TokenizedRecord",
]
