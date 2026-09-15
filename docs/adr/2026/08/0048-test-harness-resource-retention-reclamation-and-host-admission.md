# ADR 0048: Test-Harness Resource Retention, Reclamation, And Host Admission

## Title

Test-Harness Resource Retention, Reclamation, BuildKit Containment, And
Host Admission

## Status

Accepted — Outcome A. Codex Sol High (gpt-5.6-sol) review gate 1 returned
`CORRECTION_REQUIRED` and, after six correction iterations, review gate 2
returned `ACCEPT` with zero findings at any severity and no unresolved
Critical or High finding (dispositions recorded in status 00707). This is
a docs-only policy decision: acceptance authorizes the
TEST-HYGIENE3A/3B1/3B2/3B3/3C implementation slices defined in the
migration section; it does not implement anything, does not perform any
cleanup, and does not authorize the controlled-host observer comparison,
TEST-COV5K REVIEW4, R3, or SCALE29.

## Date

2026-08-02

## Context

TEST-HYGIENE1 (outcome `correction_required`, recorded in
`docs/status/2026/08/02/00706-test-hygiene1-phase-owned-resource-ledger-exit.md`)
added a versioned private resource ledger, exact current-run
scratch accounting, Docker ownership cross-checks with centralized labels,
runtime ownership adapters, opt-in PostgreSQL container labels, Buildx
refusal boundaries, dry-run historical scratch discovery, ordinary-runner
integration, and focused tests. Its pre-run inventory found severe
accumulated pressure on this development laptop: 381 scratch run roots
holding about 182 GB allocated across 7.18 million inodes, 12,882 Docker
volumes, 5,145 BuildKit cache records holding about 75 GB, and two Buildx
builders.

During TEST-HYGIENE1's final read-only review, the operator personally
cleared `agent-scratch/r` to reclaim the laptop. That removal interrupted
the phase's uninterrupted-teardown proof and removed its private evidence
root and candidate manifest, so TEST-HYGIENE1 closed as
`correction_required` and current-run hygiene was not accepted.

RepoMap now needs one durable policy so this situation does not recur:
current-run cleanup that is automatic and exact, historical retention that
is bounded and boring, operator reclamation that is explicit and separate,
and host admission that keeps ordinary development cheap while protecting
heavy work. The alternative — indefinitely re-litigating cleanup per phase —
has already consumed multiple phases and blocks the product roadmap
(performance baselining, extractor dependency architecture, and PostgreSQL
extension work).

## Operator Clarification

During TEST-HYGIENE1, the operator personally cleared `agent-scratch/r` to
reclaim the laptop after observing severe scratch, inode, memory, Docker,
and BuildKit pressure. This was an intentional operator action. It was not
an unknown external actor, a hostile mutation, or evidence that another
agent independently ran an unauthorized cleanup.

Status 00706 described the event neutrally as an "external reclamation"
because the acting party was unknown to the phase at close time. An additive
correction in status 00706 now records the attribution: pre-existing scratch
runs were in fact removed; the removal interrupted TEST-HYGIENE1's
uninterrupted teardown proof; the actor was the operator;
`foreign_scratch_runs_mutated: true` described the observed state change,
not an allegation that a foreign agent performed it; the phase's
`correction_required` disposition remains historically accurate because the
original phase evidence root and candidate manifest were removed before
closeout; and no TEST-HYGIENE1 recovery run is retroactively accepted.

The operator's action is policy evidence for an explicit
operator-reclamation boundary (mandatory decision 4). It is not evidence
that any automated candidate selector was correct, and it does not grant
agents historical-cleanup authority.

## Problem Statement

Decide, concretely and completely:

1. current-run teardown authority;
2. historical scratch retention and deletion authority;
3. operator-authorized broad reclamation;
4. report and diagnostic-evidence retention;
5. scratch byte and inode quotas;
6. project and host high-water behavior;
7. inventory cadence and index authority;
8. Docker image, tag, container, network, and volume cleanup;
9. Buildx/BuildKit isolation, cache, and build-history policy;
10. host-admission profiles from ordinary development through qualification;
11. configuration and override precedence;
12. implementation slices and the pivot point to performance and
    graph-quality architecture work.

The decision must prevent uncontrolled scratch and Docker growth without
turning every test run into a laptop-capacity qualification campaign.

### What would prove this ADR wrong

- A recurrence of multi-hundred-gigabyte unmanaged scratch or BuildKit
  growth while the selected policy is correctly implemented and enabled.
- An automated deletion of an active, pinned, foreign, or ambiguous resource
  that the selected revalidation rules permitted.
- Ordinary development runs measurably burdened (multi-second admission
  overhead or full-root scans) by the selected admission and inventory
  design.
- The BuildKit build profile proving unable to achieve exact ownership under
  the selected remote-driver architecture on the accepted local platform.

## Evidence Hierarchy

This ADR uses, in order:

1. current committed TEST-HYGIENE1 source and tests;
2. TEST-HYGIENE1 Git-show and operational reports;
3. accepted RepoMap scratch, test-runner, report, and Docker lifecycle
   architecture;
4. current official Docker, Buildx, BuildKit, OrbStack, PostgreSQL, Python,
   and Apple/macOS documentation;
5. current executable behavior and local help text (docker CLI 29.4.0,
   buildx v0.33.0, macOS `memory_pressure`, `df`);
6. historical status prose;
7. inference.

Passing tests prove current implementation behavior, not that a policy is
architecturally correct. The operator's manual cleanup proves urgency and
operator authority, not automated candidate correctness. Conflicts between
sources are recorded rather than silently resolved; this ADR records one
candidate-count discrepancy (below) and one documentation gap (Buildx
build-history persistence location; OrbStack storage internals).

## Current Architecture

Committed TEST-HYGIENE1 behavior this ADR builds on:

- `repomap-test-resource-ledger-v1` (`resource_ledger.py`): private,
  file-backed, closed-vocabulary evidence for one exact project/phase/run
  identity; records resource kind, creation observation, cleanup lifecycle,
  retention reason, size/inode facts, and final presence; rejects
  pre-existing cleanup authority, unobserved cleanup claims, retention of
  non-scratch resources, and unknown facts.
- Scratch accounting (`resource_scratch.py`): link-safe measurement without
  following symlinks, retained-versus-transient separation, top-level
  transient-group cleanup with byte and inode readback, unknown-residue
  rejection.
- Historical dry-run classification (`resource_scratch_history.py`):
  candidates require an exact RepoMap manifest, matching physical root,
  owner-uid match, terminal state, dead owner process, and absence from
  active report and monitoring sets; everything else is ambiguous or active;
  nothing is deleted.
- Docker ownership (`resource_docker.py`, `resource_docker_engine.py`):
  centralized `org.repomap.test.resource.*` labels plus ledger agreement
  plus pre-existing baseline protection plus reference checks; tag removal
  protected by exact image identity, tag multiplicity, and pre-existing
  container references; anonymous volumes preserved during container
  cleanup; Buildx/history discovery through the Docker SDK fails closed.
- Buildx containment (`resource_buildx.py`): one unique builder under
  phase-owned `BUILDX_CONFIG`; never the shared/default builder; refuses
  before bootstrap because exact labels cannot be injected through the
  `docker-container` driver.
- Runner integration (`tools/run_tests.py`): the process that allocates the
  scratch run starts the ledger, retains the default report evidence owner,
  performs exact registered transient cleanup at close, and records
  `live_runtime_residue` in the run manifest.

