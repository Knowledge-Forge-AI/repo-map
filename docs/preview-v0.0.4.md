# Common Lore Index Preview v0.0.4

Status: prospective source preview; staging qualification and promotion pending.

This is the first prospective release under the Common Lore Index (CLOE) name.
Its repository and distribution are `common-lore-index`, canonical Python package
`common_lore_index`, and preferred command `cloe`. `common-lore-index` is also a
supported command; finite `repomap-kg` and documented `repomap_kg` launch/migration
facades remain through v0.1.x. See [installed compatibility](ops/cloe-installed-upgrade-compatibility.md).

The repository rename preserves its identity and history. Current contribution,
operator and package metadata use the new name. MCP initialize advertises
`common-lore-index`; its tools and schemas remain read-only and unchanged.
The existing AGPL-3.0-or-later/commercial licensing terms, steward and prior
license grants are preserved.

The accumulated work since the final RepoMap v0.0.3 includes the coordinated
namespace/configuration transition, retrieval/navigation/context improvements,
bounded optional semantic/Rust components, and measured resource-governance
work. Acceptance is bounded by the current [roadmap](specs/cloe-roadmap-transition-v1.md):
full W5/W6/W7/W8, optional pgvector, scientific comparison, further platforms,
image admission and deployment remain separate. This preview does not claim
completion of those workstreams.

CI144's system preflight found one stale Debian Trixie builder package pin.
The candidate refreshes only the verified linux-libc-dev 6.12.117-1 artifact and
canonical manifest hash, preserving exact stale/hash refusal and dynamic Psycopg
linkage. Inherited Debian vulnerabilities remain informational under ADR0105.

The [historical RepoMap releases](releases/repomap-previews.md) identify exact
v0.0.1/v0.0.2/final v0.0.3 commits and their backfilled tags/releases. v0.0.4
must receive its own current exact-candidate hosted acceptance before main
promotion, tagging and a GitHub prerelease entry. No package-manager/registry
publication or live home/service/database migration is part of this preview.
