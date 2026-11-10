"""Checkout-only CLI exit codes, path-free output, bundle custody and the product import guard."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any

import pytest

from installed_experience import bootstrap_source_path
from installed_experience_bundle import bundle_bytes, owner_base, read_installed_bundle, write_owner_bundle
from installed_experience_cli_views import EXIT_ACCEPTED, EXIT_REJECTED, EXIT_USAGE, run
from installed_experience_domains import SCHEMA_OBSERVATION, InstalledError, observation_name
from installed_experience_records import decode_intent, encode_observation
from installed_experience_recipe import recipe_digest
from installed_experience_source_identity import Preparation, owner_intent

CENSUS = "5" * 64
ATTEMPT = "c" * 32
REPO_ROOT = Path(__file__).resolve().parents[5]


def _observations(intent: bytes) -> list[tuple[str, bytes]]:
    rows = decode_intent(intent)["scenarios"]
    out = []
    for seq, row in enumerate(rows, start=1):
        source = "filesystem" if row["id"] == "X01" else "child-stdout"
        payload: dict[str, Any] = {
            "schema": SCHEMA_OBSERVATION, "owner": "server", "attempt": ATTEMPT,
            "intent": hashlib.sha256(intent).hexdigest(), "scenario": row["id"], "seq": seq,
            "env_class": row["env_class"], "family": row["family"], "exit": 0, "outcome": "passed",
            "stderr_class": "empty", "projection": None, "failure_code": None,
            "facts": {key: {"value": value, "source": source} for key, value in row["expected"].items()},
            "origin_classes": {"env-purelib": 1, "system-site": 1} if row["id"] == "S01" else None,
            "cleanup": "removed" if row["id"] == "X01" else "not-applicable",
        }
        out.append((observation_name(seq), encode_observation(payload)))
    return out


def _written(tmp_path: Path) -> Path:
    intent = owner_intent(
        "server", Preparation("1" * 64, 3, "2" * 64, 10, 5, "3" * 64),
        {"S02": {"graph_catalog_sha256": "a" * 64, "control_catalog_sha256": "b" * 64},
         "S04": {"tools_sha256": "c" * 64}},
        fixture_digest="4" * 64, candidate_census=CENSUS, python="3.13.12", platform="aarch64")
    base = tmp_path / "first-use-workload"
    base.mkdir(mode=0o700)
    root, verdict = write_owner_bundle(owner_base(base, "server"), "server", ATTEMPT, intent,
                                       _observations(intent))
    assert verdict.outcome == "accepted"
    return root


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(list(argv), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def _bundle_bytes(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


def test_bundle_layout_reuses_first_use_custody(tmp_path: Path) -> None:
    root = _written(tmp_path)
    assert root.parent == tmp_path / "first-use-workload" / "installed-experience" / "server"
    assert root.name == f"server-{ATTEMPT}"
    files = read_installed_bundle(root)
    assert sorted(files) == ["index.json", "intent.json", *(observation_name(seq) for seq in range(1, 6)),
                             "verdict.json"]
    assert 0 < bundle_bytes(root) <= 128 * 1024
    with pytest.raises(OSError):
        write_owner_bundle(root.parent, "server", ATTEMPT, files["intent.json"], [])


def test_check_and_show_are_path_free_and_bind_the_candidate(tmp_path: Path) -> None:
    root = _written(tmp_path)
    code, out, err = _run("check", str(root), "--candidate-source-sha256", CENSUS)
    assert (code, out, err) == (EXIT_ACCEPTED, "accepted server -\n", "")
    code, out, _err = _run("check", str(root), "--candidate-source-sha256", "6" * 64)
    assert code == EXIT_REJECTED and out == "rejected server binding-mismatch\n"
    code, out, _err = _run("show", str(root), "--candidate-source-sha256", CENSUS, "--json")
    document = json.loads(out)
    assert code == EXIT_ACCEPTED and [row["scenario"] for row in document["rows"]] == [
        "S01", "S02", "S03", "S04", "X01"]
    code, out, _err = _run("show", str(root), "--candidate-source-sha256", CENSUS)
    assert code == EXIT_ACCEPTED and out.startswith("accepted server -\nseq scenario")
    for text in (out, json.dumps(document)):
        assert str(tmp_path) not in text and "/" not in text.replace("n/a", "")


def test_bundle_path_custody_rejects_cross_owner_rename_without_writing(tmp_path: Path) -> None:
    root = _written(tmp_path)
    before = _bundle_bytes(root)
    target_parent = root.parent.parent / "local"
    target_parent.mkdir(mode=0o700)
    target = target_parent / root.name
    root.rename(target)
    with pytest.raises(InstalledError) as error:
        read_installed_bundle(target)
    assert error.value.category == "unsafe-member"
    assert _bundle_bytes(target) == before


def test_bundle_path_custody_rejects_storage_token_mix_without_writing(tmp_path: Path) -> None:
    root = _written(tmp_path)
    before = _bundle_bytes(root)
    target = root.parent / f"local-{ATTEMPT}"
    root.rename(target)
    with pytest.raises(InstalledError) as error:
        read_installed_bundle(target)
    assert error.value.category == "unsafe-member"
    assert _bundle_bytes(target) == before


def test_missing_index_remains_an_interrupted_bundle_not_usage(tmp_path: Path) -> None:
    root = _written(tmp_path)
    (root / "index.json").unlink()
    files = read_installed_bundle(root)
    assert "intent.json" in files and "index.json" not in files


def test_usage_unreadable_and_unsafe_members(tmp_path: Path) -> None:
    assert _run("check", str(tmp_path), "--candidate-source-sha256", "short")[0] == EXIT_USAGE
    assert _run("unknown")[0] == EXIT_USAGE
    assert _run("check", str(tmp_path / "absent"), "--candidate-source-sha256", CENSUS)[:1] == (EXIT_USAGE,)
    root = _written(tmp_path)
    (root / "notes.txt").write_text("x", encoding="utf-8")
    os.chmod(root / "notes.txt", 0o600)
    code, out, _err = _run("check", str(root), "--candidate-source-sha256", CENSUS)
    assert code == EXIT_REJECTED and out == "rejected unknown unsafe-member\n"


def test_plan_prints_the_frozen_catalog() -> None:
    code, out, _err = _run("plan")
    document = json.loads(out)
    assert code == EXIT_ACCEPTED and document["recipe_digest"] == recipe_digest()
    assert len(document["catalog"]) == 45


def test_owner_base_refuses_unknown_owner_and_symlinked_parent(tmp_path: Path) -> None:
    with pytest.raises(InstalledError):
        owner_base(tmp_path, "release")
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    (tmp_path / "installed-experience").symlink_to(real)
    with pytest.raises(InstalledError):
        owner_base(tmp_path, "local")


def test_bootstrap_places_checkout_roots_first() -> None:
    entries = bootstrap_source_path(["/elsewhere", str(REPO_ROOT / "tools")])
    assert entries[0] == str(REPO_ROOT / "src" / "main" / "python")
    assert entries[1] == str(REPO_ROOT / "tools") and entries.count(str(REPO_ROOT / "tools")) == 1


def test_product_never_imports_installed_tools_or_test_support() -> None:
    product = REPO_ROOT / "src" / "main" / "python"
    forbidden = ("installed_experience", "installed_candidate", "installed_environment",
                 "installed_projection", "installed_origin", "installed_mcp_session",
                 "repomap_test_support", "from tools", "import tools")
    offenders = []
    for path in sorted(product.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and any(token in stripped for token in forbidden):
                offenders.append(path.relative_to(product).as_posix())
    assert offenders == []
