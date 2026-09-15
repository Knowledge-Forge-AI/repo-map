from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[6]

from repomap_kg.graph.discovery_extractors import extract_shell_file_observations

class GraphDiscoveryBoundariesUnitTests(unittest.TestCase):
    def test_discovery_extractors_safe_dispatch(self):
        obs = extract_shell_file_observations(REPO_ROOT, "tools/run_tests.py")
        self.assertTrue(len(obs) > 0)

if __name__ == "__main__":
    unittest.main()
