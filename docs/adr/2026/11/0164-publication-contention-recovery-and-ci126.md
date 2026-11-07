# ADR 0164: Publication contention recovery and CI126

## Status and authority

Accepted for forward remediation under the operator's 2026-11-07 instruction,
“ci failed try again.” Phase `REPOMAP-CLOE-CI125REPAIR1` repairs the two
executed CI125 failures and permits one reviewed successor staging campaign.
This separate manual request supplies no automatic retry after CI126.

## Context

CI125 attempt 1 failed one unit assertion and one connected integration case.
The unit owner indexed the run INSERT by its old position before ADR0162's
admission guard. The integration owner demonstrated that an admission lock
timeout, sanitized as `StorageSchemaError`, became an unexpected recovery
diagnostic. It must remain an expected bounded refusal, retaining publication
uncertainty and singleton liveness until a later heartbeat can retry.

The other seven jobs passed, including native AMD and all five assembled
system scenarios. Both hard coverage gates passed; this is not a coverage-only
failure. No failed candidate or passing constituent lane is whole-candidate
acceptance.

## Decision

- Give the storage helper's existing sanitized busy refusal a dedicated
  internal `StorageSchemaError` subtype. Preserve its message, base exception
  compatibility, SQL, bounds, transaction ownership and fail-closed behavior.
- Translate only that subtype alongside the existing PostgreSQL lock/time
  refusal types in durable closure contexts; preserve legacy quarantine's
  existing conservative refusal result. Ordinary storage/schema failures,
  even with the same message, remain unexpected and retain their identity.
- Locate the run INSERT by its statement contract in the unit owner, rather
  than assuming an incidental prefix index. Preserve receipt field/value
  assertions and legacy optional behavior.
- Prove busy versus unrelated failures, retained publication uncertainty,
  absent closure writes, bounded startup refusal, no unexpected diagnostic,
  singleton liveness and successful recovery after the lock is released.

No CLI/MCP contract, schema, graph vocabulary, dependency, image, packaging,
role, retry policy or timeout changes are introduced. ADR0162's separate
sealing and positive-BIGINT policies remain in force. Other nonblocking
follow-ups remain deferred.

## One successor campaign

After scoped proof, exact-source checks and independent resulting-state review,
publish the final repaired candidate once to existing public `staging`.
Keep PR23 draft against unchanged `main`; use its normal synchronize event.
Do not duplicate the automatic pipeline manually.

Authenticate CI125's retained artifacts before appending its actual consumption:
application start 36, native AMD Rust command 5, and two pinned wheel transfers
(cumulative 14). CI126 attempt 1 may consume exactly application start 37,
native AMD Rust command 6, and one transfer of each same pinned wheel
(cumulative cap 16). Bind the fresh approval, before ledger, reservation,
before/base pair, actual D12 source/context count and current guard digest.
Preserve historical ledger roots and list prefixes; reject CI125 and older
authority, nonce, reservation and cap values. Do not repin old native evidence.

No CI127, start38, second push, rerun, main/tag/release promotion or deployment
is authorized. Hard coverage thresholds, denominator, branch measurement,
populations, suppressions and debt ceilings remain unchanged. Desired 87/82
branch margins remain open unless new hosted evidence establishes them.

## Verification and rollback

Use exact scoped canonical unit and containerized integration selectors with
`--no-coverage`, including both CI125 failing owners and adjacent storage and
recovery contracts. Grant proof selects its exact admission cases and excludes
the unrelated real runtime-materialization case. Use the existing cached SDK;
no new local application/SDK build, acquisition or native command is selected.
Complete local unit, integration, smoke, staging, system and combined suites
and local coverage are unselected; hosted qualification remains pending.

Retain preimages, current-candidate receipts, review disposition and the one
publication result. Correct future regressions forward under fresh authority;
do not rewrite reported commits or historical evidence.
