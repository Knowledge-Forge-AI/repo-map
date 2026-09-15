# Static extraction example only. Do not execute.

#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

readonly CONFIG_FILE="./config/example.conf"
export EXAMPLE_ENV="bash-static-demo"
declare -a REPORT_COLUMNS=("name" "status" "updated_at")
declare -A LABELS=([ok]="green" [fail]="red")

source ./lib/common.bash
. ./lib/logging.sh

build_report() {
    local input_path="${1:-./data/input.tsv}"
    local output_path="./out/report.txt"

    printf '%s\n' "${REPORT_COLUMNS[@]}" > "$output_path"
    grep --extended-regexp "active|pending" "$input_path" | sort | uniq >> "$output_path"
    cat <<'REPORT_TEMPLATE' >> "$output_path"
static heredoc body for extraction only
REPORT_TEMPLATE
}

case "${1:-}" in
    --dry-run)
        echo "dry run"
        ;;
    *)
        build_report "${1:-./data/input.tsv}"
        ;;
esac
