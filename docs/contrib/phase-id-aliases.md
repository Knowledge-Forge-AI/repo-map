# Phase ID Historical Aliases

## Purpose

This document records scoped historical phase-ID aliases that are needed to
interpret immutable repository history without reintroducing ambiguous phase
identities into active documentation.

Canonical phase IDs are the public development identities used by current
documentation, tasks, prompts, roadmap entries, and new reports. A historical
alias is interpretive metadata only. It does not reserve or redefine the same
token outside its exact recorded context.

## Summary Rows Collision Resolution

PHASE-ID0 identified two completed phase families that both used
`STORAGE-ROWS0` through `STORAGE-ROWS7`. PHASE-ID1 resolved the public
documentation identity as follows:

- the earlier broad `storage/rows.py` family remains canonically
  `STORAGE-ROWS0` through `STORAGE-ROWS10`;
- the later focused `storage/summary_rows.py` family is canonically
  `STORAGE-SUMMARY-ROWS0` through `STORAGE-SUMMARY-ROWS7`.

The old token alone is not a global alias. For example, `STORAGE-ROWS3`
continues to mean the canonical Family A legacy-storage-row split unless the
reference is explicitly tied to the Family B status sequence, historical
2026-07-07 context, renamed status path, or immutable commit subject recorded
below.

## Scoped Alias Map

*Note: The status paths below are internal historical records withheld from public export.*

| Historical alias | Canonical phase ID | Historical status sequence | Historical status path (withheld) |
| --- | --- | --- | --- |
| `STORAGE-ROWS0` | `STORAGE-SUMMARY-ROWS0` | `00295` | `docs/status/2026/07/07/00295-storage-summary-rows0-split-design.md` |
| `STORAGE-ROWS1` | `STORAGE-SUMMARY-ROWS1` | `00296` | `docs/status/2026/07/07/00296-storage-summary-rows1-core-helpers.md` |
| `STORAGE-ROWS2` | `STORAGE-SUMMARY-ROWS2` | `00297` | `docs/status/2026/07/07/00297-storage-summary-rows2-storage-records.md` |
| `STORAGE-ROWS3` | `STORAGE-SUMMARY-ROWS3` | `00298` | `docs/status/2026/07/07/00298-storage-summary-rows3-language-summaries.md` |
| `STORAGE-ROWS4` | `STORAGE-SUMMARY-ROWS4` | `00299` | `docs/status/2026/07/07/00299-storage-summary-rows4-domain-summaries.md` |
| `STORAGE-ROWS5` | `STORAGE-SUMMARY-ROWS5` | `00300` | `docs/status/2026/07/07/00300-storage-summary-rows5-manifest-summaries.md` |
| `STORAGE-ROWS6` | `STORAGE-SUMMARY-ROWS6` | `00301` | `docs/status/2026/07/07/00301-storage-summary-rows6-nix-summary.md` |
| `STORAGE-ROWS7` | `STORAGE-SUMMARY-ROWS7` | `00302` | `docs/status/2026/07/07/00302-storage-summary-rows7-split-closeout.md` |

## Recognition Rules

A historical Family B alias is recognized only when at least one durable
scope discriminator identifies the summary-row family:

- status sequence `00295` through `00302`;
- the corresponding canonical status path in the table;
- the 2026-07-07 summary-row phase chronology;
- an immutable historical commit subject for the summary-row phase;
- an existing private report that binds the old label to the exact historical
  commit and status sequence.

Without one of those discriminators, `STORAGE-ROWS0` through
`STORAGE-ROWS7` refer to the canonical earlier Family A phases. A consumer must
not translate the old token globally or infer Family B from the numeric suffix
alone.

## New Reference Policy

New public documentation, roadmap entries, tasks, prompts, manager/worker
control records, and reports must use `STORAGE-SUMMARY-ROWS0` through
`STORAGE-SUMMARY-ROWS7` for the focused summary-row family.

The retired Family B labels may appear in public documentation only inside an
explicit historical alias table, collision inventory, remediation status
record, or quoted immutable commit-subject context. Such a reference must also
provide the canonical phase ID and a scope discriminator.

No new private report should use a retired Family B label after PHASE-ID1.
Future control-plane records should use the canonical phase ID even when they
also bind an exact private base or result commit.

## Immutable Git And Private Report Boundary

Existing Git commit subjects are not rewritten. The eight 2026-07-07 Family B
subjects retain their original `STORAGE-ROWS` labels as immutable historical
aliases.

Existing private `git-show-report` artifacts may retain their original phase
labels, commit subjects, exact private commit identities, and trusted-review
evidence. PHASE-ID1 does not inspect, edit, move, or rename those artifacts.
A later `repo-map_ctrl` migration may preserve both a canonical phase-ID field
and an explicit historical-alias field, but that control-repository design is
separate work.

## Maintenance

`docs/contrib/phase-identity-policy.md` defines the permanent phase-ID
uniqueness, namespace, historical-alias, and future scanner rules. This file is
the approved alias ledger, not the canonical phase registry.

New alias entries require a documentation-only review that records the
canonical target, durable discriminator, immutable-history reason, and review
condition. Stale, unused, ambiguous, or overbroad entries must be removed or
rejected. No entry may authorize a global token translation.
