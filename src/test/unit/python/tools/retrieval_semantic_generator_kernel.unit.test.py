"""Unit contracts for the dependency-free semantic generator kernel."""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import retrieval_semantic_generator_kernel as kernel
from retrieval_semantic_generator_runtime import (
    NativeRuntimeAdapter,
    RuntimeAdapterError,
    RuntimeProfile,
)
from retrieval_semantic_generator_kernel_runtime_types import (
    _Array,
    _Session,
    NumpyModule,
)


class FakeRuntime:
    def __init__(self, *, before: tuple[int, ...] = (3,)) -> None:
        self.load_seconds = 0.25
        self.before = before
        self.tokenized_calls = 0
        self.embed_calls = 0
        self.last_texts: tuple[str, ...] = ()
        self.vector_count_override: int | None = None
        self.bad_vector: object | None = None
        self.accounting_override: str | None = None

    def tokenize(
        self, texts: tuple[str, ...], *, max_tokens: int
    ) -> tuple[kernel.TokenizedRecord, ...]:
        self.tokenized_calls += 1
        self.last_texts = texts
        result = []
        for index, _text in enumerate(texts):
            before = (
                self.before[index]
                if index < len(self.before)
                else self.before[-1]
            )
            used = min(before, max_tokens)
            record = kernel.TokenizedRecord(
                ids=(1,) * max_tokens,
                attention_mask=(1,) * used + (0,) * (max_tokens - used),
                type_ids=(0,) * max_tokens,
                token_count_before_limit=before,
                token_count_used=used,
                overflow_chunks=1 if before > max_tokens else 0,
                truncated=before > max_tokens,
            )
            if self.accounting_override == "used":
                record = replace(record, token_count_used=max(0, used - 1))
            elif self.accounting_override == "overflow":
                record = replace(record, overflow_chunks=1)
            elif self.accounting_override == "truncated":
                record = replace(record, truncated=not record.truncated)
            result.append(record)
        return tuple(result)

    def embed(
        self, batch: tuple[kernel.TokenizedRecord, ...]
    ) -> tuple[tuple[float, ...], ...]:
        self.embed_calls += 1
        count = (
            self.vector_count_override
            if self.vector_count_override is not None
            else len(batch)
        )
        vector: object = (
            self.bad_vector
            if self.bad_vector is not None
            else (1.0,) + (0.0,) * (kernel.MODEL_DIMENSIONS - 1)
        )
        return tuple(
            cast(tuple[float, ...], vector) for _ in range(count)
        )


class _FakeBooleanArray:
    def all(self) -> bool:
        return True

    def any(self) -> bool:
        return False


class _FakeArray:
    def __init__(self, shape: tuple[int, ...], rows: tuple[object, ...] = ()) -> None:
        self.shape = shape
        self.dtype = "float32"
        self._rows = rows

    def __getitem__(self, index: object) -> "_FakeArray":
        if isinstance(index, tuple) and len(index) == 3:
            return _FakeArray(
                (self.shape[0], self.shape[2]),
                ((1.0, 0.0),) * self.shape[0],
            )
        return self

    def __iter__(self) -> Iterator[object]:
        return iter(self._rows)

    def __le__(self, _other: int) -> _FakeBooleanArray:
        return _FakeBooleanArray()

    def astype(self, _dtype: object) -> "_FakeArray":
        return self

    def __truediv__(self, _other: _Array) -> "_FakeArray":
        return self


class _FakeLinearAlgebra:
    def norm(
        self, value: _Array, *, axis: int, keepdims: bool
    ) -> _FakeArray:
        del axis, keepdims
        return _FakeArray((value.shape[0], 1), ((1.0,),) * value.shape[0])


class _FakeNumpy:
    __version__ = "2.5.4"
    int64 = object()
    float64 = object()
    linalg = _FakeLinearAlgebra()

    def asarray(
        self, value: Sequence[Sequence[int]], *, dtype: object
    ) -> _FakeArray:
        del dtype
        return _FakeArray((len(value), 2, 2))

    def isfinite(self, _value: _Array) -> _FakeBooleanArray:
        return _FakeBooleanArray()


