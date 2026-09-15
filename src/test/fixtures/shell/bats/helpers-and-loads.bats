#!/usr/bin/env bats
# Static extraction fixture only. Do not execute.

load 'test_helper'
load './helpers/common'
load '../support/helpers'
load "$HELPER_PATH"
bats_load_library bats-support

@test "loads helpers statically" {
    run helper_command
    assert_success
}
