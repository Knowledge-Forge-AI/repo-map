#!/usr/bin/env bats
# Static extraction fixture only. Do not execute.

@test "skips optional service" {
    skip "requires disabled example.invalid service"
    run curl https://example.invalid/status
}

@test "checks fixture paths" {
    run ./bin/check-fixtures "${BATS_TEST_DIRNAME}/fixtures"
    assert_success
    assert_file_exists "${BATS_TEST_DIRNAME}/fixtures/sample.txt"
    assert_dir_exists ./fixtures
}

@test "uses temp fixture paths" {
    skip
    run ./bin/use-temp "$BATS_TMPDIR/example.txt" "$BATS_TEST_TMPDIR/case"
}

@test "uses dynamic skip reason" {
    skip "$SKIP_REASON"
}
