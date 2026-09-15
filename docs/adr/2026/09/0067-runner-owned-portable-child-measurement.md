# ADR 0067: Runner-owned portable child measurement

## Status

Accepted; amended by PR26-STAGING-CONTRACT1 following operator approval of
Decisions A and B. Implementation and focused verification are candidate work;
this ADR does not establish integration qualification or activate a hosted gate.

## Date

2026-09-12

## Context

The portable semantic worker executes under `repomap_kg.coordinator._portable_worker_launch.run_portable_worker`
in a child process via `run_worker_spec`. In production, the worker environment
is strictly closed: `LANG=C`, `LC_ALL=C`, empty `PATH`, isolated `HOME`/`TMPDIR`,
and a sealed `PYTHONPATH`. Under test runner integration measurement, the worker
body in the subprocess remained unmeasured because the closed child environment
omitted Python coverage startup and bootstrap ownership.

Production code and default runtime environments must remain unchanged. A
protocol facade patch is insufficient because it does not bind the actual execution
boundary at `_portable_worker_launch.run_worker_spec` or enforce containment.
Furthermore, `ChildCoverageSession.combine()` previously merged all shard files matching
`.coverage.*` indiscriminately, ignoring reconciliation returns and permitting
fabricated `.parent` shards.

## Original Decision — historical measurement policy

The following decision records the pre-amendment policy. Its unconditional
whole-invocation completeness statements are superseded only as listed in the
PR26-STAGING-CONTRACT1 amendment below. All ordinary measured-child safeguards
continue to govern the measured leg and any ordinary measured children in A.

### QUAL6-FIX1 disposition

The measured conformance launch uses a second, closed runner-owned command
identity: `repomap_test_support.portable_worker_conformance`. Its exact support
source root and source commitment belong only to that identity. They do not
expand the canonical production command's permitted Python paths. The original
supervisor and installed portable authority guard still execute.

Direct capability issuance defaults to production-only command paths. The
canonical `int`/`staging` test-session caller explicitly opts into the closed
conformance identity, as do focused test-owned callers. Product launches still
receive only product paths. Every registered child must provide affirmative
collector-start and terminal-completion receipts and a measurement-content claim
matching the readable shard, including direct registrations without adapter
launch metadata. Missing metadata does not grant weaker acceptance.

Invocation-level refusal remains the policy for missing terminal measurement,
including deliberately abrupt workloads. Such a workload can satisfy its
behavioral assertion while the coverage leg remains incomplete and failed.
This phase does not introduce an expected-kill waiver or qualify that residual.
Pre-opened receipt files are not completed terminal receipts. Bootstrap failure
is missing measurement, never an unmeasured child silently removed from coverage.
Reports must preserve workload records and distinguish unavailable measurement
before optional rendering.

### 1. Runner-Owned Scoped Adapter

Instrument the actual `repomap_kg.coordinator._portable_worker_launch.run_worker_spec`
bound attribute during measured integration legs (`int` or `staging` suites) via
a runner-owned scoped adapter. Production source and default environment policies
remain completely unchanged.

The adapter installation and restoration are strictly scoped to the lifecycle of
an active `ChildCoverageSession`. Upon session enter or integration leg staging,
the adapter replaces the bound `run_worker_spec` attribute; upon session exit or
unwinding, the original attribute is restored deterministically. Single-process
execution proves that installation and restoration leave no lingering state or
leaked monkeypatches in the parent process.

### 2. Explicit Structured Capability (No Ambient Authorization)

Coverage instrumentation is governed exclusively by an explicit structured capability
issued by an active `ChildCoverageSession`. Ambient environment variables, unmanaged
flags, or arbitrary callers cannot activate child measurement.

The capability binds:
- Invocation ID and target suite (strictly `int` or `staging`; `unit`, `smoke`, and `system` suites are excluded);
- Source revision and current source tree commitment;
- Exact owned directory roots: session directory, coverage config file, bootstrap directory, child manifest directory, and shard data directory;
- Checksum / byte commitments for configuration and bootstrap assets;
- Permitted Python paths: exact product-approved paths (e.g. `src/main/python`), preserving existing `python_paths`;
- Portable command specification and unique prelaunch registration token.

