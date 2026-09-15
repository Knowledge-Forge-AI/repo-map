from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from ci import python_retention_inventory as inventory
from ci.retained_python_ratchets import BASELINE_SCHEMA, EXPECTED_TOOLS, RETAINED_CLASSES, RETAINED_TIERS
from ci.python_retention_authorities import CHECKERS



@pytest.fixture(autouse=True)
def synthetic_repository_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inventory entrypoints derive authority only from this test's repository."""
    for name in ("GITHUB_SHA", "GITHUB_EVENT_PATH", "GITHUB_REF", "GITHUB_BASE_REF"):
        monkeypatch.delenv(name, raising=False)


def baseline(selection: list[dict[str, str]]) -> dict:
    return {
        "schema": BASELINE_SCHEMA,
        "ownership": {"manifest_path": "tools/ownership.json", "sha256": "0" * 64},
        "tools": dict(EXPECTED_TOOLS, ruff_rules=["F"], ruff_target_version="py312"),
        "selection": {"ownership_classes": list(RETAINED_CLASSES),
                      "tiers": list(RETAINED_TIERS), "modules": selection},
        "ruff": {"findings": []}, "mypy": {"findings": []},
        "migration_direction_imports": {"edges": []},
        "file_length": {"warning_limit": 400, "failure_limit": 1000, "ceilings": []},
    }


