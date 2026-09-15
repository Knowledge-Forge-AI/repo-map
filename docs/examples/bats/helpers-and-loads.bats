#!/usr/bin/env bats
# Static extraction fixture only. Do not execute.

load 'test_helper'
load './helpers/common'
bats_load_library bats-support
bats_load_library bats-assert
bats_load_library bats-file

setup_file() {
  export EXAMPLE_FIXTURE_ROOT="${BATS_TEST_DIRNAME}/fixtures"
}

teardown_file() {
  :
}

setup() {
  export EXAMPLE_TMP="${BATS_TEST_TMPDIR}/example"
}

teardown() {
  rm -rf "${EXAMPLE_TMP}"
}

@test "reads helper-provided fixture" {
  run helper_read_fixture "${EXAMPLE_FIXTURE_ROOT}/sample.txt"
  assert_success
}