### 3. Containment, Ownership, and Environment Isolation

The adapter validates containment and ownership at both launch and acceptance:
- All configuration, bootstrap, manifest, and shard paths must reside within the session-owned roots;
- Paths must be regular files/directories without symlink escapes (`resolve()` containment);
- No arbitrary or inherited roots are admitted.

The child worker's closed environment only gains:
- `COVERAGE_PROCESS_START` pointing to the runner-owned coverage configuration file;
- `COVERAGE_CHILD_MANIFEST_DIR` pointing to the session-owned manifest directory;
- `COVERAGE_CHILD_REGISTRATION_TOKEN` carrying the prelaunch registration token;
- `COVERAGE_FILE` selecting its token-bound shard basename;
- Invocation, suite and revision identities for receipt validation;
- `PYTHONPATH` updated to prepend the bootstrap directory while preserving exact product-approved paths.

No credentials (`AWS_*`, `GITHUB_*`, tokens), user-site packages (`PYTHONNOUSERSITE=1`),
or general parent environment variables pass through.

### 4. Fail-Closed Boundaries

The following conditions immediately fail closed:
- Wrong configuration path or corrupted configuration content;
- Wrong run ID or invocation ID mismatch;
- Root path outside session containment or symlink escape;
- Source revision mismatch;
- Ambient spoofing (environment variables without an active, validated capability);
- Missing, corrupt, or unregistered child process;
- Cross-suite data (measurement data originating from unapproved suites like `unit`, `smoke`, or `system`).

### 5. Prelaunch Registration, Attributability, and Lifecycle

Expected child processes must be registered prior to synchronous launch.
Authority is never based on PID alone: the child process must present the matching
registration token in its start and terminal markers.

Acceptance requires:
- A matching start marker emitted by the child process;
- A matching terminal exit marker;
- A readable, valid SQLite coverage data shard attributable to the registration token.

For a killed or cancelled child that fails to produce a terminal marker and readable shard,
acceptance fails closed; there is no expected-kill waiver.
If the primary workload raises an exception, that primary workload exception and result
are preserved, while a separate measurement diagnostic snapshot is recorded.

Measurement artifacts (manifest markers, coverage shards, configuration) are stored
in session-owned directories outside the temporary attempt root (`attempt_root` is purged
by `_portable_worker_launch`), living through report and export until owned session cleanup.

### 6. Deterministic Combine

`ChildCoverageSession.combine()` is updated to:
- Accept only the exact current parent contribution identified from the actual session-created collector;
- Combine only the validated child input shards returned by manifest reconciliation;
- Strictly forbid fabricated `.parent` shards;
- Distinguish valid empty shards (valid SQLite databases with zero statement hits) from missing or corrupt shards (which fail closed).

## Implementation and Verification Boundary

The implementation lives in `runner_coverage`, `runner_coverage_execution`,
`runner_coverage_capability`, `runner_portable_coverage`, and
`runner_coverage_bootstrap`. Focused commands and outcomes belong to status 00881
and its verification ledger; earlier worker counts are not resulting-state evidence.

The bootstrap does not replace the product authority guard. It initializes the
portable collector and opens exact invocation-owned terminal receipt handles before
that guard is installed. On exit it uses those existing handles. A tiny protocol
child installs the unchanged product guard and verifies actual line and arc output;
no RepoMap integration workload is executed locally.

Portable shards use a prelaunch-token-bearing basename through `COVERAGE_FILE`.
The adapter binds the observed managed PID and synchronous reaping. Acceptance
rechecks source, bootstrap, config, containment and receipt identities before combine.
The accumulator is saved before readback; failing to save discarded child hits in
the focused regression evidence.

## Residual Boundaries

Unit-only synthetic sessions use an inert suite and cannot issue portable
capabilities. Historical receipt classification fixtures remain useful for lower
level reader tests; they are not integration aggregate authority. Integration and
staging require invocation and suite identities. Killed children without valid
terminal data fail measurement even when workload cancellation is expected.

