"""Metadata ownership is an explicit diagnostic, separate from stable identity."""
import json
from importlib.metadata import Distribution
from types import SimpleNamespace
from typing import cast

import pytest


def finder_for(rows):
    return lambda name: iter(cast(Distribution, SimpleNamespace(metadata={"Name": label})) for label in rows.get(name, []))


@pytest.mark.parametrize(("rows", "state", "exit_code"), [
    ({}, "unverified", 1),
    ({"common-lore-index": ["Common_Lore_Index"]}, "single-owner", 0),
    ({"repomap-kg": ["repomap.kg"]}, "owner-mismatch", 1),
    ({"repomap-kg": ["repomap-kg"], "common-lore-index": ["common-lore-index"]}, "conflicting", 1),
    ({"repomap-kg": ["repomap-kg", "repomap_kg", "repomap.kg"]}, "conflicting", 1),
])
def test_metadata_categories_are_bounded_and_do_not_claim_runtime_health(rows, state, exit_code):
    from common_lore_index.runtime.installation_ownership import inspect_installation_ownership
    result = inspect_installation_ownership(finder=finder_for(rows))
    payload = result.as_dict()
    assert result.exit_code == exit_code and payload["state"] == state
    assert payload["schema"] == "cloe-installation-ownership-v1" and payload["metadata_only"] is True
    assert payload["expected_distribution"] == "common-lore-index"
    distribution_rows = payload["distributions"]
    assert isinstance(distribution_rows, list)
    assert all(isinstance(row, dict) and row["count"] in (0, 1, 2) for row in distribution_rows)


@pytest.mark.parametrize("bad", [None, 13, "private/sentinel", "unknown", "repomap-kg\nsecret"])
def test_unexpected_metadata_is_unverified_without_disclosure(bad):
    from common_lore_index.runtime.installation_ownership import inspect_installation_ownership
    result = inspect_installation_ownership(finder=lambda _name: [cast(Distribution, SimpleNamespace(metadata={"Name": bad}))])
    assert result.exit_code == 1 and result.state == "unverified"
    assert "private/sentinel" not in json.dumps(result.as_dict()) and "secret" not in json.dumps(result.as_dict())


def test_reader_failure_is_a_bounded_diagnostic():
    from common_lore_index.runtime.installation_ownership import inspect_installation_ownership
    def broken(_name):
        raise OSError("private/sentinel and secret")
    result = inspect_installation_ownership(finder=broken)
    assert result.state == "unverified" and result.exit_code == 1
    assert result.as_dict()["diagnostics"] == ["distribution_metadata_unavailable"]
    assert "sentinel" not in json.dumps(result.as_dict())


def test_selected_distribution_owner_drives_classification(monkeypatch):
    from common_lore_index.runtime import installation_ownership as owner
    monkeypatch.setattr(owner, "_DISTRIBUTION_NAME", "common-lore-index")
    result = owner.inspect_installation_ownership(finder=finder_for({"common-lore-index": ["common_lore_index"]}))
    assert result.exit_code == 0 and result.state == "single-owner"
    assert result.as_dict()["expected_distribution"] == "common-lore-index"


def test_cli_explicit_check_keeps_default_identity_contract(capsys):
    from common_lore_index.cli.main import main
    from common_lore_index.cli.parser import build_parser
    args = build_parser().parse_args(["identity", "--installation-check", "--json"])
    assert args.installation_check
    assert main(["identity", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"name", "distribution", "package", "cli", "license", "database"}


@pytest.mark.parametrize("as_json", [False, True])
def test_diagnostic_cli_preserves_machine_output_and_exit_code(monkeypatch, capsys, as_json):
    from common_lore_index.cli.main import main
    from common_lore_index.runtime import installation_ownership as owner
    found = owner.inspect_installation_ownership(finder=finder_for({
        "repomap-kg": ["repomap-kg"], "common-lore-index": ["common-lore-index"],
    }))
    monkeypatch.setattr(owner, "inspect_installation_ownership", lambda: found)
    assert main(["identity", "--installation-check", *(["--json"] if as_json else [])]) == 1
    captured = capsys.readouterr()
    if as_json:
        assert json.loads(captured.out) == found.as_dict()
    else:
        assert "conflicting" in captured.out and "distribution_ownership_conflict" in captured.out
    assert not captured.err
