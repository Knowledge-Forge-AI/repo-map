#!/usr/bin/env bats
# Static extraction fixture only. Do not execute.

load "$(fixture_helper)"

@test "$DYNAMIC_TEST_NAME" {
    eval "$cmd"
    run "$cmd"
}

@test "keeps run deferred" {
    run "${COMMAND[@]}"
    assert_failure
}
