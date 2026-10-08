# ADR 0072: Portable configuration numbers and refusal state

## Status

Accepted to the extent demonstrated live by
`REPOMAP-PRODUCT1-QUAL12-READBACK1` (status 00969): **Product step 2: live DINAS
multi-source captured-snapshot proof qualified; observed browser-ux source drift
disclosed; current-worktree freshness not claimed.**

What that readback demonstrates for this ADR:

- A real ten-binding portable publication committed on its first attempt, with
  no retry and no `commit_unknown`.
- It ran under the binary64 extractor generation
  `eg1:repomap-0.1.0--config-binary64-v1` and the semantic identity
  `semantic1:multi-source-config-binary64-v1`.
- Its control, stage and publication records agree.

The deterministic-refusal, write-ahead publication-phase, startup-recovery and
evidence-retirement paths were not exercised live. They rest on the scoped
test evidence named below.

QUAL1, QUAL2 and QUAL3 failed and did not publish private main. HOST1's
`blocked_or_failed_not_qualified` disposition is historical and unchanged.
Private-main publication of this acceptance is subject to APGR finalization.

## Date

2026-09-24

## Decision and scope

Configuration value summaries represent finite parsed binary64 numbers as
`{"numeric_type":"binary64","hex":"0x1.4000000000000p+0"}`. The hex field is
exactly Python's `float.hex()` contract, preserving the parsed binary value,
signed zero and integral floats. It does not claim exact source-decimal
arithmetic. Integers, booleans, null and existing string summaries are unchanged.
Source dictionaries are never interpreted as numeric tags. Readback displays
the typed summary unchanged; display conversion is not a hashing operation.

Non-finite parsed scalars use a per-value refusal summary
`{"numeric_type":"binary64","refusal":"non-finite"}`. They are not ordinary
numbers, cannot enter artifact numeric encoding, and do not discard other
useful configuration observations. Malformed artifacts and unsupported contract
values still refuse publication. Secret-field suppression precedes summaries.
Scalar arrays share this contract. Numeric stable-member keys use the explicit
`binary64:<hex>` segment; non-finite keys fall back to summary-only arrays.
This avoids dictionary repr in identities. JSON, JSONC, JSONL, TOML, YAML and
plist paths sharing the summary helper receive the correction together.

The extractor generation and multi-source semantic identity change explicitly.
The integer-only artifact codec, framing and old-artifact decoder do not change.
Previously accepted integer-only payloads remain byte-identical with identical
headers; newly derived generation headers intentionally reflect new semantics.
Rounding, truncation, untyped stringification and broad artifact float support
were rejected because they lose meaning or enlarge the transport contract.

## Publication state

Worker terminal categories are data, separate from diagnostic strings. Preserve
deterministic contract/capability refusals as non-retryable categories. Preserve
the previous retry outcome for other portable failure classes until their
individual policy is authorized. Synthesized process exits map explicitly to
worker crash; protocol failure maps to protocol. Contract validation includes
the worker's existing bounded classification of programming/value errors and
oversized bundles; it is not retried.

Before adding evidence, inspect existing stage and committed-receipt evidence.
A missing receipt alone cannot prove that publication never started: a sent
COMMIT may finish after process termination. The correction must establish a
durable, attempt-bound write-ahead publication phase before the publisher's
transaction can begin. Disposition and startup recovery must consume this
evidence. Missing, malformed or mismatched evidence remains uncertain, and
unproved process cleanup cannot authorize a retry. Existing fencing and genuine
commit uncertainty remain authoritative. No schema change or portable-worker
database access is authorized by this decision.

## Evidence retirement and residual contract

Publication-phase evidence retirement is fail-closed, all-or-nothing, and path-identity safe.
Both candidate evidence files (`initial` and `decision`) must be validated against private
parent directory ownership, object type (rejecting symlinks), mode, link count, bounded size,
schema, and exact attempt identity before unlinking either file. Re-checking device and inode
identity immediately precedes atomic deletion with directory fsync. If any validation fails,
neither file is unlinked.

Retirement failures during terminal maintenance cleanup are never swallowed. The maintenance
contract introduces a frozen `CleanupReport(deleted_job_ids, residuals)` with property
`residual_count = len(residuals)`:
- `deleted_job_ids`: tuple of job IDs for fully unlinked and row-deleted terminal attempts;
- `residuals`: tuple of unretirable attempt tokens whose evidence failed safe retirement validation,
  preserving the underlying control rows fail-closed for future investigation;
- scan limit expands to `scan_limit = max(limit * 4, limit + 64)` when a publication retirer is
  configured, scanning past unretirable attempts while preserving rows fail-closed;
- sanitized error category tokens (`_sanitize_error_category`) classify retirement failures;
- protected states including `commit_unknown`, active leases, and active reconciliation remain untouched.

## Required evidence and rollback

Exact scoped unit and isolated container integration owners must prove numeric
round trips, sibling formats, old byte vectors, direct/portable parity,
generation change, one-attempt deterministic refusal, prior-graph preservation,
pre-publication termination and retained genuine commit reconciliation.
Rendered compose labels must drive status contract coverage. All new success
and refusal outputs participate in path-leak assertions. No complete suite is
authorized. Rollback requires reverting the correction as one semantic unit;
old portable artifacts remain readable throughout.
