"""Scoped controls for the conformance adapter's closed import probes."""
from __future__ import annotations

import sys
from types import ModuleType
import unittest
from unittest import mock

from repomap_kg.coordinator._portable_semantic_adapter import PortableExecutionError
from repomap_test_support.portable_worker_conformance import _exercise_authority


class TestPortableWorkerConformanceProbes(unittest.TestCase):
    def test_closed_imports_remain_lazy_and_translate_permission_refusal(self) -> None:
        cases = (
            ("lazy-import", "email.message"),
            ("database-import", "psycopg"),
            ("publisher-import", "repomap_kg.storage.staged_ingestion"),
            ("control-import", "repomap_kg.coordinator._control_schema"),
        )
        for probe, module in cases:
            with self.subTest(probe=probe), mock.patch.dict(sys.modules):
                denied = PermissionError("probe import denied")
                with mock.patch("builtins.__import__", side_effect=denied) as importer:
                    with self.assertRaises(PortableExecutionError) as caught:
                        _exercise_authority(probe, None)
                self.assertEqual(str(caught.exception), "unsupported_capability")
                self.assertIs(caught.exception.__cause__, denied)
                self.assertEqual(importer.call_args.args[0], module)
                self.assertEqual(importer.call_count, 1)

    def test_success_precedence_and_cache_eviction(self) -> None:
        cases = (
            ("lazy-import", "email.message", "contract_validation"),
            ("database-import", "psycopg", "semantic_workload"),
            ("publisher-import", "repomap_kg.storage.staged_ingestion", "semantic_workload"),
            ("control-import", "repomap_kg.coordinator._control_schema", "semantic_workload"),
        )
        for probe, module, code in cases:
            sentinel = ModuleType(module)
            with self.subTest(probe=probe), mock.patch.dict(sys.modules, {module: sentinel}):
                with mock.patch("builtins.__import__", return_value=sentinel) as importer:
                    with self.assertRaises(PortableExecutionError) as caught:
                        _exercise_authority(probe, None)
                self.assertEqual(str(caught.exception), code)
                self.assertEqual(importer.call_args.args[0], module)
                if probe == "lazy-import":
                    self.assertIs(sys.modules.get(module), sentinel)
                else:
                    self.assertNotIn(module, sys.modules)

    def test_unknown_probe_preserves_key_error_without_import(self) -> None:
        with mock.patch("builtins.__import__") as importer:
            with self.assertRaises(KeyError) as caught:
                _exercise_authority("unknown-probe", None)
        self.assertEqual(caught.exception.args, ("unknown-probe",))
        importer.assert_not_called()
