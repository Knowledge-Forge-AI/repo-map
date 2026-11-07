#!/usr/bin/env bash
set -euo pipefail

# Companion deployment helper referencing core bootstrap and RetrievalExecutionPipeline
CLOE_DEPLOY_LOCK_TIMEOUT_SEC=90
CLOE_DEPLOY_BOOTSTRAP_SCRIPT="../core/scripts/bootstrap.sh"

deploy_companion_unit() {
  printf 'deploying companion with lock_timeout=%s via %s\n' \
    "${CLOE_DEPLOY_LOCK_TIMEOUT_SEC}" \
    "${CLOE_DEPLOY_BOOTSTRAP_SCRIPT}"
}