class _FakeSession:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.fail_on_call = fail_on_call
        self.batch_sizes: list[int] = []

    def run(
        self, _names: Sequence[str], feed: dict[str, _Array]
    ) -> list[_FakeArray]:
        self.batch_sizes.append(feed["input_ids"].shape[0])
        if self.fail_on_call == len(self.batch_sizes):
            raise RuntimeError("controlled later chunk failure")
        return [_FakeArray((1, 2, 2), ((1.0, 0.0),))]


def _native_test_adapter(session: _FakeSession) -> NativeRuntimeAdapter:
    adapter = object.__new__(NativeRuntimeAdapter)
    adapter._np = cast(NumpyModule, _FakeNumpy())
    adapter._profile = SimpleNamespace(max_tokens=2, dimensions=2)
    # The constructor-owned graph/provider methods are outside this embed seam.
    adapter._session = cast(_Session, session)
    adapter._output_name = "last_hidden_state"
    return adapter


def _token_record() -> kernel.TokenizedRecord:
    return kernel.TokenizedRecord(
        ids=(1, 1),
        attention_mask=(1, 1),
        type_ids=(0, 0),
        token_count_before_limit=2,
        token_count_used=2,
        overflow_chunks=0,
        truncated=False,
    )


def _profile(tmp_path) -> kernel.SemanticKernelProfile:
    return kernel.SemanticKernelProfile(model_dir=tmp_path)


def _record(
    record_id: str = "node-1",
    text: str = "canonical node",
    mode: kernel.SemanticMode | str = "document",
) -> kernel.SemanticText:
    return kernel.SemanticText(record_id=record_id, text=text, mode=mode)


def test_generation_preserves_order_applies_query_prefix_and_reports_cost(
    tmp_path,
) -> None:
    runtime = FakeRuntime(before=(3, kernel.MODEL_MAX_TOKENS + 1))
    generator = kernel.SemanticGeneratorKernel(_profile(tmp_path), _runtime=runtime)

    result = generator.generate((_record(), _record("query-1", "find this", "query")))

    assert [item.record_id for item in result.embeddings] == ["node-1", "query-1"]
    assert [item.mode for item in result.embeddings] == [
        kernel.SemanticMode.DOCUMENT,
        kernel.SemanticMode.QUERY,
    ]
    assert runtime.last_texts[1] == kernel.QUERY_PREFIX + "find this"
    assert result.status == "partial" and result.partial is True
    assert result.embeddings[1].token_count_before_limit == kernel.MODEL_MAX_TOKENS + 1
    assert result.cost.token_count_before_limit == kernel.MODEL_MAX_TOKENS + 4
    assert result.cost.truncated_records == 1
    assert result.cost.token_count_used == kernel.MODEL_MAX_TOKENS + 3


@pytest.mark.parametrize(
    ("records", "code"),
    [
        ((_record("same"), _record("same", "other")), "duplicate_record_id"),
        ((_record(mode="unknown"),), "invalid_mode"),
        ((_record(text="bad\x00text"),), "invalid_input"),
        ((_record(text="\ud800"),), "invalid_input"),
    ],
)
def test_invalid_inputs_refuse_before_runtime(records, code: str, tmp_path) -> None:
    runtime = FakeRuntime()
    generator = kernel.SemanticGeneratorKernel(_profile(tmp_path), _runtime=runtime)

    with pytest.raises(kernel.SemanticKernelError) as exc_info:
        generator.generate(records)

    assert exc_info.value.code == code
    assert runtime.tokenized_calls == 0
    assert runtime.embed_calls == 0


def test_batch_and_oversize_limits_are_strict(tmp_path) -> None:
    runtime = FakeRuntime()
    generator = kernel.SemanticGeneratorKernel(_profile(tmp_path), _runtime=runtime)

    with pytest.raises(kernel.SemanticKernelError, match="batch_limit"):
        generator.generate(
            tuple(
                _record(str(index)) for index in range(kernel.MAX_BATCH_SIZE + 1)
            )
        )
    with pytest.raises(kernel.SemanticKernelError, match="input_oversized"):
        generator.generate((_record(text="x" * (kernel.MAX_RECORD_TEXT_BYTES + 1)),))
    assert runtime.tokenized_calls == 0


