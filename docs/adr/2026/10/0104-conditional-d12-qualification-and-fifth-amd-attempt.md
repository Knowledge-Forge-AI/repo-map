# ADR 0104: Conditional D12 qualification and one further AMD attempt

## Status

Accepted before implementation. On 2026-10-28 the maintainer selected A from the
reviewed CI84 next-attempt packet: conditional acceptance implementation, scoped
proof, exactly one fifth native AMD application start for CI85 attempt 1,
at most one necessary unchanged hosted SDK materialization, and one reviewed
public-staging publication. New vulnerability dispositions are not granted.
Implementation, source review and all resulting-state evidence remain pending.

ADR0105 subsequently supersedes the inherited Debian classification/disposition
holds and permits current stable-slim runtime pin refreshes. Its responsibility
boundary governs the successor qualification route; the fifth-build ceiling
and other limits below remain.

## Date

2026-10-28

## Context

CI84 tested staging 57e2023913db899ca5b5c5d72a7662ae00c19833 and merge
1743fd302405b20cd6b51ff63da3bfa7b11625f1. Eight jobs passed; main-system
refused before SDK/application construction because the spent CI72 grant's
d12_context differs from the current candidate. All measured Python coverage
floors plus two percentage points passed. Four application starts remain spent.

ADR 0095 deliberately introduced a diagnostic-only system path. Its unconditional
aggregate failure and v1 sidecar false flags remain correct for that historical
scope. A grant-only change would spend another build but still guarantee red.
The current collector is also insufficient for an acceptance path: the retained
CI72 inventory counted 3559 package verification results but listed only 1500.
CI72's 142-package population is a forecast, not qualification of the new image.
CI84's positive native preflight contains no final assembled application inventory.

## Decision

Implement a separate, strict evidence-driven acceptance path under ADR 0087,
then conditionally allocate exactly one fifth native AMD application start to
CI85 attempt 1. This supersedes the no-fifth scope clauses in ADRs 0099/0100/0101/0103 and the
diagnostic-only aggregate behavior for the new acceptance path. It never
rewrites historical evidence or treats a successful build as P3 acceptance.

The operator approved this implementation and conditional allocation, not any
new vulnerability disposition. If evidence reveals another affected or unknown
finding requiring disposition, present its exact component, version, sources,
severity and options before publication. Do not spend the fifth build merely
to rediscover an already known, unresolved pre-build hold.

### Preserved existing dispositions

Retain ADR 0101's exact finite 21-glibc finding record, owner and hash. No new
finding, identity or range is added to that acceptance. No November 1 cutoff.
ADR 0091 Choice A already carries the missing incumbent comparison unresolved
under Samuel Leighton Lair for this D12 candidate/staging evidence scope and
expressly says it is not a fresh operator acceptance requirement. Preserve it
as unresolved, not clean/fixed/worse, without a new incumbent build or a repeated
approval question. Neither disposition constitutes deployment or D15 admission.

### Closed catalogue and assessment

Before grant reservation, assemble a finite, versioned catalogue for the pinned
PostgreSQL final base, exact frozen closure and final Python/Go/first-party
payloads. Reuse retained inventories only as forecast input. Bind each finding
to exact binary/source versions, component/platform applicability, primary and
named secondary records, record hashes, collection date and all severity data.
Debian urgency never lowers a numerical score. Highest applicable severity wins.
Supplier exact-revision/backport applicability governs the class: a generic
upstream banner range cannot turn a supplier-proved fixed revision into affected.
Record conflicting applicability explicitly; unresolved conflict stays unknown.

Use the supplier primary (Debian tracker, PostgreSQL, PSF, Go or relevant upstream)
and named CVE records as secondary, retaining upstream/GHSA/OSV aliases where
applicable. Fix collection date to the actual collection date; refuse future,
foreign, missing, conflicting-lowered or incomplete records. A completed query
with no matching published advisory is recorded as that observation, not a
clean-component claim or an invented finding. Unknown concrete applicability
remains a hold. Refresh the collection if publication moves beyond its declared
candidate/date boundary; do not invent an expiry or operator deadline.