The full integration population and final manager readiness decision remain deferred.

### First-run dependencies and failure scope

Capability validation requires an available Git executable, successful
`git rev-parse HEAD` under the container's ownership/safe-directory environment,
and a readable source tree whose commitment matches issuance. The focused proof
uses a tiny synthetic source root; the complete product root in the owned
integration container remains unexercised. No container issuance preflight was
run locally. These are first-run availability risks, not qualification evidence.

A SIGKILL, SIGTERM, or `os._exit` can bypass the terminal atexit receipt. One
registered child missing that receipt causes combine to reject measurement for
the entire invocation, including otherwise valid parent and sibling data. Future
cancellation/timeout scenarios must account for this run-cost risk; no waiver is
introduced. The workload result/exception remains separately preserved.

Saving the combined accumulator intentionally retains the current parent data
file through readback and export. Its existence assertion replaces the former
deleted-shard assertion; invocation-owned purge and cleanup bound retention.

## PR26-STAGING-CONTRACT1 Amendment — two required evidence obligations

### Amendment Status

Accepted by the operator's current approval to proceed with Decisions A and B,
2026-09-12. This is an explicit change to the measurement-completeness policy
for the whole executed integration population, not a report-label correction.
Historical QUAL1–QUAL6 outcomes remain unchanged. Implementation does not grant
hosted execution, trusted-executor deployment, promotion or release authority.

### Statements Superseded By This Amendment

The original QUAL6-FIX1 disposition, section 5 and Residual Boundaries required
complete terminal measurement for every child across the entire invocation,
including intended abrupt termination. Those requirements remain strict for M
and every child registered for ordinary measurement. They no longer require
orderly measurement completion from the exact predeclared abrupt roles in A.
No other missing-data case gains an expected-kill waiver.

### Current normative policy

Before executing required integration bodies, the runner seals the candidate's
actual policy-eligible population S into disjoint, exhaustive M and A:
`S = M union A`, `M intersect A = empty`. M is ordinary measured integration;
A is required intentional abrupt-termination behavior. The maintained declaration
uses exact node IDs, parameter cases and child roles with launch, intended fault,
termination and cleanup owners. Receipt attribution includes inherited children;
portable adapter tokens are not the sole population boundary. Names mentioning
cancellation, nonzero exit, emergency cleanup and historical PID3857 do not
authorize classification. Graceful cancellation with terminal measurement stays M.

The declaration and ordered runtime population bind policy, candidate/source and
planned invocation identities before outcomes exist. Missing or stale IDs,
duplicates, unresolved parameters, arbitrary selection exemptions and accidentally
empty required legs fail accounting. Existing explicit platform/opt-in skips and
build-profile deselections remain separately visible, never passes. Scoped runs
describe exact selected intersections and remain diagnostic. `--no-coverage`
disables measurement qualification, not required behavior or accounting.

PR26-STAGING-CONTRACT1-FIX1 replaces the preliminary in-process seal with an
invocation-owned collection-only child, followed by separate serial M/A execution
sessions. Discovery executes no test bodies and contributes no coverage data.
Its ordered raw, eligible and deferred identities are validated before either
leg starts. Each execution collection must match the same immutable seal before
its bodies run. M collects and imports in its own normal measured context;
discovery imports remain confined to the child. No arbitrary module-cache
clearing or reloading is permitted, and an enclosing collector remains owned by
its caller.

The discovery request and bounded result bind invocation, source, declarations
and effective collection inputs. Missing, malformed, stale, cross-invocation or
unsuccessful discovery refuses execution without retry. Source stability is
checked around discovery and before actual legs. The discovery process and its
temporary artifacts have bounded ownership and cleanup; no unsettled child may
authorize continued execution.

