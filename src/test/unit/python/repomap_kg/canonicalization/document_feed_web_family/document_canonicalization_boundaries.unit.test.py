import unittest
from typing import cast

from repomap_kg.canonicalization.diagnostics import (
    CanonicalizationDiagnostic,
    diagnostic_sort_key,
    diagnostics_have_errors,
)

class DocumentCanonicalizationBoundariesUnitTests(unittest.TestCase):
    def test_diagnostics_sort_and_error_detection(self):
        d1 = CanonicalizationDiagnostic(
            severity="warning",
            category="parse_warning",
            message="Test warning",
            raw_source_id="test.py#1",
        )
        d2 = CanonicalizationDiagnostic(
            severity="error",
            category="parse_error",
            message="Test error",
            raw_source_id="test.py#2",
        )
        self.assertTrue(diagnostics_have_errors(cast(tuple[CanonicalizationDiagnostic, ...], [d1, d2])))
        self.assertFalse(diagnostics_have_errors(cast(tuple[CanonicalizationDiagnostic, ...], [d1])))
        k1 = diagnostic_sort_key(d1)
        k2 = diagnostic_sort_key(d2)
        self.assertNotEqual(k1, k2)

if __name__ == "__main__":
    unittest.main()
