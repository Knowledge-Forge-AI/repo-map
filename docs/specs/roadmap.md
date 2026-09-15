# RepoMap Roadmap

## Cloud-First And Multi-Source Migration Program

[ADR 0057](../adr/2026/08/0057-cloud-first-multi-source-architecture-reconciliation.md)
establishes cloud-first commercial delivery and immediate multi-source graph
composition while preserving the current local PostgreSQL implementation as
the as-built/reference, qualification, contributor/power-user, and possible
private/self-hosted distribution. Acceptance of that ADR and this ordering is
not authority to implement any successor.

The ordered strangler program is (prefix abbreviations: `MS` = Multi-Source,
`STR` = Strangler Seam, `CTRL` = Control Plane, `FED` = Federation):

1. `CLOUD-MULTISOURCE0` — architecture and documentation reconciliation.
2. `MS-ID1` — additive source definition, binding, immutable snapshot, and
   candidate identity with one-binding compatibility. The local implementation
   candidate exists. `MS-ID1-FIX1` restores the full predecessor-accepted
   legacy source-field domain, corrects unsupported worker classification, and
   removes arbitrary-binding readback attribution in a local correction
   candidate. `MS-ID1-FIX2` removes the remaining first-binding graph
   configuration projection, reserves disjoint compatibility extractor-profile
   identities, and documents the versioned legacy/strict selection distinction.
   Both permitted local PostgreSQL diagnostic executions were historically
   refused before collection by the repository harness; that checkpoint remains
   truthful and TEST-ISO2 does not authorize another local attempt. The
   candidate may be retained, while complete integration qualification and
   promotion evidence remain pending for the eventual logically approved
   Staging Gate because hosted-CI state is `EXHAUSTED`.
3. `MS-FLAKE2` — a local implementation candidate now carries a complete
   explicit binding inventory through immutable content snapshots, bounded
   static Nix resolution, the current Python semantic path, one staged
   publication, and source-qualified canonical file readback. Legacy graph
   syntax remains one-source compatible. Focused unit/static evidence supports
   retaining the candidate; its added PostgreSQL integration owners remain
   intentionally unexecuted locally. The hosted Staging Gate is still required
   before qualification or promotion, and this checkpoint does not authorize
   `STR-SEAM3`. `MS-FLAKE2-FIX1` corrects its local semantic/configuration and
   snapshot-vector fences, immutable whole-inventory capture, explicit static
   Nix export proof, mandatory provenance, non-conflated non-exact relations,
   conservative mixed-privacy redaction, and source-qualified CLI/MCP readback.
   Focused local evidence may support the correction commit only; hosted
   Staging Gate, main-source-policy, and Main System Gate evidence remain
   pending, so `STR-SEAM3` remains unauthorized.
4. `STR-SEAM3` — portable filesystem/object-storage snapshot, existing-worker
   extension, extraction receipt, publication bundle, and publisher validation contracts.
   The local implementation candidate establishes the deterministic seam, codecs,
   store neutrality, and non-production conformance adapters. It is inactive in
   production by itself; ADR 0061 now owns its validated production consumption.
5. `STR-WORK4` — a local implementation candidate now provides one supervised,
   database-independent Python semantic worker over sealed snapshot artifacts. Its
   STR-WORK4-FIX1 correction compares actual managed-subprocess bundle records with
   incumbent seven-family pre-publication records for public one-source and multi-source
   Nix fixtures, closes stage-identity selection and selected replay/conflict, runtime-
   authority, and cleanup-precedence gaps, and replaces placeholder pipeline claims with
   executable owners. STR-WORK4-FIX2 completes the local typed-terminal,
   receipt-unavailable, deterministic cancellation, process-tree/cleanup, behavioral
   runtime-authority, harness isolation, replay/conflict, versioned stage-row, and
   truthful pipeline-owner matrices. ADR 0061 now selects the worker for supported
   direct/coordinator forced-full refresh. Complete hosted integration, the Staging
   Gate, main-source-policy, and Main System Gate evidence remain pending.
