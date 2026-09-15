from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from ci.retained_python_ratchets import (
    EXPECTED_MYPY_CONFIG,
    RatchetContractError,
    collect_snapshot,
    file_length_inventory,
    mypy_command,
    ruff_command,
    ruff_files_command,
)


def _ownership_entry() -> dict[str, str]:
    return {
        "module_prefix": "repomap_kg.future",
        "match": "exact",
        "ownership_class": "python_retained",
        "architecture_box": "synthetic_public_fixture",
        "enforcement_tier": "T1-future",
        "justification": "Synthetic public-safe ownership fixture.",
        "disposition": "synthetic_fixture",
    }


def _synthetic_repository(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "src/main/python/repomap_kg/future.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")
    manifest = tmp_path / "tools/ci/python_type_ownership.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema": "repomap-python-type-ownership-v1",
                "resolution": "longest-component-prefix-wins",
                "entries": [_ownership_entry()],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    mypy_lines = "\n".join(
        f"{key} = {json.dumps(value) if isinstance(value, str) else str(value).lower()}"
        for key, value in EXPECTED_MYPY_CONFIG.items()
    )
    (tmp_path / "pyproject.toml").write_text(
        f'[tool.ruff]\ntarget-version = "py312"\n\n[tool.mypy]\n{mypy_lines}\n',
        encoding="utf-8",
    )
    return manifest, source


def _install_collection_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
    *,
    mypy_output: str,
    shown_files: tuple[Path, ...] | None = None,
) -> list[tuple[tuple[str, ...], Path]]:
    calls: list[tuple[tuple[str, ...], Path]] = []
    monkeypatch.setattr(
        "ci.retained_python_ratchets.maintained_modules",
        lambda repo_root: {"repomap_kg.future": source},
    )
    monkeypatch.setattr(
        "ci.retained_python_ratchets._attest_environment",
        lambda: {"versions": {"mypy": "2.1.0"}},
    )
    monkeypatch.setattr(
        "ci.retained_python_ratchets.importlib.metadata.version",
        lambda distribution: "0.16.2" if distribution == "ruff" else pytest.fail(),
    )

    def run(command: list[str], *, repo_root: Path) -> subprocess.CompletedProcess[str]:
        argv = tuple(command)
        calls.append((argv, repo_root))
        if argv[0] == "git":
            return subprocess.CompletedProcess(command, 0, "tools/ci/python_type_ownership.json\n", "")
        if "--show-files" in argv:
            files = shown_files if shown_files is not None else (source,)
            return subprocess.CompletedProcess(
                command, 0, "".join(f"{path}\n" for path in files), ""
            )
        if "ruff" in argv:
            return subprocess.CompletedProcess(command, 0, "[]", "")
        return subprocess.CompletedProcess(command, 1, mypy_output, "")

    monkeypatch.setattr("ci.retained_python_ratchets._run", run)
    return calls


def test_collect_snapshot_attests_tool_argv_and_selected_file_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, source = _synthetic_repository(tmp_path)
    mypy_output = f"{source}:12:4: error: Bad value 7  [arg-type]\n"
    calls = _install_collection_boundaries(
        monkeypatch, source, mypy_output=mypy_output
    )

    snapshot = collect_snapshot(manifest, repo_root=tmp_path)

    selected_path = "src/main/python/repomap_kg/future.py"
    commands = [call[0] for call in calls]
    assert tuple(ruff_files_command((selected_path,))) in commands
    assert tuple(ruff_command((selected_path,))) in commands
    assert tuple(mypy_command((selected_path,))) in commands
    assert all(repo_root == tmp_path for _, repo_root in calls)
    assert snapshot["selection"]["modules"][0]["module"] == "repomap_kg.future"
    assert snapshot["mypy"]["findings"][0]["count"] == 1


def test_collect_snapshot_rejects_unparseable_mypy_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, source = _synthetic_repository(tmp_path)
    _install_collection_boundaries(
        monkeypatch,
        source,
        mypy_output=f"{source}:12:4: error: missing code\n",
    )

    with pytest.raises(RatchetContractError, match="unparseable"):
        collect_snapshot(manifest, repo_root=tmp_path)


def test_collect_snapshot_rejects_silent_ruff_file_omission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, source = _synthetic_repository(tmp_path)
    _install_collection_boundaries(
        monkeypatch, source, mypy_output="", shown_files=()
    )

    with pytest.raises(RatchetContractError, match="file selection"):
        collect_snapshot(manifest, repo_root=tmp_path)


def test_retained_file_lengths_reject_tracked_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("value = 1\n", encoding="utf-8")
    selected = tmp_path / "src/main/python/repomap_kg/future.py"
    selected.parent.mkdir(parents=True)
    selected.symlink_to(target)

    with pytest.raises(RatchetContractError, match="retained file path"):
        file_length_inventory(
            ({"path": "src/main/python/repomap_kg/future.py"},),
            repo_root=tmp_path,
        )
