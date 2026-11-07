# REPOMAP-CLOE-CONTEXT1 Exit: Intent ranking and bounded metadata context

Status: **NOT ACCEPTED for whole-candidate qualification**. The introducing
commit records final scoped proof and independent review for one public staging
campaign. Complete hosted populations, coverage and assembled-system evidence
remain pending for that exact candidate.

Authority: the operator reported CI104 passed and requested roadmap continuation.
[ADR 0133](../../docs/adr/2026/11/0133-intent-aware-navigation-and-bounded-context.md)
admits three connected W4 epics. [ADR 0134](../../docs/adr/2026/11/0134-compact-context-milestone-staging-campaign.md)
binds one successor campaign. The [specification](../../docs/specs/cloe-intent-context-v1.md)
and [operations guide](../../docs/ops/compact-context.md) describe the product.

## Delivered scope

- Explicit definition, implementation, tests, docs, messages and general intents
  rank stored metadata deterministically. Equal-tier ambiguity and incomplete
  scans are disclosed. Legacy MCP ordering and direct-evidence policy remain
  unchanged.
- `cloe ops context-pack` and the library assemble compact metadata with exact
  UTF-8 byte accounting, including the final newline. Legal budgets are 4096
  through 65536 bytes, default 16384. Admission preserves a strict seed prefix
  and stored relation endpoints. It reserves diagnostics and worst-case
  freshness before source opens; finalization cannot silently remove inspected
  locations or invent a required-envelope minimum from optional overflow.
- `cloe ops context-select` creates exclusive 0600 root-free selection files.
  Revalidation checks configured graph/repository/backend and policy fields,
  every full publication pin and the complete snapshot vector. Raw database
  metadata is validated before coercion; malformed numeric types, conflicting
  aliases, duplicate vector IDs and malformed unselected rows refuse.
- SQLite uses one owned read snapshot and a pre-execute guard before statement 37.
  PostgreSQL compares publication identity across its statements. Ceilings stay
  at 36/12 SQL statements, 16 logical units, 8 scan units and 5 expanded seeds.
  SQLite reports actual progress callbacks, including zero, with a 250-callback
  per-statement cap at a 1000-operation interval; the VM-step product is an
  estimate. Caller instrumentation cannot raise these ceilings.
- Opt-in structural freshness anchors each explicitly selected root descriptor
  for one request, refuses unsafe traversal/nonregular files and closes owned
  descriptors. Bounds are 16 file attempts, 65536 actual bytes/file, 262144 bytes
  total and 80 span lines. Concurrent growth consumes no over-limit probe.
  A later request may select a replacement root. Default metadata retrieval
  performs no source reads; observations expose no source body.
- Stored relations to admitted nonexpanded seeds are retained without duplicate
  neighbors. Observed output-budget omissions and aggregate relation-limit hits
  are counted; explicit edge-kind sets use normative lexical order.
- The real context CLI routes before unrelated PostgreSQL release helpers.
  Existing legacy command contracts, read-only MCP, body-owner separation,
  dependencies, supplier pins, schema SQL and migrations remain unchanged.

## Source review and verification

Parent review corrected the producer's root reopening, coercible pins, hidden
CLI bypass, post-freshness trimming, synthetic work counters and synthetic
evaluation backends. A historical producer result does not accept later source. Independent Claude
review then identified canonical SQLite open/error classification and confirmed
empty-envelope, historical-vector and ambiguous-line boundaries. These were
corrected under the ADR before final proof; the earlier primary review prose is
not relied upon where it cited nonexistent symbols or incorrect constants.
The corrected pre-freeze checkpoint passed 245 exact scoped unit cases and 44
containerized integration cases. Later structural typing reconciliation is
covered by final frozen proof; its exact selectors and counts are recorded in
the introducing commit's Verification block and exact-commit report.

New product modules enter the retained profile with clean findings. Existing
ownership, inventory cohorts, selected-module history and numerical debt/tool
sections are preserved through one forward clean addition. Static enforcement,
changed-source compilation, file lengths, public export, topology, suppression,
privacy and both Git diff checks are required before publication.

The functional evaluator uses actual bounded Git grep and real SQLite/PostgreSQL
capabilities. Native evidence is a controlled fixture-manifest bridge, not full
portable-publication content correspondence. Native grading is binding/path
only; it claims no canonical identity or typed relationships. Graph grading
requires the highest-relevance canonical key plus exact binding/path identity.
Unsupported capability states are explicit and never counted as fabricated
answers or pooled wins.

The parent selects one final 420-observation functional collection: 20 calibration
tasks, 7 arms and 3 repetitions, attempt `w4-context-functional-attempt-7`. Source
and input bytes are admitted before queries. Terminal journal hashes and its
six exact members are retained through bounded developer stdout transport before
disposable sandbox cleanup, without enabling project coverage or changing the
canonical runner. The retained second functional attempt exposed a supported-population accounting
error, corrected with missing/duplicate/unavailable negative tests before the
passing third attempt. The fourth collection passed functional checks while two unrelated integration
fixtures failed setup. The fifth collection passed all52 scoped integration cases for that source.
The sixth passed functional checks; one integration fixture still used an open
kind scope that intentionally reported partial. The seventh binds its closed-kind
precondition and the final relation-accounting correction, preserving earlier
journals.
Earlier synthetic collections remain unqualified history;
ephemeral journals from already removed containers are not claimed recovered.
All retained W2/W3 evidence and named comparison limitations remain unchanged.

## Hosted CI and deferred work

- Capacity: AVAILABLE. CI104 executed and passed for predecessor staging
  `7babd887cb6b46c2791a22d57baddcdc24914463`; it does not qualify W4 source.
- Remote action at source freeze: none. One ordinary staging push is authorized
  for automatic `repomap-release-qualification` CI105 attempt1 through existing
  draft PR23. Recheck current refs and ordinal immediately before pushing.
- Build custody: 21 native AMD starts remain spent. One fresh 22nd reservation
  binds this changed runtime context; no automatic retry or local application/
  SDK build is allocated. The unchanged hosted SDK has a one-materialization cap.
- Pending hosted gates: complete unit, staging smoke/M/A and integration,
  static/security and native assembled-system qualification. Hard coverage floors
  and populations remain unchanged; desired margins are 87/82.
- Complete local Python unit, integration, smoke, staging, system and combined
  populations and Python project coverage remain intentionally unselected.
  Scoped tests use `--no-coverage`; the canonical fixed Go metrics/race/lint
  prerequisites remain visible and separate.
- Context and mixed-v1 held-out tasks, scientific criteria acceptance, MCP
  additions, PostgreSQL bounded expansion parity, configured-root shortcuts,
  source excerpts, vector/fusion work, package/repository rename, main promotion,
  releases/tags and live deployment remain deferred.
