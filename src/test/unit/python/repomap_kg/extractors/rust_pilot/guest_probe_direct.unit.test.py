"""Direct pure-Python ownership of the maintained runtime-probe guest source."""

from __future__ import annotations

from collections.abc import Callable
from io import StringIO
import json
from types import ModuleType
import sys
from typing import Any

import pytest

from common_lore_index.extractors.rust_pilot.guest import runtime_probe
from common_lore_index.extractors.rust_pilot.construction import (
    EXPECTED_ABI_VERSION,
    EXPECTED_PYTHON,
    MIN_GLIBC,
    REQUIRED_FIELDS,
    REQUIRED_KINDS,
    ConstructionRefused,
    check_runtime_facts,
)


class _FakeBindingModule(ModuleType):
    __version__: str
    LANGUAGE_VERSION: int
    MIN_COMPATIBLE_LANGUAGE_VERSION: int
    Language: type[Any]


class _FakeGrammarModule(ModuleType):
    language: Callable[[], object]


def _fake_pair(version: str = "0.26.0", abi: int = EXPECTED_ABI_VERSION) -> tuple[
        _FakeBindingModule, _FakeGrammarModule]:
    binding = _FakeBindingModule("tree_sitter")
    grammar = _FakeGrammarModule("tree_sitter_rust")

    class FakeLanguage:
        def __init__(self, _marker: object) -> None:
            self.abi_version = abi

        def id_for_node_kind(self, kind: str, named: bool) -> int | None:
            return len(kind) + 1 if named else None

        def field_id_for_name(self, name: str) -> int:
            return len(name) + 1

    binding.__version__ = version
    binding.LANGUAGE_VERSION = EXPECTED_ABI_VERSION
    binding.MIN_COMPATIBLE_LANGUAGE_VERSION = EXPECTED_ABI_VERSION - 2
    binding.Language = FakeLanguage
    binding.__file__ = runtime_probe.RUNTIME_ROOT + "/site/tree_sitter/__init__.py"
    grammar.__file__ = runtime_probe.RUNTIME_ROOT + "/site/tree_sitter_rust/__init__.py"
    grammar.language = lambda: object()
    return binding, grammar


def _run_probe(monkeypatch: pytest.MonkeyPatch, binding: _FakeBindingModule | None,
               grammar: _FakeGrammarModule | None,
               *arguments: str) -> tuple[int, dict[str, Any]]:
    old_path = list(runtime_probe.sys.path)
    output = StringIO()
    monkeypatch.setitem(sys.modules, "tree_sitter", binding)
    monkeypatch.setitem(sys.modules, "tree_sitter_rust", grammar)
    monkeypatch.setattr(runtime_probe.sys, "argv", ["runtime_probe.py", *arguments])
    monkeypatch.setattr(runtime_probe.sys, "stdout", output)
    try:
        code = runtime_probe.main()
    finally:
        runtime_probe.sys.path[:] = old_path
    return code, json.loads(output.getvalue())


class _Readable:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def __enter__(self) -> "_Readable":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int) -> bytes:
        return self.data


