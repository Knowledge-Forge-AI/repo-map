import unittest
from repomap_kg.extractors.shell.bats import extract_bats_file_observations
from repomap_kg.extractors.shell.zunit import extract_zunit_file_observations

class ShellBatsZunitBoundariesUnitTests(unittest.TestCase):
    def test_bats_extractor_test_cases_and_hooks(self):
        bats_code = """
setup() {
    load 'test_helper/bats-support/load'
    load 'test_helper/bats-assert/load'
    TEST_DIR="$(temp_make)"
}

teardown() {
    temp_del "$TEST_DIR"
}

@test "validate deployment output" {
    run ./bin/deploy --dry-run
    assert_success
    assert_output --partial "Dry run completed"
}
"""
        obs = extract_bats_file_observations("test/deploy.bats", bats_code)
        self.assertEqual(obs[0].kind, "bats.file")

    def test_zunit_extractor_test_cases(self):
        zunit_code = """
@setup {
    export TEST_VAL="active"
}

@test 'should pass validation' {
    run echo "hello"
    assert $state equals 0
    assert $output same_as "hello"
}
"""
        obs = extract_zunit_file_observations("tests/app.zunit", zunit_code)
        self.assertEqual(obs[0].kind, "zunit.file")

if __name__ == "__main__":
    unittest.main()