def candidate(tmp_path: Path, paths: tuple[str, ...]) -> tuple[Path, Path]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    inv = tmp_path / "inventory.json"
    inv.write_text(json.dumps({"schema": inventory.SCHEMA_VERSION, "files": []}))
    subprocess.run(["git", "-C", str(tmp_path), "add", "inventory.json"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Inventory genesis"], check=True)
    folder = tmp_path / "tools/ci"
    folder.mkdir(parents=True)
    (tmp_path / "src/test/fixtures").mkdir(parents=True)
    (tmp_path / ".gitignore").write_text("/tools/ci/*.py\n")
    for name in CHECKERS:
        (folder / name).write_text('"""Synthetic checker authority."""\n')
    (tmp_path / "pyproject.toml").write_text("[tool]\n")
    (folder / "retained_python_scope_transitions.json").write_text(json.dumps({"records": []}))
    (folder / "python_retention_transitions.json").write_text(json.dumps({
        "schema": "repomap-python-retention-transitions-v1", "records": [],
    }))
    (folder / "python_fixture_authority.json").write_text(json.dumps({
        "schema": "repomap-python-fixture-authority-v1", "version": 1,
        "fixture_root": "src/test/fixtures", "entries": [],
    }))
    entries = []
    selection = []
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value: int = 1\n", encoding="utf-8")
        root = inventory.category_for_path(name)
        entry = {"path": name, "root": root, "confidence": 0.9,
                 "maintained_executable": True, "rationale": "Maintained implementation",
                 "governing_profile": inventory.PROFILES[root],
                 "status": "retained_ratchet" if root == "product" else "active_tool"}
        entries.append(entry)
        if root == "product":
            selection.append({"path": name, "module": name.removeprefix("src/main/python/").removesuffix(".py").replace("/", "."),
                              "ownership_class": "python_retained", "tier": "T1-future"})
    inv.write_text(json.dumps({"schema": inventory.SCHEMA_VERSION, "files": entries}))
    rules = [{"module_prefix": item["module"], "match": "exact", "ownership_class": "python_retained",
              "architecture_box": "go_control_and_api", "enforcement_tier": "T1-future",
              "justification": "Synthetic maintained product owner", "disposition": "retained_python_ratcheted"}
             for item in selection]
    if not rules:
        rules = [{"module_prefix": "repomap_kg", "match": "exact", "ownership_class": "python_retained",
                  "architecture_box": "go_control_and_api", "enforcement_tier": "T1-future",
                  "justification": "Synthetic product root owner", "disposition": "retained_python_ratcheted"}]
    (folder / "python_type_ownership.json").write_text(json.dumps({
        "schema": "repomap-python-type-ownership-v1", "resolution": "longest-component-prefix-wins",
        "entries": rules,
    }))
    ratchet = tmp_path / "ratchet.json"
    document = baseline(selection)
    document["ownership"]["sha256"] = hashlib.sha256((folder / "python_type_ownership.json").read_bytes()).hexdigest()
    ratchet.write_text(json.dumps(document))
    return inv, ratchet


def validate(root: Path, paths: tuple[Path, Path]) -> dict:
    return inventory.validate_inventory(root, *paths)


def change(inv: Path, **fields: object) -> None:
    data = json.loads(inv.read_text())
    data["files"][0].update(fields)
    inv.write_text(json.dumps(data))


def test_candidate_paths_are_lossless_and_additions_are_visible(tmp_path: Path) -> None:
    names = ("tools/a \n.py", "tools/ leading.py")
    paths = candidate(tmp_path, names)
    assert inventory.git_candidate_python_files(tmp_path) == sorted(names)
    result = validate(tmp_path, paths)
    assert result["counts"]["total_files"] == 2
    assert result["census_complete"] is True
    assert result["status"] == "not_checked"
    assert result["enforcement_complete"] is False
    (tmp_path / "tools/new.py").write_text("")
    with pytest.raises(inventory.InventoryValidationError, match="missing from inventory"):
        validate(tmp_path, paths)


def test_rename_reconciles_exact_membership(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("tools/old.py",))
    subprocess.run(["git", "-C", str(tmp_path), "add", "tools/old.py"], check=True)
    (tmp_path / "tools/old.py").rename(tmp_path / "tools/new.py")
    with pytest.raises(inventory.InventoryValidationError, match="absent"):
        validate(tmp_path, paths)
    change(paths[0], path="tools/new.py")
    assert validate(tmp_path, paths)["assigned"]["tools"] == ["tools/new.py"]


@pytest.mark.parametrize("fields, message", [
    ({"confidence": float("nan")}, "finite confidence"),
    ({"confidence": float("inf")}, "finite confidence"),
    ({"confidence": True}, "finite confidence"),
    ({"confidence": -0.1}, "finite confidence"),
    ({"root": "product"}, "root classification"),
    ({"maintained_executable": None}, "executable classification"),
    ({"rationale": " "}, "rationale"),
    ({"confidence": 0.5}, "counterevidence"),
])
def test_invalid_classification_fails(tmp_path: Path, fields: dict, message: str) -> None:
    paths = candidate(tmp_path, ("tools/owner.py",))
    change(paths[0], **fields)
    with pytest.raises(inventory.InventoryValidationError, match=message):
        validate(tmp_path, paths)


def test_reasoned_lower_confidence_is_an_exclusion(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("tools/owner.py",))
    change(paths[0], confidence=0.5, counterevidence="Scheduled removal in accepted replacement plan")
    assert validate(tmp_path, paths)["eligible"]["tools"] == []


def test_analysis_inputs_are_separate_from_executable_fixtures(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("src/test/fixtures/input.py",))
    fixture_path = "src/test/fixtures/input.py"
    consumer = tmp_path / "tools/consumer.py"
    consumer.write_text('from pathlib import Path\nsource = Path("src/test/fixtures/input.py").read_text()\n')
    data = json.loads(paths[0].read_text())
    data["files"].append({"path": "tools/consumer.py", "root": "tools", "confidence": 0.9,
                          "maintained_executable": True, "rationale": "Synthetic static fixture consumer",
                          "status": "active_tool", "governing_profile": "clean_tooling"})
    paths[0].write_text(json.dumps(data))
    manifest_path = tmp_path / "tools/ci/python_fixture_authority.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["entries"] = [{
        "path": fixture_path, "role": "inert_data",
        "content_sha256": hashlib.sha256((tmp_path / fixture_path).read_bytes()).hexdigest(),
        "consumer": ["tools/consumer.py"], "consumption_mode": "static_extraction",
        "source_shape": "valid", "rationale": "Synthetic parser reads source bytes without execution",
        "provenance": None,
    }]
    manifest_path.write_text(json.dumps(manifest))
    change(paths[0], maintained_executable=False, counterevidence="Static parser input")
    assert validate(tmp_path, paths)["eligible"]["fixtures"] == []
    change(paths[0], maintained_executable=True)
    with pytest.raises(inventory.InventoryValidationError, match="contradicts role"):
        validate(tmp_path, paths)
    manifest["entries"][0].update(role="executable_first_party", consumption_mode="direct_execution")
    consumer.write_text('import runpy\nrunpy.run_path("src/test/fixtures/input.py")\n')
    manifest_path.write_text(json.dumps(manifest))
    assert validate(tmp_path, paths)["assigned"]["fixtures"] == [fixture_path]


