# Static extraction example only. Do not execute.

#!/usr/bin/env bash

declare -a COMMAND=(git status --short)
cmd_name="${COMMAND[0]}"
dynamic_source="./lib/${EXAMPLE_HELPER:-helper}.sh"

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
    cat "$(pwd)/computed.txt"
}
