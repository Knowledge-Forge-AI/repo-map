"""Typed interfaces for the optional numeric runtime boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, Protocol, Sequence, runtime_checkable


class _Array(Protocol):
    shape: Sequence[int]
    dtype: object

    def __getitem__(self, index: object) -> "_Array": ...

    def __iter__(self) -> Iterator[object]: ...

    def __le__(self, other: int) -> "_BooleanArray": ...

    def astype(self, dtype: object) -> "_Array": ...

    def __truediv__(self, other: "_Array") -> "_Array": ...


class _BooleanArray(Protocol):
    def all(self) -> bool: ...

    def any(self) -> bool: ...


@runtime_checkable
class _Floatable(Protocol):
    """Runtime values that can be converted to a finite Python float."""

    def __float__(self) -> float: ...


class _LinearAlgebra(Protocol):
    def norm(self, value: _Array, *, axis: int, keepdims: bool) -> _Array: ...


class NumpyModule(Protocol):
    __version__: str
    int64: object
    float64: object
    linalg: _LinearAlgebra

    def asarray(self, value: Sequence[Sequence[int]], *, dtype: object) -> _Array: ...

    def isfinite(self, value: _Array) -> _BooleanArray: ...


class _Encoding(Protocol):
    ids: Sequence[int]
    attention_mask: Sequence[int]
    type_ids: Sequence[int]
    overflowing: Sequence[object]


class _Tokenizer(Protocol):
    def no_padding(self) -> None: ...

    def no_truncation(self) -> None: ...

    def enable_truncation(
        self,
        *,
        max_length: int,
        stride: int,
        strategy: str,
        direction: str,
    ) -> None: ...

    def enable_padding(
        self,
        *,
        length: int,
        direction: str,
        pad_id: int,
        pad_token: str,
    ) -> None: ...

    def encode_batch(
        self, values: list[str], *, add_special_tokens: bool
    ) -> Sequence[_Encoding]: ...

    def token_to_id(self, token: str) -> int | None: ...


class _TokenizerType(Protocol):
    @staticmethod
    def from_file(path: str) -> _Tokenizer: ...


class TokenizersModule(Protocol):
    Tokenizer: _TokenizerType


class _ExecutionMode(Protocol):
    ORT_SEQUENTIAL: object


class _SessionOptions(Protocol):
    execution_mode: object
    intra_op_num_threads: int
    inter_op_num_threads: int
    enable_profiling: bool


class _NodeArg(Protocol):
    name: str
    type: str
    shape: Sequence[object]


class _Session(Protocol):
    def get_providers(self) -> Sequence[str]: ...

    def get_inputs(self) -> Sequence[_NodeArg]: ...

    def get_outputs(self) -> Sequence[_NodeArg]: ...

    def run(
        self, names: Sequence[str], feed: dict[str, _Array]
    ) -> Sequence[object]: ...


class OnnxRuntimeModule(Protocol):
    __version__: str
    ExecutionMode: _ExecutionMode
    SessionOptions: Callable[[], _SessionOptions]

    def InferenceSession(
        self,
        model: bytes,
        *,
        sess_options: _SessionOptions,
        providers: Sequence[str],
    ) -> _Session: ...


@dataclass(frozen=True, slots=True)
class NativeRuntimeModules:
    """Exact optional modules supplied by the trusted composition root."""

    numpy: NumpyModule
    onnxruntime: OnnxRuntimeModule
    tokenizers: TokenizersModule
    tokenizers_version: str


__all__ = [
    "NativeRuntimeModules",
    "NumpyModule",
    "OnnxRuntimeModule",
    "TokenizersModule",
]
