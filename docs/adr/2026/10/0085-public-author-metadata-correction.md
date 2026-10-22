# ADR 0085: Exact public author metadata correction

## Status

Accepted bounded design and reviewed implementation for the operator-requested
historical author correction. Final publication and hosted verification remain
pending. Public content promotion requires fresh CI qualification of preview
v0.0.3 and resolution of its promotion topology.

## Date

2026-10-22

## Context and authority

The operator requests author metadata `Samuel Leighton Lair
<sam.lair@knowledge-forge.ai>` for existing steward-authored public history and
future public commits. The operator selected correction of main and staging only;
ten dependency-bot branches remain unchanged for later rebase. Historical
committer fields remain unchanged. Correcting author headers also translates
parent hashes and invalidates one old GitHub signature; it does not promote
staging product content into main.

The main/staging range contains fifteen historical commits. A metadata-only
prototype preserves every tree, message, timestamp and committer field. The
existing exact retained-projection authority refers to original commit IDs, so
a fresh clone of that rewritten graph fails lineage inspection. Old authority
records and debt ceilings must remain immutable.

## Decision

Introduce one exact, offline author-correction proof for the reviewed historical
range through the original NAV40 staging tip. It binds original and corrected
Git object IDs one-to-one and proves complete parent closure and corrected-tip
ancestry. It accepts only the exact requested author name/email, corresponding
parent-ID translation and removal of invalidated signature headers. All trees,
messages, author dates/offsets, committer metadata and unrelated headers remain
identical. New ordinary commits after that historical range remain outside the
metadata transform.

For every corrected commit, reconstruct the original raw commit and verify its
original Git object hash. Fourteen old author name/email prefixes derive from
the preserved committer header. The remaining prefix derives from the already
published immutable recovered-projection witness. Restore a removed original
signature header at its exact original position only to authenticate the old
object; it is not a signature on the corrected commit. This avoids adding a new
plaintext copy of old identity data or whole historical commit messages.

Only fixed author-source discriminators are accepted; no caller-chosen file
path or executable expression is evaluated. Missing, duplicate, cyclic,
ambiguous, incomplete, unused or forged mappings fail closed. The proof and
decision enter the existing governing-input evidence surface, and published
proof history is immutable. No Git replacement refs or network fetches are used.

The proof is `tools/ci/public_author_corrections.json`, identifier
`REPOMAP-PRODUCT6-NAVIGATION40-CI57-PUBLIC-AUTHOR-CORRECTION1`. Its schema,
identifier, this decision path, target identity and `preserve` committer policy
are pinned in the checker. Rows and tips are file-supplied, authenticated only
by the object hashes below and frozen once committed. Rows list corrected
commits parent-first; each corrected object must hash to its new ID, have its
parents inside earlier rows, and rebuild to its original ID. Signature
preimages are restorable only after the committer header and must be `gpgsig`
headers. A corrected commit carrying a `gpgsig` or `gpgsig-sha256` signature, a
second author/committer or misplaced structural headers is rejected. The rows must equal the full parent closure of the new tip, which must
be an ancestor of `HEAD`. Every committed version of the proof must be
byte-identical to the current file; any edit or deletion after introduction
fails. Without a current or committed proof, lookups are unchanged.

Resolve authenticated historical IDs only at exact revision/edge lookup seams.
Old source-commit strings inside authority records are preserved and must still
yield the identical ownership blob in a fresh clone without original objects.
Recovered source-object authentication, ordinary direct/projection replay,
selection checks and every debt/ceiling comparison remain in force. The proof
does not grant scope admission or allow new policy/finding debt.

## Scope and non-scope

Only public author metadata and its necessary lineage compatibility are covered.
The private development history, bot branches/authorship/signatures, old scope
records, projection evidence, historical manifest content, product selection,
checker versions, coverage gates, dependencies and production runtime behavior are
unchanged. Existing contact documents use the new address. Future public steward
commits use the requested identity through explicit publication configuration
and identity checks.

Preview v0.0.3 metadata must agree before its new hosted qualification run. It
does not relax a gate or authorize unqualified content promotion. Main's
historical metadata rewrite preserves its current tree. Main content promotion
requires separately accepted fresh CI for the exact candidate/base pair.

## Publication and recovery

The parent preserves a verified private bundle and exact old/new object/ref map.
Local metadata correction verifies every historical tree and preserves the
working files and index. Public history publication uses one atomic push with
explicit leases on main and staging. Moved refs or rejection stop the operation;
there is no blind force or automatic retry. No bot branch, tag, PR state,
protection, billing or runner policy is changed. Operator-selected bot PR rebases
remain deferred.

## Required evidence

Keep the existing projection adversarial tests. Add exact corrected-history
success in a fresh clone with original objects absent, and negative tests for
changed tree/message/committer/author/time, wrong parents, forged original IDs,
missing or wrong signature preimages, missing/extra/duplicate/cyclic rows,
unused authority and edited historical material. Verify normal histories without
the new proof keep existing behavior. Run canonical public ownership, retention,
ratchet and export checks with no new debt. Independent review and parent
resulting-state acceptance precede any remote rewrite.

## Rejected alternatives

A mailmap changes presentation rather than the requested Git author metadata.
Unchecked aliases and new baseline genesis discard existing exact-edge assurance.
Rewriting old proof/authority blobs breaks their immutability. Public backup
branches retain the old author history as published ancestry. None satisfies
this bounded correction; retain the original graph privately for recovery.

## Preview v0.0.3 promotion boundary

The public changelog specifies squash releases, while this proof requires the corrected staging tip in HEAD ancestry. The operator topology choice remains pending. The staging retry can proceed; main content promotion waits for that decision and fresh accepted CI.
