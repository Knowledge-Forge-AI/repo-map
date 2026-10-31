#!/usr/bin/env bash
set -euo pipefail

# Core bootstrap script for mixed-v1 retrieval fixture
CLOE_BOOTSTRAP_RETRY_BACKOFF_MS=250
CLOE_BOOTSTRAP_MAX_ATTEMPTS=4
CLOE_BOOTSTRAP_TARGET_ENTRY="pkg.pipeline:RetrievalExecutionPipeline"

run_bootstrap_check() {
  local seal_prefix="snapmanifest1:"
  printf 'bootstrap target=%s backoff=%s seal=%s\n' \
    "${CLOE_BOOTSTRAP_TARGET_ENTRY}" \
    "${CLOE_BOOTSTRAP_RETRY_BACKOFF_MS}" \
    "${seal_prefix}"
}
