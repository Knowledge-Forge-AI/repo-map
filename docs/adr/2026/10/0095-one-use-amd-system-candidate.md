# ADR 0095: One-use AMD system candidate and diagnostic evidence

## Status

Accepted design before implementation. The operator approved route B on
2026-10-25. Independent design review completed; the parent resolved its three
implementation-allocation findings. Candidate, image, platform, P3 and promotion
acceptance remain pending.

## Date

2026-10-25

## Context

CI68 completed eight of nine jobs. Main-system refused unresolved prerequisites
before any SDK or application build. Native AMD exploration measured libpq
180006, 48 signed builder packages, no closure additions and 77 retained Python
imports. Exploration is not final-image evidence. A separate D12 build followed
by system qualification would lose the first inner daemon and build twice.

## Decision

Designate main-system-gate's existing managed builder as the sole AMD D12
application builder. Use one canonical system sandbox, one inner daemon, one
candidate and one resource ledger. Preserve the original two-total,
one-per-platform, no-retry application ceiling. The old D12 integration builder
cannot consume AMD. ARM stays held.

Allow one diagnostic system campaign on this unaccepted candidate while final
P3 classification remains incomplete. This accepts no concrete security finding.
Identity, provenance, byte ownership, ABI, platform, dynamic linkage, licensing
and lifecycle refusals remain fatal. New concrete affected/high or unknown
runtime findings require their exact operator disposition.

## Candidate data and defaults

Mechanically freeze only the verified CI68 AMD manifest in a candidate-only
runtime companion. Keep release.py, its None/empty product defaults and local
rendering behavior unchanged. The granted system recipe passes explicit candidate
data to the existing renderer. Retain exact approved base/source pins and C
Psycopg 3.3.6 dynamically linked to distribution-owned shared libpq. No static or
bundled libpq substitute. Recompute source, recipe, Dockerfile and context count;
do not equate those identities or extrapolate ARM data.

## One-use admission and budget custody

A strict bounded committed grant binds the approved prior staging transition,
same-repository PR13 synchronize event, main base, exact next workflow ordinal,
attempt 1, native Linux AMD, candidate identities and a parent-held reservation.
Validate actual event bytes, environment and Git merge/tree/parents before SDK
materialization. Transfer only normalized public proof over the existing owned
sandbox pipe; revalidate inner Git, context and canonical gate binding. No new
gate-request fields, inherited GitHub environment, trust flag or local bypass.

Keep hold/proof files in an owned RUNNER_TEMP admission directory. The system
report destination must remain unused until normal sandbox export. A separate
system-only proof argument transports exact bounded bytes to an exclusive 0600
inner file. Missing, duplicate, stale, symlinked or unverifiable evidence refuses.

The parent retains the original held ledger and appends one narrow route-B AMD
reservation after source acceptance. Existing generic and ARM admission stay
held. Grant nonce, reservation ID and intent ID are the same 32-hex value. After
positive same-daemon preflight, acquire a nonblocking lock and fsync an exclusive
intent before entering the sole managed build. Actual or uncertain starts spend
the slot; no automatic retry or rearm. Reconcile exact hosted evidence later.

## Same-image evidence and cleanup

Use existing D12 preflight algorithms against the real inner daemon and immutable
bases, comparing every frozen package and runtime fact before intent. Reuse
cohesive extracted probes; retain current security classifiers and full archive
round-trip invariants. Bound exec and waits by the existing system deadline.
Keep the existing 900-second build clamp, total budget and cleanup reserve.

Capture the image ID immediately, including partial failures. Attach inventory,
dynamic-linkage, packaging and disposable round-trip evidence to that exact
image, then use it for the existing system scenarios. Reset inherited Compose
build descriptors with !reset null and prohibit pulls/build commands. Verify the
merged model; both up and run must be unable to create a second candidate.
The existing cleanup owner removes exact owned resources on every outcome.

A separate bounded D12 sidecar retains raw-probe hashes, intent binding, failures,
scenario results and actual cleanup evidence. SystemReport and GateResult v1
schemas remain unchanged. While P3 is unaccepted, the canonical aggregate fails
with merge_authorized=false even when diagnostic steps pass. Lost or uncertain
evidence remains unqualified. No success-by-skip or fabricated classification.

## Scope and verification

Use named cohesive companions for grant/hold, proof capture/transfer, arguments,
candidate identity/session, bounded exec, shared probes/evidence and Compose
commands. Preserve existing facades and injected-call seams. Every tracked Python
file stays within 400 physical lines. Enroll only actual clean new owners;
preserve historical authority, classifications and every debt ceiling.

Before source acceptance retain one meaningful scoped RED, final current-source
GREEN unit and container integration evidence, static/inventory enforcement and
complete independent implementation review. Initial caps are one RED, two GREEN
unit, two integration and two static executions; repeats require a concrete
failure and correcting change. Use exact canonical selectors with --no-coverage.
Complete local suites, local coverage, local SDK/application builds and pulls,
new dependencies, emulation and infrastructure are excluded. Hosted CI owns the
first native application/system observation.

## Alternatives and consequences

Keeping the hold produces no assembled-image evidence. A new shared-session
runner policy is unnecessary for the selected existing builder. Duplicate builds,
cross-job image transfer and manifest-only admission violate the boundary.
Publication is one reviewed ordinary staging update and its existing automatic
campaign. There is no main/tag/history action or live deployment. A later rollback
is a reviewed forward change; it never resets spent application authority.
