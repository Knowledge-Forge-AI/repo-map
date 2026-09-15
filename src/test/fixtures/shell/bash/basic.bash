#!/usr/bin/env bash
# Static extraction fixture only. Do not execute.
set -euo pipefail
shopt -s nullglob

readonly CONFIG_FILE="./config/example.conf"
EXAMPLE_MODE="static-fixture"
export PUBLIC_FLAG="enabled"
export OPTIONAL_NAME

build_report() {
    local input_path="${1:-./data/input.tsv}"
    declare report_name="example"
    printf '%s\n' "$report_name"
}
