# ADR 0195: Finish Common Lore Index identity and qualify preview v0.0.4

## Status and authority

Selected before source changes on 2026-11-13 for CLOE-REBRAND-PREVIEW004. The
operator requests CI144 remediation, completed branding, public/private repository
and local private-checkout renames, historical RepoMap tags/releases, then v0.0.4
promotion/release after passing CI. Continue the accepted v0.1.0 roadmap afterward.
This explicitly supersedes earlier exclusions of these rename/release actions;
earlier spent CI/build reservations remain historical and are never rearmed.

## Identity and historical release decisions

Canonical repository is Knowledge-Forge-AI/common-lore-index; the private
development repository and physical checkout use common-lore-index_dev. Renaming
preserves repository IDs, visibility, branch objects and concurrent private work.
A legacy local-path symlink preserves existing tooling without a second checkout.
No private source mirroring or live home/service/database migration is selected.

Existing corrected public history supplies immutable historical tag targets:
v0.0.1=001cac6298ff18b272e2f92a4c5ff8b047cdfbcf;
v0.0.2=1bc81cf88d58305251b61e01069a75c932f7d2de;
v0.0.3=5ad00d162ad8a04430874275246a53227578c533. The last is the final CI87/PR13
closeout, superseding the earlier interim v0.0.3 promotion. Annotated tags and
prerelease entries are backfilled with truthful current creation dates and
historical source-promotion dates. No original commit or prior license is changed.

Coordinate v0.0.4 in canonical source, pyproject, the root editable lock entry,
export policy and installed tests. External dependency/lock entries remain exact.
Root README, contributor/notice/security documents and current operator guidance
use Common Lore Index and the new canonical URL. Preserve archived ADR/status
bytes, historical source URLs, the separate Apache archive and prior-license
grants. Contribution terms change project name only, preserving their grantee,
rights, contact and license. Correct the remaining stale current notice email.

MCP initialize serverInfo.name becomes common-lore-index and version follows the
canonical version. The server remains read-only. Tool names, request/result
schemas, storage identities, changesets, environment fallbacks, service labels
and finite repomap-kg/repomap_kg launch compatibility through v0.1.x stay unchanged
under ADR0123. The existing qualification workflow file identity stays stable
for historical run/campaign accounting; its display name may use CLOE branding.

## CI144 correction and dependency review

CI144 passed unit, staging integration, static and native jobs; only the assembled
system preflight refused. Hash-verified retained evidence shows one differing
existing builder package: linux-libc-dev 6.12.116-1/all advances to6.12.117-1/all,
SHA256 8b4848725a2705e5b1612f2135c44300716690ba762368ab87df127e9a5ed416.
All other 47 builder entries, runtime closure, libpq/Psycopg dynamic linking,
PostgreSQL/Python bases and inventories are unchanged. No application build began.

Refresh that exact existing Debian Trixie builder pin and canonical manifest hash,
with same-daemon refusal/admission tests. This follows the operator's standing
Debian-stable direction and current remediation request, not a new parser/runtime
class. No package is added. The existing Linux headers' GPL-with-syscall-exception
licensing role is unchanged; only verified distro-provided builder metadata
advances. Retained hosted artifact digests bind provenance, architecture and hash.
The package is used during existing container builds and adds no Python/runtime
dependency. Alternatives are stale-pin installation (can disappear upstream) or
relaxing equality (loses reproducibility); both are rejected. Rollback retains the
old manifest/source and requires an available exact predecessor artifact. Scoped
tests prove current acceptance and stale/tampered refusal before build intent.
Inherited Debian vulnerability findings remain informational under ADR0105.

## Current presentation completion

Current CLI report headings, server listening banner and read-only MCP tool
descriptions use Common Lore Index. Fifteen formatter/description owners change
only selected string literals. Existing exact owning unit and integration
assertions are updated; JSON keys, tool names, request/result schema structure,
read-only enforcement, persisted graph names, backup protocols and ownership/error
contracts remain unchanged. A source AST replay proves no other program change.
Internal historical identifiers and fixture graph names are not branding aliases.

## Installed systemd description compatibility

Independent review found that replacing the human Description alone would make
the exact rendered-byte ownership check refuse pre-preview units. New units use
Common Lore Index. Recognition and validation admit exactly two rendered byte
strings: the canonical current definition and the otherwise identical definition
with the legacy RepoMap Description line. No input normalization, prefix match,
unknown description or alternate command/metadata is admitted. Existing module
classification and legacy-module reinstall/refusal behavior remain unchanged.
Unit and containerized integration owners cover old/current descriptions, both
module classifications, tampering refusal and temporary-file lifecycle without
host systemd activation. This is the compatibility repair within the approved
rebrand, not a new service migration or test-runner policy.

Published dynamic import records remain an exact prefix. Eight successor records
renew owner/test/target source hashes for the version and CLI prose changes; all
other census/cohort/debt values and closed AST recipes remain unchanged. Synthetic
test secrets use repeated-character public placeholders without scanner changes.
Current guides may use the new URL for the same immutable GitHub repository/run
IDs; archived ADR/status and prior-license source URLs remain historical.

## Operator-selected v0.0.4 promotion topology

On 2026-11-13 the operator selected A: preserve staging ancestry for v0.0.4.
The existing v0.0.3-only squash exception is extended to this preview because
the inert squash probe refused inherited predecessor evidence. No history or
debt guard is relaxed. Only after the exact current hosted campaign and its
same-attempt M/A/system reports pass audit, advance main by ordinary fast-forward
to that qualified staging commit, then tag and publish the Common Lore Index
v0.0.4 GitHub prerelease at the same commit. Preserve the qualified tree, complete
ancestry and required author/committer. No squash, new merge commit, force-push,
history rewrite, extra campaign or build is selected. A failed or superseded
attempt grants no promotion, tag or release. Later releases retain the default
convention unless separately resolved against their lineage obligations.

## Verification, campaign and release boundary

Use exact scoped canonical unit and containerized integration selectors with
--no-coverage for package preflight, version/metadata coherence, entrypoint and
MCP compatibility, export/repository binding and installed packaging consumers.
Strict static/type/retention, privacy/suppression, lengths, topology, links,
compilation and whitespace remain unchanged gates. No complete local Python
suite/coverage, new SDK/application image, live activation or model study is
selected. New APGR dispatches remain serial dynamic_default; never interrupt an
active dispatch. Source/grant review and exact commit/report precede one fresh
normal staging campaign. New repository identity is enforced, never bypassed.

CI144's zero application starts and actual Rust/transfer spend must be appended
from retained artifacts. A fresh reservation preserves all old ledger prefixes,
retired identities and numerical/coverage ceilings outside the one requested
successor campaign. Limits are never labeled observed consumption.

v0.0.4 remains prospective until all current hosted jobs and exact-candidate
same-attempt reports pass audit. Promotion must preserve required lineage proofs,
qualified tree and author/committer Samuel Leighton Lair
<sam.lair@knowledge-forge.ai>. Evaluate the existing squash convention against
the actual lineage guards before moving main; do not silently waive either.
No v0.0.4 tag/release or main move occurs on red, missing or superseded evidence.
GitHub source previews remain separate from package-manager/registry publication.
