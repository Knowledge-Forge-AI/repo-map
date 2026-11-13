# ADR 0192: Cooperative source capture with explicit cancellation custody

## Status and scope

Parent adopts the amended ordinary W7 design following a fully read, hash-bound
independent 19-input checkpoint. Implementation, exact scoped proof and independently audited resulting-source
acceptance pass after parent advisory dispositions. Hosted qualification remains
pending. Phase:
REPOMAP-CLOE-RESOURCE-GOVERNANCE9. Date: 2026-11-13.

This is the third connected epic after preparation and bounded materialization.
The current operator requests continuation through the next staging milestone.
No dependency, native/helper/runner policy class, new quota, public CLI/MCP/schema
or report vocabulary, model/study, image/build/acquisition, live target, complete
local Python suite or Python coverage is selected. New dispatches remain
dynamic_default. Publication needs a fresh exact one-campaign binding.

## Problem and preserved behavior

Actual semantic capture is bracketed by the adapter's event checks but traverses,
hashes/stages and extracts complete sources between them. Add cooperative checks
inside that work. Preserve the staged copy and both authoritative stable-content
inventory passes; transient A/B/A changes defeat staged-copy elision. Keep source
signatures, retry ceiling3, hashes, identities, observations/order, byte-equivalent
reference bundles, static-only extraction, accepted-pin publication rules and
default dynamic callable seams. Do not claim parser/native preemption or a time,
CPU/RSS/filesystem quota or maximum cancellation latency.

## Boundary and architecture

Both capture entrypoints gain optional cancel_check=None; None forwards no new
keywords to existing patched callables. The sealed function forwards a supplied
callback to ordinary capture. Validate it before creating a workspace. The
adapter supplies only its existing _cancelled(event), never _checkpoint; event,
checkpoint names/frequency, terminal protocol and worker cancellation precedence
remain unchanged. Scan/sealing metering is unchanged; an internal explicit meter
and cancellation combination refuses before IO rather than weaken accounting.

Only the public ordinary-capture boundary creates a private BaseException carrier
for callback-raised Exception. KeyboardInterrupt/SystemExit need no wrapper.
Shared helpers call the provided callback without creating carriers. Discovery
extraction and hook callbacks are plain; lower private capture helpers retain
their existing OSError/ValueError normalizers. Only the public capture boundary
promises callback identity across those normalizers. The control helper has
only standard-library imports. It never imports coordinator/artifact owners.

Run the guarded capture body through an ordinary call helper INSIDE the owned
temporary-directory with-body. Save a carrier's original inside except, then
raise it after that except has ended. A generator context manager is unsuitable:
the parent reproduced that its throw retains the active carrier even after the
generator's except, corrupting __context__. Preserve the actual original object,
cause/context attributes and callback traceback frames; do not promise identical
complete traceback frames. A lower legacy file-close error can replace callback
failure while the carrier is active. Before returning any failure to outer
workspace cleanup, replace carrier links in cause/context chains with their
originals, using cycle-safe traversal. Preserve the actual legacy winning error
and category. No private carrier may escape in an exception chain. Outer owned
root cleanup then receives the actual public failure and keeps its existing
refusal/precedence rules; do not suppress ownership refusal or claim cleanup when
it refused. Tests must cover original preexisting cause/context, lower close
failure, outer cleanup failure and callback identity.

Move the pure semantic identity helpers unchanged to one graph-local owner and
decompose the existing capture body into cohesive extraction, candidate creation
and final conversion helpers. The facade passes its CURRENT dynamic inventory,
discovery, extraction and resolver functions as one explicit engine record, so
patch seams survive without a circular import. Resolve those four facade names
through late getters at their original work phases, including final recapture;
do not snapshot later function lookups at entry. Routing and identity helpers
execute in their cohesive owners; former pipeline globals beyond these four
named seams are no longer internal capture patch points. Public exports remain
available. Every new owner/routine must be
clean under existing profiles; no inherited numerical debt grows. Keep each
included owner <=400 lines. The original 384 count was module length, not routine
length. No broad language-dispatch rewrite is selected.

## Cooperative work and iterator ownership