Known implementation corrections carried to TEST-HYGIENE3A (not implemented
here): exact Boolean validation rather than `bool(value)` coercion in ledger
registration; strict loaded-ledger schema validation; exact nonnegative
integer validation; controlled malformed-evidence errors; and
mutation-facts-required-and-exact before any host-restoration claim.

## Resource And Pressure Evidence

Measured facts (TEST-HYGIENE1 preflight, private metadata-only scan):

| Resource | Count or size |
| --- | ---: |
| Scratch run roots | 381 |
| Scratch allocated bytes | 182,003,687,424 |
| Scratch apparent bytes | 172,506,266,170 |
| Scratch inodes | 7,184,027 |
| Docker volumes | 12,882 |
| BuildKit cache records | 5,145 |
| BuildKit cache bytes | 75,249,291,397 |
| Buildx builders | 2 |

These are separate resource totals; scratch and BuildKit bytes are not
summed because they do not necessarily represent disjoint physical storage.

Measured facts (TEST-HYGIENE1 operational report, one focused run):
`peak_run_scratch_bytes: 16,379,904`, `peak_run_scratch_inodes: 2,094`,
`final_retained_evidence_bytes: 32,768`, `final_owned_scratch_inodes: 9`.

Estimates derived from aggregates (marked as estimates, not measurements):
mean historical run size ≈ 478 MB and ≈ 18.9 k inodes (182 GB / 7.18 M over
381 roots); mean dry-run candidate size ≈ 203 MB (45.7 GB over 225).

Preserved discrepancy: the TEST-HYGIENE1 pre-review private Git-diff
report's snapshot of the draft status recorded 224 historical candidates
(25 active, 135 ambiguous, 45,529,919,488 bytes); the committed status
00706 and the final private operational report both record 225 (26 active,
136 ambiguous, 45,737,902,080 bytes). The TEST-HYGIENE2-ADR phase prompt attributes 224 to
the committed status and 225 to the operational report; the observed
placement differs — 224 appears only in the pre-review draft snapshot. Both
counts are preserved; the private candidate manifest was later deleted by
the operator, so neither count is current deletion authority. This ADR uses
only the range and aggregate pressure as planning evidence.

## Definitions

- **Run root** — one directory under `/Users/Shared/agent-scratch/r/`
  allocated through the accepted scratch layout with a
  `repomap-test-scratch-manifest-v1` manifest.
- **Ledger** — the private `repomap-test-resource-ledger-v1` file for one
  run identity.
- **Retention class** — the closed lifecycle state of a run root or
  registered evidence group (next section).
- **TTL** — elapsed wall time since the run manifest's terminal-state
  timestamp (falling back to manifest mtime when the terminal timestamp is
  absent), after which a class becomes GC-eligible.
- **Soft/hard watermark** — aggregate allocated-byte and inode thresholds
  over the RepoMap-owned run subtree that change admission and GC behavior.
- **Practical exclusive window** — no other live RepoMap-mutating agent run
  (live manifests under the shared scratch root plus operator attestation),
  not proof that every unrelated process or socket is absent.
- **Bounded batch** — a GC mutation set limited simultaneously by run
  count, bytes, and wall time.
- **Quarantine** — a same-filesystem holding area receiving atomically
  renamed GC candidates before physical deletion.
- **Advisory index** — a rebuildable summary of run classifications that is
  never deletion authority.

## Options Considered

Full matrices appear inline in the two decisions with genuinely competing
architectures (historical GC; BuildKit). Compact analyses for the remaining
decisions appear in their sections. Safety invariants (never violated by any
option) are distinguished from selected defaults (changeable by a future
ADR) and operator policy (changeable by the operator within architectural
maximums) throughout.

### Historical scratch GC (mandatory decision 3)

**Option A — operator-only reclamation.** Agents inventory and report; only
the operator deletes.
Safety: maximal — no automated deletion path exists. Availability/DX: poor;
the August 2026 event shows pressure accumulates until a human performs an
emergency, evidence-destroying cleanup. Performance/disk: unbounded growth
between interventions. Privacy: good (inventory-only). Portability: total.
Complexity: minimal. Failure modes: neglect; emergency `rm -rf` recurrence.
Rollback: trivial. Compatibility: works with committed dry-run classifier.
Rejected as the sole mechanism because it demonstrably failed on this host;
retained as a component (the operator path of decision 4).

**Option B — TTL-based automatic cleanup.** Every eligible terminal run
older than its class TTL is deleted during any maintenance pass.
Safety: weaker — deletion volume is unbounded in a single pass, and a clock
or classification defect propagates to every expired run at once.
Availability/DX: good. Performance/disk: good steady-state. Privacy: fine.
Complexity: moderate. Failure modes: mass deletion on misclassification;
races with slow-starting runs. Rollback: moderate. Rejected because
unbounded automated deletion approximates an automated
`rm -rf agent-scratch/r`, which the invariants prohibit.

**Option C — bounded quota-driven hybrid (selected).** Current-run cleanup
stays automatic; historical GC runs only when operator-requested, scheduled
by the operator, or triggered above the soft watermark by an admission
profile that permits it; each pass deletes a bounded batch of exactly
revalidated candidates and stops when the target watermark is restored.
Safety: strong — double-bounded (eligibility and batch), exact revalidation
immediately before mutation, quarantine indirection. Availability/DX: good;
ordinary runs never pay GC cost. Performance/disk: pressure-responsive.
Privacy: counts-only public output. Portability: full. Complexity: the
highest of A–C, concentrated in one maintenance entry point. Failure modes:
starvation under sustained pressure (mitigated by operator path), quarantine
accumulation (bounded by quarantine TTL). Rollback: disable trigger,
falling back to Option A behavior. Compatible with the committed classifier
as the discovery layer. Selected.

**Option D — external scheduled service (launchd).** A host service owns
maintenance independently of test runs.
Safety: weakest for this repository — deletion authority migrates outside
the repository and review boundary, runs without operator presence, and
requires host configuration this project treats as sysadmin work.
Availability/DX: good once installed. Complexity: host-specific installer,
service identity, log ownership. Failure modes: silent divergence from
repository policy; unattended deletion. Rejected as the deletion owner;
the operator may separately schedule invocations of the repository-owned
maintenance command, which remains the sole mutation authority.

### Buildx/BuildKit architecture (mandatory decision 7)

**Option A — dedicated Buildx `docker-container` builder per run.**
Safety: exact ownership is not achievable — the driver's documented
driver-opts (image, memory, memory-swap, cpu-quota, cpu-period, cpu-shares,
cpuset-cpus, cpuset-mems, default-load, network, cgroup-parent,
restart-policy, env.\*, provenance-add-gha) include no label option, so the
builder container `buildx_buildkit_<name>0` and state volume
`buildx_buildkit_<name>0_state` cannot carry the centralized ownership
labels; label-plus-ledger agreement is impossible by construction.
TEST-HYGIENE1 already refused on exactly this boundary. DX: simplest.
Rejected as default; name-only ownership violates the invariants.

**Option B — directly launched labelled BuildKit daemon plus Buildx remote
driver (selected for the build profile).** The harness itself creates the
BuildKit container from an exact preloaded pinned image, its dedicated named
state volume, and (when needed) a dedicated network — all with exact
`org.repomap.test.resource.*` labels and ledger registration — then attaches
Buildx as a pure client via the documented `remote` driver
(`docker-container://` endpoint). Official documentation places daemon
lifecycle ownership entirely on the user under this driver, which is
precisely the ownership boundary RepoMap requires.
Safety: exact label+ledger ownership of container, state volume, network,
and volume-contained cache; build-history ownership remains a 3C
acceptance precondition to observe, not an established property. DX:
moderate setup cost, isolated to the build profile. Performance/disk: cache bounded
by daemon GC config and deleted with the volume. Failure modes: image-pin
drift (admission-refused, fail closed); remote-driver behavior changes
(revisit condition). Complexity: moderate. Selected for the `build`
profile.

