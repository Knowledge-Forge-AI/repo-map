# Test-Hygiene Operator Reclamation

`tools/test_hygiene_maintenance.py operator-reclaim` is an irreversible,
operator-only recovery command. Implementation and test acceptance do not
authorize an agent to use it. Every real invocation requires a new, current,
explicit operator instruction in the same session.

## Destructive scope

The command removes every entry and descendant under the explicitly selected
scratch authority's `r` directory. It includes valid RepoMap runs, malformed
or foreign manifests, non-RepoMap co-tenants, report-pending data, pinned data
when separately overridden, and other retained evidence that automated GC may
never delete. The `r` directory itself remains.

The command does not clear `.quarantine`, `.gc`, `.index`, or
`.operator-reclamation`. It reconciles only exact advisory records,
protection records, and monitoring links attributable to reclaimed run
identities. It never expands automated-GC authority.

There is no rollback promise.

## Required authorization

The scratch root must already exist, be explicitly selected through
`REPOMAP_TEST_SCRATCH_ROOT`, be owner-private mode 0700, and carry the existing
RepoMap index authority. The command has no path, project, glob, regular
expression, or run-ID argument and never creates the selected root.

The required confirmation value is exactly:

```text
IRREVERSIBLY RECLAIM ALL CONTENTS OF THE SELECTED SCRATCH RUN DIRECTORY INCLUDING NON-REPOMAP AND RETAINED EVIDENCE
```

It must be passed as the value of `--confirm`. Equality is literal: changed
case, leading or trailing whitespace, prefixes, suffixes, substrings, and
environment or configuration values do not authorize anything. As with any
CLI argument, the literal may be visible in shell history or process
inspection while the command runs.

Live RepoMap runs block by default. `--force-live` is a separate explicit
override, still requires the literal confirmation, writes durable
`operator_interrupted` markers before deletion, and never kills a process.
UNKNOWN liveness always refuses and has no override.

Only an exact-valid RepoMap manifest supplies RepoMap liveness authority.
Foreign, ambiguous, and opaque entries remain inside the explicitly confirmed
broad deletion scope, but their manifest metadata cannot establish a RepoMap
LIVE or UNKNOWN veto. This does not make those entries automated-GC eligible,
does not assert that a referenced foreign process is dead, and does not change
the exact-valid UNKNOWN refusal.

Operator pins block by default. `--override-pins` is a separate explicit
override and still requires the literal confirmation. `--force-live` does not
imply `--override-pins`; `--override-pins` does not imply `--force-live`.

Agents, defaults, configuration, disk pressure, prior conversations, earlier
operation records, phase acceptance, or an earlier typed value may not
self-authorize this command.

## Evidence and interruption

The command acquires global maintenance and an admission barrier before its
complete no-follow inventory. Strict private operation, progress, and
interruption evidence is stored below `.operator-reclamation` outside the
deleted `r` scope. Public-safe JSON output and the local JSONL log contain only
bounded counts, byte/inode totals, closed categories, flags, timestamp, scope
class, and outcome.

A pre-point-of-no-return failure deletes no scoped bytes. A post-point-of-no-
return failure is `partial`, is not rolled back, and may retain the admission
barrier until the existing maintenance recovery command restores safe index
authority. A later attempt is a new operation and requires a fresh current
confirmation and fresh overrides; operation evidence is never resume
authority.

Post-PNR deletion has one operation-scoped 1800-second physical-deletion
budget. The same absolute monotonic deadline is computed once and applies
across all immediate entries and inside every descriptor-relative tree. There
is no CLI, environment, or configuration override. This explicit broad
operator window is approximately thirty times the automated historical-GC
window; large selected roots are therefore not expected to require the former
one-minute operator slices. Automated historical GC remains separately bounded
to 60 seconds and receives no authority from this operator-only command. The
budget bounds physical tree deletion; exact
captured-record reconciliation after a completed entry remains identity-bound
but is not charged to that physical-deletion clock. If it expires, the command stops at the first
incomplete entry, reports `outcome: partial` and
`partial_reason: wall_time_limit`, returns exit status 2, retains exact partial
byte/inode progress, leaves that immediate entry present, and does not delete
later entries. For every earlier immediate entry that completed physically,
the command first persists full-entry progress and then reconciles only its
exact pre-captured monitoring, protection, and advisory-index records. Records
attributable to the incomplete or later entries remain. Nonzero
partial bytes or inodes mean physical mutation occurred even when no immediate
entry was fully removed. Expiry after a directory's children are gone but
before its final removal can leave an empty immediate directory. A
`wall_time_limit` result is exact durable progress, retains the admission
barrier, and requires separately authorized recovery before another operation;
it grants no retry or resume authority.

