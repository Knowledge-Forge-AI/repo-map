# Static extraction example only. Do not execute.

#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly DEFAULT_CONFIG="./config/example.conf"
export EXAMPLE_MODE="static-demo"

. ./lib/common.sh
source ./lib/logging.bash

run_report() {
    local input_path="${1:-./data/input.txt}"
    local output_path="./out/report.txt"

    printf '%s\n' "building report" > "$output_path"
    grep --line-number "example" "$input_path" | sort | uniq >> "$output_path"
    cat <<'REPORT_TEMPLATE' >> "$output_path"
static heredoc body for extraction only
REPORT_TEMPLATE
}

if [ "${1:-}" = "--dry-run" ]; then
    echo "dry run"
fi
