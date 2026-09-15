# Static extraction example only. Do not execute.

#!/usr/bin/env bash
set -u

declare -a COMMAND=(git status --short)
cmd_name="${COMMAND[0]}"
helper_name="${EXAMPLE_HELPER:-common}"
dynamic_source="./lib/${helper_name}.bash"

alias ll='ls -la'
trap 'cleanup_static_example' EXIT

cleanup_static_example() {
    printf '%s\n' "cleanup"
}

run_dynamic_examples() {
    "$cmd_name" "${COMMAND[@]:1}"
    "${COMMAND[@]}"
    eval "${EXAMPLE_EVAL_TEXT:-:}"
    bash -c "${EXAMPLE_SCRIPT_TEXT:-:}"
    source "$dynamic_source"
    diff <(printf '%s\n' "left") <(printf '%s\n' "right")
    result_count="$(wc -l < ./data/input.txt)"
    sudo env EXAMPLE_MODE=static-demo apt-get install example-package
    find ./scripts -name '*.bash' -exec printf '%s\n' {} \;
    printf '%s\n' "$((result_count + 1))"
}
