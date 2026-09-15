"""Unit tests for public retention lineage and authority transitions."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from ci.python_retention_authorities import (
    bind_inputs,
    validate_recovered_rules,
)
from ci.retained_python_ratchet_lineage import (
    ACCEPTED_GENESIS_BASELINE_SHA256S,
    PUBLIC_GENESIS_BASELINE_SHA256,
    SCOPE_TRANSITIONS_SCHEMA,
    TRUSTED_GENESIS_BASELINE_SHA256,
)
from ci.retained_python_records import validate_scope_registry_records


class TestPythonRetentionPublicLineage(unittest.TestCase):
    def test_public_genesis_baseline_accepted(self) -> None:
        self.assertIn(PUBLIC_GENESIS_BASELINE_SHA256, ACCEPTED_GENESIS_BASELINE_SHA256S)
        self.assertIn(TRUSTED_GENESIS_BASELINE_SHA256, ACCEPTED_GENESIS_BASELINE_SHA256S)
        self.assertEqual(
            PUBLIC_GENESIS_BASELINE_SHA256,
            "e6a4830df94a210d83da9e37bce147eb3891d74a7868e50cfc1c648d858475f4",
        )

    def test_scope_registry_records_accepts_public_status_paths(self) -> None:
        # Valid records with public release paths, changelog, and tools/ci
        valid_records = [
            {
                "old_ownership_manifest_sha256": "0" * 64,
                "new_ownership_manifest_sha256": "1" * 64,
                "old_selected_set_sha256": "2" * 64,
                "new_selected_set_sha256": "3" * 64,
                "phase": "V001",
                "reason": "initial release",
                "status_path": "CHANGELOG.md",
                "changes": [],
            },
            {
                "old_ownership_manifest_sha256": "4" * 64,
                "new_ownership_manifest_sha256": "5" * 64,
                "old_selected_set_sha256": "6" * 64,
                "new_selected_set_sha256": "7" * 64,
                "phase": "V001",
                "reason": "release notes",
                "status_path": "docs/releases/v0.0.1.md",
                "changes": [],
            },
            {
                "old_ownership_manifest_sha256": "8" * 64,
                "new_ownership_manifest_sha256": "9" * 64,
                "old_selected_set_sha256": "a" * 64,
                "new_selected_set_sha256": "b" * 64,
                "phase": "V001",
                "reason": "ci evidence",
                "status_path": "tools/ci/public_export_policy.py",
                "changes": [],
            },
        ]
        document = {
            "schema": SCOPE_TRANSITIONS_SCHEMA,
            "records": valid_records,
        }
        validated = validate_scope_registry_records(document, schema=SCOPE_TRANSITIONS_SCHEMA)
        self.assertEqual(len(validated), 3)

    def test_recovered_rules_fallback_to_historical_manifests(self) -> None:
        repo_root = Path(__file__).resolve().parents[6]
        hist_path = repo_root / "tools/ci/historical_ownership_manifests.json"
        self.assertTrue(hist_path.is_file(), "historical_ownership_manifests.json must exist")

        hist_data = json.loads(hist_path.read_text(encoding="utf-8"))
        self.assertEqual(len(hist_data), 10, "must contain exactly 10 historical manifests")

        # Test with known historical records from python_retention_transitions.json
        transitions_path = repo_root / "tools/ci/python_retention_transitions.json"
        transitions_data = json.loads(transitions_path.read_text(encoding="utf-8"))
        retained_records = [
            r for r in transitions_data.get("records", [])
            if r.get("disposition") == "retained_python"
        ]
        self.assertTrue(len(retained_records) > 0)

        # validate_recovered_rules must succeed using historical_ownership_manifests fallback
        validate_recovered_rules(repo_root, retained_records[:10])

    def test_bind_inputs_binds_historical_manifests_without_error(self) -> None:
        repo_root = Path(__file__).resolve().parents[6]
        inventory_path = repo_root / "tools/ci/python_retention_inventory.json"
        ratchet_path = repo_root / "tools/ci/retained_python_ratchets.json"

        bindings = bind_inputs(repo_root, inventory_path, ratchet_path)
        self.assertIn("tools/ci/historical_ownership_manifests.json", bindings)
        for key in bindings:
            self.assertFalse(key.startswith("docs/status/"), f"docs/status should not be bound: {key}")


if __name__ == "__main__":
    unittest.main()