**Option C — Docker Engine build API / classic builder.** The classic
non-BuildKit Linux builder is deprecated since Docker v23.0 (bugfix-only,
deprecation warning); Engine-API builds produce daemon-side intermediate
state without exact ownership labels. Rejected as a durable default; not
prohibited for a future narrowly scoped test double where no real build
occurs.

**Option D — no image build in ordinary tests (selected as default).**
Ordinary and integration tests never build images; they consume exact
preloaded image digests provisioned by a separately authorized
image-preparation activity. Absence of the exact local image is an
admission refusal, not a pull.
Safety: maximal for the common case; zero build state created. DX: requires
occasional operator-run image preparation. Selected as the default for
every profile except `build`.

Composition selected: Option D by default; Option B inside the explicit
`build` profile; BuildKit uncertainty therefore cannot block ordinary unit
and focused integration testing.

## Decision

RepoMap adopts the following policy set. Immutable safety invariants are
labelled **[invariant]**; selected defaults **[default]** (changeable only
by a future ADR); operator policy **[operator]** (changeable by the
operator within architectural maximums).

### 1. Lifecycle and retention classes

The closed lifecycle for run roots and registered evidence is:

`active` → `transient-current-run` (in-run groups) →
{`successful-evidence` | `failed-evidence` |
`correction-required-evidence` | `report-source-pending-append`} →
`historical-gc-candidate` → `quarantined-or-revalidation-pending` →
`deleted`, with `operator-pinned` and `ambiguous-or-foreign` as
out-of-band states and `report-packet-transient` covering APG packets
outside the scratch root.

The retention-class table below is normative. APG Git-diff, Git-show, and
operational report packets are transient ChatGPT-reporting conveniences,
not durable phase-acceptance authority **[invariant]**; durable acceptance
lives in Git commits, ADRs, and status records. A run's scratch report
source becomes GC-eligible (class `historical-gc-candidate`, 24-hour grace
TTL) only when all of the following hold: `append-operational-report`
succeeded; the appended packet's integrity summary verifies
(`RECORD-COMPLETE: true` and matching SHA-256); and the owning phase has
reached a durable close, proved by a private post-commit close receipt —
a restricted-mode record in the run's private evidence, written by the
phase closeout strictly after the local phase commit and the report
append both completed, carrying the phase ID, the exact commit identity
(private receipts may hold exact private SHAs), and the append record ID —
or the operator explicitly releases the source **[default]**. The receipt
is deliberately outside tracked documentation, so the predicate is not
self-referential: the tracked exit document never needs to name its own
resulting commit. A missing receipt holds the source indefinitely and
escalates to operator attention rather than releasing **[invariant]**.
Verified append alone never releases report
sources; a pending peer review or unfinished phase closeout keeps them
held, so a delayed review cannot recreate the TEST-HYGIENE1 evidence-loss
condition **[invariant]**. Malformed or missing manifests, ledgers,
or evidence demote a run to `ambiguous-or-foreign` — inventory-only,
operator-handled, never automated **[invariant]**.

### 2. Scratch quotas and watermarks

Profile-based quotas per the quota table below **[default]**, enforced at
registered checkpoints (run entry, workload boundaries, cleanup, close) —
not by continuous filesystem watching. At ≥ 80 % of a per-run quota the run
records a quota warning checkpoint; at 100 % the run stops and fails closed
with `quota_exceeded` **[invariant]**: it preserves already-registered
diagnostic evidence, performs normal exact teardown of registered transient
groups, and never silently discards evidence, switches scratch roots,
deletes ambiguous resources, or broadens cleanup authority.

Aggregate RepoMap watermarks (allocated bytes and inodes over the
RepoMap-owned run subtree, from the advisory index plus `statvfs`): soft
40 GiB / 1.5 M inodes; hard 80 GiB / 3.0 M inodes **[default]**.
Architectural maximums: no configuration may raise the hard watermark above
256 GiB / 8 M inodes or lower the free-disk reserve below 10 GiB
**[invariant]**. Above soft: new runs still admitted; GC eligibility
triggers for profiles that permit it. The hard watermark bounds the
reserved aggregate: a managed run is refused (`host_admission_refused`)
whenever the reconciled conservative bound plus the run's own full
profile byte and inode quotas would exceed the hard watermark
(decision 5); active runs continue. An operator override may raise the
effective hard watermark only within the architectural clamps
(configuration layer 3); no override bypasses the
prospective-reservation inequality itself, which is always evaluated
against the effective watermark **[invariant]**. Minimum free-disk reserve: a managed run refuses to
start when the scratch filesystem has under 20 GiB or under 5 % free
**[default]**. Free-inode reserve applies only where the filesystem
reports a bounded inode table (not APFS, which reports ~9.5 billion free
inodes on this host): 1 M free inodes **[default]**.

Values are selected policy defaults with a stated basis, not measurements,
and they satisfy their own derivation rule: hard ≤ 50 % of the lowest
observed host-distress aggregate; soft = 50 % of hard; per-run default ≥
2× the trailing-quarter per-profile p95 **[default]**. Concretely, 50 % of
the observed 182,003,687,424-byte distress aggregate is 91,001,843,712
bytes (≈ 84.75 GiB), and the selected hard watermark of 80 GiB
(85,899,345,920 bytes) is below it; 50 % of the observed 7,184,027-inode
aggregate is 3,592,013, and the selected 3.0 M hard inode watermark is
below it. Per-run quotas sit at roughly 4× the estimated historical
per-run means, with headroom profiles above (quota table).

### 3. Historical scratch GC

Option C — bounded quota-driven hybrid (matrix above). Normative behavior:

- **Discovery** uses the committed dry-run classifier
  (`classify_historical_scratch`) semantics: exact manifest schema, project,
  run-kind, run-id and physical-root match, owner-uid match, terminal state,
  dead owner pid, absence from active report and monitoring sets,
  link-safety. Discovery output is advisory.
- **Eligibility** additionally requires class TTL expiry per the retention
  table and absence of an operator pin.
- **Lifecycle lease protocol**: every consumer that grants a run new
  protection — operator pinning, report-source registration, and
  monitoring-index registration — and every GC mutation must first acquire
  the run's exclusive lifecycle claim: an `O_EXCL`-created claim record in
  a single private claim registry keyed by run identity. GC acquires the
  claim before revalidation and holds it through the quarantine rename;
  physical deletion re-acquires the claim and re-verifies the quarantine
  record before removing bytes. A consumer that finds the claim held by GC
  fails its registration cleanly and retries after the pass; GC finding
  the claim held by a consumer skips the candidate as active. Eligibility
  is therefore atomic relative to pin, report, and monitoring writers —
  not merely rename-atomic **[invariant]**.
  Claim records carry an owner token (purpose, process ID, process start
  time, and creation timestamp) so a claim is valid only while its exact
  owner process is alive. Stale-claim recovery is maintenance-only: under
  the single global maintenance lock, a claim whose owner is provably dead
  (process ID absent or start time mismatched) and older than the claim
  lease TTL (1 hour **[default]**) is atomically renamed to a tombstone in
  the GC ledger before any new claim is created, so recovery can never
  produce two simultaneous holders and an unlinked-and-recreated claim
  (ABA) is excluded by the start-time check. A run whose claim was
  recovered is skipped for that pass and re-enters ordinary discovery
  later; improvised stale-claim unlinking outside maintenance is
  prohibited **[invariant]**.