6. `STR-PUB5` — local implementation selects one parent-sealed portable-worker
   route for direct and coordinator forced-full refresh and consumes its validated
   seven-family bundle in the existing sole PostgreSQL publisher. It owns physical
   stage identity, complete final-receipt binding, reconciliation retention, and
   executable hosted integration/system owners. `PYLEN-SCALE14-FIX1` is complete:
   terminal reconciliation coordination was extracted without changing the existing
   supervisor import or behavior boundary, and the repository-wide file-length gate
   has zero failures. Hosted PR Fast, Staging Gate, main-source-policy, and Main
   System Gate evidence remain pending. The accumulated branch must be promoted to
   `main` before `CLOUD-ALPHA6` or later product development starts.
7. `CLOUD-ALPHA6` — the smallest useful hosted single-tenant or
   operator-tenant alpha.
8. `CTRL-BAKEOFF7` — production-shaped comparison of retained Python, Go, and
   managed-job control-plane shapes under identical semantic contracts.
9. `CLOUD-HARDEN8` — multi-tenant authorization, quotas, billing,
   retention/deletion, placement, and enterprise hardening.
10. `FED-LATER9` — federation only after single-graph multi-source value and
    independent-authority contracts are accepted.

Local deterministic qualification owns semantic equivalence, identity,
ambiguity, replay, failure, algorithmic cost, and regression evidence.
Production selection requires cloud-shaped Linux-container, managed-network
PostgreSQL, object-storage, concurrency, recovery, latency, resource, and cost
evidence. Laptop measurements do not select the hosted control plane.

This program precedes new late local-only stabilization that would deepen the
single-root or physical database coupling. Existing accepted local maintenance
and qualification work remains valid and separately authorized.

## Current Architecture Normalization Program

The accepted ARCH program normalizes the mature implementation before SCALE
resumes. The governing decision and live phase sequence are recorded in
`docs/adr/2026/07/0041-as-built-architecture-normalization.md` and
`docs/status/2026/07/16/00569-arch-epic-log.md`.

- ARCH0 documented and accepted the as-built baseline and target architecture.
- ARCH1A completed run, publication, generation, and result authority
  vocabulary without changing writers or schema.
- ARCH1B completed resolved graph/control/maintenance topology, exact private
  ownership projection, and the relocation-stable configured repository
  identity contract without changing schema or rows.
- ARCH1C completed unified graph-local publication exclusion, independent
  graph-claim ordering, stale-owner rejection, and preserved receipt/recovery
  behavior without schema change.
- ARCH1D published the allowed package dependency matrix, added static cycle
  and production/test-support guards, and removed the storage telemetry SCC
  while preserving all telemetry facades.
- ARCH1E removed the graph discovery/extractor-routing SCC by extracting the
  neutral `FileInfo` record while preserving discovery imports and behavior.
- ARCH1F removed the coordinator protocol/launch/refresh-adapter SCC while
  preserving public protocol, launch, refresh, and patch-target behavior.
- ARCH1G removed the CLI/server SCC by placing canonical filter validation
  below both presentation adapters.
- ARCH1H removed the operations/runtime SCC by placing configuration loading
  below runtime while retaining the public operations status facade.
- ARCH1I removed the final extractor-configuration SCC while preserving the
  generic registry facade and format behavior.
- ARCH1J moved the synthetic-worker fixture target, support path, mode
  allowlist, and coordinator factory out of production, resolved
  `ARCH0-LAYER-001`, and completed ARCH1.
- ARCH2A defined one closed typed descriptor for every retained staging family,
  made technical and semantic ordinals explicit, and proved exact parity with
  the existing DDL and runtime mappings without changing behavior.
- ARCH2B made descriptors authoritative for family order, row adaptation,
  COPY, checksums, duplicate validation, validation and merge dispatch,
  cleanup, publication completeness, and privacy, resolving
  `ARCH0-NORM-001` and `ARCH0-STORAGE-001` without changing publication.