A catchable exceptional safe-tree failure preserves exact observed removed
bytes and inodes in durable evidence under a closed failure category. The
incomplete immediate entry is not counted complete, and later entries remain
untouched. When a removal syscall succeeds and the following directory fsync
fails, the removal is credited because it was observed, while
`durability_error` records that the following durability confirmation failed;
the evidence does not overclaim durable persistence. Hard process death remains
uncatchable and may still leave a retained barrier requiring authorized
recovery.

The retained admission barrier is recoverable only after its existing
3,600-second lease has expired and its owner is provably dead. Maintenance is
released when the partial operation returns. Existing recovery restores
barrier/index authority. Normal complete-then-partial handling leaves no exact
captured monitoring, protection, or index record for an earlier fully deleted
entry. An unusual exact-record reconciliation failure still stops post-PNR,
retains the barrier, leaves later entries untouched, and requires operator
attention; it is not rolled back or represented as successful cleanup.

Before PNR, private operation evidence also records aggregate running-state
observations for foreign and ambiguous manifests. Positive PIDs use the
existing read-only signal-zero probe for audit classification only; missing,
non-integer, and nonpositive PIDs use an invalid/missing count. These counts
never feed RepoMap LIVE/UNKNOWN, force, refusal, marker, or deletion authority
and never enter public output. Permission failures classify UNKNOWN, so the
counts are bounded observations rather than a complete co-tenant census.
Ambiguous entries without a parseable manifest have no running state or PID to
observe and therefore contribute to none of the twelve activity aggregates.

## Preflight diagnostics

Structurally pre-record failures use one of these closed categories:

- `scratch_root_authority_unavailable`
- `maintenance_authority_unavailable`
- `index_authority_unavailable`
- `admission_barrier_unavailable`
- `inventory_authority_unavailable`
- `inventory_identity_changed`
- `liveness_authority_unavailable`
- `protection_authority_unavailable`
- `monitoring_authority_unavailable`
- `index_record_authority_unavailable`
- `operator_evidence_authority_unavailable`

For these typed results, `physical_mutation_performed: false` means no entry or
descendant was deleted from `r`; it does not claim that a transient maintenance
claim, barrier, or evidence record was never created. Their cleanup is proved
separately. Names ending in `authority_unavailable` also include authority
refused as unsafe and do not imply that a blind retry is safe.

An unexpected exception outside the typed pre-record guarantee remains
`operator_authority_unavailable` with
`physical_mutation_performed: unobserved`. Raw chained causes are private
debugging evidence and are not rendered by the public CLI projection. Normal
confirmation, LIVE, UNKNOWN, and pin refusals remain normal operator results,
not preflight exception categories.

## Exact dead maintenance-owner recovery

`tools/test_hygiene_maintenance.py recover-maintenance-owner` is a separate,
cooperative recovery entry point (ADR 0069). It requires an explicitly configured
absolute `REPOMAP_TEST_SCRATCH_ROOT`, `--record-id` equal to the existing
maintenance record identity, and `--confirm` equal to:

```text
RECOVER EXACT PROVABLY DEAD MAINTENANCE OWNER
```

A real invocation requires current operator authorization. The command checks
private ownership, exact schema and file identity, expired lease, PID and process
start evidence. Live or unknown owners are refused. A matching dead recovery
owner's admission barrier may be retired with it; foreign barriers are refused.
Private intent and completion/interruption evidence live beneath the existing
maintenance root. The command does not reclaim runs, reconstruct the index, or
acquire the dead maintenance lease first. Normal test startup never invokes it.
A refused or interrupted attempt is not authorization to retry or broaden scope.
