# ADR 0185: Retain temporary-row custody through transfer and cancellation

Status: bounded source accepted by the parent after two independently audited
resulting-source checkpoints; hosted qualification remains pending.
Date: 2026-11-12. Phase: `REPOMAP-CLOE-RESOURCE-GOVERNANCE4`.

## Context

Three regression witnesses reproduce private row-file leaks after a timing
observer failure, normal unfinished writer exit, and partial parser setup.
Parser ownership begins too late and partial finishes are not registered
incrementally. Bundle sorting consumes its input before observing cancellation,
and the worker adapter maps encoder cancellation to contract validation.
Large preparation spools use ambient temporary storage outside the worker's
owned attempt. ADR0184 separately removes discarded discovery hashes.

## Decision

Keep row serialization, canonical bundle encoding, semantic checks, checksums,
candidate identities, receipts and protocol fields unchanged. Defer raw byte
reuse because spool JSON and canonical bundle records have different contracts.

Row creation retains descriptor/path custody through observers, stat and object
construction. Writers transfer custody only when finish successfully returns a
replay spool. Unfinished normal and abnormal exits reclaim the writer's own
file. A finished writer cannot delete its transferred spool. Acquisition and
cleanup attempt every owned resource while preserving an existing primary
failure; an otherwise unaccompanied cleanup failure remains visible.

An artifacts-local parser owner registers each writer and completed spool as
soon as it is acquired, covering partial setup, partial finish and BaseException.
Link validation closes before a successful descriptor releases spool custody.
The parser's existing constructor seams remain available. No unowned directory
is swept and no hostile path-replacement guarantee is added.

The optional staged-row spool directory defaults to the current behavior.
The portable adapter explicitly selects its live materialized attempt root for
both staged rows and sorting runs; its existing outer owned-directory cleanup
remains the fallback. Other attempts and unrelated files remain untouched.

Actual event checks raise an internal ValueError subtype with the existing
safe cancellation message. Sorter ingestion, spill and merge cooperate with the
encoder's event. The adapter maps that subtype to existing `cancelled` and
preparation ValueError to existing `contract_validation`. Neither event state
nor exception text reclassifies an unrelated data error. Unrelated preparation
operational and BaseException failures retain their own cause. Encoding/store
I/O retains its existing artifact-error mapping. No signal, native preemption
or hard time guarantee is introduced.

## Alternatives and rollback

Status quo retains reproduced leaks. Extending one try block leaves ambiguous
partial transfer; a narrow owner centralizes that obligation. A generic resource
framework or raw-byte fast path is unnecessary. Coordinated source/test reversion
rolls back this change without a format or data migration.

## Acceptance and exclusions

Require scoped canonical unit and containerized integration with --no-coverage:
partial acquisition/finish, observer and cleanup failures, successful transfer,
real buffered/spilled cancellation, error-category negatives, unchanged bundle
bytes, Local worker behavior and disposable PostgreSQL publication. Independent
resulting-source review and static checks precede any milestone publication.

Cleanup failure state is explicit in the owning guard. An exception previously
handled by a caller is not evidence of a current primary failure. Prepared rows
support a context-managed lifetime; normal close attempts every known spool and
reports the first failure, while a context unwinding its own primary retains it.
Production encoder guards and artifact temporary cleanup use the same explicit
distinction. A regression that previously suppressed a new cleanup error under
an already handled caller exception establishes this requirement.

This source decision grants no dependency, runner-policy class, schema, CLI/MCP,
new protocol/category, model/study, image/build, complete local suite, local
coverage or remote campaign. It closes neither full W5/W6/W7/W8 nor desired
coverage cushions. Deferred worker/process/native limitations remain unchanged.

## Parent review disposition

The independent reviewer read all19 original grants conformingly and identified
three blockers: atomic parser/writer migration, store error-policy accuracy and
a spool-free proposed integration fixture. The parent resolves them by atomic
source delivery, unchanged encoding/store OSError categories with primary-safe
temporary cleanup, and a real greater-than4096-row fixture. Raw preparation
operational errors remain outside its new ValueError mapping. A stage-level
audit found two missing read bounds in the producer metadata handoff; the full
checkpoint is nonconforming despite the valid independent reviewer evidence.
A corrected checkpoint stopped on Muse protocol refusal before review, with
source unchanged and cleanup proven. No complete design-checkpoint acceptance
or provider failure cause is inferred.

The parent accepts the bounded amended source decision under the renewed W7
continuation, with fresh independent resulting-code review required before
publication. Explicit generator closure, partial link initialization cleanup,
prepared-family measurement custody and all-family primary-safe cleanup are in
scope. Existing full-family spill/fan-in admission gaps, outer workspace identity
refusal and OwnedTemporaryDirectory finalizer policy remain deferred. This is
cooperative temporary custody, not a universal asynchronous cleanup guarantee.

The first resulting-source review found a material evidence gap: its packet
omitted exact PostgreSQL selectors. The correction records those selectors and
runs the named worker-to-PostgreSQL baseline with explicit accepted-marker and
family preservation checks after authority refusal. Two additional regression
witnesses confirm existing descriptor defects in the touched store: permission
setup before descriptor handover, and failed read-stream construction after it.
Correct these through the existing store leaves, preserving validation and
module-level constructor/identity seams; no new dependency or public contract.

The data-error/cancellation distinction is adapter-scoped. The unchanged worker
terminal still prioritizes an observed cancellation event, and non-permission preparation
OSError retains its worker `source_capture` category. Production encoder guards
preserve their own primary; standalone sorter, link-validator and RowSpool
contexts, raw store-handle exits, OwnedTemporaryDirectory and outer workspace
cleanup retain their existing failure policy. There is no general primary-error
preservation claim for those legacy surfaces or simultaneous I/O failures.

The corrective review verified the evidence and two descriptor repairs without
blocking findings. The parent confirmed that raw open/fstat OSError propagation
was already present in open_stream. Its unchanged verify_stream_path descriptor
lifetime gap remains a named W7 follow-up; no general store-closure claim follows.
