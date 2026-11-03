# ADR 0140: CI108 OCI fixture repair and CI109 retry

## Status

Accepted parent-bounded remediation under the current maintainer instruction
`ci failed try again`. This records one successor allocation; it is not a
numerical human reply and does not authorize a general build-budget increase.

## Evidence and cause

CI108 attempt 1, workflow run `41569511859`, tested public head
`4eae9e49da880508b0ac4bc77665be7ab487da7d` through merge candidate
`6fdc3c86bc323dd20f10340a1280482dad7b3844`. The authenticated system receipt
passed all five system scenarios, and cleanup terminal absence was verified.
The hosted campaign nevertheless failed only in the unit job: 46 raw-OCI
fixture cases were red in two existing owners, 10 in
`d12_native_python_proof.unit.test.py` and 36 in
`d12_native_python_observer.unit.test.py`. Exactly one application build
occurred; no second start occurred in that campaign.

The authenticated observation is retained at
`evidence/CI108-OBSERVATION.json`; its system artifact is SHA-256
`abf30312403553354e449c39ecf295e243f2ac9fd70893c484def811674fa59f`.
The terminal observation records one actual start, cumulative actual starts
24, spent slot, and no automatic rearm. The full ledger prefix and its legacy
hold (`maximum_total=0`, `maximum_per_platform=1`) remain unchanged; the
observed ledger appends the CI108 consumption record only.

## Decision

Repair the two raw-OCI fixture consumers against the actual frozen envelope,
manifest/config/rootfs relationships and existing strict refusal contracts.
Keep the current SDK recipe, dependency policy, public schema and native
system contracts. A fixture-only repair is not required to change the frozen
source, recipe or context identity; CI109 binding records the actual identity
and never relies on an assumed change.

Authorize one fresh CI109 `linux/amd64` attempt 1 for the existing draft PR23
with cumulative maximum 25 after 24 authenticated actual starts. Bind a fresh
nonce, reservation, authority, current candidate context and the complete
historical ledger. Reject the spent CI108 nonce/reservation and every earlier
spent or superseded identity before any build. Do not mutate the old
reservation, legacy hold, workflow policy, or prior evidence.

## Limits and verification

The repair must use exact scoped unit and integration owners with
`--no-coverage`, plus static, checks and privacy receipts, followed by an
independent `dynamic_default` resulting-state review. Complete local suites,
coverage, application/SDK builds and production acceptance remain outside
scope. A successful reservation or system gate is not hosted qualification.

CI109 permits one ordinary staging synchronization only. There is no automatic
retry, duplicate push, manual dispatch, main/tag/release promotion, live
activation, or reuse of CI108 evidence as current proof. A failed CI109 attempt
retains its exact reservation and consumption history and requires a new
authority.

## Rollback

Rollback is a reviewed forward change. It preserves the published CI108
history, authenticated artifact, complete ledger prefix, spent nonce and
legacy stop state; it cannot reset the cumulative count or silently admit a
different OCI fixture contract.
