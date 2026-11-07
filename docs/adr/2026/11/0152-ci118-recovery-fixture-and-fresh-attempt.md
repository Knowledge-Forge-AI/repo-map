# ADR 0152: CI118 recovery-fixture isolation and fresh staging attempt

## Status

Accepted under the operator's new instruction, "ci failed try again". This is
a fresh bounded campaign after CI118, not automatic reuse of ADR 0151.

## Context

CI118 passed source/export, unit, static, native, system, SBOM and CodeQL jobs.
All SDK builds succeeded without changing their inputs. The integration
population had one failure: the nested missing-selector recovery probe hit
the disk-reserve admission guard before reaching the discovery failure it
intended to test. A valid host refusal was mistaken for the probe's expected
collection failure. The probe depended on remaining disk space late in the
complete population. Hard coverage floors passed; the 87/82 goals remain open.

## Decision

Isolate only this test fixture's host-capacity inputs using the existing
`TestResourceRun.start(host_signals=...)` injection seam. Run the real canonical
entrypoint, profile/configuration validation, admission decision, managed
scratch lifecycle, discovery subprocess and typed failure-report writers.
Provide a positive controlled signal fixture for missing-node discovery and
a zero-capacity fixture that must still fail the real admission guard. Reject
unexpected workload execution in both probes. Keep ordinary runner defaults,
physical-host and sandbox admission, thresholds, quotas and cleanup unchanged.
The enclosing canonical integration run still needs real admission and the
authenticated disposable sandbox. Synthetic probe signals establish no host
capacity or qualification claim.

After exact scoped unit and containerized integration proof, unchanged-debt
static enforcement, privacy/hygiene checks, independent `dynamic_default`
review and an exact-commit report, publish one ordinary staging synchronization
for automatic CI119 attempt 1. No PR-state, main, tag or history mutation and
no manual or duplicate workflow trigger.

Authenticate CI118's native and system artifacts before binding the new grant.
CI118 used application start 29. This new operator-requested attempt permits
one additional native AMD application start, 30 after 29: increase cumulative
caps 29/29 to 30/30 only. Preserve all historical ledger rows, record actual
CI118 consumption, bind fresh approval/nonce/reservation identities, and reject
CI118 replay and stale ceilings. This does not authorize CI120, start 31,
automatic retry, local SDK/application builds or a new dependency class.

## Verification and boundaries

Exercise real discovery failure and low-capacity refusal in the existing
authenticated integration sandbox. Unit-test the fixture's exact injected
inputs, preserved configuration, refusal of conflicting inputs and unexpected
execution, and fresh grant denial. Use exact selectors with `--no-coverage`.
Do not execute a complete local population or measure candidate coverage.

No product behavior, public CLI/MCP, storage/schema, runtime dependency,
package/lock, SDK recipe, runner policy, threshold, denominator, scientific,
full-W5, production, main or release acceptance changes. Hosted qualification
remains pending for the new exact candidate.
