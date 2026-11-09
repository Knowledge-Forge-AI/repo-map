"""CLI exit codes, path-free output, deterministic plan, source identity and import guards."""

from __future__ import annotations

import ast
import io
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

import first_use_workload
import first_use_workload_cli_views as cli_views
import first_use_workload_source_identity as identity
import runner_integration_execution
from first_use_workload_bundle import BundleWriter
from first_use_workload_census import CENSUS_RELATIVE, FIXTURE_RELATIVE, REPO_ROOT, load_census
from first_use_workload_cli_views import EXIT_ACCEPTED, EXIT_REJECTED, EXIT_USAGE, run
from first_use_workload_records import decode_intent
from first_use_workload_source_identity import (
    SourceIdentityError, candidate_census, current_intent, product_digest,
)
from first_use_workload_domains import ALIASES, WorkloadError
from repomap_test_support.first_use_workload_samples import ATTEMPT, sample_files

TOOLS = REPO_ROOT / "tools"
PRODUCT = REPO_ROOT / "src" / "main" / "python"


def _lister(_root: Path) -> bytes:
    return b"pyproject.toml\0"


def _run(
    *argv: str, repo_root: Path = REPO_ROOT, lister: Any = _lister,
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(list(argv), repo_root=repo_root, lister=lister, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def _minimal_repo(root: Path) -> Path:
    census = root / CENSUS_RELATIVE
    census.parent.mkdir(parents=True)
    census.write_bytes((REPO_ROOT / CENSUS_RELATIVE).read_bytes())
    fixture = root / FIXTURE_RELATIVE
    for alias in ALIASES:
        (fixture / alias).mkdir(parents=True)
    return root


def _bundle(base: Path) -> Path:
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    files = sample_files(load_census())
    writer = BundleWriter(base, "local", ATTEMPT)
    for name in sorted(name for name in files if name != "index.json"):
        writer.write(name, files[name])
    writer.write("index.json", files["index.json"])
    return writer.root


def test_plan_is_deterministic_canonical_and_path_free() -> None:
    first, second = _run("plan"), _run("plan")
    assert first == second and first[0] == EXIT_ACCEPTED and first[2] == ""
    intent = decode_intent(first[1].encode("utf-8"))
    assert intent["declared_source_parent"] is None
    assert intent["candidate_census"] == candidate_census(REPO_ROOT, lister=_lister)
    assert intent["product_digest"] == product_digest(REPO_ROOT)
    assert len(intent["steps"]) == 36
    assert str(REPO_ROOT) not in first[1]
    parent = _run("plan", "--source-parent", "a" * 40)
    assert decode_intent(parent[1].encode())["declared_source_parent"] == "a" * 40


@pytest.mark.parametrize("argv", [(), ("unknown",), ("check",), ("show", "--bundle"), ("plan", "--x")])
def test_usage_errors_exit_two_without_detail(argv: tuple[str, ...]) -> None:
    code, out, err = _run(*argv)
    assert (code, out, err) == (EXIT_USAGE, "", "first-use-workload: usage\n")


def test_invalid_source_parent_is_usage() -> None:
    assert _run("plan", "--source-parent", "XYZ")[0] == EXIT_USAGE


def test_missing_bundle_is_unreadable_and_path_free(tmp_path: Path) -> None:
    code, out, err = _run("check", "--bundle", str(tmp_path / "absent"))
    assert (code, out, err) == (EXIT_USAGE, "", "first-use-workload: unreadable\n")


def test_missing_fixture_source_is_unreadable_and_path_free(tmp_path: Path) -> None:
    repo_root = _minimal_repo(tmp_path)
    code, out, err = _run("plan", repo_root=repo_root)
    assert (code, out, err) == (EXIT_USAGE, "", "first-use-workload: unreadable\n")
    assert str(tmp_path) not in out and str(tmp_path) not in err


def test_candidate_read_oserror_is_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b"[project]\n")

    def failing_read_bytes(_path: Path) -> bytes:
        raise OSError("private path")

    monkeypatch.setattr(Path, "read_bytes", failing_read_bytes)
    with pytest.raises(SourceIdentityError) as error:
        candidate_census(tmp_path, lister=lambda _root: b"pyproject.toml\0")
    assert str(error.value) == "candidate source unreadable"


def test_candidate_read_failure_is_usage_and_path_free(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_intent(*_args: Any, **_kwargs: Any) -> bytes:
        raise SourceIdentityError("candidate source unreadable")

    monkeypatch.setattr(cli_views, "current_intent", failing_intent)
    assert _run("plan") == (EXIT_USAGE, "", "first-use-workload: unreadable\n")


def test_product_walk_error_never_returns_a_partial_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "src/main").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_bytes(b"[project]\n")

    def failed_walk(_root: Path, *, followlinks: bool, onerror: Any) -> Any:
        assert followlinks is False
        onerror(PermissionError("private directory"))
        yield from ()

    monkeypatch.setattr(identity.os, "walk", failed_walk)
    with pytest.raises(SourceIdentityError) as error:
        product_digest(tmp_path)
    assert str(error.value) == "product source unreadable"


def test_check_rejects_a_foreign_intent_with_categories_only(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    code, out, err = _run("check", "--bundle", str(bundle))
    assert code == EXIT_REJECTED and err == ""
    outcome, scenario, categories = out.strip().split(" ")
    assert (outcome, scenario) in {("rejected", "local"), ("incomplete", "local")}
    assert "intent_mismatch" in categories.split(",")
    assert str(tmp_path) not in out and ATTEMPT not in out


def test_unsafe_bundle_is_a_rejected_line(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "real")
    link = tmp_path / "link"
    link.symlink_to(bundle)
    assert _run("check", "--bundle", str(link)) == (EXIT_REJECTED, "rejected unknown unsafe_input\n", "")


def test_check_and_show_never_mutate_the_bundle(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)

    def snapshot() -> dict[str, tuple[int, int, bytes]]:
        return {
            str(path.relative_to(bundle)): (path.stat().st_mtime_ns, path.stat().st_mode, path.read_bytes())
            for path in sorted(bundle.rglob("*")) if path.is_file()
        }

    before = snapshot()
    _run("check", "--bundle", str(bundle))
    _run("show", "--bundle", str(bundle))
    _run("show", "--bundle", str(bundle), "--json")
    assert snapshot() == before
    assert sorted(os.listdir(bundle)) == sorted(before)


def test_show_prints_per_step_rows_without_sums(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    code, out, _err = _run("show", "--bundle", str(bundle))
    lines = out.splitlines()
    assert code == EXIT_REJECTED and lines[1].startswith("step sub action backend result")
    assert len(lines) == 2 + 5 + 1 and lines[-1] == "note: observations are per step; nothing is summed"
    assert "test_process_threads" in lines[1] and "reaped_descendants" in lines[1]
    code, out, _err = _run("show", "--bundle", str(bundle), "--json")
    document: dict[str, Any] = json.loads(out)
    assert code == EXIT_REJECTED and [row["step"] for row in document["rows"]] == [1, 2, 3, 4, 5]
    assert document["outcome"] != "accepted"
    assert set(document["rows"][0]["cpu"]) == {"test_process_threads", "reaped_descendants"}
    assert not any(key.startswith("total") for row in document["rows"] for key in row)
    assert str(tmp_path) not in out


def test_stale_fixture_is_rejection_rather_than_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    def stale(*_args: Any, **_kwargs: Any) -> bytes:
        raise WorkloadError("stale_input")

    monkeypatch.setattr(cli_views, "current_intent", stale)
    assert _run("plan") == (EXIT_REJECTED, "rejected unknown stale_input\n", "")


def test_candidate_census_is_the_runner_candidate_identity_algorithm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, body in (("tools/a.py", b"a\n"), ("src/main/x.py", b"x\n"), ("pyproject.toml", b"[p]\n"),
                       ("src/test/fixtures/task-gold.json", b"{}\n")):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    listing = b"tools/a.py\0src/main/x.py\0pyproject.toml\0src/test/fixtures/task-gold.json\0tools/a.py\0"

    def fake_check_output(argv: list[str], **_kwargs: Any) -> Any:
        if argv[:2] == ["git", "rev-parse"]:
            return "0" * 40 + "\n"
        return listing

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    expected = runner_integration_execution.candidate_identity(tmp_path)["source_sha256"]
    assert candidate_census(tmp_path, lister=lambda _root: listing) == expected
    (tmp_path / "tools" / "a.py").write_bytes(b"changed\n")
    assert candidate_census(tmp_path, lister=lambda _root: listing) != expected


def test_product_digest_excludes_caches_and_tracks_bytes(tmp_path: Path) -> None:
    (tmp_path / "src" / "main" / "pkg" / "__pycache__").mkdir(parents=True)
    (tmp_path / "src" / "main" / "pkg" / "m.py").write_bytes(b"one\n")
    (tmp_path / "pyproject.toml").write_bytes(b"[project]\n")
    first = product_digest(tmp_path)
    (tmp_path / "src" / "main" / "pkg" / "__pycache__" / "m.cpython-313.pyc").write_bytes(b"\0")
    (tmp_path / "src" / "main" / "pkg" / "stale.pyc").write_bytes(b"\0")
    assert product_digest(tmp_path) == first
    (tmp_path / "src" / "main" / "pkg" / "m.py").write_bytes(b"two\n")
    assert product_digest(tmp_path) != first


def test_current_intent_binds_product_and_candidate_separately() -> None:
    base = decode_intent(current_intent(lister=_lister))
    other = decode_intent(current_intent(lister=lambda _root: b"pyproject.toml\0tools/first_use_workload.py\0"))
    assert base["product_digest"] == other["product_digest"]
    assert base["candidate_census"] != other["candidate_census"]
    census = load_census()
    assert (base["census_digest"], base["fixture_digest"]) == (census.digest, census.fixture_digest)


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_bytes(), filename=path.name)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_no_product_module_imports_the_workload_or_test_support() -> None:
    offenders = [
        str(path.relative_to(PRODUCT))
        for path in sorted(PRODUCT.rglob("*.py"))
        if any(name.split(".")[0].startswith("first_use_workload") or name.split(".")[0] == "repomap_test_support"
               for name in _imports(path))
    ]
    assert offenders == []


def test_workload_tools_never_import_test_support() -> None:
    owners = sorted(TOOLS.glob("first_use_workload*.py"))
    assert len(owners) == 17
    for path in owners:
        assert not any(name.startswith("repomap_test_support") for name in _imports(path)), path.name


def test_entry_point_puts_this_checkout_first() -> None:
    entries = ["/elsewhere", str(PRODUCT), "/site-packages"]
    result = first_use_workload.bootstrap_source_path(entries)
    assert result[:2] == [str(PRODUCT), str(TOOLS)]
    assert result.count(str(PRODUCT)) == 1 and result[-1] == "/site-packages"
