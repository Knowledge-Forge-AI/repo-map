# Changelog

All notable changes to Common Lore Index will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Release Policy & Versioning

- `0.0.x` releases are public source previews.
- All versions `< 0.1.0` are intentionally pre-publication with respect to package managers (no distribution to PyPI, npm, Go module proxies, or container registries).
- `0.1.0` or later will be the earliest package-manager publication line.
- `main` represents released public versions.
- Public `staging` is the prospective next-version branch; release promotions to `main` are squash merges where each resulting commit represents one version release.
- Exception for v0.0.3 and v0.0.4: `main` is fast-forwarded to the exact qualified staging commit so that it keeps the history required by the author-correction and forward lineage proofs ([ADR 0086](docs/adr/2026/10/0086-preview-003-staging-ancestry.md), [ADR 0195](docs/adr/2026/11/0195-common-lore-index-preview004-identity.md)). Later releases return to squash merges unless a separate lineage-safe exception is approved.

## [Unreleased]

## [0.0.4] — First Common Lore Index source preview

- Complete current repository, package, contributor and operator branding as
  Common Lore Index (CLOE); the public repository is
  [common-lore-index](https://github.com/Knowledge-Forge-AI/common-lore-index).
- Coordinate version 0.0.4 across source, packaging, root editable lock metadata
  and export checks. Keep `cloe`/`common-lore-index` primary commands and finite
  legacy launch/migration compatibility through v0.1.x.
- Advertise the canonical MCP server identity while preserving wire tool names,
  schemas, read-only behavior and existing storage/service ownership.
- Carry forward the accumulated retrieval/navigation and resource-governance
  milestone work. Full remaining-roadmap and platform/image/scientific admission
  stay separately bounded; see the roadmap for actual workstream acceptance.
- Refresh the single verified Debian Trixie linux-libc-dev builder artifact from
  6.12.116-1 to 6.12.117-1. Preserve exact manifest/hash refusal and dynamic linking.
- Backfill annotated tags and GitHub prerelease entries for the three existing
  [RepoMap source previews](docs/releases/repomap-previews.md).

The [v0.0.4 notes](docs/preview-v0.0.4.md) describe this version's scope.
The annotated tag and GitHub source prerelease identify its published commit.
On staging, this entry describes the candidate until exact hosted qualification
and the authorized ancestry-preserving promotion complete.

## [0.0.3] - 2026-10-29

Final RepoMap public source preview at
`5ad00d162ad8a04430874275246a53227578c533`, promoted through PR13 after
[CI87 attempt1](https://github.com/Knowledge-Forge-AI/common-lore-index/actions/runs/40779161422).
All nine jobs and retained same-attempt staging/system contracts passed. Unit
coverage 87.9763%/87.6070% and measured integration 90.1658%/82.3417% cleared hard
85/85 and 80/80 floors and the requested two-point margins. Core qualification
does not admit optional pgvector, other platforms or live deployment.

This final closeout follows the earlier interim 2026-10-22 promotion recorded in
the [historical note](docs/preview-v0.0.3.md). The exact final commit, source tree
and backfilled tag/release are reconciled in the
[historical release index](docs/releases/repomap-previews.md).

### Changed
- Restore driver-free SQLite startup while preserving explicit PostgreSQL custody.
- Correct steward author metadata on public main and staging with authenticated proof.
- Update contact/export metadata and extension-restore/packaging checks.
- Qualify diagnostic native AMD/system execution and retain informational
  handling of inherited Debian issues, without weakening project guards.

## [0.0.2] - 2026-10-08

### Added
- Consolidated single release qualification workflow model (`repomap-release-qualification.yml`) with closed CI topology verification.
- Schema v2 for retained Python ratchet scope transitions with cryptographically sealed provenance.
- Persistent typed failure summaries across coordinator reconciliation and crash handling.

### Changed
- Promoted public development line to version 0.0.2.
- Hardened CI topology contracts to prevent split-brain workflows and disallow workflow dispatch or path filtering.

## [0.0.1] - 2026-09-15

Initial public source preview of RepoMap.

### Added
- **Deterministic Polyglot Extractors**:
  - Python: AST parsing, module imports, function/class declarations, call sites, and type annotations.
  - Go: package definitions, AST models, and cross-package symbol relations.
  - Nix: static expression extraction, derivations, and package attributes.
  - Shell & PowerShell: script structures, command invocations, sourced files, entry points, and host-mutating operations.
  - Documentation & Configuration: Markdown headers and document graphs, HTML, XML, CSS selectors, OpenAPI/Swagger specifications, and Terraform/HCL resources.
- **Canonical Graph Model**:
  - Pure canonicalization layer normalizing raw observations into `canonical_nodes`, `canonical_edges`, and `canonical_evidence`.
  - Deterministic node keys, symbol resolution, and typed edge semantics.
  - Subgraph and neighborhood query capabilities (canonical node search, depth-1 neighborhoods, edge explanations).
- **PostgreSQL Storage Engine**:
  - Normalized schema with transactional loading, idempotency tracking, and dual-write compatibility.
  - Bounded query readback for graph nodes, edges, file neighborhoods, and host mutators.
- **Model Context Protocol (MCP) Server**:
  - Stdio-based MCP server integration for AI coding assistants and developer tools.
  - Read-only graph exploration tools: `repomap_list_graphs`, `repomap_graph_status`, `repomap_search_nodes`, `repomap_neighborhood`, `repomap_canonical_neighborhood`, `repomap_project_summary`, and language-specific summaries.
- **Local Container Runtime**:
  - Docker Compose orchestration managing local PostgreSQL and RepoMap MCP services on isolated, localhost-bound ports.
  - CLI commands (`repomap-kg local setup`, `up`, `status`, `down`).
- **Full Refresh Coordination**:
  - Supervised background worker execution with typed failure categories and deterministic diagnostics.
  - Strict child process measurement, process group isolation, and settlement grace.

### Known Limitations
- **Coordinator Interruption Recovery**: Recovery following coordinator process interruption or abrupt container restarts is not reliable in v0.0.1; interrupted jobs remain in `reconciliation_required` state and require manual reconciliation or clean job re-execution.
- Multi-source logical graph composition is planned for future releases; v0.0.1 maps a single repository/folder tree per configured graph.
- Incremental differential refresh is experimental; full refresh is the authoritative ingestion method.
