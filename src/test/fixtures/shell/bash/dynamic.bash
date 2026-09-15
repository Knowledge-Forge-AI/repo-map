#!/usr/bin/env bash
# Static extraction fixture only. Do not execute.
cmd_name="${EXAMPLE_COMMAND:-git}"
declare -a COMMAND=(git status --short)
result_count="$(wc -l < ./data/input.txt)"
legacy_count=`wc -l ./data/legacy.txt`

run_dynamic_examples() {
    eval "$cmd_name"
    $cmd_name status
    "${COMMAND[@]}"
    bash -c "$EXAMPLE_SCRIPT_TEXT"
    sh -c "$EXAMPLE_SH_TEXT"
}