Check per binding/file and before each existing 1 MiB stable read; check after that
read and before the staged write. Existing file descriptor/writer cleanup policy
and retries stay unchanged. During sealed/elided discovery, reuse the existing
CaptureDiscoveryHooks probe and live classifier delegates, adding checks before
reader calls and controlled directory traversal. Yield the identical os.walk
tuple and mutable list objects so in-place pruning survives. An ExitStack around
the complete discovery call owns the walk iterator explicitly, releasing it even
when classification fails while its wrapper is suspended. Acquire iter()'s
returned object before the first consumption check and register its release
immediately, including an already-refusing callback. A failing iter() acquires
no iterator and its actual error wins. Close only that returned object once,
never a distinct source iterable. Never explicitly
retry an uncertain release. Preserve an active body/iteration/callback primary
against Exception from close; KeyboardInterrupt/SystemExit from close propagate.
Normal-path close failure remains visible even inside an unrelated handled
caller exception. Track this context body's failure explicitly; sys.exception()
alone cannot distinguish caller state. This concerns new controlled iterator
custody, not arbitrary parser/backend internals or legacy root/file cleanup.

Ordinary non-elided discovery remains one atomic existing call per binding; no
speculative composing reader implementation is introduced. Both public modes
still support checks in actual stable capture/extraction. Discovery selection's
individual directory pruning/sort and skipped-file loops remain atomic. No claim
that every directory entry receives a callback follows.

The parent inspected all 20 file-adapter declarations in discovery_extractors:
each returns tuple[RawObservation,...]. Collector checks also consume already
built lists/tuples; they do not preempt their construction or prior parsing.
Keep a check per file and around module/anchor index,
repository-Go and CSS postpass operations. Those constructors and individual
extractor/parser/resolver/validation/sorting calls remain atomic. Add owned
checked consumption where a custom extraction/discovery seam actually returns
a lazy iterable; check before and after next. Keep lazy namespacing and final
conversion cooperative. No new Red routine; the inherited discovery dispatcher
has only declared control-call statement growth and no new language branch.

## Failure order and evidence

An actual source read/extraction fault that occurs after an event is set but
before the next check keeps its existing in-process category. Event-set alone
does not replace an actual error. Actual worker terminal precedence remains
separate. Prove source OSError and extractor ValueError with the event set,
without reclassifying either as cancellation. Shared helper direct exceptions
remain free of carriers; the public boundary preserves callback OSError/ValueError identity.

Before implementation, the same module-local OS proxy fdopen/read hook must
record old continuing work after setting the event on the first actual stable
read. Never patch the shared os.fdopen globally. Use a multi-MiB inert file plus
small Python source; no tens of thousands of function bodies. Record real source
and staged-write bytes. GREEN observes one admitted source chunk and no staged
write in this first-read witness, not a universal timing guarantee. API-only
failures remain separately labelled.

Use exact canonical scoped unit/container integration --no-coverage. Exercise
both hash modes, default keyword seams, live classifier delegates/probe behavior,
ignored-directory pruning, both initial/final fences, source changes, iterator
acquire/read/body/release errors, no retry, real cause/context and byte-equivalent
success. Capture-side adapter faults are in-process evidence, not a new native
signal qualification. Set tempfile.tempdir to a dedicated fixture directory and
assert its emptiness, unchanged artifact store and workspace sentinel after
actual mid-capture cancellation. Existing real spawned Local/PostgreSQL success,
refusal pin-preservation and recovery remain exercised. Frozen Rust closure
metadata must be refreshed from the official inert resolver and tested before
publication; this does not execute or qualify its native component.

Final source review receives complete changed owners, actual RED preimages,
current source and exact proof/quality lineage. Historical review artifacts stay
immutable. Local success remains scoped acceptance; hosted population/coverage
and platform/image/full-roadmap gates remain pending. Revert coordinated source,
tests and metadata without a data migration if compatibility fails.

## Alternatives and review disposition

Status quo leaves the identified gap. Thread killing/tracing/signals or parser
preemption alter safety/ownership policy; per-artifact only checks miss capture.
Unconditional new keywords break defaults, and unguarded ValueError/OSError
callbacks are normalized incorrectly. The original proposed broad helper wrapping
and outside-workspace unwrap were rejected. Design findings on traversal pruning,
lazy iterator lifetime, BaseException release, real temp cleanup, source-fault
precedence, return-type evidence, fixture cost and closure ownership are resolved
above. Primary hash-tool absence was disclosed; independent reviewer computed
all19 digests and the parent reconciled every granted stage's native read bytes.
No assumption that ordinary capture has no other production caller is required.
