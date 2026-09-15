#!/usr/bin/env bats
# Static extraction fixture only. Do not execute.

@test "records command-under-test intent" {
    run git status --short
    assert_success
    refute_output --partial "dirty"
}

@test "models expected status from run flag" {
    run -1 ./bin/example-tool --input ./fixtures/missing.txt
    assert_failure
    assert_output --partial "missing"
    assert_equal "$status" 1
}

@test "models negated and separate stderr run" {
    run --separate-stderr ! ./bin/example-tool --mode fixture
    assert_line --partial "stderr"
}

@test "checks file and directory expectations" {
    assert_file_exists "${BATS_TEST_DIRNAME}/fixtures/sample.txt"
    assert_dir_exists "${BATS_TEST_DIRNAME}/fixtures"
    refute_line "unexpected"
}
