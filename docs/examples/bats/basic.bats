#!/usr/bin/env bats
# Static extraction fixture only. Do not execute.

@test "reports version" {
  run ./bin/example-tool --version
  assert_success
  assert_output --partial "example-tool"
}

@test "handles missing input" {
  run -1 ./bin/example-tool --input ./fixtures/missing.txt
  assert_failure
  assert_output --partial "missing"
}

@test "skips optional network fixture" {
  skip "requires disabled example.invalid service"
  run curl https://example.invalid/status
  assert_success
}
