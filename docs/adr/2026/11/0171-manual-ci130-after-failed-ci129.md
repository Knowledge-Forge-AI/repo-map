# ADR 0171 — One manual CI130 staging attempt after failed CI129

Status: Accepted for one manually requested staging retry after final proof and independent review. Hosted qualification remains pending.

Date: 2026-11-08

Campaign phase: `REPOMAP-CLOE-CI129REPAIR1` (the active repair phase whose
single successor attempt is workflow ordinal 130).

## Decision

Prepare exactly one manually authorized CI130 attempt 1 against the existing
draft PR 23, using the ordinary `synchronize` event on `staging` against
`main`. The application-start budget is 40 authenticated starts already
consumed plus one new start: total/per-platform cap 41. The native AMD plan
adds one command and two wheel transfers, taking the authenticated counters
from 9/22 to caps 10/24. These are reservations and caps, not qualification
results.

The preparation must append an authenticated CI129 consumption observation to
the inherited ledger before deriving the CI130 reservation. CI129 remains
`EXECUTED_FAIL` overall: the system lane and Rust/native lane passed, but the
unit and integration lanes reported failures, hard coverage and staging
obligations did not qualify, and whole-candidate acceptance is false. The
failed campaign consumes its slot and is denied for reuse; its successful
system/native sub-results must not be promoted into whole-candidate
acceptance.

The proposal keeps every inherited ledger root value, list prefix, and
`SPENT_`/`SUPERSEDED_` constant. The guard receives one new
`SPENT_CI129` tuple; no earlier result is repinned. The binder refuses an old
129 reservation and a new 131/42 attempt, while making only the newly valid
130/41 values available to the owner tests.

## Scope

Only these six governance owners are proposed:

* `tools/ci/d12_system_build_grant.json`
* `tools/ci/d12_hosted_candidate.json`
* `tools/ci/d12_system_grant.py`
* `src/test/unit/python/tools/ci/d12_system_grant.unit.test.py`
* `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py`
* `tools/ci/rust_pilot_qualification_manifest.json`

The unit and integration templates retain their 400 physical lines and all
existing negative cases. Imports are folded into existing import lines. The
exact current integration preimage differs from the prior CI129 postimage by
one blank-line amendment; adoption must validate that explicit override and
must never silently accept a receipt mismatch.

The Rust closure remains 264 paths unless an accepted parent proof establishes
an actual overlap. The current `_server_retention_lock.py` and
`_portable_retention.py` changes are not closure entries by default. The
manifest proposal binds the accepted closure decision without repinning an
old native result.

## Binding and serialization

The private binder requires a parent-accepted preparation packet and
final-source proof. It derives the D12 context from the live Q checkout with
Git's cached-plus-untracked listing, including final untracked source, rather
than copying a prior file count. The parent packet supplies only the recipe
and Dockerfile digests and the acceptance boundary; the binder verifies the
derived source digest and count against that proof.

Approval construction intentionally excludes approval, reservation, guard,
and post-render-manifest fields. The one-way dependency is:

```text
approval -> guard raw bytes -> guard SHA -> manifest raw bytes -> reservation
```

The candidate JSON is parsed and freshly serialized with real JSON
serialization to remove the inherited indentation defect. All other owner
postimages are strict raw-byte bindings. The binder preserves public author
and committer metadata as Samuel Leighton Lair
`<sam.lair@knowledge-forge.ai>`.

## Post-bind proof boundary

After parent adoption, the required governance proof is exactly five unit
owner checks and three integration owner checks, excluding materialization.
Static, privacy, quality, and history checks remain required, as does an
independent `dynamic_default` review. The final integrated readonly APGR
review is a single parent checkpoint; the proposal does not invent a second
feature-only acceptance gate. Source acceptance remains conditional until
that review and the parent’s final proof packet.

This decision permits the scoped proof above, independent review, one source commit and one ordinary staging push under the current retry request. New local application or SDK builds, native qualification, acquisitions, main/tag publication, automatic retries, a second push and CI131 remain excluded.

## Alternatives and rollback

* Reusing CI129 is rejected because its slot is spent and its overall result
  is failed.
* Raising the cap to 42 or opening CI131 is rejected because it would be a
  retry/successor outside this one-attempt authority.
* Binding a copied D12 count or silently repinning the prior native result is
  rejected because final source is still being accepted and the context must
  be recomputed.

Rollback is proposal disposal before adoption. After adoption, the parent
must stop on any preimage, ledger-prefix, closure, approval-cycle, or
post-bind-proof mismatch; no replacement reservation is implied.

## Unresolved assumptions

The parent must supply the accepted packet, final-source pins, current D12
recipe/Dockerfile proof, native plan, closure decision, and exact prebind
amendment override before running the inert binder. Those values are not
invented here. The active repair-phase naming is retained even though the
successor workflow ordinal is 130; the parent must reject the proposal if
the current operator’s phase authority changes.
