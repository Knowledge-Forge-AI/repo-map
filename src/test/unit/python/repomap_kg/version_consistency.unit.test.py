from __future__ import annotations

from pathlib import Path
import tomllib

import sys

import common_lore_index
import json
import pytest


repo_root = Path(__file__).resolve().parents[5]
tools_dir = repo_root / "tools"
if str(tools_dir) not in sys.path:
    sys.path.insert(0, str(tools_dir))

from ci.public_export_policy import DEFAULT_TARGET_VERSION


def test_version_consistency() -> None:
    pyproject_path = repo_root / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        pyproject = tomllib.load(f)
    pyproject_version = pyproject["project"]["version"]
    assert pyproject_version == "0.0.4"
    assert common_lore_index.__version__ == "0.0.4"
    assert DEFAULT_TARGET_VERSION == "0.0.4"
    assert common_lore_index.__version__ == pyproject_version
    assert DEFAULT_TARGET_VERSION == pyproject_version


def test_locator_bundle_reproduces_both_exact_release_version_identities(monkeypatch: pytest.MonkeyPatch) -> None:
    from common_lore_index.extractors.documents import markdown
    from repomap_test_support.node_location_fixtures import entry_response_differences, locator_bundle

    monkeypatch.setattr(markdown, "__version__", "0.0.3")
    previous = locator_bundle()
    monkeypatch.setattr(markdown, "__version__", "0.0.4")
    current = locator_bundle()
    assert previous.bundle_id == "bundle1:723185f89f9f45ddd5154dfba6fe6383b6cca7f5c57f033be8b2506e1e6bb403"
    assert current.bundle_id == "bundle1:1a8a2a2cd3970c5a14189c5de51767420ac2aa31f442d38d302187e28a6df4f9"
    old_frames = [json.loads(line) for line in previous.canonical_bytes().splitlines()]
    new_frames = [json.loads(line) for line in current.canonical_bytes().splitlines()]
    assert len(old_frames) == len(new_frames)
    assert old_frames[0] == new_frames[0]
    changes = [difference for family in previous.families if family != "raw_observations"
               for difference in entry_response_differences(
                   {str(row["family_ordinal"]): row for row in previous.families[family]},
                   {str(row["family_ordinal"]): row for row in current.families[family]}, family)]
    assert changes == [("canonical_evidence/5/extractor_version", "0.0.3", "0.0.4")]
    previous_rows = {row["source_ordinal"]: row for row in previous.families["raw_observations"]}
    current_rows = {row["source_ordinal"]: row for row in current.families["raw_observations"]}
    assert previous_rows.keys() == current_rows.keys()
    changed = []
    for ordinal, original in previous_rows.items():
        updated = current_rows[ordinal]
        if original == updated:
            continue
        before, after = dict(original), dict(updated)
        old_value, new_value = before.pop("payload_json"), after.pop("payload_json")
        assert isinstance(old_value, dict) and isinstance(new_value, dict)
        old_payload, new_payload = dict(old_value), dict(new_value)
        assert old_payload["extractor"] == "repo-markdown"
        assert old_payload.pop("extractor_version") == "0.0.3"
        assert new_payload.pop("extractor_version") == "0.0.4"
        assert old_payload == new_payload
        changed.append((before.pop("payload_hash"), after.pop("payload_hash")))
        assert before == after
    assert changed == [(
        "791b50aa061af7373b945ce165888d75edb3c790d20a241850292ed7b8a92939",
        "f3f21fc8870f582c65864ace5261af10404ab72984a3565cbeee34564172fd8a",
    )]
