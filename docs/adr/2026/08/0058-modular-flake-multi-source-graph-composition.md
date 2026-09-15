# ADR 0058: Modular-Flake Multi-Source Graph Composition

## Status

Accepted for the MS-FLAKE2 local implementation candidate. Complete
PostgreSQL integration qualification, hosted publication, and promotion remain
pending. This decision grants no authority for STR-SEAM3 or any later phase.

## Date

2026-08-30

## Context

ADR 0057 requires one logical graph candidate and one accepted publication
from a complete vector of explicitly bound source snapshots. MS-ID1 supplied
deployment-neutral source, binding, snapshot, and candidate identities, but it
deliberately did not choose the persisted binding namespace or cross-source
edge representation.

The first use case is an open-ended modular Nix flake constellation. Files with
the same relative path commonly occur in several bindings, while literal flake
input/module references can establish useful cross-binding relationships.
RepoMap must represent both without evaluating Nix, selecting an arbitrary
binding, exposing a checkout path, or introducing a second semantic engine or
publisher.

## Decision

### Binding-qualified graph-key-v1 paths

Legacy graph syntax retains its existing unqualified source-relative paths and
canonical keys. Every explicit-binding graph, including one with exactly one
binding, instead encodes a source-local path as:

```text
<binding-alias>/<normalized-source-relative-path>
```

Binding aliases use the closed MS-ID1 token grammar and cannot contain `/`.
Normalized relative paths cannot escape their binding root. The encoding is
therefore injective across admitted aliases and relative paths. It applies from
the first explicit binding so adding another binding changes the graph
candidate but cannot re-key existing source-local entities. The public
graph-file record continues to display the unqualified `source_relative_path`
alongside explicit binding provenance.

This is the smallest versioned extension that fits current authority. It keeps
`GRAPH_KEY_VERSION = 1`, repository-scoped uniqueness, edge foreign keys, and
all seven existing staging/final families. No new table, column, edge kind, or
Liquibase migration is required. Moving a legacy graph into explicit-binding
syntax is an operator-visible configuration migration, not an implicit rewrite
of legacy rows.

### Complete snapshot vector and candidate

Only enabled local `folder` and `git-working-tree` bindings are admitted.
Stable binding ID determines order. Each binding receives one exact manifest
snapshot over selected path, content digest, byte size, and executable state.
Hash, size, and executable mode come from one descriptor-stable read. Extraction
uses an immutable temporary staging copy of those accepted bytes. After every
binding has been extracted and Nix relations resolved, one final pass verifies
the complete inventory; any changed, missing, replaced, or unreadable binding
refuses the whole candidate. For a Git working tree the selected clean or dirty
content is bound directly; this slice does not claim `git_commit` or `git_tree`
evidence.

The candidate binds the complete ordered binding revision/snapshot vector,
multi-source configuration identity, extractor capability, resolver,
canonicalizer, semantic contract, and quality rule. Resolver identity also
binds binding roles and explicit Nix input names. Physical roots, worker,
container, database, region, and scheduling values are excluded.

Every resulting observation carries validated binding ID, alias, role,
revision, snapshot, source-relative path, and candidate provenance; path
prefixes are not provenance authority. The existing `source_generation`
receipt field binds the ordered binding revision/snapshot vector. Each snapshot
transitively binds selection and ignore policy plus exact path, digest, size,
and executable state. `config_generation` binds the multi-source configuration,
role/input map, resolution policy and resolver version, extractor capability,
canonicalizer, semantic contract, and quality rule. These two deterministic
projections reconstruct every candidate input while excluding physical roots,
worker path, database, container, and region. Coordinator and worker fences use
the same inventory scan without semantic extraction; execution performs the one
full capture and must match the accepted four-generation receipt. One complete
observation spool enters the existing staged transaction and sole publisher.
The strengthened four-field receipt automatically governs direct, coordinator,
worker, replay, reconciliation, and `commit_unknown` paths; no schema migration
or second authority is introduced.

### Bounded static Nix resolution

The resolver accepts only evidence established by static literal syntax and an
explicit binding/input map:

- literal relative imports resolving to a selected file in the same binding;
- literal `inputs.<name>.nixosModules.<module>` references resolving through a
  source-qualified target-flake export that directly assigns that output to a
  selected literal path, either `nixosModules.<module> = import ./path.nix`,
  `nixosModules.<module> = ./path.nix`, or the corresponding directly visible
  literal `nixosModules = { ... };` member.

Outcomes are `exact`, `ambiguous`, `conflicting`, `evaluation-dependent`, and
`unsupported`. Bare input references and filename convention alone are not file
relations. Dynamic, conditional, inherited, merged, interpolated, indirect, and
helper-generated output shapes remain non-exact. Only `exact` gets a resolved
file target. Other outcomes retain bounded unknown/dynamic evidence under an
opaque per-observation identity so unrelated scalar provenance cannot merge.
Binding order, alias order, repository name, and path location never break a
tie.

### Privacy and readback

Any non-public binding makes the graph `private-ops`. Every binding root and
expanded root is then redacted in public-safe configuration, status, CLI, and
MCP projections, including roots belonging to nominally public bindings.
Diagnostics contain no physical paths or source bytes. Canonical file readback exposes the owning
binding/snapshot, accepted candidate, and complete source inventory using only
stable IDs, configured aliases/roles, revisions, and snapshot digests. Public
configuration projections redact the effective-private constellation's physical
locators and names. A file record never includes another binding's metadata; an authorized
operator determines participation by enumerating records for the same
candidate. This decision creates no public-safe projection of a private graph.

## Consequences

- Duplicate relative paths and symbols remain binding-distinct.
- Explicit one-binding graphs start with their durable multi-source namespace;
  legacy graphs remain behaviorally and key compatible.
- Existing PostgreSQL staging, generation fencing, receipts, retries,
  `commit_unknown` reconciliation, and readback SQL remain authoritative.
- The representation is locally useful without committing machine locators or
  private fixture content.
- Full PostgreSQL behavior is specified by integration tests but remains
  unexecuted locally under the TEST-ISO2/hosted-Staging-Gate policy.

## Rejected Alternatives

- Graph key version 2: unnecessary for an injective graph-key-v1 namespace and
  would re-key legacy data.
- New binding columns/tables: more migration and dual-representation surface
  without additional vertical-slice value.
- Per-binding publication: violates complete-candidate atomicity and sole
  publisher authority.
- Repository-name or first-binding precedence: unstable and semantically
  arbitrary.
- Nix evaluation: executes target semantics and exceeds the static extraction
  boundary.

## Rollback

Disable or remove explicit multi-source graph configuration and retain the
prior accepted generation. Because this decision adds no schema object or new
writer, rollback requires no database down migration. Legacy one-source graphs
continue through their unchanged path.
