# ADR 0186: Admit bundle records before spill and bound merge fan-in

Status: bounded source accepted by the parent after an independently audited
corrective review; hosted qualification remains pending.
Date: 2026-11-12. Phase: `REPOMAP-CLOE-RESOURCE-GOVERNANCE5`.

## Context

The sorter consumes a complete family before the encoder checks aggregate
record/byte limits, then opens every run for its final merge. The buffer's byte
threshold alone bounds neither descriptors nor spill work. ADR0185 defers these
gaps and a separate descriptor leak in verify_stream_path.

The built-in store defaults to 4 GiB; validated portable capability limits are
positive integers no greater than 4 GiB. The encoder's own default is 1 GiB,
which differs from that worker ceiling. Custom stores retain their own limits.
Only the portable semantic adapter constructs the encoder in maintained product
source. Metered storage has a separate verification owner and is unchanged.

## Decision

Give sort_family_records optional byte_budget and record_budget keyword
arguments. None preserves direct callers' current aggregate admission behavior.
At each family start, the encoder supplies its remaining existing byte limit
after header/prior families and its current module-global record limit after
prior families. Keep output-side checks and trailer accounting authoritative.

For each row: check cancellation, acquire the row, check cancellation, encode,
check line size, then record and byte budgets, then buffer/spill. Equality is
admitted; one proving overflow row may be acquired/encoded but is not buffered
or written. Use existing bounds messages and exception/category vocabulary.
Trailer-only overflow still refuses late. Do not pre-refuse from a RowSpool
count: that would unnecessarily preempt existing encoding/line faults.

Use a private fixed merge fan-in of 32. Refuse a non-integer or value below two
before acquiring IO, so an internal invalid value cannot prevent progress.
Initial runs are registered before
writing. A full level compacts into one run on the next level; carry repeatedly
as needed. At input end, promote/compact the lowest nonempty levels until at
most 32 runs remain, then stream the final merge. Preserve canonical line bytes,
duplicates and order, and therefore descriptor/family checksums and bundle IDs.
Initial spill_run_count and spill_bytes keep their existing ingress meanings;
rewrite IO is not silently included or claimed absent.

Register partial output custody immediately after acquisition. Open at most
32 run inputs and one merge output; close every partial acquisition. Unlink
inputs only after successful output close. A failed normal close/unlink is
visible and aborts further compaction rather than accumulating stale inputs.
Attempt every owned cleanup; preserve an actual primary failure. The owned
temporary-directory cleanup remains fallback. Never sweep another directory.

Repair verify_stream_path acquisition through fstat, identity validation,
reference construction, fdopen and verifier construction. Retain fd custody
until a raw owner exists, then raw custody until verifier transfer. Preserve
safe read-error mapping and current factory/identity seams. The existing
verification context's close-error precedence is unchanged. No asynchronous,
hostile replacement or fdopen-internal-close/reused-fd guarantee is added.

## Refusal ordering and scope

The parent explicitly accepts earlier refusal of invalid over-limit input
within ordinary W7 resource governance. Accepted bundles remain byte-identical;
no threshold, protocol, category, CLI/MCP contract or public setting is added.
An overflow now preempts faults reachable only after that arrival, including
later source/encoding/line/merge/store IO, checkpoint callbacks and cancellation.
Mixed-fault messages or adapter categories can therefore differ. Reached
faults keep their own cause; unrelated data faults do not become cancellation.
Worker terminal event precedence is unchanged and is not inferred from adapter
tests. This is not a claim of identical rejection timing for invalid streams.

## Calculated resource limits and exclusions

With admission, sorter spill payload is at most the admitted byte budget B;
while a compaction output is being written, it is at most 2B, assuming successful
IO/cleanup. An IO/cleanup failure stops progress and is not reported as normal
completion. Run metadata grows logarithmically in initial run count, bounded by
the fan-in per level plus the current output. Merge heads hold at most 32 lines,
each subject to the existing line limit. Python object overhead, reader buffers
and the configured payload buffer are separate costs.

Concurrent store temporary bytes and prepared-row spools must be counted
separately. Capture/preparation can already have materialized the source before
sorter admission, so this is not a whole-worker disk, CPU or OS-quota guarantee.
Direct unlimited sorter callers retain their aggregate behavior. At the generic
1 GiB/64 MiB defaults no compaction is expected; this is a calculation, not a
worker-wide or measured speed claim. The 4 GiB capability can require compaction.

## Alternatives, acceptance and rollback

Status quo preserves the resource gaps. Larger buffers do not bound fan-in;
one all-run merge retains descriptor growth. External sort dependencies, format
changes, new settings and a generic resource framework are unnecessary.
Coordinated source/test reversion needs no data migration.

Require RED witnesses and scoped canonical unit plus actual containerized
integration with --no-coverage: exact admission boundaries across families,
closeable input consumption, canonical bytes/checksums, bounded real handles,
multi-level spills, partial IO/cancellation/consumer close, descriptor identity,
other-file preservation and Local/Server publication refusal atomicity. Include
the maintained worker-to-PostgreSQL corpus and post-finalize rollback where the
shared publication contract is affected. Keep owners within project limits and
all inherited quality/debt ceilings unchanged. Independent resulting-source
review and parent acceptance are required before milestone publication.

No dependency, metadata/lock, runner-policy/native class, image/acquisition/build,
model study, full local suite, local Python coverage, live target or remote
action is granted. CI140 50/20/44 and both earlier claude_only reviews are spent;
future dispatches use dynamic_default. Full W5-W8 and coverage cushions stay open.

## Review disposition

The independent reviewer read all 23 exact copies and attested their hashes.
Parent audits reconcile actual bytes, pages and scope for every granted stage.
All ten advisory findings are incorporated: citations/seams, complete fault
class, adapter/terminal distinction, exact bounds, handle counting, combined
space and rejected pre-count. Source inspection resolves the built-in-store
limit question and capability ceiling. Parent additionally requires failed
unlink to abort compaction, because suppress-and-continue would invalidate the
claimed bounds. The hash helper was absent from producer/closer tools; those
stages disclose no hash attestation. Their exact reads and the reviewer's hashes
are independently reconciled; no missing tool proof is manufactured.
