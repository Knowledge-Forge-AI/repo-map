#!/usr/bin/env bats
# Static extraction fixture only. Do not execute.

# @test "commented test" { run rm -rf ./out; }
# assert_output "commented assertion"

not_a_test='@test "string test" { run docker rm example; }'
assertion_text='assert_success'
array_values=(
  '@test "array test" { run curl https://example.invalid; }'
  'assert_output "array assertion"'
)

cat <<'BATS_TEXT'
@test "heredoc test" {
  run rm -rf ./out
  assert_success
}
BATS_TEXT

helper_function() {
  printf '%s\n' "${not_a_test}" "${assertion_text}"
}

case "${1:-}" in
  assert_success)
    printf '%s\n' "case labels are not assertions"
    ;;
esac