def test_profile_values_are_not_caller_overridable(tmp_path) -> None:
    runtime = FakeRuntime()
    profile = kernel.SemanticKernelProfile(model_dir=tmp_path, dimensions=383)

    with pytest.raises(kernel.SemanticKernelError, match="profile_mismatch"):
        kernel.SemanticGeneratorKernel(profile, _runtime=runtime).generate((_record(),))
    assert runtime.tokenized_calls == 0


def test_native_generation_requires_and_uses_explicit_factory(
    tmp_path, monkeypatch
) -> None:
    runtime = FakeRuntime()
    events: list[str] = []
    model_path = tmp_path / "model.onnx"
    tokenizer_path = tmp_path / "tokenizer.json"

    def verify(_profile: object, _model_dir: object) -> tuple[Path, Path]:
        events.append("verify")
        return model_path, tokenizer_path

    expected_paths = (model_path, tokenizer_path)

    def factory(
        profile: RuntimeProfile,
        model_path: Path,
        tokenizer_path: Path,
    ) -> FakeRuntime:
        events.append("factory")
        assert (model_path, tokenizer_path) == expected_paths
        return runtime

    monkeypatch.setattr(kernel, "verify_artifacts", verify)
    with pytest.raises(kernel.SemanticKernelError, match="runtime_unavailable"):
        kernel.SemanticGeneratorKernel(_profile(tmp_path)).generate((_record(),))
    assert events == ["verify"]

    result = kernel.SemanticGeneratorKernel(
        _profile(tmp_path), runtime_factory=factory
    ).generate((_record(),))
    assert result.status == "complete"
    assert events == ["verify", "verify", "factory"]


def test_native_runtime_uses_one_record_microbatches() -> None:
    session = _FakeSession()
    adapter = _native_test_adapter(session)

    result = adapter.embed((_token_record(), _token_record()))

    assert len(result) == 2
    assert session.batch_sizes == [1, 1]


def test_native_runtime_validates_all_records_before_session_call() -> None:
    session = _FakeSession()
    adapter = _native_test_adapter(session)
    invalid = replace(_token_record(), token_count_used=1)

    with pytest.raises(RuntimeAdapterError, match="accounting"):
        adapter.embed((_token_record(), invalid))

    assert session.batch_sizes == []


def test_native_runtime_later_microbatch_failure_has_no_partial_result() -> None:
    session = _FakeSession(fail_on_call=2)
    adapter = _native_test_adapter(session)

    with pytest.raises(RuntimeAdapterError, match="inference"):
        adapter.embed((_token_record(), _token_record()))

    assert session.batch_sizes == [1, 1]


@pytest.mark.parametrize("override", ["used", "overflow", "truncated"])
def test_token_accounting_refuses_inconsistent_runtime(
    tmp_path, override: str
) -> None:
    runtime = FakeRuntime()
    runtime.accounting_override = override

    with pytest.raises(kernel.SemanticKernelError) as exc_info:
        kernel.SemanticGeneratorKernel(
            _profile(tmp_path), _runtime=runtime
        ).generate((_record(),))

    assert exc_info.value.code == "runtime_accounting"


@pytest.mark.parametrize(
    "failure", ["drop", "shape", "numeric", "wrong_type", "nonnumeric"]
)
def test_runtime_failures_cannot_publish_partial_vectors(
    tmp_path, failure: str
) -> None:
    runtime = FakeRuntime()
    if failure == "drop":
        runtime.vector_count_override = 0
    elif failure == "shape":
        runtime.bad_vector = (1.0,)
    elif failure == "numeric":
        runtime.bad_vector = (math.nan,) + (0.0,) * (kernel.MODEL_DIMENSIONS - 1)
    elif failure == "wrong_type":
        runtime.bad_vector = [1.0] * kernel.MODEL_DIMENSIONS
    else:
        runtime.bad_vector = ("not-a-number",) * kernel.MODEL_DIMENSIONS

    with pytest.raises(kernel.SemanticKernelError) as exc_info:
        kernel.SemanticGeneratorKernel(
            _profile(tmp_path), _runtime=runtime
        ).generate((_record(),))

    assert exc_info.value.code in {"runtime_drop", "runtime_shape", "runtime_numeric"}