- ARCH2C added public-safe, bounded staging family and boundary observability,
  proved four-query and 96-event overhead bounds plus exact result/receipt
  parity, resolved `ARCH0-PUB-001` for this phase, and completed ARCH2.
- ARCH3A froze legacy node-list semantics, added a bounded source-backed
  compatibility adapter, established canonical-node and first-class
  file/source replacement contracts, and proved repeated-import plus connector
  parity without stopping legacy writers.
- ARCH3B froze legacy edge-list and embedded-evidence semantics, added a
  bounded source-backed adapter, and proved canonical edge/explanation,
  repeated-import, missing-path error, and connector parity without stopping
  legacy writers.
- ARCH3C froze node/file neighborhood, raw entrypoint, and storage host-mutator
  semantics; added bounded source-backed adapters; and proved legacy-shape,
  canonical-semantic, error, and connector parity.
- ARCH3D migrated legacy CLI, MCP/ops status, connector comparison, and
  legacy/canonical summary compatibility reads to bounded source-backed
  collectors while confirming canonical MCP and baseline/drift authority.
- ARCH3E closed the row-wise caller census with typed migration contracts and
  an AST-backed inventory for every production and repository-tool binding.
- ARCH4A migrated complete row-wise callers to staged receipt-bearing
  publication.
- ARCH4B converted partial acquisition to explicit non-publishing input,
  retired the canonical-only public load and row-wise SCALE7 baseline, and
  reduced the executable receiptless-binding census to zero.
- ARCH4C removed the uncalled row-wise mutation primitives and all legacy
  node/edge/evidence construction, staging, validation, merge, cleanup, and
  final writes while retaining rollback tables and migrated readers.
- ARCH4D accepted exact normalized direct/coordinator parity, unchanged
  failure/cancellation/commit-unknown behavior, retained-table code rollback,
  migrated-reader compatibility, and the deterministic seven-family resource
  shape. ARCH4 is complete.
- ARCH5A1 established ordered checksummed graph migration discovery, a
  product-owned applied-version ledger for fresh managed databases,
  transactional DDL/ledger updates, exact-current replay, and drift refusal.
- ARCH5A1R1 corrected the local fresh-from-source lifecycle path to consume the
  same ledger-bearing transaction instead of concatenating historical SQL.
- ARCH5A2 now provides exact catalog recognition, verified backup-first
  adoption, ledger-only bootstrap, and restore evidence for supported
  pre-ledger graph databases.
- ARCH5A3 now provides equivalent ordered, checksummed control-database
  migration authority, exact-current readiness, and verified backup-first
  adoption for supported pre-ledger control databases.
- ARCH5A4A establishes the coordinator half of executable maintenance
  exclusion: shared worker lifetime ownership, fail-closed submission,
  coalescing and claim admission, exclusive drain, failure release, and
  schema-upgrading/not-ready projection.
- ARCH5A4B completes cross-plane maintenance ownership: staged graph
  publication/import holds graph-local shared ownership, configured direct
  work also holds control ownership, and graph/control upgrades own control
  then affected graph-exclusive locks before backup through cleanup.
- ARCH5B adds deterministic graph/control provisioning recovery: targets
  created by the current invocation are provisional until exact schema
  readiness, failed targets are removed for clean retry, and pre-existing
  unrecognized state is never adopted.
- ARCH5C1 establishes backup-first exact-prefix forward graph migration and
  additively introduces nullable stable repository identity while retaining
  private mutable source location and existing writer behavior.
- ARCH5C2A provides backup-first configured identity population and
  deterministic path-keyed duplicate reconciliation, retaining historical
  families, merging replacement identities, and leaving no direct family
  ownership outside the survivor.
- ARCH5C2B cuts configured staged writers over to stable identity, updates the
  mutable private root without changing repository ID, and preserves explicit
  historical root-keyed publication and row-wise SQL compatibility.