Final-image P3 covers deployed components, not builder-only components proved
absent from the final image. Existing source/SDK security gates stay active.
Component removal, observed distribution population, resolved runtime paths and
first-party source/build provenance must prove this distinction. Merely naming
a directory or a stage is insufficient. Builder-stage findings remain recorded
and governed by their existing scope; this decision accepts none of them.

The catalogue lives under tools/ci, outside the Docker COPY context. Bind its
exact catalogue and assessor bytes through a new closed system-admission-proof
version: the host computes them from verified committed blobs of the full Git
candidate SHA/tree, binds them to the one-use grant and carries them through the
existing exclusive system-proof transport. The inner session recomputes and
compares them before assessment. The post-export host verifier uses that retained
host proof as its expected input, never hash values chosen only by the output.
Retrieve expected bytes fail-closed from verified committed Git blobs, not merely
mutable workspace paths; missing, foreign or modified material refuses.
Keep historical proof refusal coverage and every existing event/Git/SDK check.
No new GateRequest or GateResult fields or workflow trigger/job changes.
Keep d12_context's source, recipe, Dockerfile and count meanings unchanged.
Do not put gate-only metadata into image inputs to create a circular binding.

### Collector and byte reconciliation

Collect complete package-verification and unowned-path results within explicit
report bounds. A bound exceeded, truncation, duplicate or count mismatch refuses;
do not increase limits until outputs happen to pass. Record binary-to-source
mapping, resolved invoked paths, interpreters/modules, loaded ELF libraries,
actual byte digests and ownership. Reconcile package bytes and supplier exclusion
configuration; inherited missing files are not automatically safe. Generated
files require exact reproducible origin. Preserve dynamic Psycopg 3.3.6/libpq
ABI and native-platform checks. Require the notices/licenses and provenance
appropriate to every observed runtime component and final distribution. Missing
license, provenance, ABI or lifecycle evidence cannot be waived by a disposition.

### Acceptance state transition

1. Validate the canonical event/Git/grant/platform/SDK admission as today.
2. Before an exclusive application-build intent, collect pinned server evidence
   in the existing owned daemon and assess it against the closed catalogue.
   Refuse a known catalogue miss, unknown/undisposed finding or evidence gap
   before consuming the application slot. Ordinary bounded setup is separate.
3. Build the application once. Actual or uncertain starts consume that slot.
   Observe its config ID, complete final inventory, dynamic linkage, packaging,
   notices/provenance, applicability and all finite dispositions. Provisional
   evidence alone never sets the canonical gate to passed.
4. Execute the existing unchanged system scenarios and archive round trip on
   that same image. No second build, fallback, pull-created replacement or skip.
5. After inner scenario and owned-resource cleanup success, write the new v2
   acceptance supplement first, with raw-probe/catalogue/assessor/host-proof
   digests and actual image/scenario/cleanup identities. Then write SystemReport
   and its existing binding: use the existing coordinator_evidence mapping for
   a closed D12 supplement reference (relative filename/schema/SHA-256). The
   supplement contains no SystemReport digest, so the chain is non-circular.
   Keep historical v1 diagnostic generation/validation available for its old
   route, including its false flags; never promote an old record. The new
   acceptance route emits only v2, mutually exclusive with the historical route;
   never send v2 through a v1 writer/validator or emit a false statement that classification was
   never performed. Its explicit per-obligation outcomes replace no evidence:
   actual classification discharges that stop; ADR0091 carries the comparison
   gap as accepted-unresolved; any remaining gap still holds.
6. An inner passed report is provisional. In the existing outer managed sandbox
   command, after archive export, independently validate the exported supplement
   and report/binding against the retained host proof and verified candidate
   code/data. Reject absent, duplicate, unsafe-path, stale, foreign or tampered
   files and recompute all links. Preserve outer cleanup and terminal snapshot
   verification; any export, validation, logging or outer cleanup failure makes
   the command nonzero even if the provisional inner report says passed. No
   retroactive rewriting of that report. Add a narrowly scoped D12-only optional
   post-export verifier hook; generic/unit/integration sandbox behavior stays.
