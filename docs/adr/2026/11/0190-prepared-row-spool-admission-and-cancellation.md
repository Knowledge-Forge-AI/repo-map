# ADR 0190: Admit prepared spools and cooperate with preparation cancellation

## Status

Bounded source accepted by the parent after independently audited design and
resulting-source review, exact scoped proof and documentation corrections.
Hosted qualification remains pending. Phase: `REPOMAP-CLOE-RESOURCE-GOVERNANCE7`.

## Date

2026-11-13.

## Context and decision

CI142 qualified the governance4/5/6 and CI141-repair source. Prepared rows are
still fully buffered or spooled before the portable encoder applies its byte
and record limits. The adapter checks cancellation around build_staged_rows,
leaving actual preparation loops without a cooperative check.

Supply one private call-owned spool-admission observer from the portable
adapter. Reuse the existing spool_artifact_observer(family, projected_bytes)
seam, which runs after encoding and before writing. Its limits are the current
capability max_bundle_bytes and _bundle_stream_encode.MAX_BUNDLE_RECORDS,
read through the encoder module at call time. Introduce no default limit.

Count one shared total of spooled records and the latest projected byte count
for each spooled family. Check the record total first, then the sum of byte
growth. Equality is admitted. Update neither counter after refusal. Reuse
publication bundle record/byte bounds exceeded ValueErrors and the adapter's
contract_validation mapping. One proving row may be acquired, checksummed and
encoded, but must not be written. The encoder's header, record, line, total and
trailer checks remain authoritative; in-memory rows are not charged by this
observer. This is earlier partial admission, not complete preflight.

This expressly amends ADR 0186's rejection of prepared-spool pre-refusal at this
earlier, still-growing seam. It does not introduce a post-preparation count
shortcut or change sorter admission. The parent accepts earlier refusal of
inevitably over-limit input, including preemption of later canonical/line/store
faults, disk exhaustion beyond the limit, checkpoints and cancellation. Reached
unrelated data or IO errors keep their current mapping. Cancellation encountered
at an earlier new check can preempt later contract errors; no event overrides
an actual already-raised data error.

## Accepted-data argument and its boundary

For each ordinary JSON-shaped worker row, compact sorted UTF-8 spool JSON plus
LF is no longer than the ASCII-escaped canonical bundle record containing that
same row. ASCII escaping is at least as long for each supported character class,
and the bundle adds its family/frame/record wrapper. Sorting preserves every
row and duplicate; there is no deduplication or privacy rewrite in the encoder.
An accepted bundle has header + all record lines + trailer <= B. Therefore its
spooled subset is < B and its spooled record count <= the encoder record bound.
An accepted candidate on this owned static-data path cannot fail the new checks.

The independent review correctly required unique JSON member names at every
depth. Parent inspection adds an existing owner omitted from those grants:
rows_with_checksum calls _FamilyChecksumAccumulator.add before yielding each
row to RowSpool. The accumulator recursively checks payload mappings through
_typed_value and rejects non-string keys before serialization. The worker's
stage_id is the fixed plain string stage-unassigned. Ordinary worker rows have
the required domain without a new validation rule. Tests must cover nested
non-string/NaN-key refusal before spool observation and representative Unicode.

No universal guarantee is made for adversarial Python key subclasses with
overridden equality/hash or concurrent mutation between validation and encoding.
Those objects are outside this private static worker's owned-data guarantee;
default direct storage/RowSpool callers retain their current behavior. Do not
silently tighten their domain or reinterpret RowSpool's existing observer.
Spool encoding remains UTF-8, bundle encoding remains canonical ASCII, and no
row-byte reuse or format change is selected.

## Cooperative preparation and ownership

Add only an optional keyword-only cancel_check: Callable[[], None] | None = None
to build_staged_rows and its private preparation helpers. The adapter supplies
its existing _cancelled(cancel_event); add no checkpoint name or worker event.
None retains the existing direct-caller path and dependency/test seams.

