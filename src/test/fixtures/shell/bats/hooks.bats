#!/usr/bin/env bats
# Static extraction fixture only. Do not execute.

setup_file() {
    printf '%s\n' "prepare suite"
}

teardown_file() {
    rm -rf ./tmp/fixture-suite
}

setup() {
    mkdir -p ./tmp/fixture-test
}

teardown() {
    rm -rf ./tmp/fixture-test
}

helper_function() {
    printf '%s\n' "ordinary helper, not a Bats hook"
}

@test "uses hooks as test intent" {
    run ./bin/example
    assert_success
}
