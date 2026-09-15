"""Installed typing and tool changes cannot inherit invocation authority."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ci import python_retention_environment as environment
from ci.python_retention_environment import fingerprint_inputs


def test_same_size_stub_edit_invalidates_binding(tmp_path: Path) -> None:
    stub = tmp_path / "example.pyi"
    stub.write_text("value: int\n")
    before = fingerprint_inputs({tmp_path}, set())
    stub.write_text("value: str\n")
    assert fingerprint_inputs({tmp_path}, set()) != before


def test_unrecorded_stub_addition_and_removal_invalidate_binding(tmp_path: Path) -> None:
    before = fingerprint_inputs({tmp_path}, set())
    stub = tmp_path / "unrecorded.pyi"
    stub.write_text("value: int\n")
    introduced = fingerprint_inputs({tmp_path}, set())
    assert introduced != before
    stub.unlink()
    assert fingerprint_inputs({tmp_path}, set()) != introduced


def test_console_binary_outside_package_root_is_bound(tmp_path: Path) -> None:
    package = tmp_path / "packages"
    package.mkdir()
    tool = tmp_path / "checker"
    tool.write_bytes(b"first")
    before = fingerprint_inputs({package}, {tool})
    tool.write_bytes(b"other")
    assert fingerprint_inputs({package}, {tool}) != before


def test_identity_change_with_identical_content_is_detected(tmp_path: Path) -> None:
    stub = tmp_path / "first.pyi"
    stub.write_text("value: int\n")
    before = fingerprint_inputs({tmp_path}, set())
    stub.rename(tmp_path / "other.pyi")
    assert fingerprint_inputs({tmp_path}, set()) != before


def test_generated_bytecode_does_not_invalidate_source_binding(tmp_path: Path) -> None:
    (tmp_path / "owner.py").write_text("value = 1\n")
    before = fingerprint_inputs({tmp_path}, set())
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "owner.pyc").write_bytes(b"generated")
    assert fingerprint_inputs({tmp_path}, set()) == before
    assert str(tmp_path) not in str(before)


def test_bind_environment_binds_versions_source_and_addition_without_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = tmp_path / "site-packages"
    site.mkdir()
    source = site / "checker.pyi"
    source.write_text("value: int\n", encoding="utf-8")
    binary = tmp_path / "bin" / "ruff"
    binary.parent.mkdir()
    binary.write_bytes(b"ruff-v1")
    executable = tmp_path / "python"
    executable.write_bytes(b"python-v1")

    class Distribution:
        metadata = {"Name": "synthetic-checker"}
        version = "1.0"
        files = ("checker.pyi", "bin/ruff")

        @staticmethod
        def locate_file(entry: object) -> Path:
            return source if str(entry) == "checker.pyi" else binary

    distribution = Distribution()
    monkeypatch.setattr(environment, "sys", SimpleNamespace(executable=str(executable)))
    monkeypatch.setattr(environment, "sysconfig",
                        SimpleNamespace(get_path=lambda name: str(site)))
    monkeypatch.setattr(environment, "importlib",
                        SimpleNamespace(metadata=SimpleNamespace(
                            distributions=lambda: [distribution])))

    first = environment.bind_environment()
    assert first["versions"] == [("synthetic-checker", "1.0")]
    assert first["input_count"] >= 3
    assert str(tmp_path) not in repr(first)

    source.write_text("value: str\n", encoding="utf-8")
    source_changed = environment.bind_environment()
    assert source_changed["sha256"] != first["sha256"]

    addition = site / "new_stub.pyi"
    addition.write_text("value: bytes\n", encoding="utf-8")
    addition_changed = environment.bind_environment()
    assert addition_changed["sha256"] != source_changed["sha256"]

    distribution.version = "2.0"
    version_changed = environment.bind_environment()
    assert version_changed["versions"] == [("synthetic-checker", "2.0")]
    assert str(tmp_path) not in repr(version_changed)
