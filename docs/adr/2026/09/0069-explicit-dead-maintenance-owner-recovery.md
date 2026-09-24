# ADR 0069: Explicit recovery of a provably dead maintenance owner

- Date: 2026-09-23
- Status: Accepted for implementation by FIX37; focused verification passed
- Supplements: ADR 0048

## Context

The normal maintenance lease must exclude concurrent maintenance. Requiring that
same lease before recovering its dead owner makes the recovery path unusable.
FIX37 authorizes a bounded cooperative single-user recovery command, exercised
only against test-owned roots during implementation. Prior operator recovery is
consumed authority and is not replayed.

## Decision

Add an explicit `recover-maintenance-owner` maintenance subcommand requiring an
absolute configured scratch root, the exact existing maintenance record ID, and
literal recovery confirmation. Ordinary test startup continues to fail closed.
Validate private regular-file ownership, record schema, project, expired lease,
positive PID and process-start evidence. Only proven-dead ownership is recoverable;
live, unknown, malformed, replaced, or mismatched records are refused.

Serialize recovery attempts with a nonblocking OS lock on the existing owner
inode. Process termination releases that lock without a new persistent authority.
Before changing either record, durably retain the exact records and file identity
in a private intent. Revalidate liveness and exact identity before unlinking.
A paired admission barrier is eligible only for the same dead `recover-index`
owner, matching owner token, PID and start evidence. Remove that barrier before
the maintenance record so interruption leaves the original recovery entry point
usable. Retain completion or interruption evidence; never suppress the original
interruption. This is cooperative local maintenance, not hostile-host attestation.

## Boundaries and alternatives

No run deletion, index reconstruction, resource reclamation, runtime restart,
startup auto-retirement, or global permission change belongs to this command.
Acquiring ordinary maintenance first is rejected because it recurses into the
obstruction. Creating a second persistent recovery lock is rejected because it
can itself strand ownership. The existing inode lock adds no dependency.

## Verification

Sixteen focused recovery cases passed within the 124-test FIX37 unit selection.
They cover actual exited and live process evidence, unknown status,
PID reuse, exact identity replacement, lease and confirmation rejection, paired
and foreign admission records, competing recovery, interruption, evidence
preservation and ordinary maintenance reacquisition. Tests use private temporary
roots; no owner maintenance is performed on the developer runtime.

## Consequences and rollback

Operators gain an explicit, auditable escape from a proved dead lease. Recovery
records are evidence, not admission locks. Unsupported non-POSIX environments
refuse this command. Removing the subcommand and helper restores prior behavior;
retained private evidence remains untouched.
