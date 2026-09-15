# ADR 0059: Portable Snapshot, Extraction Receipt, And Publication Bundle Contracts

## Status

Accepted and implemented as the portable contract seam. ADR 0060 owns the
database-independent worker; ADR 0061 selects validated bundle consumption for the
STR-PUB5 local production route. Deployment and promotion remain pending.

## Context

RepoMap is cloud-first with a deterministic, deployment-neutral semantic engine.
ADR 0057 and ADR 0058 established the multi-source identity foundation and modular
flake composition. Prior to STR-SEAM3, the extraction worker required direct database
access to stage raw observations and canonical nodes/edges into PostgreSQL tables.
To enable database-independent worker execution across isolated compute environments,
a clean contract seam is required that separates:
1. immutable sealed source snapshot artifacts;
2. worker extraction and receipt generation;
3. deterministic publication bundle representation; and
4. publisher-side byte and semantic authority validation.

## Decision

### 1. Artifact Reference And Portable Snapshot Manifest

Define `ArtifactReference` and `PortableSnapshotManifest` (`snapmanifest1:`):
- Separates semantic content identity (`sha256:` digest, byte length, media type,
  record format, privacy classification) from physical storage locators.
- Physical locators (`kind`, `value`, `store_version`) are store-relative, POSIX-only,
  contain no credentials, host paths, or URIs, and are excluded from semantic identity
  and public projections.
- `PortableSnapshotManifest` deterministically binds graph identity, the ordered
  binding-to-snapshot vector, semantic generations (`sg1:`, `cg1:`, `eg1:`, `kg1:`),
  engine identities (extractor capability, resolver, canonicalizer, semantic contract,
  quality rules), artifact entries (relative path, digest, size, executable mode),
  effective privacy, and count/byte bounds.
- Traversal, absolute paths, duplicates, symlinks, hardlinks, and special files fail closed.

### 2. Transport Neutrality: Filesystem And Object Store Parity

Implement store neutrality via the `ArtifactStore` protocol:
- `FileSystemArtifactStore`: private command-owned roots (0700/0600 modes), atomic
  write-to-temporary followed by digest/length verification and atomic rename with directory
  sync, no symlink following, link count check (1), and exact temporary cleanup.
- `MemoryArtifactStore`: deterministic in-memory fake object store with exact monotonic
  immutable version modeling (`object-v1`, `object-v2` upon deletion and re-put).
- Identical logical bytes produce identical semantic mappings, digests, and manifest
  identities across both backends.

### 3. Worker Protocol Extension

Extend the ASYNC1 protocol via capability negotiation:
- Workers advertise capability `portable_snapshot_v1` in `worker_hello`.
- Coordinator may supply `portable_snapshot` envelope in `job_start` binding the
  `ArtifactReference` to the snapshot manifest.
- Terminal messages (`result`, `error`) carry the `portable_snapshot` result extension
  binding the `ExtractionReceipt` reference and optional `PublicationBundle` reference.
- Current worker terminals add exact `receipt_status` and `receipt_diagnostic`
  fields. A non-completed terminal may carry `receipt: null` only with
  `receipt_status: unavailable` and one bounded closed receipt-write diagnostic;
  the primary typed outcome remains unchanged. Legacy four-field result extensions
  remain decodable and still require a receipt reference.
- Legacy workers and requests without `portable_snapshot` execute with unchanged semantics.
- Silent version downgrade is forbidden; unsupported versions fail closed with `unsupported_extension`.

### 4. Deterministic Extraction Receipt

Define `ExtractionReceipt` (`receipt1:`):
- Binds request/job/attempt/graph identity, worker capability, contract version,
  generations, manifest identity, snapshot vector, engine identities, terminal outcome,
  family counts, diagnostic category/summary, and attestation class.
- Retains exact internal error categories (`source_unavailable`, `source_changed`,
  `source_invalid`, `source_capture`, `artifact_missing`, `artifact_stale`,
  `artifact_corrupt`, `cancelled`, `unsupported_contract`, `unsupported_capability`,
  `contract_validation`) while mapping to bounded public-safe error classes.
- Producer receipts are untrusted evidence and confer no publication authority.

### 5. Deterministic Publication Bundle

Define `PublicationBundle` (`bundle1:`):
- Represents all seven staging families (`files`, `raw_observations`, `canonical_nodes`,
  `canonical_edges`, `canonical_evidence`, `canonical_node_evidence`, `canonical_edge_evidence`)
  without requiring database connections.
- Canonical JSONL framing with header, deterministic per-family sorted record frames,
  and trailer with per-family summaries (record count, byte length, content digest).
- Strict line bounds (`MAX_BUNDLE_LINE_BYTES`), bundle size limits (`MAX_BUNDLE_BYTES`),
  and record bounds (`MAX_BUNDLE_RECORDS`).
- Current portable-worker bundles declare header contract
  `row_stage_contract: stage-unassigned-v1`; every emitted family row then carries
  exactly the fixed bundle-local, non-authoritative `stage-unassigned` value.
  A header without `row_stage_contract` selects the explicit
  `legacy-absent-v1` decoder, where every row must omit `stage_id`. Mixed shapes
  and every physical stage value are rejected. STR-PUB5 must replace the
  placeholder with its publisher-generated stage identity before COPY or staged
  ingestion.

### 6. Publisher-Side Validation Contract

Implement `PublisherBundleValidator`:
- Byte integrity layer: verifies store locator resolution, byte length, digest recomputation,
  canonical framing, and complete 7-family inventory.
- Semantic authority layer: enforces exact identity agreement (request, job, attempt,
  graph, candidate, manifest, generations, snapshot vector), accepted capability and contract
  versions, single mutating owner, privacy consistency, and intra-bundle referential integrity.
- Rejects semantically invalid but hash-consistent bundles.
- Separately records byte-valid failed/cancelled terminal receipts so the same
  job/attempt cannot later be reinterpreted as completed. Identical completed
  validation remains idempotent; changed manifest, snapshot, capability,
  semantic identity, receipt, or bundle is conflicting attempt reuse.
- Does not mutate graph tables in STR-SEAM3.

### 7. Sealed Snapshot Reuse

- Sealed manifests allow downstream execution to read exclusively from the authorized
  artifact store without touching or rereading original source repositories.
- Coordinator generation fencing verifies the bound manifest identity.

## Consequences

- The portable contract seam is established with complete test coverage and storage parity.
- Existing staged PostgreSQL publication remains the sole production authority.
- STR-WORK4 separately owns completion of the standalone database-independent worker
  without changing production route selection.
- ADR 0061 owns STR-PUB5 bundle ingestion and route selection.
## STR-WORK4-FIX3 Contract Corrections

Current `PublicationBundle.create` callers must select
`row_stage_contract="stage-unassigned-v1"` explicitly. Only the version-1
decoder may interpret an absent header as the legacy `legacy-absent-v1` shape;
current and legacy row shapes cannot be mixed. Physical PostgreSQL stage
allocation remains future `STR-PUB5` publisher authority.

Receipt-write diagnostics derive from the artifact store's closed error code,
not exception text. Non-completed terminals may report an absent receipt with
bounded `store_unavailable`, `permission_denied`, `receipt_bounds`, or
`write_failed` evidence. A completed terminal still requires a stored receipt.
