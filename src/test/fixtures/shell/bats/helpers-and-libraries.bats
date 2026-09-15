#!/usr/bin/env bats
# Static extraction fixture only. Do not execute.

load 'test_helper'
load './helpers/common'
bats_load_library bats-support
bats_load_library bats-assert
bats_load_library bats-file
bats_load_library "$DYNAMIC_BATS_LIBRARY"

@test "uses helper" {
    run helper_read_fixture "${BATS_TEST_DIRNAME}/fixtures/sample.txt"
    assert_success
}
