#!/usr/bin/env bats
# Static extraction fixture only. Do not execute.

@test "redacts expected output secrets" {
    run ./bin/example-tool --token "FAKE_BATS_RUN_TOKEN"
    assert_output "FAKE_BATS_OUTPUT_TOKEN"
    refute_output --partial "FAKE_BATS_HELPER_TOKEN"
    skip "FAKE_BATS_SKIP_SECRET"
}
