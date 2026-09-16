# Changelog

All notable changes to RepoMap will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Release Policy & Versioning

- `0.0.x` releases are public source previews.
- All versions `< 0.1.0` are intentionally pre-publication with respect to package managers (no distribution to PyPI, npm, Go module proxies, or container registries).
- `0.1.0` or later will be the earliest package-manager publication line.
- `main` represents released public versions.
- Public `staging` is the prospective next-version branch; release promotions to `main` are squash merges where each resulting commit represents one version release.

## [0.0.2] - Unreleased

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