- **Revalidation immediately before mutation** re-reads the manifest and
  re-checks every discovery fact plus pin, class, TTL, physical identity
  (device+inode of the run root captured at discovery must match), and
  link-safety, inside the maintenance process that performs the rename and
  while it holds the lifecycle claim. If any revalidation field changed,
  the candidate is skipped: as active when a legitimate consumer holds or
  acquired protection, otherwise classified `ambiguous-or-foreign` for
  this pass **[invariant]**.
- **Mutation** is a same-filesystem atomic rename into
  `<scratch-root>/.quarantine/repo-map_dev/<run-id>` with a GC-ledger
  record (private, restrictive mode). Physical deletion happens only on a
  later maintenance pass, after the quarantine TTL (7 days **[default]**),
  under a re-acquired lifecycle claim, and only after re-validating,
  under that claim, every mutable protection predicate — pin absence,
  report and monitoring non-membership, and quarantine-record
  integrity — not merely the quarantine record: mutual exclusion alone
  does not detect protections registered and released during the
  quarantine window **[invariant]**. A quarantined entry found protected
  is excluded from deletion, flagged in public counts, and restored by
  maintenance to its pre-quarantine location under the same claim.
- **Batching**: one pass mutates at most 25 runs, at most 10 GiB
  allocated, within at most 60 seconds of mutation wall time
  **[default]**, and stops early once the aggregate is back under the
  soft watermark. The byte bound governs batch composition, not
  candidate eligibility: a single eligible candidate larger than the
  byte bound forms a single-candidate batch of its own (quarantine is
  one atomic rename regardless of size), so no eligible entry is
  permanently undeletable; a candidate that still cannot be processed
  within the wall-time bound escalates to operator attention rather
  than being silently deferred forever.
- **Triggers**: operator-requested; operator-scheduled; or admission-time
  when the aggregate exceeds the soft watermark and the requesting profile
  permits pre-work GC (profile table). Ordinary runs never trigger GC
  **[default]**.
- **Interruption recovery**: every rename is preceded by a GC-ledger intent
  record and followed by a completion record; on restart, an intent without
  completion is resolved by observing which single location exists (the
  rename is atomic), and quarantine entries lacking valid records are
  `ambiguous-or-foreign`.
- **New unrelated runs** are never candidates: a live manifest, a running
  state, a live owner pid, report/monitoring membership, or a missing TTL
  each independently excludes them; runs newer than their class TTL are not
  even discovered as eligible.
- **Why this cannot reproduce `rm -rf agent-scratch/r`**: there is no
  recursive root-deletion primitive; every deletion is per-candidate with
  exact per-candidate revalidation; passes are triple-bounded; active,
  pinned, foreign, malformed, and ambiguous entries are excluded by closed
  rules; when the eligible set exceeds the batch bounds, the maintenance
  command selects a deterministic bounded batch in the single normative
  batch order — tier one: `over-retention` entries, oldest terminal state
  first; tier two: remaining eligible candidates, oldest terminal state
  first; stable tie-break on run identity in both tiers — and defers the
  remainder to later passes; it never expands its bounds within a pass;
  and only the quarantine subdirectory is ever physically deleted from
  **[invariant]**.

### 4. Operator reclamation

A separate, broader, repository-owned path (implemented in TEST-HYGIENE3B3,
which must be accepted before any use of the command):

- Authorization requires an explicit operator-typed CLI flag on the
  maintenance command (a literal confirmation phrase naming the scope); it
  cannot be supplied via configuration file or environment **[invariant]**.
  Agents must not invoke it without a current, explicit, in-session operator
  instruction; disk pressure, old manifests, or previous conversations are
  not authority **[invariant]**.
- Default checks: refuses while any live RepoMap run manifest exists
  (running state with live owner pid); the operator may add a second
  explicit force flag to proceed, which records `operator_interrupted`
  against the affected runs **[operator]**.
- Scope: may clear the entire RepoMap run subtree, including classes
  automated GC may never touch (ambiguous, foreign-manifest,
  report-pending) **[operator]**. Operator pins block broad cleanup unless
  a third explicit override flag is given; the command warns and logs the
  pin count either way **[default]**.
- Logging: a public-safe summary (counts, byte totals, categories, flags
  used, timestamp) is appended to a local operator log outside Git; no
  private paths or identities **[invariant]**.
- A running phase that observes the reclamation records
  `operator_interrupted` and does not invent uninterrupted cleanup evidence
  **[invariant]** — exactly the TEST-HYGIENE1 lesson.
- Ownership: the command is repository-owned (versioned, reviewed, tested),
  not APG-owned and not a manual `rm` recipe. The August 2, 2026 manual
  `agent-scratch/r` cleanup is recorded as the motivating example of why
  the operator needs a safe first-class path — not as a failed automated
  GC and not as automated-cleanup precedent.
- Rollback: none is promised. Deletion is final; the operator path may
  optionally route through quarantine but is not required to.

### 5. Inventory cadence and index authority

- **Per-run entry**: the existing lightweight own-run checkpoint plus one
  `statvfs` read and one bounded index reconciliation (below). An
  admitted run immediately writes an immutable admission record
  (`runs/<run-id>.admitted.json`, `O_EXCL`) carrying its profile and
  byte/inode quotas. Maximum ordinary-run admission scan work is O(own
  run tree) plus the bounded reconciliation — never a foreign-run walk
  **[invariant]**.
- **Per-run exit**: mandatory exact close accounting (existing final
  projection) plus an immutable close record for the closing run, which
  supersedes its admission record.
- **Full inventory** (the only operation allowed to walk foreign runs'
  metadata): operator-scheduled, operator-requested, or triggered when the
  index is absent/corrupt or `statvfs` free space is below reserve while
  the index claims otherwise. Millions of inodes are avoided on ordinary
  runs by construction: aggregate state comes from the index and `statvfs`,
  and full scans are maintenance-only, metadata-only, and rate-limited to
  at most one per 24 hours absent operator request **[default]**.
- **Index**: `<scratch-root>/.index/repo-map_dev/`, private mode, advisory
  and rebuildable from a full scan. Concurrency and freshness contract:
  runs never edit a shared summary in place; run owners write only
  immutable per-run records (`O_EXCL`, single writer): an admission
  record at entry and a close record at exit. Only maintenance compacts
  records into `summary.json` under the maintenance lock with a monotonic
  generation stamp, and it removes folded records only after the new
  summary is atomically renamed into place. The watermark admission check
  computes a **conservative upper bound**, never an exact figure: summary
  aggregate, plus the measured sizes of uncompacted close records, plus
  the **full profile quota** of every admitted-but-not-closed run (its
  admission record without a matching close record). Active runs
  therefore count at their worst case, and a record transiently visible
  both in a fresh summary and as an unfolded file is double-counted — the
  bound may transiently overcount and refuse, but can never undercount
  and wrongly admit **[invariant]**. Admission reads the summary
  generation, performs one flat listing of the record directory, then
  re-reads the generation; if it changed, admission retries once and
  otherwise fails closed. Above the record cap (512 uncompacted records
  **[default]**), or when freshness cannot be established (missing
  generation, unreadable summary, `statvfs` inconsistent with the claimed
  aggregate direction), **every** profile — including `ordinary` — fails
  closed with `host_admission_refused` and flags maintenance; the
  free-disk reserve is an independent additional check, never a
  substitute for the watermark check **[invariant]**. Admissions
  serialize: the watermark check and the admission-record write happen
  atomically under one exclusive admission lock (an `O_EXCL` lock file in
  the index directory carrying the same owner token as lifecycle claims,
  with the same maintenance-only stale-lock recovery), so two concurrent
  requests cannot both check against a snapshot that includes neither of
  their reservations **[invariant]**. The admission inequality includes
  the requester's own prospective reservation: a request is admitted only
  when the reconciled conservative bound **plus the requesting profile's
  full byte quota** is at or below the hard byte watermark, and the
  reconciled inode bound **plus the requesting profile's full inode
  quota** is at or below the hard inode watermark — admission can
  therefore never move the reserved aggregate across the hard watermark,
  not even for a single request **[invariant]**. Ordinary admission
  cost is therefore one `statvfs` plus one bounded index reconciliation:
  one `summary.json` read, one capped flat listing, and at most 512 small
  record reads. Drift between index and filesystem is resolved in favor
  of the filesystem and triggers a rebuild **[invariant]**. The index is
  never deletion authority **[invariant]**.