7. Preserve SystemReport, binding and GateResult v1 schemas AND semantics:
   hosted success implies merge_authorized=true. It records logical gate
   eligibility, not permission to perform a Git/GitHub mutation. If a GateResult
   is emitted, its existing report/binding hashes transitively cover the nested
   supplement reference; tools/ci/gate_contract_results.py is the named D12 GateResult consumer and
   must run the same verifier with the
   retained expected host proof before accepting success. Do not create a
   success/false exception or weaken an existing runtime check.
8. The existing artifact-upload step and job result remain separate. Failed
   upload cannot be described as retained qualification. The direct parent's
   postflight downloads/hash-checks the actual archive and repeats the D12
   verifier against exact CI/event/candidate bindings before reporting accepted
   hosted evidence. No main/tag/deployment action follows automatically.

Any failed or ambiguous step leaves the candidate NOT ACCEPTED and the aggregate
red. Never delete diagnostic stops as a substitute for completing assessment.

### Exact additional build and publication authority

One new native linux/amd64 application start; total and per-platform ceilings
4->5, including the four immutable historical starts. CI85 attempt 1 only,
same-repository PR13 synchronize, staging before 57e2023913db899ca5b5c5d72a7662ae00c19833,
main base 24d15650a2d4563d188acb8bbf34a0dabf8f3d65, sole existing main-system
builder. No retry, attempt 2, ARM application build, emulation or sixth start.
Fresh approval, nonce, reservation and pre-append ledger hashes; preserve every
event/Git/SDK/candidate/platform binder and add the spent CI72 pair to the denylist.
Append the new parent-held authority/reservation only after source acceptance,
immediately before the single ordinary staging publication. Refuse remote drift.

Use only the pipeline's existing managed SDK preparation and pinned recipe;
at most one necessary hosted SDK materialization in this campaign, no SDK retry
or changed SDK/dependency pin. No local SDK/application build or image pull is
granted. Scoped integration may use its existing managed dependency-runtime
setup, under its ordinary cleanup/accounting contract, never an app build.

The fifth start can still be spent red if actual final bytes differ from the
prepared catalogue, a scenario fails or cleanup is uncertain. This allocation
does not promise green or authorize a sixth start. If any pre-build obligation
cannot be satisfied, retain reviewed work and ask only for the concrete missing
decision; do not publish another known-red candidate.

## Source scope and verification

New bounded stdlib assessor/catalogue, supplement and post-export verifier
companions; collector, session, evidence, runner, closed system-proof v2 and
D12-only outer-sandbox verifier integration; exact grant rebind only
after approval. Keep modules cohesive and within the existing file-length
profile. Update exact scoped unit and containerized integration owners,
including positive orchestration and adversarial refusal cases. Ordinary scoped
proof uses tools/run_tests.py with --no-coverage, repeating only after a finding
and correction. No complete local suite or local Python coverage. Static,
retention, topology/history/export/privacy and scanner gates remain unchanged.

The direct parent owns source, integration and acceptance. Muse CLI assists use
muse-wonder-full-1.0 high for bounded source/design review. This is the operator's
chosen execution path; no APGR/Claude quota checkpoint is required. Review
limitations remain explicit, and assistance alone is not source acceptance.

## Alternatives, rollback and exclusions

Keep the grant held: safe but no new assembled-image evidence or publication.
A fifth diagnostic build alone necessarily retains a red workflow; a later
corrected green campaign would need separate sixth-build authority. Neither is
selected by this proposal. Grant-only publication, constant-success flags,
blanket risk acceptance and a removed security gate are rejected.

Rollback is a reviewed forward source change. It never resets spent authority.
Keep Trixie, dynamic C Psycopg 3.3.6, all base/SDK/dependency pins, debt/coverage
ceilings, existing failing/negative tests and whole hosted populations. No new
dependency, lockfile, infrastructure, trigger/workflow topology, PR state,
history rewrite, main promotion, tag, deployment, pgvector or D15 work.
