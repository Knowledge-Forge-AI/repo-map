# ADR 0123: Coordinated CLOE package and namespace cutover

## Status and authority

Accepted before implementation, 2026-10-30, for REPOMAP-CLOE-CUTOVER1.
The maintainer reports CI98 passed, requests continuing the accepted roadmap,
and asks for roughly 10,000–100,000 meaningfully changed lines per public CI.
This instantiates W1's names and compatibility direction from ADR0118 and the
consumer inventory from ADR0121. It grants their previously deferred source,
package-metadata and disposable installed-proof work for this milestone. It
does not add a dependency or change a test-runner policy.

CI98 attempt 1 qualifies staging
`6d818ad6d43d38d47c64b8c474c2b64b853f631a`: all nine jobs and retained
same-attempt smoke/M/A/system contracts pass. Unit coverage is 88.1%/87.7%;
measured integration coverage is 90.1%/82.2%. Fifteen actual native AMD starts
remain spent. A successor campaign needs its own frozen candidate binding.

## Decision

Deliver three connected local phases before one public staging publication:

1. Add strict, forward-only namespace-projection authority and its adverse
   tests, keeping the current namespace and baseline unchanged.
2. Move the complete product tree to `common_lore_index` and coordinate the
   `common-lore-index` distribution, resource prefix and three commands. Prove
   the namespace mapping and transform current ownership/quality records from
   their predecessors without regenerating or forgiving numerical debt.
3. Add only documented compatibility facades, command branding and installed
   upgrade proof; update current consumer documentation and runners together.

Local commits may separate these review questions. Public CI follows their
integrated milestone, aiming for the requested rename-aware added-plus-deleted
line range. Record net change and moved-source volume separately. Padding,
unrelated cleanup and gate reduction are not ways to meet the target.

## Exact namespace and history projection

The only root mapping is `repomap_kg` to `common_lore_index`, and the corresponding
`src/main/python/` product path mapping. Component boundaries are exact: unknown
roots, look-alikes, mixed/partial maps, collisions and extra or omitted files
refuse. Preserve every historical authority record, proof blob, SQL/catalog byte,
scope transition, trusted genesis, ownership class/tier and numerical ceiling.

Use a separate append-only namespace authority keyed by the exact predecessor
and successor ownership hashes and selection digests. Bind it to this decision,
using record identifier `cloe.namespace.cutover1`,
its source commit and the complete sorted source path/blob mapping. The product
code mapping permits only the exact namespace token rewrite, declared literal
rewrites of implementation module paths, and the root's selected installed-name
constants. Durable legacy spellings are an explicit keep-list. Changes outside
that closed mapping are separate behavior changes with ordinary scoped proof.

Current baseline records are a deterministic projection of their predecessor,
not a fresh analyzer baseline. Tools and selection policy remain identical.
Selection, lint/type counts, import edges and file-length ceilings must equal
their mapped predecessors, including decreases: a broken root scanner must not
erase debt. Recompute path-bearing Ruff fingerprints from their stored messages.
A changed mypy fingerprint requires the old normalized-message preimage, exact
namespace-only message rewrite and both hash proofs; reject unused, extra,
forged or identity translation rows. Opaque, untranslated fingerprints retain
their original ceilings and confer no newly broadened allowance.

Namespace authority must be consumed exactly once, cannot substitute for scope
or inherited-export proof authority, and cannot authorize another edge. Check
all reachable ledger history for mutation, deletion, divergent loss or shallow
history. Existing unauthorized-rename and projection-negative tests remain strict.
The effective product census and every profile must include the new namespace;
new compatibility modules require explicit clean admission. Historical test
directory names need not move.

The retention census's historical decomposition, dynamic-operation and authority
records remain immutable. Any needed current-path or operation successor must
have an exact bijective source/AST derivation and preserve the closed recipe,
targets and obligations. A path or fingerprint substitution alone never proves
a dynamic operation safe. Missing profile or uncertainty coverage fails closed.

## Installed identity and compatibility

One distribution, `common-lore-index`, owns the canonical `common_lore_index`
namespace, `share/common-lore-index` resources and `cloe`, `common-lore-index`
and transitional `repomap-kg` commands through v0.1.x. Keep version 0.0.3,
all external dependency versions/hashes, the build backend and optional
dynamic Psycopg linkage unchanged. Update only root-project metadata and its
lock entry. The three commands delegate to one canonical CLI implementation;
branding is an explicit entrypoint choice, not inference from `argv[0]`.

Preserve exactly the documented migration functions through
`repomap_kg.ops.config_migration`, re-exporting the canonical objects. Keep finite
legacy module launch shims for `python -m repomap_kg` and
`python -m repomap_kg.server.mcp`; compatibility notices use stderr only. Do not
install generic import hooks, duplicate canonical module identities, eagerly
load optional drivers or promise every internal old import path.

MCP remains read-only. Its wire tool names and schemas, storage identities,
changesets/checksums, configuration recovery journals, environment selectors,
service labels and owned filenames retain their existing contracts. Existing
legacy native definitions remain status/uninstall-only under ADR0121, including
no legacy start/enable during failure recovery. No live service or home is changed.

## Evidence and rollback

Require exact unit and containerized integration selectors with --no-coverage,
covering namespace/history refusal, clean-process canonical/legacy object identity,
CLI/MCP stdout and driver isolation, catalog identity and preserved graph readback.
Compile all moved Python owners; execute full static retention enforcement,
suppression/export/topology/privacy/link checks and independent resulting-state
review. Complete local suites and project coverage remain unselected.

Use existing pinned setuptools/wheel/pip in the cached sandbox for bounded offline
wheel assemblies and disposable environment checks through the existing arch7f
packaging boundary. No application/SDK image build, external pull, new launch
family or dependency is authorized by this proof. Compare an immutable incumbent
wheel from CI98 with the integrated candidate. Verify both install orders and
uninstall effects, metadata conflicts, wrappers, package/resource ownership and
catalog equality. Overlap remains unsupported; observing destructive installer
effects does not certify safe coexistence. Fresh isolated installation, or removal
of the old distribution before replacement, remains the supported upgrade.

Rollback uses the prior qualified source/package in a fresh environment and the
explicit original home. This source cutover performs no data migration and makes
no automatic rollback claim after later live writes. Preserve protected private
work and private experiment owners through the explicit path map.

No repository rename, package-manager publication, main promotion, tag, live
deployment, complete local gate or additional native image start follows from
this ADR. Public author and committer remain Samuel Leighton Lair
<sam.lair@knowledge-forge.ai>.
