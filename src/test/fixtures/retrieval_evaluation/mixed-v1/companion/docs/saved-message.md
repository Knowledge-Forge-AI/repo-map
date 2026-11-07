# Saved Operator Escalation Message

From: operations-lead@example.invalid
Subject: Escalation checklist for RouteDispatchTable target normalization

When an operator updates `RouteDispatchTable` in `core/pkg/router.py`, follow
the saved operator escalation checklist:

1. Confirm `normalize_dispatch_target` lowercases the URI scheme.
2. Verify `COMPANION_OPS_SYNC_CODE` in `companion/shared/status_codes.py`.
3. Quote check: `"ERR_CLOE_MANIFEST_SEAL_MISMATCH_409: snapshot_vector!=accepted_vector"`
   must never be silenced during route lookup.
