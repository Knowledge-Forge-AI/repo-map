# Sealing governance, worker attribution and v2 resource reports

Operator reference for `REPOMAP-CLOE-RESOURCE-GOVERNANCE2`
([ADR 0173](../adr/2026/11/0173-call-owned-resource-governance.md),
[contract](../specs/cloe-resource-governance2-v1.md)). Everything here is
opt-in. A refresh without the new options keeps its incumbent output, exit
code and I/O, and `--resource-report` alone still writes
`cloe-resource-view-v1`.

## What is measured

The governed boundary is one parent-side sealing call of a direct
`ops refresh-graph`: traversal and classification readers, discovery content
hashing, stable capture (with retries), the descriptor-bound copy, store writes,
store readback and collision comparison, the second scan and the manifest.
Worker, validation, publication and attempt-setup I/O are outside it.

Counters are program I/O, not physical storage traffic:

- read bytes are bytes returned by the owned readers, split by reader class
  (discovery hash, classification, stable capture, copy, store readback);
- write bytes are bytes admitted to the owned store writer;
- opens count every admitted descriptor, listing and temporary-file attempt,
  including attempts that then fail; entries count directory entries visited
  (including entries later filtered out); fsyncs and stable-capture retries are
  counted separately. Metadata calls are bounded but not counted.

A successful seal of a stable tree of `S` bytes reads at least `6S` (`8S` when
objects already exist), plus the manifest and classification reads. Stable
capture retries and the unknown-extension completion check add more.

## Budgets: `--sealing-max-*`

Available on single-graph direct `ops refresh-graph` (Local and Server):

| Option | Bounds | Refusal limit |
|---|---|---|
| `--sealing-max-read-bytes N` | owned reader bytes | `read_bytes`, `planned_read_bytes` |
| `--sealing-max-write-bytes N` | owned writer bytes | `write_bytes`, `planned_write_bytes` |
| `--sealing-max-opens N` | open attempts | `opens` |
| `--sealing-max-entries N` | directory entries across all walks | `directory_entries` |
| `--sealing-max-elapsed-ms N` | cooperative elapsed time | `elapsed_ms` |

Values are unsigned ASCII digits (at most 19; elapsed at most 86,400,000).
Every operation is admitted before it runs, so a counter never exceeds its
budget. Any budget makes the call *governed*: it first walks every binding's
metadata, applies the existing artifact limits and refuses a provable overrun
(`6S+1` reads, `S` writes) before any body read. Governed calls also bound
retained classification text (`classification_retention`, 1,048,576
characters) and always have a finite directory-entry ceiling: the supplied
value, or 100,000 for this explicit operation. That fallback is a visit
ceiling across preflight and both scans, not a selected-file count. There is
no default budget.

An exact-need run needs the per-file costs above plus the manifest plus one
byte of end-of-file headroom. The elapsed limit is checked between operations;
it is not a hard operating-system deadline.

Refusals:

- Local prints `ERROR: sealing-budget-exceeded:<limit>` and exits 1.
- Server returns a failure with `error_category=resource_budget_exceeded`,
  `publication_state=not_started` and diagnostic code `sealing-budget-exceeded`
  only when the refusal is the terminal error and the publisher was provably
  never entered. A later cleanup failure stays an ordinary failure.
- No refusal deletes stored objects or the attempt root; incumbent retention
  applies.

Usage errors refused before any configuration is read:
`invalid sealing budget: <option>`, `resource-report-schema-requires-report`,
`sealing-budget-unsupported-mode` (coordinator mode) and
`sealing-budget-requires-report-schema-2`.

## Report schema 2: `--resource-report-schema 2`

`--resource-report-schema {1,2}` requires `--resource-report` and is accepted
on every report seam. A budget combined with a report requires explicit schema
2, because v1 can only say the sealing limit is absent. The Python API applies
the same rule: a nonempty `SealingBudget` with a v1 observer is refused before
work.

`cloe-resource-view-v2` keeps the v1 time and total rows and adds, for refresh:

- twelve `sealing_*` rows (`call_meter_exact` when the call closed its meter,
  `call_meter_partial` and an `incomplete` report otherwise);
- `planned_inventory_files`, `planned_inventory_bytes` (`metadata_inventory`)
  and `planned_min_read_bytes` (`derived_lower_bound`) for governed calls;
- six worker rows measured from the parent's single `wait4` of the launched
  worker (POSIX only). Linux reports CPU including waited descendants and the
  largest single-process peak RSS (KiB x 1024); Darwin values are
  `wait4_platform_defined`. Values that cannot be observed are `unavailable`
  with a closed reason. `worker_group_members_after_reap` reports members still
  in the worker's process group; processes that left the group are
  unobservable.

Usage collection also enables a bounded kill-first interrupt cleanup for that
worker launch only. The default path and coordinator launches are unchanged.

v2 files are at most 16,385 bytes; `ops resource-report check|show` reads both
schemas and keeps every v1 bound. Older readers refuse v2 files.

## `ops sealing-plan`

```sh
cloe ops sealing-plan --repo-map-home HOME --graph ID [--json] \
  [--sealing-max-entries N] [--sealing-max-opens N] [--sealing-max-elapsed-ms N]
```

After ordinary configuration resolution it walks source metadata only: no body
read, database, graph lock, worker or write. The canonical
`cloe-sealing-plan-v1` output (at most 4,096 bytes, identity-free) reports the
inventory, the visits and listings it used, `planned_min_read_bytes` as a lower
bound for one successful seal at that instant, and
`projected_directory_entries` as an estimate of three walks of an unchanged
tree. It is not a promise about a later refresh. The plan is not exposed over
MCP.

## Limits of these claims

No hard RSS cap, physical-storage, PostgreSQL work, efficiency, Windows or
installed qualification is claimed. Classification retention stays unbounded in
default and observe-only calls, and the default-path interrupt orphan risk
remains. When several inventory limits are exceeded at once, the governed
preflight, which checks file by file, may name a different limit first than
the default post-scan admission. The messages are the same.


The plan’s inventory file/byte totals use unique canonical selected paths per
binding. Eligible in-root aliases still add real discovery/classification work;
`inventory_symlinked_files` counts eligible symlink entries before deduplication
and may exceed the unique-file count. The labelled read bound is a successful-
seal lower bound, not a prediction that aliases, classification, collisions or
retries will cost no extra work.

## Elapsed timing scope

The elapsed clock starts at portable capture entry, before attempt setup and
retention pruning. Those operations are excluded from the I/O counters, but
their duration and retention-lock waits consume the opted-in elapsed budget.
A slow setup can therefore cause refusal at the first sealing admission. This
conservative timing scope is accepted for this preview; it is a cooperative
check between operations, not a per-syscall deadline.