- ARCH5C3 accepts migration-only baseline/drift invariance, configured staged
  relocation, historical logical restore, and forward reconstruction to the
  same stable post-refresh baseline. ARCH5C is complete.
- ARCH5D removes runtime legacy staging and final schema through one guarded,
  foreign-key-safe forward migration after backup/restore/reapply rehearsal.
  Historical migrations remain intact and current readiness now requires only
  the retained file/raw/canonical schema.
- ARCH5E removes the expired compatibility API/facade boundary, including
  aliases, mode flags, legacy result schemas, connector operations, and
  source-backed migration adapters. Canonical graph readback is the sole
  graph API; file/source readback remains current. ARCH5 is complete.
- ARCH6A corrects the proven CSS descendant-matching amplification by building
  one element lookup per matched HTML document. Deterministic adversarial
  traversal counts grow from 51 to 99 to 195 for 16, 32, and 64 descendants.
- ARCH6B corrects canonical edge metadata accumulation with a retained
  equality-key index and exact first-seen ordering. Adversarial keyed work grows
  from 192 to 384 to 768 for 16, 32, and 64 edge proposals. `ARCH0-ALG-001` is
  resolved.
- ARCH6C measures pipeline lifetime on 32, 512, and 4,200 public-safe
  observations. The full fixture retains five spools and replays all 21,000
  spooled rows once for checksums before COPY.
- ARCH6D fuses the unchanged checksum-v2 accumulator with private spool
  creation. The full fixture preserves every count, byte total, and digest while
  reducing checksum-only replay from five passes and 21,000 rows to zero. COPY,
  publication, receipts, and rollback remain unchanged. The next ARCH6 slice
  must measure another demonstrated pipeline cost before changing it.
- ARCH6E measures spool transfer lifetime. The full fixture retains all five
  spools and 8,131,599 bytes before every family COPY and after the loop, while
  exactly five replay passes and 21,000 rows are attributable to COPY. ARCH6F
  is next and closes each spool after its successful final consumer.
- ARCH6F releases each private spool after successful COPY. Full-fixture live
  spool count before successive family boundaries falls to 5, 4, 3, 2, 2, 1,
  and 0; final live spool bytes are zero. COPY rows, digests, failure cleanup,
  receipts, rollback, and publication remain exact. ARCH6G performs the bounded
  observation-pass and pre-COPY lifetime closeout measurement.
- ARCH6G attributes exactly one file-projection, Go-context-filter,
  canonical-dispatch, and raw-projection pass, each with `N` visits and no
  unattributed traversal. Pre-COPY spools are the required pending COPY sources
  and release at their final consumer. The four fixed-count linear passes are
  accepted bounded architecture, `ARCH0-PERF-001` is resolved, and ARCH6 is
  complete. ARCH7A bounded public read contracts are next.
- ARCH7A1 bounds direct CLI and MCP canonical node/edge lists with one
  schema-version 1 envelope, stable existing ordering, 1-through-200 limits,
  lookahead truncation, offset continuation, and table/JSON item parity.
  Bounded legacy-array aliases preserve the compatibility interval.
- ARCH7A2 bounds neighborhood node/edge collections and explanation evidence
  with independent versioned windows, stable continuation, collection-specific
  truncation diagnostics, and table/JSON/MCP parity. Bounded legacy-object
  aliases preserve the compatibility interval. `ARCH0-API-001` is resolved,
  ARCH7A is complete, and ARCH7B owns HTTP privacy and readiness normalization.
- ARCH7B replaces identifier-bearing HTTP output with schema-version 1
  path-free projections for process liveness, configuration health, storage
  readiness, required-schema readiness, and aggregate status. Graph probes cap
  at 200, serialized responses cap at 8 KiB, and the generated server
  healthcheck uses readiness. `ARCH0-PRIV-002` is resolved; ARCH7C owns exact
  lifecycle ownership and maintenance exclusion.