Discovery uses the current interpreter with isolated startup, then copies the
caller's effective source/support/tools search paths into the child only. The
request binds cwd, pytest arguments, declarations, invocation/source identity and
test-owned environment, including Go helper and sandbox/PG container inputs.
Coverage bootstrap and Go coverage-output variables are excluded. Request and
receipt are invocation-owned regular files, each limited to 2 MiB; receipt hashes
bind the exact request and ordered collection. The collection bound is 120
seconds, followed by at most two five-second process-group settlement windows.
There is no inherited discovery deadline in the existing caller interface.
Output streams use the null device. On nonzero exit the parent validates any
receipt before cleanup and retains its digest, exception type and population
counts in the refusal report. Missing, invalid or exit-mismatched receipts are
identified as unavailable; raw partial node lists and collection tracebacks are
not retained. Failure receipts never authorize either leg. No retry, integration
population execution or measured credit is inferred from discovery.

Isolated startup ignores Python environment options; the allowlist therefore
omits `PYTHONHASHSEED` and `PYTHONDONTWRITEBYTECODE`. The child has its own hash
seed. Hash-sensitive collection ordering can cause an exact-population refusal;
the runner does not sort away disagreement or weaken ordered equality. That
compatibility risk and the adequacy of the 120-second bound require manager
disposition using a separately authorized real-population attempt.

This supersedes 00886's deferred cached-import risk. Hermetic controls establish
the isolation boundary; they do not quantify recovery for the live integration
population or predict an 80/80 pass. The complete denominator and independent
floors still apply. Seal hits are never added to M, and actual hosted M/A
population qualification remains separately required.

M retains the complete product-source denominator and independent 80% line and
80% branch floors. Unit retains independent 85/85 floors. No product statement,
branch or file is excluded by placing a behavior test in A. M combines only its
same-invocation validated data: no A, unit, smoke, prior-attempt or foreign-copy
contributions. Every measured child still requires attributable affirmative
start and terminal evidence, source/capability identity, readable shard and valid
content claim. Missing, corrupt, foreign or incomplete measurement, clean exit
without a shard, bootstrap/save failure and unproved settlement fail measurement.

A chooses test-owned launch/measurement configuration before each declared launch.
It cannot stop an issued measured collector or revoke registration to erase a
failure. Each role requires authentic parent-attributed launch and child identity,
proof of the intended startup/checkpoint, exact observed exit/signal and bounded
supervisor/resource settlement. Expected values never populate observed fields.
PID disappearance alone is insufficient. Wrong child, successful exit, wrong
termination, pre-fault bootstrap failure, foreign data, source drift or uncertain
cleanup fails the obligation. Production launch policy and worker isolation remain
unchanged. Ordinary children registered for measurement in A remain strict.

Abrupt child measurement is explicitly unavailable/incomplete, never complete or
0%. Genuine partial data may be retained only as labeled diagnostics; no A data,
including parent or sibling hits, contributes to M. No synthetic terminal receipt,
empty shard, hit or graceful substitute is permitted. Every A behavior test must
execute and satisfy its real assertions and cleanup; skips and doubles cannot
replace that hosted obligation.

Staging remains smoke-first, followed by both integration obligations in the
existing governed sandbox. Ordinary assertion failures preserve the other leg's
available evidence; interruption or unsafe resource settlement blocks unsafe
continuation. Aggregate success requires smoke success, both required legs
completed and passing, valid M coverage above both floors, exhaustive population
reconciliation and all existing cleanup/security obligations. Missing/blocked
legs fail the aggregate. No retry selects a preferred outcome.

Structured reports must preserve planned and actual test records, separate leg
results, policy/candidate/source/invocation identities, M coverage and every A
role's actual lifecycle evidence and unavailable measurement. Validation must
reject missing records/fields and preserve teardown failures without double
counting. Workload, measurement, accounting, cleanup, rendering and export errors
remain distinct; substantive JSON records survive HTML rendering failure. When
report rendering is requested, its failure fails the aggregate even though the
machine-readable evidence is retained.

The existing trusted staging command can invoke candidate runner semantics, but
its old step-derived gate result does not itself bind this new report policy.
Acceptance additionally requires same-attempt report validation and a separately
authorized exact-candidate hosted request adopting this amendment. No candidate
workflow or gate-contract copy may silently deploy that consumer change.