Check after file-row preparation and canonicalization, before each family,
before and after actual row acquisition, during buffered-row spool replay and
immediately before spool admission/write, and before an in-memory checksum.
The latter loop remains bounded by 4096 rows and is checked per family. A single
canonicalization, row conversion/checksum/encoding or IO operation is not
preemptible. This is cooperative responsiveness, not a wall-clock or CPU quota.

The controlled path owns its newly acquired row iterator, checksum generator
and the directly created family sources. Close every directly owned iterator
on success, failure and consumer close. A partial acquisition is registered
before the next operation. Exhausted-generator close is harmless. When no body
failure exists, attempt all closes and raise the first cleanup failure. With
an active body failure, attempt all owned closes while preserving that actual
exception object. Do not retry an uncertain release. Close any completed spool
before propagating an iterator close failure; retain existing all-family cleanup
and exact attempt-directory fallback. Do not close a caller's reusable iterable
merely because it is iterable. New helper scopes must distinguish acquired
iterators from iterable containers and avoid duplicate close attempts.

Existing measurement-hook and MaterializedWorkspace cleanup precedence is not
broadened by this decision. The private adapter supplies no staging measurement
sink. No native preemption, hostile replacement or absolute asynchronous cleanup
guarantee follows. Source/body fences, default discovery, candidate identity,
family checksums, receipt/bundle bytes and worker terminal protocols stay intact.

## Resource calculation and exclusions

With ordinary owned JSON-shaped data, successful IO and cleanup, the prepared
spool payload is <= B. ADR 0186's active sorter payload is <= 2B; the new bundle
store temporary is <= B. Their conservative combined payload bound is 4B, plus
materialized source, independent metadata/receipt objects, memory buffers,
Python overhead, filesystem allocation/metadata and pre-existing store objects.
This is not a whole-worker disk, RSS, physical-PG or operating-system quota.
Memory families are bounded in row count by the existing 4096-row threshold,
not in Python byte size. Encoder header/trailer overhead can still refuse late.

Parser stage_id overhead is a separate conditional bound: decoded spool payload
can add caller-supplied stage_id bytes per row. No parser change, new length
restriction or parser-wide B quota is selected. Canonicalization/capture
cancellation and outer workspace identity/refusal policy remain separate.

## Implementation, proof and rollback

Keep included Python owners <=400 physical lines and new owners clean under
the unchanged retention/type profiles. A narrow private spool-preparation helper
may be extracted while retaining the staged_rows facade's RowSpool, threshold
and checksum-constructor seams. Preserve PreparedStageRows' public import and
type. This is a local Orange design response for existing long routines and
optional API/failure semantics; no new Red growth or quality-debt allowance.

Use exact canonical unit and containerized integration selectors --no-coverage.
Add admission equality/+1/shared-family/state-on-refusal tests; characterize
Unicode/domain assumptions; prove cancellation during actual acquisition and
buffered replay, all-owned cleanup and exact primary identity. Reproduce actual
over-budget spooling and ignored mid-preparation cancellation before repair.
Reuse the existing real sealed portable-worker fixture, then exercise unchanged
Local and PostgreSQL publication state, failure/recovery and accepted bytes.
Distinguish in-process injected failures from actual spawned-worker success.
Do not claim native signal qualification from threading.Event witnesses.

Current owners to extend/regress include storage/row_spool.unit.test.py,
storage/staged_spool_custody.unit.test.py, storage/row_spool_custody.unit.test.py,
artifacts/bundle_sort_resources.unit.test.py and
coordinator/portable_spool_custody.int.test.py. New focused unit/integration
owners may be added under those existing roots, with matching scoped selectors
recorded in the exit. Resulting-source review must include the recursive checksum,
measurement and row-adapter owners omitted from the design grants.

Coordinated source/test reversion needs no data migration. No dependency,
package/lock, image/SDK, runner-policy/native class, schema/DDL/role, CLI/MCP/report
vocabulary, model/held-out/study, live/installed mutation, local build, complete
local suite or local coverage is granted. All old budgets stay spent. Source
readiness precedes independent work review and parent acceptance. Batch useful
connected epics toward the 10k–100k line aim without padding; this slice's estimate
is below that aim and does not select a public campaign. New dispatches use
dynamic_default. Full W5/W6/W7/W8 and desired coverage cushions remain open.
