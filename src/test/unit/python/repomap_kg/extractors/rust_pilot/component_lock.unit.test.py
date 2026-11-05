"""ADR 0155 component lock: exact artifacts, closed members, notices, identity."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from importlib import resources

import pytest

from common_lore_index.extractors.rust_pilot import component_lock as lock


def test_exactly_two_packages_on_two_cpus_with_locked_totals() -> None:
    assert {(w.package, w.version, w.cpu) for w in lock.WHEELS} == {
        (p, v, c) for p, v in (("tree-sitter", "0.26.0"), ("tree-sitter-rust", "0.24.2")) for c in lock.CPUS}
    assert sum(w.size for w in lock.WHEELS) == lock.UNIQUE_ARTIFACT_BYTES == 1_642_452
    for wheel in lock.WHEELS:
        assert wheel.url.startswith("https://files.pythonhosted.org/packages/") and wheel.url.endswith(wheel.filename)
        assert ("cp313-cp313" if wheel.package == "tree-sitter" else "cp39-abi3") in wheel.filename
        assert wheel.cpu in wheel.filename and len({m.name for m in wheel.members}) == len(wheel.members)
        assert wheel.member(wheel.record_name).wheel_mode == 0o664
        assert wheel.member(wheel.extension).wheel_mode == 0o755
        assert wheel.elf.machine == {"aarch64": 183, "x86_64": 62}[wheel.cpu]
        assert wheel.elf.needed == ("libc.so.6", "libpthread.so.0") and wheel.elf.nx_stack and wheel.elf.relro
        assert all(len(m.sha256) == 64 and int(m.sha256, 16) >= 0 for m in wheel.members)
        tops = {m.name.split("/", 1)[0] for m in wheel.members}
        assert tops == set(wheel.top_level)
    assert [len(w.members) for w in lock.WHEELS] == [9, 9, 13, 13]


def test_wheels_for_cpu_returns_the_binding_then_grammar_pair_or_refuses() -> None:
    binding, grammar = lock.wheels_for_cpu("x86_64")
    assert (binding.package, grammar.package) == ("tree-sitter", "tree-sitter-rust")
    for cpu in ("arm64", "amd64", "riscv64", ""):
        with pytest.raises(KeyError):
            lock.wheels_for_cpu(cpu)


def test_lock_identity_is_the_canonical_json_digest() -> None:
    document = lock.lock_document()
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    assert lock.LOCK_SHA256 == hashlib.sha256(encoded).hexdigest()
    assert document["lock_id"] == "rust-pilot-lock-1" and document["schema"] == lock.LOCK_SCHEMA
    mutated = json.loads(encoded)
    mutated["wheels"][0]["members"][0][2] = "0" * 64
    assert lock.digest_json(mutated) != lock.LOCK_SHA256


def test_supplemental_notices_ship_unchanged_as_package_data() -> None:
    package = resources.files("common_lore_index").joinpath("third_party_licenses")
    for notice in lock.NOTICES:
        data = package.joinpath(notice.package_file).read_bytes()
        assert (len(data), hashlib.sha256(data).hexdigest()) == (notice.size, notice.sha256)
    record = json.loads(package.joinpath("tree-sitter-rust-pilot-source.json").read_text(encoding="utf-8"))
    assert {item["sha256"] for item in record["supplemental_notices"]} == {n.sha256 for n in lock.NOTICES}
    assert record["redistribution"]["wheels_redistributed_by_repomap"] is False
    assert {item["license_sha256"] for item in record["components"]} == {
        lock.wheels_for_cpu("aarch64")[0].member("tree_sitter-0.26.0.dist-info/licenses/LICENSE").sha256,
        lock.wheels_for_cpu("aarch64")[1].member("tree_sitter_rust-0.24.2.dist-info/licenses/LICENSE").sha256}


def test_lock_module_imports_only_the_standard_library() -> None:
    tree = ast.parse(resources.files(lock.__package__).joinpath("component_lock.py").read_text(encoding="ascii"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}
