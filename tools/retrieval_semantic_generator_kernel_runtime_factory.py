"""Fixed native-runtime construction after kernel artifact verification."""

from __future__ import annotations

from pathlib import Path

from retrieval_semantic_generator_runtime import (
    NativeRuntimeAdapter,
    RuntimeAdapter,
    RuntimeFactory,
    RuntimeProfile,
)
from retrieval_semantic_generator_kernel_runtime_types import NativeRuntimeModules


def build_native_runtime(
    profile: RuntimeProfile,
    model_path: Path,
    tokenizer_path: Path,
    modules: NativeRuntimeModules,
) -> RuntimeAdapter:
    """Construct the fixed adapter only after the kernel verifies artifacts."""

    return NativeRuntimeAdapter(profile, model_path, tokenizer_path, modules)


def make_native_runtime_factory(modules: NativeRuntimeModules) -> RuntimeFactory:
    """Bind the exact module bundle for a trusted phase-private controller."""

    def create(
        profile: RuntimeProfile, model_path: Path, tokenizer_path: Path
    ) -> RuntimeAdapter:
        return build_native_runtime(profile, model_path, tokenizer_path, modules)

    return create