@pytest.mark.parametrize("path", [
    "src/main/python/repomap_kg/owner.py", "tools/owner.py",
    "src/test/support/python/owner.py", "src/test/unit/python/owner.py",
    "src/test/int/python/owner.py", "src/test/conftest.py",
])
def test_boilerplate_cannot_exclude_maintained_roots(tmp_path: Path, path: str) -> None:
    paths = candidate(tmp_path, (path,))
    change(paths[0], maintained_executable=False, counterevidence="Static parser input")
    with pytest.raises(inventory.InventoryValidationError, match="requires fixture root"):
        validate(tmp_path, paths)


@pytest.mark.parametrize("profile", ["unit_test_suite", "unknown", None, [], "analysis_input"])
def test_unknown_or_inapplicable_profile_fails_closed(tmp_path: Path, profile: object) -> None:
    paths = candidate(tmp_path, ("tools/owner.py",))
    change(paths[0], governing_profile=profile)
    with pytest.raises(inventory.InventoryValidationError, match="governing profile"):
        validate(tmp_path, paths)


def test_known_wrong_root_profile_is_unassigned(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("tools/owner.py",))
    change(paths[0], governing_profile="clean_test_owners")
    result = validate(tmp_path, paths)
    assert result["unassigned"]["tools"] == ["tools/owner.py"]
    assert not result["enforcement_complete"]


def test_fixture_authority_outside_git_census_fails_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = candidate(tmp_path, ("tools/owner.py",))
    fixture_path = "src/test/fixtures/ignored.py"
    (tmp_path / fixture_path).write_text("value = 1\n")
    with (tmp_path / ".gitignore").open("a") as output:
        output.write(f"/{fixture_path}\n")
    monkeypatch.setattr(inventory, "validate_fixture_manifest", lambda *args: {
        "entries": [{"path": fixture_path, "role": "inert_data"}],
    })
    with pytest.raises(inventory.InventoryValidationError, match="fixture authority path absent"):
        validate(tmp_path, paths)


def test_missing_required_ratchet_fails(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("tools/owner.py",))
    paths[1].unlink()
    with pytest.raises(inventory.InventoryValidationError, match="required ratchet"):
        validate(tmp_path, paths)


def test_duplicate_classification_fails(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("tools/owner.py",))
    data = json.loads(paths[0].read_text())
    data["files"].append(data["files"][0])
    paths[0].write_text(json.dumps(data))
    with pytest.raises(inventory.InventoryValidationError, match="duplicate path"):
        validate(tmp_path, paths)