- **Facts required before any deletion**: exact manifest identity, ledger
  presence for ledger-era runs, terminal state, dead owner, report and
  monitoring non-membership, physical identity match, link-safety, TTL
  expiry, pin absence — all revalidated at mutation time (decision 3)
  **[invariant]**.

### 6. Docker object lifecycle

Current-run cleanup authority remains exactly TEST-HYGIENE1's: creation
observation + centralized labels + private ledger agreement + baseline
protection + reference checks + exact removal + final readback
**[invariant]**. Labels alone are never sufficient **[invariant]**.

Per class (current-run / historical):

- **Containers**: automatic exact teardown / operator-only.
- **Image tags**: automatic with exact image identity, tag multiplicity,
  and pre-existing-reference protection / operator-only.
- **Image IDs**: automatic only for run-created images with no surviving
  reference, `noprune`-style removal preserving shared parents /
  operator-only.
- **Networks**: automatic when run-created, no pre-existing attachment /
  operator-only.
- **Named volumes**: automatic when run-created, labelled, ledgered, and
  unreferenced / operator-only.
- **Anonymous volumes**: never deleted by RepoMap automation, current or
  historical **[invariant]** — they cannot carry creator labels (official
  volumes documentation); prevention continues by design (tmpfs override in
  the PostgreSQL harness; no `-v`-style implicit removal flags).
- **Buildx builder metadata**: automatic for the run's dedicated builder
  under phase-owned `BUILDX_CONFIG` / not applicable historically (metadata
  lives under run-owned config).
- **BuildKit builder containers, state volumes, and volume-contained
  cache**: automatic only under the decision-7 remote-driver ownership,
  where they are run-created and exactly owned; otherwise they are never
  created. **Build-history records**: automatic removal only after
  TEST-HYGIENE3C has observed where history persists and proved exact
  ownership (decision 7); until that acceptance, an unproved history
  location is a `buildkit_admission_refused` stop condition for the build
  profile, never a cleanup target. Historical BuildKit state:
  operator-only.

Historical Docker cleanup is **deferred**: automated historical Docker GC is
not authorized by this ADR, because legacy objects lack the labels and
ledgers exact revalidation requires — every legacy object is by definition
ambiguous. Until all build paths emit the centralized labels and ledger
records for at least one full retention cycle, historical Docker cleanup is
operator-only. A future ADR may authorize automated historical Docker GC
over exclusively ledger-era objects.

No broad prune of any kind (`system prune`, `image prune`, `volume prune`,
`builder prune`, or equivalents) is ever executed by RepoMap automation
**[invariant]**. "Dangling" or "unused" status is never deletion evidence
**[invariant]**. Port freedom is not PostgreSQL-cluster cleanup proof;
missing tags are not image-deletion proof; a stopped builder container is
not builder/state/cache/history cleanup proof **[invariant]**.

### 7. Buildx and BuildKit

Composition selected in the options section: Option D (no builds in
ordinary tests) as the default for all profiles; Option B (harness-launched
labelled BuildKit daemon + Buildx `remote` driver client) exclusively
inside the `build` profile. Normative details:

- **Image provisioning**: the exact BuildKit image is pinned by digest
  **[default]** and provisioned only by a separately authorized,
  operator-run image-preparation activity; test runs have no pull
  authority **[invariant]**.
- **Admission**: absence of the exact local pinned image is
  `buildkit_admission_refused` before any workload creation **[invariant]**.
- **Ownership**: the harness creates the daemon container, its named state
  volume, and any dedicated network itself, with full centralized labels
  and ledger registration, before Buildx attaches via
  `docker-container://` **[invariant]**. The shared/default builder is
  never selected, bootstrapped, configured, or pruned **[invariant]**.
- **Network**: the daemon runs with no external network access
  (network-disabled or a dedicated internal labelled network)
  **[default]**.
- **Cache**: no cross-run build cache by default **[default]** — the state
  volume is per-run and removed at teardown. In-run cache is bounded as
  defense in depth via the daemon's GC configuration
  (`reservedSpace 1 GiB`, `maxUsedSpace 8 GiB`, `minFreeSpace` equal to
  the host free-disk reserve) **[default]**; upstream BuildKit defaults
  (10 %/10 GB reserved, 60 %/100 GB max, 20 GB min-free) are documented
  for comparison but not relied on. Any future shared cache profile
  requires its own ADR.
- **History**: official documentation does not state where build-history
  records persist, so exact history ownership is **not** an established
  property of this decision — it is a TEST-HYGIENE3C acceptance
  precondition that must be observed before any build path is accepted.
  The accepted ownership claim of Option B is bounded, until then, to the
  labelled daemon container, its named state volume, its dedicated
  network, and cache demonstrably contained in that volume. The intended
  teardown sequence (`docker buildx history rm --all` against the
  dedicated builder, then daemon container and state volume removal) is a
  plan, and a failed history listing against a removed builder is never
  by itself absence evidence — 3C must demonstrate where records live and
  prove their exact absence, or the build profile stops with
  `buildkit_admission_refused` and records the platform gap
  **[invariant]**.
- Ordinary unit and focused integration testing never depends on any of
  the above; BuildKit work is isolated in the `build` profile and the
  TEST-HYGIENE3C slice **[invariant]**.

### 8. Host-admission profiles

Five profiles per the host-profile table below. Cross-cutting rules:

- Memory admission uses macOS memory-pressure levels (normal/warn/critical
  via the unprivileged `memory_pressure` tool; Apple documents pressure,
  not free RAM, as the strain indicator). Raw used-RAM percentage is never
  the sole admission signal **[invariant]**. Where pressure levels are
  unreadable (sandbox denial observed for the `kern.memorystatus` sysctl on
  this host), the profile's pressure gate degrades to "tool-reported free
  percentage plus operator attestation" and records the degradation.
- Swap and compressor statistics (`vm_stat` pageouts, compressor pages) are
  recorded as advisory evidence where observable, never as sole gates.
- A failed admission stops before workload creation with
  `host_admission_refused`; it never retunes product deadlines, never
  retries until the laptop happens to be quiet, and never silently
  downgrades the requested profile **[invariant]**.
