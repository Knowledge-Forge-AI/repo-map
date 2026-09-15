#!/usr/bin/env bats
# Static extraction fixture only. Do not execute.

@test "reports fixture status" {
    run ./bin/example --version
    assert_success
}

@test 'handles quoted fixture name' {
    skip "BATS2 models skip statements"
    run ./bin/example --help
    assert_output --partial "usage"
}