def test_eligible_deferred_product_is_unassigned(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("src/main/python/repomap_kg/example.py",))
    change(paths[0], status="deferred_decomposition")
    paths[1].write_text(json.dumps(baseline([])))
    manifest_path = tmp_path / "tools/ci/python_type_ownership.json"
    manifest = json.loads(manifest_path.read_text())
    rule = manifest["entries"][0]
    rule.update(ownership_class="planned_go", enforcement_tier="T3", disposition="planned_go")
    manifest_path.write_text(json.dumps(manifest))
    document = baseline([])
    document["ownership"]["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    paths[1].write_text(json.dumps(document))
    (tmp_path / "tools/ci/python_retention_transitions.json").write_text(json.dumps({
        "schema": "repomap-python-retention-transitions-v1", "records": [{
            "path": "src/main/python/repomap_kg/example.py", "disposition": "pending_admission",
            "superseded_rule": rule, "reason": "Maintain Python obligations while migration remains forecast",
        }],
    }))
    assert validate(tmp_path, paths)["unassigned"]["product"] == [
        "src/main/python/repomap_kg/example.py"]


def test_removal_requires_preserved_history(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("tools/old.py",))
    subprocess.run(["git", "-C", str(tmp_path), "add", "inventory.json", "tools/old.py"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Protected owner"], check=True)
    (tmp_path / "tools/old.py").rename(tmp_path / "tools/new.py")
    change(paths[0], path="tools/new.py")
    with pytest.raises(inventory.InventoryValidationError, match="scope history"):
        validate(tmp_path, paths)
    data = json.loads(paths[0].read_text())
    data["path_transitions"] = [{"from": "tools/old.py", "to": "tools/new.py",
                                 "rationale": "Renamed owner preserves behavior"}]
    paths[0].write_text(json.dumps(data))
    result = validate(tmp_path, paths)
    assert result["path_transitions"] == data["path_transitions"]


def test_census_cli_does_not_claim_enforcement(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    paths = candidate(tmp_path, ("tools/owner.py",))
    assert inventory.main(["--repo-root", str(tmp_path), "--inventory", str(paths[0]),
                           "--ratchet", str(paths[1]), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "not_checked"
    assert inventory.main(["--repo-root", str(tmp_path), "--inventory", str(paths[0]),
                           "--ratchet", str(paths[1])]) == 1
    assert capsys.readouterr().out == (
        "python-retention-inventory: not_checked\ncensus files: 1\nenforcement complete: False\n")


@pytest.mark.parametrize("passed", [True, False])
def test_effective_assignment_requires_current_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, passed: bool,
) -> None:
    paths = candidate(tmp_path, ("tools/owner.py",))
    result = validate(tmp_path, paths)
    monkeypatch.setattr(inventory, "check_paths", lambda requested, **kwargs:
                        {"status": "passed" if passed else "failed", "paths": list(requested)})
    checked = inventory.check_inventory(result, tmp_path, paths[1])
    assert checked["enforcement_complete"] is passed
    assert checked["eligible_minus_enforced"]["tools"] == ([] if passed else ["tools/owner.py"])


def test_source_change_invalidates_enforcement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = candidate(tmp_path, ("tools/owner.py",))
    result = validate(tmp_path, paths)
    (tmp_path / "tools/owner.py").write_text("value = 2\n")
    with pytest.raises(inventory.InventoryValidationError, match="candidate changed"):
        inventory.check_inventory(result, tmp_path, paths[1])


def test_product_type_tool_failure_is_retained_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = candidate(tmp_path, ("src/main/python/repomap_kg/owner.py",))
    result = validate(tmp_path, paths)
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if "tools/ci/retained_python_ratchets.py" in command:
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "schema": "repomap-retained-python-ratchets-result-v1",
                "classification": "passed",
            }), "")
        if "tools/ci/python_type_check.py" in command:
            return subprocess.CompletedProcess(command, 2, json.dumps({
                "schema": "repomap-python-type-check-v1", "tool_failure": "missing tool",
            }), "")
        raise AssertionError(f"unexpected checker command: {command}")

    monkeypatch.setattr(inventory, "subprocess", SimpleNamespace(
        run=run, check_output=subprocess.check_output,
        PIPE=subprocess.PIPE, CalledProcessError=subprocess.CalledProcessError,
    ))
    checked = inventory.check_inventory(result, tmp_path, paths[1])
    product = checked["check_results"]["product"]
    assert product["classification"] == "tool-failure"
    assert product["type_returncode"] == 2
    assert product["checks"]["type_ownership"]["tool_failure"] == "missing tool"
    assert checked["enforced"]["product"] == []


@pytest.mark.parametrize("product_passed,direct_debt", [(True, False), (False, False), (True, True)])
def test_dependency_attribution_requires_current_product_pass_and_clean_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    product_passed: bool, direct_debt: bool,
) -> None:
    product = "src/main/python/repomap_kg/owner.py"
    tool = "tools/owner.py"
    paths = candidate(tmp_path, (product, tool))
    result = validate(tmp_path, paths)

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "tools/ci/retained_python_ratchets.py" in command:
            return subprocess.CompletedProcess(command, 0 if product_passed else 1, json.dumps({
                "schema": "repomap-retained-python-ratchets-result-v1",
                "classification": "passed" if product_passed else "policy-finding",
            }), "")
        if "tools/ci/python_type_check.py" in command:
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "schema": "repomap-python-type-check-v1",
            }), "")
        raise AssertionError("unexpected checker command")

    def profile(requested: tuple[str, ...], **kwargs: object) -> dict[str, object]:
        assert requested == (tool,)
        findings = [{"path": product, "dependency": True}]
        if direct_debt:
            findings.append({"path": tool, "dependency": True})
        return {
            "status": "failed", "paths": [tool], "analyzed_paths": [tool],
            "checks": {
                "ruff": {"status": "passed", "findings": [], "completed": True},
                "file_length": {"status": "passed", "findings": [], "completed": True},
                "mypy": {"status": "failed", "findings": findings, "completed": True},
            },
        }

    monkeypatch.setattr(inventory, "subprocess", SimpleNamespace(
        run=run, check_output=subprocess.check_output,
        PIPE=subprocess.PIPE, CalledProcessError=subprocess.CalledProcessError,
    ))
    monkeypatch.setattr(inventory, "check_paths", profile)
    checked = inventory.check_inventory(result, tmp_path, paths[1])
    assert checked["enforced"]["tools"] == ([tool] if product_passed and not direct_debt else [])
    assert checked["check_results"]["tools"]["checks"]["mypy"]["findings"][0]["path"] == product