- `heavy` and `qualification` require a practical exclusive window: no
  other live Claude, Codex, RepoMap, or repo-map_ctrl mutating run
  (live-manifest check plus operator attestation), not proof that every
  unrelated process, container, or socket is absent **[invariant]**. They
  stop if such activity is detected **[invariant]**.
- The controlled-host observer comparison remains frozen unless a future
  operator explicitly reauthorizes it under the `qualification` profile
  **[invariant]**.

### 9. Configuration precedence

Authority order, highest first **[invariant]**:

1. immutable safety invariants (hardcoded; not configurable);
2. architectural maximums (hardcoded ceilings that clamp all lower layers);
3. operator command-line overrides;
4. environment overrides in the closed `REPOMAP_TEST_HYGIENE_*` namespace;
5. repository-local nonsecret configuration
   (`test-hygiene.local.toml` at the repository root, gitignored);
6. repository defaults (committed code).

The per-phase requested profile is a selection input validated against all
of the above; it can select among defined profiles but cannot define new
scopes or exceed maximums. Cleanup scope is not configuration: no layer may
name arbitrary deletion paths, add retention classes, or widen mutation
authority — model-controlled arbitrary cleanup scopes are rejected by
construction **[invariant]**. Configuration is schema-validated and
bounded before use; invalid configuration fails closed to refusal, not to
defaults **[invariant]**. Keys are explicit about units
(`*_BYTES`, `*_INODES`, `*_SECONDS`, `*_PERCENT`); values are public-safe
and credential-free; the effective merged configuration is included in
private run evidence by SHA-256 digest and is re-derived identically in
subprocesses from the same sources **[default]**.

### 10. Failure and interruption semantics

Closed outcome vocabulary (failure-taxonomy section below):
`current_run_cleanup_failed`, `historical_gc_refused`, `quota_exceeded`,
`host_admission_refused`, `buildkit_admission_refused`,
`operator_interrupted`, `external_unattributed_mutation`,
`ambiguous_resource_present`, `evidence_retained`, `cleanup_complete`.

Actor distinction is mandatory: operator-authorized deletion (explicit
flags, operator log), automated GC (GC-ledger records), current-run
teardown (run ledger), unknown actor (`external_unattributed_mutation` —
used only when no operator attribution is available; the TEST-HYGIENE1
event is retro-attributed to the operator via the 00706 correction),
another legitimate run being created (live manifest of the new run), and
ambiguous/malformed resources (`ambiguous_resource_present`). No outcome
may claim host restoration from selected-port freedom or absence of one
container class **[invariant]**.

### 11. Implementation and migration sequence

Authorized slices — strictly ordered TEST-HYGIENE3A, then 3B1 (lease +
quarantine-only GC), then 3B2 (physical deletion, separately accepted) as
the hygiene core; after 3B2 acceptance, 3B3 (operator reclamation, own
destructive-path review) and 3C (Docker/BuildKit) are authorized in
parallel or either order — per the migration section.

### 12. Pivot to performance and graph quality

Hygiene exit criteria: acceptance of TEST-HYGIENE3A, 3B1, and 3B2 (the
hygiene core). Once those are accepted, PERF-BASE1, XDEP0, and DBEXT0 are
authorized to begin, and TEST-HYGIENE3B3 and 3C proceed in parallel
without blocking them. TEST-COV5K qualification, the controlled-host comparison,
and perfect historical cleanup are explicitly **not** prerequisites for
those architecture studies. Hygiene work beyond 3A/3B/3C requires a new
ADR with new evidence; hygiene must not become an indefinite substitute
for RepoMap product development.

## Retention-Class Table

| Class | Creator | Durability | Default TTL | Max without pin | Deletion authority | Revalidation | Public reporting | Malformed/missing evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `active` | run allocator | transient | n/a (live) | n/a | none (never deletable) | live manifest + pid | count | demote to ambiguous |
| `transient-current-run` | run layout | transient | end of run | end of run | owning run's exact teardown | ledger registration | counts/bytes | `current_run_cleanup_failed` |
| `successful-evidence` | run close (passed) | durable until TTL | 7 days | 30 days | bounded GC or operator | full (decision 3) | counts/bytes | demote to ambiguous |
| `failed-evidence` | run close (failed) | durable until TTL | 30 days | 90 days | bounded GC or operator | full | counts/bytes | demote to ambiguous |
| `correction-required-evidence` | phase close | durable until TTL | 90 days | 180 days | bounded GC or operator | full | counts/bytes | demote to ambiguous |
| `report-source-pending-append` | run close | transient-durable | until verified append + private post-commit close receipt (or operator release) + 24 h grace | 7 days, then operator attention | bounded GC only after verified append and close receipt | append integrity (RECORD-COMPLETE + SHA-256) + close-receipt validation, then full | counts | never auto-deleted; operator attention |
| `report-packet-transient` | APG tooling (outside scratch) | transient convenience | operator-owned | operator-owned | operator | n/a | none | n/a |
| `operator-pinned` | operator | durable | none | indefinite | operator only | pin record | count | pin survives; operator attention |
| `historical-gc-candidate` | maintenance classification | transient state | immediate eligibility | n/a | bounded GC or operator | full, at mutation time | counts/bytes | demote to ambiguous |
| `quarantined-or-revalidation-pending` | GC rename | transient | 7 days quarantine TTL | 30 days, then operator attention | later GC pass or operator | quarantine record recheck | counts/bytes | operator attention |
| `ambiguous-or-foreign` | classification | durable | none | indefinite | operator only | n/a | counts | is the malformed sink |
| `deleted` | GC/operator bookkeeping | record only | n/a | n/a | n/a | n/a | counts | n/a |

The "max without pin" column is a binding escalation threshold, not a new
spontaneous deletion authority: an entry past its class maximum is flagged
`over-retention` in public counts and enters tier one of the single
normative batch order defined in decision 3 (over-retention entries
oldest-first, then remaining eligible candidates oldest-first) at the
next maintenance pass, however that pass was triggered. If no maintenance
pass occurs, the entry remains held and reported; nothing deletes outside
a maintenance pass **[invariant]**.

TTLs are selected policy defaults **[default]** with a stated basis:
7 days matches the operator's weekly review cadence for passing evidence;
30 days covers failure-diagnosis windows across successor phases; 90 days
covers multi-phase remediation lineages (the TEST-COV5K family has already
spanned weeks); pins are indefinite by definition. The derivation rule for
future tuning: no class TTL may be shorter than the longest observed
phase-remediation gap that actually consumed its evidence class in the
trailing two quarters.

## Quota And Watermark Table

Per-run quotas (allocated bytes / inode count) **[default]**:

| Profile | Byte quota | Inode quota | Basis |
| --- | ---: | ---: | --- |
| `ordinary` | 2 GiB | 50,000 | ≈ 4× estimated historical per-run mean (478 MB / 18.9 k, estimate) |
| `integration` | 8 GiB | 200,000 | container fixtures + reports headroom |
| `build` | 16 GiB | 300,000 | plus BuildKit in-run cache quota (8 GiB) inside the daemon volume |
| `heavy` | 32 GiB | 750,000 | scale campaigns; ≈ 2× largest routine int-run estimate |
| `qualification` | 64 GiB | 1,500,000 | full campaign evidence; one run still fits under the 80 GiB hard watermark |

Aggregate and host values:

| Signal | Value | Kind |
| --- | ---: | --- |
| Soft watermark (bytes) | 40 GiB | default |
| Soft watermark (inodes) | 1.5 M | default |
| Hard watermark (bytes) | 80 GiB | default |
| Hard watermark (inodes) | 3.0 M | default |
| Architectural max hard watermark | 256 GiB / 8 M | invariant ceiling |
| Free-disk reserve (managed runs) | ≥ 20 GiB and ≥ 5 % free | default |
| Architectural min free-disk reserve | 10 GiB | invariant floor |
| Free-inode reserve (non-APFS only) | 1 M | default |