- ARCH7C1 applies the resolved exact graph/control allowlist to local lifecycle
  and coordinator maintenance admission. Unrelated safe names fail before
  external access, and database DDL uses the resolved non-owned maintenance
  connection. Exact destructive ownership is complete; ARCH7C2 owns stable
  exclusion from recovery-point capture through destruction.
- ARCH7C2 acquires cross-plane maintenance before a confirmed backup-first drop
  captures its recovery point and holds it through backup verification and
  destruction. Graph drops lock control plus the exact graph; control drops
  lock control plus every configured graph. Failure release, operation
  diagnostics, confirmation, and non-locking dry-run behavior remain intact.
  ARCH7D owns coordinated streaming backup and recovery.
- ARCH7D1 replaces whole-dump client buffering with file-stream subprocess IO,
  bounded-chunk digest accounting, explicit private modes, hidden
  same-filesystem staging, and atomic complete-directory publication. Orphaned
  hidden staging sets are invisible to enumeration and refused for restore.
  Existing manifest version 1 and published single-target contracts remain
  compatible.
- ARCH7D2 makes `dump-all` enumerate every resolved graph/control database in
  deterministic order and holds control plus all graphs through streaming,
  checksumming, and atomic complete-set publication. Stable coordinated sets
  add a bounded recovery-point assertion to manifest version 1. Mid-set failure
  publishes nothing; dry-run remains non-locking.
- ARCH7D3 adds complete-set restore for only an exact current, stable,
  checksum-complete coordinated manifest and empty target topology. It verifies
  all artifacts before runtime access, preflights every target before mutation,
  restores sorted graphs followed by control, and removes every invocation-
  created database in reverse order on failure.
- ARCH7E separates read/status, refresh/publication, coordinator-control, and
  lifecycle-administration database authority. It generates distinct private
  non-administrative secrets, reapplies deterministic grants after graph/control
  init, upgrade, and restore, projects HTTP/MCP onto read/status, and prevents
  the foreground coordinator from loading lifecycle-administrator credentials.
  ARCH7F owns installed release resources and pinned runtime clients.
- ARCH7F installs the Python distribution and both migration catalogs in a
  digest-pinned multi-architecture image, pins Psycopg and its libpq closure,
  uses server-matched fixed-path PostgreSQL clients, and builds the matching
  package-local Linux arm64/amd64 Go helper only in the builder stage.
- ARCH7G composes PostgreSQL, one-shot initialization/upgrade, HTTP
  health/status, read-only MCP integration, the foreground coordinator, and
  one-shot lifecycle administration from the immutable artifact. It accepts
  deterministic UTF-8/C provisioning, exact-current startup gates, per-unit
  secrets and mounts, loopback-only HTTP, packaged query/dump/restore clients,
  and restart recovery without ambient application toolchains. ARCH8 owns the
  integrated public-safe repository ladder.
- SCALE remains paused until ARCH-CLOSE accepts the normalization gates.

## Planned RECON Investigation Program

[ADR 0056](../adr/2026/08/0056-reconciled-investigation-and-program-direction.md)
accepts a product direction toward deterministic, publication-pinned,
evidence-cited cross-artifact investigation. ADR 0057 amends its order: the
cloud-first multi-source program above now owns the immediate identity,
snapshot, worker, bundle, publisher, and cloud seams. This investigation
program does not authorize implementation, graph refresh, benchmarking, or a
successor phase.

The shared first step is:

1. `RECON0`--authority/resulting-state mapping; identity and `PublicationRef`;
   snapshot, evidence-security, read-pinning, fixture, corpus, comparator, and
   scorer contracts. Execution requires separate operator authorization.

ADR 0056's advisory `HYB-*` order is superseded by the ordered program above.
Its retained invariants — one semantic authority, one
publisher, delta-only extension of the existing worker contract, source-blind
MCP, and a measured rather than preferred Go hypothesis — govern that new
sequence.

The advisory investigation branch is:

1. `REPOMAP-EVID1`--reference-first evidence and capsule foundation.
2. `REPOMAP-PATH2`--generation-pinned typed investigation engine.
3. `REPOMAP-CAP3`--accepted first slice of `sc1:` subject-capability
   intelligence.
4. `REPOMAP-DELTA4`--coordinator-owned overlay and conservative test view.
5. `REPOMAP-PREC5`--conditional precision experiments after measured gaps.
6. `REPOMAP-FED6`--conditional federation after single-graph value and
   identity/privacy contracts are accepted.

Every investigation item after `RECON0` returns as an independently
dispositionable packet and depends on the applicable accepted identity and
publication seams above. It cannot create a competing read product or displace
the accepted Python semantic owner. Standalone `COMP0`, a preferred Go
destination, default MCP source-byte access, broad superiority claims,
private-first benchmarks, and implicit successor authorization remain
rejected.

## Phase 0: Project Skeleton

- Establish repository structure.
- Add Apache-2.0 license.
- Add public architecture, storage, extractor, and roadmap specs.
- Define initial coding and testing expectations.

## Phase 1: Core Graph Schema

- Define raw observation JSONL schema.
- Define Postgres schema and migrations.
- Implement repository discovery.
- Implement profile loading.
- Implement normalization from raw observations to graph tables.
- Add CLI commands for database setup and basic inspection.

## Phase 2: File and Entry-Point Graph

- Detect files, languages, executable scripts, and roles.
- Create File, Script, EntryPoint, and Repository nodes.
- Add project profile support for user-facing command directories and internal
  implementation directories.
- Add first CLI queries: `entrypoints`, `files`, and `explain`.

## Phase 3: Shell Extractor

- Parse shell-family scripts.
- Extract functions, sourced files, command invocations, environment contracts,
  redirections, and obvious file operations.
- Mark dynamic shell facts with appropriate confidence.
- Add host-mutator detection.

## Phase 4: Nix Extractor

- Extract imports, flake outputs, packages, apps, checks, dev shells, overlays,
  and script references.
- Add optional safe evaluation mode.
- Connect Nix outputs to executable scripts and tools.

## Phase 5: Python and Ruby Extractors

- Add Python AST-based extraction.
- Add conservative Ruby extraction.
- Connect shell wrappers to Python and Ruby implementation files where possible.

## Phase 6: Query Layer

- Add CLI queries for common impact-analysis work:
  - callers;
  - tests-for;
  - host-mutators;
  - paths;
  - env-contract;
  - blast-radius.

## Phase 7: Reports and Adapters

- Add human-readable reports.
- Add optional MCP adapter after the CLI and database model are useful.
- Consider graph export formats for visualization or dedicated graph tools.

## Deferred Ideas

- Web UI.
- Embedding or vector search.
- Dedicated graph database backend.
- Multi-user server mode.
- Language-server integration.
### STR-WORK4-FIX3 and PYLEN-SCALE14-FIX1

STR-WORK4-FIX3 closes the portable worker's observed-evidence, typed-receipt,
real-operation guard, parent-attempt cleanup, evidence-classification, and
explicit current stage-row creation gaps. `STR-PUB5` may be separately invoked
only after this worker correction satisfies its focused criteria; it remains
the owner of PostgreSQL bundle ingestion and physical stage substitution.

`PYLEN-SCALE14-FIX1` is complete as a separate branch-hygiene phase. It reduced
`tools/scale14_actual_refresh_supervisor.py` from 1,003 to 803 physical lines by
extracting terminal reconciliation coordination into a cohesive 316-line private
helper, while retaining the supervisor as canonical owner of its public imports and
mutable state. The repository-wide tracked-Python file-length gate now has zero
failures. The durable result is
[status 00833](../status/2026/09/02/00833-pylen-scale14-fix1-refactor-actual-refresh-supervisor-file-length-exit.md).
Hosted PR Fast, Staging Gate, main-source-policy, and Main System Gate evidence
remain pending; this branch must enter the promotion pipeline before
`CLOUD-ALPHA6` or any later product architecture phase begins.
