# ADR 0157: CI121 grant-only manifest digest lineage

## Status

Accepted by the operator on 2026-11-05. Amendment approval
SHA-256: `2a751829eb6bfb53c6305cf4768d0ba9620e46ac3704cdcd91d8a0648b0e9724`. No additional resource allocation.

## Date

2026-11-05

## Context

[ADR 0156](0156-rust-milestone-ci121-one-use-publication.md) permits the CI121
ordinal-specific D12 admission update but requires the Rust manifest to remain
byte-identical. Its grant guard is itself a pinned closure member. These two
conditions conflict: the stale manifest correctly refuses after the approved
guard update. No publication or new native execution followed that refusal.

## Decision

Amend only the manifest-byte-identity condition for CI121. Replace the
`tools/ci/d12_system_grant.py` entry's SHA-256 in the Rust qualification
manifest from
`72bbde96f34e3016f2f9b83c4ac7678c4b86ce1afa02c7202abc188b3ef2dd1b`
to
`3ef020bb400f61816beda3d2d767e6bbdf410d5813145d0f88a7591b325d48c6`.
No other manifest field, source pin or closure path changes.

The original manifest digest is
`73b56dcbba3f925573b2176aa2fb442c7d63db15554200ecedc35b4e8ef666bc`;
the successor is
`604150870defd0f94f0bf858e22d255cf123a487a643a973dcd3e75030249d2c`.
All other 263 source rows, parser/controller code, profiles, fixtures/golds,
claims, scenarios, SDK, artifact pins, budgets and thresholds stay identical.
Preserve both exact manifests and the original ARM2 report as distinct evidence.

The guard changes only current campaign binding literals, ordinal/cumulative
caps and the added spent-CI120 constants and denylist entries. Full source
comparison and independent review are the primary evidence; the declared
normalized AST comparison supplies supporting structure only. Strict scoped
admission tests also pass. The full manifest
validator accepts the successor. This does not waive digest checking or permit
an arbitrary closure update.

## Evidence boundary

Carry the useful ARM2 parser/containment evidence only for the unchanged
component behavior. Its actual native result remains bound to the original
source commit and manifest; do not claim the successor whole manifest was
natively ARM-qualified. ARM 2/2 is spent and no third command is granted.
The existing native AMD command in CI121 must independently validate the
successor and still fail on any current source or qualification discrepancy.

Append a separate ledger lineage record binding the original and successor
manifest digests, current grant source digest, review and actual amendment
approval digest. Preserve every existing record and the grant's approval and
before-ledger bindings; changing the guard again would change its source pin.

Before publication, recompute the unpatched live frozen build-context identity
on the exact final tree and require equality with both grant and candidate.
Check the exact successor manifest and all pins, run exact
manifest unit/connected containerized checks plus final hygiene/privacy/binding
proof, and disposition the independent review against the applied bytes.
No new application allocation, acquisition, command, build, campaign or retry
is granted: ADR 0156's one start 32, existing AMD slot, one staging push and
automatic CI121 attempt 1 remain the complete limits.

## Alternatives and consequences

Leaving the stale digest would guarantee a native gate refusal. A third ARM
command is neither allocated nor necessary to re-execute unchanged parser and
containment code for this campaign-only metadata change. Generalizing the
exception or dropping closure ownership would weaken the boundary and is
rejected. Full W6, Local Rust, image, whole-candidate and release acceptance
remain separate.