Behavior: 80 % per-run quota → warning checkpoint; 100 % → fail closed
(`quota_exceeded`, evidence preserved, exact teardown only). Above soft
watermark → admission continues, GC-permitting profiles may trigger a
bounded pass. Hard watermark → a run is refused
(`host_admission_refused`) whenever the reconciled conservative bound
plus its own full profile quotas would exceed the effective hard values;
active runs continue; an operator may raise the effective hard watermark
only within the architectural clamps, and no override bypasses the
inequality itself. Values distinguish selected portable defaults (table), operator
overrides (configuration layers 3–5), architectural maximums (clamps), and
machine-derived values (free-space percentages and the APFS inode
exception, derived at admission time).

## Host-Profile Table

| Profile | Concurrent agents | Exclusive window | Memory gate | Free disk | Scratch state | Docker/OrbStack | Long campaigns | Max complete gates | Pre-work GC | On failed admission |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `ordinary` | unrestricted | no | none (quota-only) | ≥ 20 GiB | below hard WM | not required | no | 0 | never | stop, `host_admission_refused` |
| `integration` | ≤ 2 RepoMap-mutating | no | not critical | ≥ 40 GiB | below hard WM | responsive (`docker version` ≤ 10 s) | no | 0 | bounded, optional | stop |
| `build` | 1 | no | not critical | ≥ 60 GiB | below hard WM | responsive + exact pinned BuildKit image present | no | 0 | bounded, optional | stop (`buildkit_admission_refused` for image absence) |
| `heavy` | 1 (practical exclusive) | yes | pressure normal | ≥ 100 GiB | below soft WM preferred, below hard required | responsive | bounded, declared | 1 | bounded, optional | stop; no deadline retuning |
| `qualification` | 1 (operator-attested exclusive) | yes, attested | pressure normal | ≥ 150 GiB | below soft WM | responsive | declared campaign plan only | 2 | bounded, before work only | stop; no retry loops |

`ordinary` admission cost is one `statvfs`, one bounded index
reconciliation (summary read, capped listing, at most 512 record reads
per decision 5), and own-run
setup — it never proves the laptop is a qualification host. `heavy` and
`qualification` stop when unrelated Claude/Codex/RepoMap/repo-map_ctrl
mutation is live and never adapt by retuning product deadlines. The
controlled-host observer comparison stays frozen pending explicit operator
reauthorization under `qualification`.

## Historical-GC State Machine

```text
                          +--------------------------+
                          |         active           |
                          +-----------+--------------+
                                      | run reaches terminal state
                                      v
        +-----------------------------+------------------------------+
        | terminal evidence classes                                   |
        | successful- / failed- / correction-required-evidence /      |
        | report-source-pending-append                                |
        +------+----------------------+------------------------------+
               | TTL expired, no pin;  | operator pin
               | report sources also   v
               | need verified append  |
               | + close receipt (or   |
               |   operator release)   |
               |                 +-----------+
               |                 | operator- |--- unpin --> (re-enter
               v                 |  pinned   |              TTL clock)
   +-----------------------+     +-----------+
   | historical-gc-        |
   | candidate (advisory)  |
   +----------+------------+
              | maintenance pass, batch capacity available
              v
   [ exact revalidation at mutation time ]
              | pass                         | any field changed
              v                              v
   +----------------------------+   +---------------------+
   | quarantined-or-            |   | ambiguous-or-       |
   | revalidation-pending       |   | foreign (operator   |
   | (atomic same-FS rename,    |   | inventory only)     |
   | GC-ledger intent+complete) |   +---------------------+
   +----------+-----------------+
              | quarantine TTL elapsed; under re-acquired
              | claim: record recheck + full protection
              | revalidation (pin absence, report and
              | monitoring non-membership) pass —
              | protected entries are restored instead
              v
   +----------------------------+
   |          deleted           |
   +----------------------------+
```

Every transition into quarantine or deleted is bounded per pass by
25 runs / 10 GiB / 60 s (a single oversized candidate may form a
single-candidate batch per decision 3) and stops early at the soft
watermark. Interrupted passes recover via intent/completion records and
rename atomicity.

## Operator-Reclamation Boundary

See decision 4. Summary of the boundary: explicit typed authorization per
invocation; live-run refusal with explicit force escalation recorded as
`operator_interrupted`; whole-subtree scope available; pins warn and block
absent a further explicit override; public-safe logging; repository-owned
command; no rollback promise; agents may never self-authorize. Operator
reclamation and automated historical GC remain distinct authorities with
distinct records; neither may be inferred from the other's evidence.

## Docker And BuildKit Policy

See decisions 6 and 7 (normative). Summary: current-run exact ownership is
automated; historical Docker cleanup is deferred to operator-only until a
full label+ledger retention cycle exists; anonymous volumes are never
automated targets; no broad prune ever; builds happen only in the `build`
profile through a harness-owned labelled BuildKit daemon with the Buildx
remote driver, pinned preloaded image, no pull authority, per-run state
volume, and bounded in-run cache; build-history removal and final-absence
proof remain TEST-HYGIENE3C acceptance preconditions per decisions 6
and 7.

## Configuration Precedence

See decision 9 (normative order, closed namespace, schema validation,
fail-closed invalid configuration, digest into private evidence, no
configurable cleanup scopes).

## Failure Taxonomy

PR26-STAGING-FIX2's revised candidate, with the supplied review dispositioned,
specializes disk measurement for authenticated DinD execution: the host reserve
protects the target-inspected classic `overlay2` writable-layer mapping, while
sandbox scratch and inner-Docker capacity retain separate refusal reasons.
Non-sandbox measurement is unchanged. See [ADR 0055](0055-isolated-unified-integration-sandbox.md)
for the current-owner binding and independent whole-tmpfs pressure check; no
host reserve or managed quota is lowered. Capacity failure must not prevent
exact current-run cleanup.

| Outcome | Meaning | Terminal for | Never means |
| --- | --- | --- | --- |
| `cleanup_complete` | every registered transient resource removed with readback; facts observed | run | host restoration |
| `evidence_retained` | retention classes hold registered evidence per policy | run | leak or failure |
| `current_run_cleanup_failed` | exact teardown incomplete; residue identified | run | authority to broaden cleanup |
| `quota_exceeded` | per-run quota reached; fail-closed stop with evidence preserved | run | permission to evict or switch roots |
| `host_admission_refused` | admission gate failed before workload creation | run request | deadline retuning or retry loops |
| `buildkit_admission_refused` | exact pinned image or ownership preconditions absent | build request | pull authority |
| `historical_gc_refused` | eligibility, revalidation, batch, or trigger conditions unmet | GC pass | expansion of scope |
| `operator_interrupted` | operator reclaimed resources during a phase | affected runs | uninterrupted-cleanup evidence |
| `external_unattributed_mutation` | state changed with no operator attribution available | affected runs | proof of a foreign agent |
| `ambiguous_resource_present` | malformed, foreign, unowned, or link-unsafe resources inventoried | inventory | deletion candidacy |

## Security And Privacy

- Private inventories, ledgers, GC ledgers, and the advisory index keep
  restrictive modes (0700 directories, 0600 files) and never enter Git.
