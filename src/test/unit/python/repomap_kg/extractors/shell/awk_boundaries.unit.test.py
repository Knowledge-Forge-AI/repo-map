import unittest
from repomap_kg.extractors.shell.awk import extract_awk_file_observations

class ShellAwkBoundariesUnitTests(unittest.TestCase):
    def test_awk_extractor_script_features(self):
        awk_code = """
BEGIN {
    FS = ","
    OFS = "\t"
    count = 0
    "date +%s" | getline current_time
    close("date +%s")
}

function process_record(name, val) {
    if (val > 100) {
        print name, val | "sort -n"
    }
}

$1 ~ /^[0-9]+/ {
    process_record($2, $3)
    count++
}

END {
    print "Total:", count
}
"""
        obs = extract_awk_file_observations("scripts/process.awk", awk_code)
        self.assertEqual(obs[0].kind, "awk.program")
        kinds = {o.kind for o in obs}
        self.assertIn("awk.begin", kinds)

if __name__ == "__main__":
    unittest.main()
