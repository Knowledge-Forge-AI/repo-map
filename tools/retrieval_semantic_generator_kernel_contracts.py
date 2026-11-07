"""Public contracts and fixed limits for the offline BGE kernel."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal


MODEL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
MODEL_SHA256 = "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35"
TOKENIZER_SHA256 = (
    "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"
)
CONFIG_SHA256 = "094f8e891b932f2000c92cfc663bac4c62069f5d8af5b5278c4306aef3084750"
TOKENIZER_CONFIG_SHA256 = (
    "9261e7d79b44c8195c1cada2b453e55b00aeb81e907a6664974b4d7776172ab3"
)
ONNX_RUNTIME_VERSION = "1.31.1"
TOKENIZERS_VERSION = "0.23.3"
NUMPY_VERSION = "2.5.4"
MODEL_DIMENSIONS = 384
MODEL_MAX_TOKENS = 512
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MAX_BATCH_SIZE = 500
MAX_RECORD_TEXT_BYTES = 1024 * 1024
MAX_TOTAL_TEXT_BYTES = 8 * 1024 * 1024
MAX_RECORD_ID_BYTES = 512


class SemanticMode(str, Enum):
    """The only input modes admitted by the fixed generator."""

    DOCUMENT = "document"
    QUERY = "query"


class SemanticKernelError(ValueError):
    """A bounded, non-sensitive kernel refusal or runtime failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class SemanticText:
    """One explicitly named text input; privacy authority remains external."""

    record_id: str
    text: str
    mode: SemanticMode | str


@dataclass(frozen=True, slots=True)
class SemanticKernelProfile:
    """The fixed runtime profile; every field is revalidated at execution."""

    model_dir: str | Path
    revision: str = MODEL_REVISION
    model_sha256: str = MODEL_SHA256
    tokenizer_sha256: str = TOKENIZER_SHA256
    onnxruntime_version: str = ONNX_RUNTIME_VERSION
    tokenizers_version: str = TOKENIZERS_VERSION
    numpy_version: str = NUMPY_VERSION
    dimensions: int = MODEL_DIMENSIONS
    max_tokens: int = MODEL_MAX_TOKENS
    provider: str = "CPUExecutionProvider"
    execution_mode: str = "ORT_SEQUENTIAL"
    intra_op_threads: int = 1
    inter_op_threads: int = 1


@dataclass(frozen=True, slots=True)
class SemanticCost:
    input_records: int
    input_bytes: int
    model_input_bytes: int
    token_count_before_limit: int
    token_count_used: int
    overflow_chunks: int
    truncated_records: int
    load_seconds: float
    inference_seconds: float
    total_seconds: float


@dataclass(frozen=True, slots=True)
class SemanticEmbedding:
    record_id: str
    mode: SemanticMode
    vector: tuple[float, ...]
    token_count_before_limit: int
    token_count_used: int
    overflow_chunks: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class SemanticGeneration:
    embeddings: tuple[SemanticEmbedding, ...]
    cost: SemanticCost
    status: Literal["complete", "partial"]
    partial: bool


KNOWN_MODES = frozenset(mode.value for mode in SemanticMode)


__all__ = [
    "CONFIG_SHA256",
    "KNOWN_MODES",
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
    "SemanticKernelError",
    "SemanticKernelProfile",
    "SemanticMode",
    "SemanticText",
    "TOKENIZER_CONFIG_SHA256",
    "TOKENIZER_SHA256",
    "TOKENIZERS_VERSION",
]