- Public projections expose only bounded counts, sizes, categories, and
  closed policy outcomes. No private paths, raw Docker IDs, process
  arguments, environment contents, SQL, credentials, or evidence payloads
  enter public status or commits.
- Durable Git commits, ADRs, and status records remain distinct from
  transient agent-report packets and private diagnostics; packets are never
  acceptance authority.
- Configuration is nonsecret by construction; the schema rejects
  credential-shaped keys; effective configuration enters private evidence
  only as a digest.
- The GC and reclamation logs are public-safe summaries; exact identities
  stay in private run-local state.

## Consequences

Positive: ordinary development stays cheap (O(own-run) admission);
pressure now has three graduated, bounded responses (per-run quotas,
watermark-triggered bounded GC, explicit operator reclamation) instead of
none-then-emergency; every deletion authority is explicit, closed, and
audited; BuildKit stops being an unbounded invisible consumer; the product
roadmap unblocks at a defined point (3A+3B1+3B2 acceptance).

Negative / accepted costs: retained evidence can still transiently occupy
tens of GiB within watermarks; bounded GC may lag sustained pressure
(operator path is the relief valve); the build profile carries a real
setup cost (pinned image provisioning, daemon ownership); historical
Docker debt (12,882 volumes, 75 GB cache observed) remains operator-only
until label+ledger coverage matures — this ADR deliberately does not
authorize automation it cannot revalidate.

Risks accepted with mitigations: index staleness (advisory-only, rebuild
rule); quarantine growth (own TTL + operator attention); host-signal
degradation under sandboxes (recorded degradation, attestation fallback).

## Rejected Alternatives

- Historical-GC options A (alone), B, and D — see the option matrix.
- Buildx `docker-container` driver ownership (labels unachievable — primary
  source), Engine classic-builder default (deprecated since v23.0), and
  unrestricted in-test builds — see the BuildKit matrix.
- One universal quota number instead of profiles — collapses either DX
  (too small for scale work) or safety (too large for unit runs).
- Raw used-RAM percentage as an admission gate — contradicts Apple's
  documented pressure model and observed 93 %-free readings on a host that
  was simultaneously experiencing pressure symptoms from other causes.
- A root-level index with deletion authority — accidental authority
  migration; kept advisory-only.
- Continuous filesystem watching for quota enforcement — cost and
  complexity without matching safety gain; checkpoints suffice.
- Automated historical Docker GC in this ADR — no exact historical ledgers
  exist for legacy objects; revalidation would be fictional.
- An APG-owned or manual operator cleanup recipe — unreviewed deletion
  authority; the command must be repository-owned and tested.

## Migration And Implementation Slices

Authorized sequence (each slice is separately reviewable, bounded, and
reversible; slices may be combined only if reviewability remains strong):

- **TEST-HYGIENE3A — ledger strictness and retention core.** Strict ledger
  deserialization and type authority (exact Boolean validation replacing
  `bool(value)` coercion; strict loaded-schema validation rejecting unknown
  or missing fields; exact nonnegative integer validation; controlled
  malformed-evidence errors), current-run teardown completion, retention
  classes and TTL stamping, per-run quotas with fail-closed
  `quota_exceeded`, operator-interruption classification, and the advisory
  index writer. Mutation facts must be required and exact before any
  host-restoration claim.
- **TEST-HYGIENE3B1 — lifecycle lease and quarantine-only GC.** The claim
  registry and lease protocol, discovery, revalidation, batching, the GC
  ledger, interruption recovery, and quarantine renames only — no
  physical deletion. Fully reversible: quarantined runs can be renamed
  back.
- **TEST-HYGIENE3B2 — physical deletion from quarantine.** Deletion of
  quarantine entries whose TTL elapsed, under a re-acquired lease with
  record recheck plus full protection revalidation (pin absence, report
  and monitoring non-membership; protected entries are restored, not
  deleted), only after at least one real quarantine cycle from 3B1
  has been observed and reviewed. This is the first irreversible
  increment and is accepted separately.
- **TEST-HYGIENE3B3 — operator reclamation command.** The broad
  operator-authorized path of decision 4, with its own destructive-path
  review, separate from automated GC. Hygiene core completes at 3B2
  acceptance; 3B3 is not a core prerequisite.
- **TEST-HYGIENE3C — Docker historical lifecycle and BuildKit/build-profile
  containment.** Label+ledger coverage for remaining creation paths, the
  build profile's owned-daemon architecture (decision 7 Option B), history
  and cache teardown proof, and the deferred-historical-Docker posture.
  Runs in parallel with product work after 3A+3B1+3B2.

Carried corrections (listed in Current Architecture) are implementation
content for 3A; this ADR does not implement them.

## Verification Strategy

For this docs-only phase: `git diff --check`, `git diff --cached --check`,
ADR path/numbering uniqueness, link and fragment resolution for changed
documents, status-number uniqueness, privacy-leakage scan, and a scope
check that no source, test, dependency, or authorization change slipped in.
Source tests and compileall are intentionally not run (docs-only).

For the implementation slices (future phases, recorded here as acceptance
expectations, not executed now): red-first focused tests per module;
synthetic fixtures for every retention class including malformed, pinned,
report-pending, quarantined, and ambiguous; GC race tests covering a
candidate becoming live between discovery and revalidation, a pin or
report registration arriving between revalidation and the quarantine
rename (must be excluded by the held lifecycle claim or safely lose the
claim race), and a consumer arriving between the quarantine recheck and
physical deletion (must be blocked by the re-acquired claim);
interruption-recovery tests over intent/completion records; quota
fail-closed tests proving evidence preservation; admission-profile tests
with faked signals proving no deadline mutation; and for 3C a bounded real
proof of daemon/volume/history creation and exact absence. Complete gates
and long campaigns remain governed by the testing standards and profile
table, not by this ADR.

## Refresh/Revisit Conditions

Revisit this ADR when any of the following occurs:

- the falsification conditions in the problem statement trigger;
- Buildx/BuildKit changes driver label support, `rm --keep-state`
  semantics, or documents build-history persistence (closing the recorded
  gap);
- Docker changes prune scopes or anonymous-volume semantics;
- OrbStack publishes storage/builder documentation material to ownership;
- the host or scratch filesystem changes (watermarks are host-derived
  policy);
- two consecutive quarters pass with GC never triggering (quotas may be
  too loose) or with monthly hard-watermark refusals (too tight);
- label+ledger coverage reaches one full retention cycle (enables the
  deferred historical-Docker automation ADR);
- a shared build-cache need emerges (requires its own ADR).

## Explicit Authorizations And Prohibitions

Authorized by this ADR's acceptance:

```text
test_hygiene3_authorized: true    (3A, then 3B1, then 3B2; afterwards
                                   3B3 and 3C in parallel or either order)
perf_base1_authorized_after_hygiene3_core: true
xdep0_authorized_after_hygiene3_core: true
dbext0_authorized_after_hygiene3_core: true
```

"Hygiene core" means accepted TEST-HYGIENE3A, 3B1, and 3B2. Nothing in
this ADR is implemented in the current phase.

Not authorized (unchanged prohibitions):

```text
historical_cleanup_performed: false
docker_cleanup_performed: false
buildkit_bootstrap_performed: false
automated_historical_docker_gc: false
controlled_host_comparison_started: false
qualification_observations_accepted: false
test_cov5k_r2_review4_authorized: false
test_cov5k_r3_authorized: false
scale29_candidate_authorized: false
scale29_started: false
```

Agents acquire no reclamation authority from this ADR; decision 4's
explicit-authorization rule governs.
