#!/usr/bin/env bats
# Static extraction fixture only. Do not execute.

# @test "commented out test" { run rm -rf ./tmp; }
# load './commented-helper'
# bats_load_library bats-assert
# run docker rm fixture
# assert_success
# skip "comment only"

not_a_test='@test "string test" { run curl https://example.invalid; }'
also_not_load="load './string-helper'"
also_not_assertion="assert_output 'secret-looking text'"
assertions=(assert_success "run rm -rf ./tmp" "bats_load_library bats-file")

cat <<'BATS_FIXTURE_TEXT'
@test "heredoc test" {
    load './heredoc-helper'
    run docker rm fixture
    assert_success
    refute_output "unexpected"
    skip "not a real skip"
}
BATS_FIXTURE_TEXT

case "${1:-}" in
    assert_success)
        printf '%s\n' "case label only"
        ;;
    run)
        printf '%s\n' "another case label only"
        ;;
esac
