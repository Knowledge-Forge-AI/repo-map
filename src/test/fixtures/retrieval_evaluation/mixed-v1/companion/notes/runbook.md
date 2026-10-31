# Companion Worker Drain Runbook

## Drain Procedure

Before restarting the companion service, drain every active worker lease:

1. Pause incoming calls to `execute_pipeline_step` in `core/pkg/pipeline.py`.
2. Wait for the worker lease drain timeout (`CLOE_DEPLOY_LOCK_TIMEOUT_SEC=90`).
3. Confirm Unicode telemetry tag `Δ-quorum-λ-verified` in status output.
