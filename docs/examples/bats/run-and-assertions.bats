#!/usr/bin/env bats
# Static extraction fixture only. Do not execute.

@test "records command-under-test intent" {
  run git status --short
  assert_success
  refute_output --partial "[redacted-token]"
}

@test "checks output lines" {
  run ./bin/list-items --format lines
  assert_success
  assert_line --partial "alpha"
  refute_line "unexpected-secret-placeholder"
}

@test "checks fixture paths" {
  run ./bin/check-fixtures "${BATS_TEST_DIRNAME}/fixtures"
  assert_success
  assert_file_exists "${BATS_TEST_DIRNAME}/fixtures/sample.txt"
  assert_dir_exists "${BATS_TEST_DIRNAME}/fixtures"
}

@test "models negated run wrapper" {
  run ! ./bin/example-tool --token "[redacted-token]"
  assert_failure
}