def test_cost_only_main_reads_only_the_isolated_cgroup_peak_path(
        monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[tuple[str, str]] = []

    def fake_open(path: str, mode: str) -> _Readable:
        opened.append((path, mode))
        if path.endswith("memory.peak"):
            return _Readable(b"4096\n")
        raise OSError("the first cgroup source should have stopped the probe")

    output = StringIO()
    monkeypatch.setattr(runtime_probe, "open", fake_open, raising=False)
    monkeypatch.setattr(runtime_probe.sys, "argv", ["runtime_probe.py", "--cost-only"])
    monkeypatch.setattr(runtime_probe.sys, "stdout", output)
    assert runtime_probe.main() == 0
    assert json.loads(output.getvalue()) == {
        "t": "cost", "memory_peak_bytes": 4096, "unavailable_reason": None,
    }
    assert opened == [("/sys/fs/cgroup/memory.peak", "rb")]


def test_cost_only_main_reports_unavailable_cgroup_without_fabricating_zero(
        monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []

    def missing_open(path: str, _mode: str) -> _Readable:
        opened.append(path)
        raise OSError("cgroup is intentionally absent")

    output = StringIO()
    monkeypatch.setattr(runtime_probe, "open", missing_open, raising=False)
    monkeypatch.setattr(runtime_probe.sys, "argv", ["runtime_probe.py", "--cost-only"])
    monkeypatch.setattr(runtime_probe.sys, "stdout", output)
    assert runtime_probe.main() == 0
    assert json.loads(output.getvalue()) == {
        "t": "cost", "memory_peak_bytes": None, "unavailable_reason": "cgroup_peak_unavailable",
    }
    assert opened == [
        "/sys/fs/cgroup/memory.peak",
        "/sys/fs/cgroup/memory/memory.max_usage_in_bytes",
    ]


def test_probe_main_reports_concrete_facts_from_strict_pure_fake_modules(
        monkeypatch: pytest.MonkeyPatch) -> None:
    binding, grammar = _fake_pair()
    code, facts = _run_probe(monkeypatch, binding, grammar)
    assert code == 0 and facts["t"] == "probe" and facts["import"] == "ok"
    assert facts["ts_version"] == "0.26.0" and facts["abi_version"] == EXPECTED_ABI_VERSION
    assert facts["module_files"] == [
        runtime_probe.RUNTIME_ROOT + "/site/tree_sitter/__init__.py",
        runtime_probe.RUNTIME_ROOT + "/site/tree_sitter_rust/__init__.py",
    ]
    assert facts["kind_ids"]["function_item"] == len("function_item") + 1
    assert facts["field_ids"]["body"] == len("body") + 1
    assert sys.modules.get("tree_sitter") is binding and sys.modules.get("tree_sitter_rust") is grammar


def test_blocked_native_names_produce_explicit_probe_import_refusal(
        monkeypatch: pytest.MonkeyPatch) -> None:
    code, facts = _run_probe(monkeypatch, None, None)
    assert code == 4 and facts["t"] == "probe" and facts["import"] == "failed"
    assert "ts_version" not in facts and sys.modules.get("tree_sitter") is None
    assert sys.modules.get("tree_sitter_rust") is None


def _contract_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Normalize host facts while retaining the direct probe's module identity."""

    cpu = "aarch64"  # synthetic contract CPU; never inherit host architecture
    glibc = ".".join(str(part) for part in MIN_GLIBC)
    return {
        **facts,
        "machine": cpu,
        "executable": EXPECTED_PYTHON[0],
        "version": EXPECTED_PYTHON[1],
        "cache_tag": EXPECTED_PYTHON[2],
        "soabi": f"cpython-313-{cpu}-linux-gnu",
        "abiflags": "",
        "libc": ["glibc", glibc],
        "min_compatible_language_version": EXPECTED_ABI_VERSION - 2,
        "abi_version": EXPECTED_ABI_VERSION,
        "language_version": EXPECTED_ABI_VERSION,
        "kind_ids": {kind: index + 1 for index, kind in enumerate(REQUIRED_KINDS)},
        "field_ids": {name: index + 1 for index, name in enumerate(REQUIRED_FIELDS)},
    }


def test_probe_version_mismatch_is_refused_by_parent_contract_with_fake_modules(
        monkeypatch: pytest.MonkeyPatch) -> None:
    good_binding, good_grammar = _fake_pair()
    _, good_probe = _run_probe(monkeypatch, good_binding, good_grammar)
    good_facts = _contract_facts(good_probe)
    check_runtime_facts(good_facts, good_facts["machine"])

    bad_binding, bad_grammar = _fake_pair(version="0.25.0")
    _, bad_probe = _run_probe(monkeypatch, bad_binding, bad_grammar)
    bad_facts = _contract_facts(bad_probe)
    assert bad_facts["ts_version"] == "0.25.0"
    with pytest.raises(ConstructionRefused, match="runtime_mismatch"):
        check_runtime_facts(bad_facts, bad_facts["machine"])


@pytest.mark.parametrize("lower", [True, None, 13.0])
def test_runtime_abi_range_rejects_non_integer_observations(
        monkeypatch: pytest.MonkeyPatch, lower: object) -> None:
    binding, grammar = _fake_pair()
    _, probe = _run_probe(monkeypatch, binding, grammar)
    facts = _contract_facts(probe)
    facts["min_compatible_language_version"] = lower
    with pytest.raises(ConstructionRefused, match="runtime_mismatch"):
        check_runtime_facts(facts, facts["machine"])
