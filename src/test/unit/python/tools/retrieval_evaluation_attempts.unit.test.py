"""Focused filesystem admission and journal tests for retrieval evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from retrieval_evaluation_attempts import admit_attempt


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _declaration(
    attempt_id: str = "attempt-1", source_files: dict[str, bytes] | None = None, **extra: object
) -> dict[str, object]:
    files = source_files or {"src/example.py": b"print('fixture')\n"}
    return {
        "attempt_id": attempt_id,
        "candidate_closure_digests": {path: _digest(data) for path, data in files.items()},
        "intended_output": "first-output.json",
        **extra,
    }


def test_duplicate_admission_refuses_different_intended_output(tmp_path: Path) -> None:
    source = {"src/example.py": b"print('fixture')\n"}
    declaration = _declaration(source_files=source)
    journal = admit_attempt(tmp_path / "attempts", declaration, source)

    duplicate = {**declaration, "intended_output": "different-output.json"}
    with pytest.raises(FileExistsError):
        admit_attempt(tmp_path / "attempts", duplicate, source)
    assert journal.directory.is_dir()
    assert (journal.directory / "declaration.json").is_file()


def test_source_mismatch_is_rejected_before_admission_directory_creation(tmp_path: Path) -> None:
    root = tmp_path / "attempts"
    declaration = _declaration(source_files={"src/example.py": b"expected\n"})

    with pytest.raises(ValueError, match="digest mismatch"):
        admit_attempt(root, declaration, {"src/example.py": b"different\n"})
    assert not root.exists()


@pytest.mark.parametrize("attempt_id", ["", ".", "..", "nested/id", r"nested\id", "/absolute", "C:drive"])
def test_unsafe_attempt_ids_are_rejected_before_directory_creation(
    tmp_path: Path, attempt_id: str
) -> None:
    root = tmp_path / "attempts"
    source = {"src/example.py": b"fixture\n"}

    with pytest.raises(ValueError, match="portable component"):
        admit_attempt(root, _declaration(attempt_id, source), source)
    assert not root.exists()


@pytest.mark.parametrize("path", ["", ".", "./src.py", "../escape.py", "src/../escape.py", "/absolute.py", r"src\escape.py"])
def test_unsafe_source_paths_are_rejected_before_directory_creation(
    tmp_path: Path, path: str
) -> None:
    root = tmp_path / "attempts"
    source = {path: b"fixture\n"}

    with pytest.raises(ValueError, match="archive paths"):
        admit_attempt(root, _declaration(source_files=source), source)
    assert not root.exists()


def test_declaration_and_report_are_immutable(tmp_path: Path) -> None:
    source = {"src/example.py": b"fixture\n"}
    declaration = _declaration(source_files=source)
    journal = admit_attempt(tmp_path / "attempts", declaration, source)
    declaration_bytes = (journal.directory / "declaration.json").read_bytes()

    with pytest.raises(FileExistsError):
        admit_attempt(tmp_path / "attempts", declaration, source)
    assert (journal.directory / "declaration.json").read_bytes() == declaration_bytes

    journal.finish("completed", {"result": "ok"})
    report_bytes = (journal.directory / "report.json").read_bytes()
    with pytest.raises(RuntimeError, match="already terminal"):
        journal.finish("failed", {"result": "changed"})
    assert (journal.directory / "report.json").read_bytes() == report_bytes


def test_failed_report_serialization_keeps_partial_observations_and_no_terminal(
    tmp_path: Path,
) -> None:
    source = {"src/example.py": b"fixture\n"}
    journal = admit_attempt(tmp_path / "attempts", _declaration(source_files=source), source)
    journal.append({"event": "query-start", "task_id": "task-1"})

    with pytest.raises(ValueError, match="finite canonical JSON"):
        journal.finish("failed", {"error": float("nan")})
    assert not (journal.directory / "terminal.json").exists()
    assert not (journal.directory / "report.json").exists()
    journal.append({"event": "query-result", "status": "failed"})
    journal.finish("failed", {"status": "failed"})

    observations = (journal.directory / "observations.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in observations] == ["query-start", "query-result"]
    assert json.loads((journal.directory / "terminal.json").read_text())[
        "status"
    ] == "failed"


def test_append_and_finish_after_terminal_are_refused(tmp_path: Path) -> None:
    source = {"src/example.py": b"fixture\n"}
    journal = admit_attempt(tmp_path / "attempts", _declaration(source_files=source), source)
    journal.append({"event": "query-result", "status": "completed"})
    journal.finish("completed")

    with pytest.raises(RuntimeError, match="terminal"):
        journal.append({"event": "late"})
    with pytest.raises(RuntimeError, match="already terminal"):
        journal.finish("completed")


def test_archive_manifest_and_declaration_hashes_are_consistent(tmp_path: Path) -> None:
    source = {"src/example.py": b"fixture\n", "src/nested.txt": b"text\n"}
    inputs = {"fixture/input.json": b"{\"fixture\":true}\n"}
    declaration = _declaration(source_files=source)
    journal = admit_attempt(tmp_path / "attempts", declaration, source, input_files=inputs)

    declaration_bytes = (journal.directory / "declaration.json").read_bytes()
    archive_bytes = (journal.directory / "sources.zip").read_bytes()
    manifest = json.loads((journal.directory / "source-manifest.json").read_text())
    assert journal.declaration_sha256 == _digest(declaration_bytes)
    assert manifest["archive_sha256"] == _digest(archive_bytes)
    assert manifest["source_files"] == {path: _digest(data) for path, data in sorted(source.items())}
    assert manifest["input_files"] == {path: _digest(data) for path, data in sorted(inputs.items())}

    with zipfile.ZipFile(journal.directory / "sources.zip") as archive:
        assert set(archive.namelist()) == {
            "sources/src/example.py",
            "sources/src/nested.txt",
            "inputs/fixture/input.json",
        }
        assert archive.read("sources/src/example.py") == source["src/example.py"]
        assert archive.read("inputs/fixture/input.json") == inputs["fixture/input.json"]
