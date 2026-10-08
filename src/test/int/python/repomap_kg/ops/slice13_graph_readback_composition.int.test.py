"""Integration tests for Slice 13 graph readback composition (Group S13-C).

Covers:
- S13-C01: External psql nonzero versus valid recovery
- S13-C02: Invalid JSON syntax versus decoded schema shape
- S13-C03: Array/object connector contract through query
- S13-C04: Connector selection normalization and mismatch through maintained caller
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.readback_driver import (
    execute_json_readback,
    selected_json_readback_driver,
)
from repomap_test_support.test_scratch import select_scratch_root


class Slice13GraphReadbackCompositionIntegrationTests(unittest.TestCase):
    """Slice 13 Group S13-C integration tests for readback connector contracts and subprocess boundaries."""

    def _write_fake_psql(self, directory: Path, stdout_text: str = "", exit_code: int = 0) -> str:
        script = directory / "fake_psql.sh"
        script.write_text(
            f"""#!/bin/sh
cat > "{directory}/invoked.sql"
cat <<'EOF'
{stdout_text}
EOF
exit {exit_code}
""",
            encoding="utf-8",
        )
        script.chmod(0o755)
        return str(script)

    def test_s13_c01_external_psql_nonzero_exit_and_valid_recovery(self) -> None:
        """Surfaces non-zero psql exit codes with process error diagnostic and recovers upon valid output."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            psql_path = self._write_fake_psql(root, stdout_text="ERROR: catalog unreachable", exit_code=2)
            env = {
                "REPOMAP_STORAGE_PG_CONNECTOR": "psql",
                "REPOMAP_STORAGE_READBACK_DRIVER": "psql",
            }
            with patch.dict(os.environ, env):
                with self.assertRaises(StorageSchemaError) as ctx:
                    execute_json_readback(
                        "SELECT 1;",
                        psql_args=[],
                        psql_command=psql_path,
                        label="test catalog",
                        expected_shape="object",
                    )
                self.assertIn("psql failed", str(ctx.exception))
                self.assertIn("ERROR: catalog unreachable", str(ctx.exception))
                invoked_sql = (root / "invoked.sql").read_text(encoding="utf-8")
                self.assertIn("SELECT 1;", invoked_sql)

                # Recovery: external process succeeds and emits valid JSON payload
                self._write_fake_psql(root, stdout_text='{"status": "ok", "rows": 1}', exit_code=0)
                payload = execute_json_readback(
                    "SELECT 1;",
                    psql_args=[],
                    psql_command=psql_path,
                    label="test catalog",
                    expected_shape="object",
                )
                self.assertEqual(payload, {"status": "ok", "rows": 1})

    def test_s13_c02_invalid_json_syntax_versus_decoded_payload_recovery(self) -> None:
        """Discriminates malformed JSON syntax diagnostics from query failures and recovers on valid payload."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            psql_path = self._write_fake_psql(root, stdout_text="{broken json: missing quotes", exit_code=0)
            env = {
                "REPOMAP_STORAGE_PG_CONNECTOR": "psql",
                "REPOMAP_STORAGE_READBACK_DRIVER": "psql",
            }
            with patch.dict(os.environ, env):
                with self.assertRaises(StorageSchemaError) as ctx:
                    execute_json_readback(
                        "SELECT json_query();",
                        psql_args=[],
                        psql_command=psql_path,
                        label="test query",
                        expected_shape="object",
                    )
                self.assertIn("did not return test query as JSON", str(ctx.exception))
                invoked_sql = (root / "invoked.sql").read_text(encoding="utf-8")
                self.assertIn("SELECT json_query();", invoked_sql)

                # Recovery: external process produces well-formed JSON object
                self._write_fake_psql(root, stdout_text='{"result": "parsed"}', exit_code=0)
                payload = execute_json_readback(
                    "SELECT json_query();",
                    psql_args=[],
                    psql_command=psql_path,
                    label="test query",
                    expected_shape="object",
                )
                self.assertEqual(payload, {"result": "parsed"})

    def test_s13_c03_array_shape_validation_and_recovery(self) -> None:
        """Rejects JSON object when array shape is required and recovers when array payload is provided."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            psql_path = self._write_fake_psql(root, stdout_text='{"not": "an_array"}', exit_code=0)
            env = {
                "REPOMAP_STORAGE_PG_CONNECTOR": "psql",
                "REPOMAP_STORAGE_READBACK_DRIVER": "psql",
            }
            with patch.dict(os.environ, env):
                with self.assertRaises(StorageSchemaError) as ctx:
                    execute_json_readback(
                        "SELECT json_agg(items) FROM data;",
                        psql_args=[],
                        psql_command=psql_path,
                        label="item collection",
                        expected_shape="array",
                    )
                self.assertIn("did not return item collection as a JSON array", str(ctx.exception))

                # Recovery: external process delivers expected JSON array
                self._write_fake_psql(root, stdout_text='[{"id": "a"}, {"id": "b"}]', exit_code=0)
                payload = execute_json_readback(
                    "SELECT json_agg(items) FROM data;",
                    psql_args=[],
                    psql_command=psql_path,
                    label="item collection",
                    expected_shape="array",
                )
                self.assertEqual(payload, [{"id": "a"}, {"id": "b"}])

    def test_s13_c04_connector_selection_normalization_and_conflict(self) -> None:
        """Normalizes connector selector values and rejects conflicting configurations without invoking process."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            invoked_marker = root / "invoked.sql"
            psql_path = self._write_fake_psql(root, stdout_text='{"ok": true}', exit_code=0)

            # Conflicting selectors: REPOMAP_STORAGE_PG_CONNECTOR vs REPOMAP_STORAGE_READBACK_DRIVER
            conflict_env = {
                "REPOMAP_STORAGE_PG_CONNECTOR": "psql",
                "REPOMAP_STORAGE_READBACK_DRIVER": "psycopg",
            }
            with patch.dict(os.environ, conflict_env):
                with self.assertRaises(StorageSchemaError) as ctx:
                    execute_json_readback(
                        "SELECT 1;",
                        psql_args=[],
                        psql_command=psql_path,
                        label="conflict check",
                        expected_shape="object",
                    )
                self.assertIn("conflicting PostgreSQL connector selectors", str(ctx.exception))
                # Ensure no external process or database connection was attempted
                self.assertFalse(invoked_marker.exists())

            # Normalization: uppercase and whitespace are stripped and mapped to supported driver
            norm_env = {
                "REPOMAP_STORAGE_PG_CONNECTOR": "  PSQL  ",
                "REPOMAP_STORAGE_READBACK_DRIVER": "  psql  ",
            }
            with patch.dict(os.environ, norm_env):
                self.assertEqual(selected_json_readback_driver(), "psql")
                payload = execute_json_readback(
                    "SELECT 1;",
                    psql_args=[],
                    psql_command=psql_path,
                    label="normalized check",
                    expected_shape="object",
                )
                self.assertEqual(payload, {"ok": True})
                self.assertTrue(invoked_marker.exists())


if __name__ == "__main__":
    import sys
    sys.exit(
        "Direct execution unsupported; use tools/run_tests.py for container sandbox admission."
    )
