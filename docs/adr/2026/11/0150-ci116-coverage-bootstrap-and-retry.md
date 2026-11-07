# ADR 0150: CI116 coverage bootstrap repair and fresh staging attempt

## Status

Accepted under the operator's explicit instruction to repair failed CI116 and
publish another attempt. This is a new operator-directed campaign, not an
automatic rearm of ADR 0149.

## Context

CI116 passed its selected staging tests but refused an unregistered coverage
shard. Retained shard forensics identify the new component-dossier CLI. Its
isolated Python interpreter ignores the runner's `PYTHONPATH` bootstrap while
the installed coverage startup hook still runs. This permits measurement
without the required process-registration receipts.

The system lane separately failed while building its sandbox SDK, before any
application build. Its retained diagnostic contains only a generic build
failure and a full stderr digest. The native lane built the same SDK recipe
successfully. The underlying system-lane build cause is not established; a
dependency or base-image change would be speculative.

## Decision

Keep isolated CLI execution and its forbidden-runtime import guards. Execute
the existing runner-owned bootstrap explicitly before the dossier imports and
use the maintained observed CLI launch family. Preserve measurement and strict
registration, combination, coverage-source and threshold rules. Regression
tests use disposable synthetic source selections and actual CLI subprocesses;
they do not measure the candidate's coverage or substitute for hosted gates.

Extend the existing closed sandbox diagnostic projection with fixed failure
categories. Do not publish raw output, command arguments, environment values,
paths or URLs. Preserve the full output digest, primary failure and no-retry
behavior. Leave SDK inputs and dependencies unchanged pending actual evidence.

After scoped unit and containerized integration proof, static/privacy checks,
independent `dynamic_default` review and an exact-commit report, permit one
ordinary staging synchronization for CI117 attempt 1. Keep public main and
draft PR state unchanged; do not dispatch a duplicate workflow.

CI116's native sealed receipt records zero application builds; its system
lane stopped before sandbox creation. The authenticated application total
therefore remains 28. A fresh campaign-bound reservation may use the unspent
29th start, with cumulative cap 29 unchanged. Preserve all prior ledger rows,
record CI116's zero consumption, reject the spent CI116 nonce/reservation and
bind new approval, nonce and reservation identities. No automatic retry,
CI118 rearm or application start 30 is authorized.

## Verification and boundaries

Use exact selectors with `--no-coverage`. Check successful and refused CLI
returns, registered terminal receipts, absence of orphan shards, observed
process identity and unchanged import purity. Check closed diagnostic reason
classification and redaction with synthetic build output, with no real build.
Hosted CI owns complete populations, candidate coverage and actual SDK/system
qualification. Existing hard floors and 87/82 goals remain unchanged.

No new dependency, lockfile, SDK recipe, model, scientific or held-out
acceptance, production admission, complete local suite, local candidate
coverage, application/SDK build, main promotion, tag or history rewrite.
