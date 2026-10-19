# ADR 0084: Forward-only retained projection proofs

## Status

Accepted design after independent plan review; implementation and final-byte
verification remain subject to dispatcher work review and local acceptance. It extends the lineage authority of
[ADR 0062](../09/0062-retained-python-enforcement-authorities.md) and supersedes nothing.

## Date

2026-10-18

## Context

The retained-Python lineage audit walks every committed change of
`tools/ci/retained_python_ratchets.json` from the trusted genesis. A transition that
restricts the retained selection or changes the ownership manifest needs exactly one
scope-transition record, read from `tools/ci/retained_python_scope_transitions.json` at
that same commit. The record's ownership and selected-set digests must equal the
transition, its `changes` must equal the selection delta, and its status authority must
be valid. Records are append-only, and every record added after genesis must be used.

Public commit `1adfc7a15e830c8709f76f4e61abb9e24a8c0b17` (parent
`d1671f8088531c4be11de65908f762c61f986844`) published two separately reviewed hops as
one commit: 56 clean additions (`REPOMAP-PRODUCT5-PUBLIC-STAGING-REPAIR1`) followed by
6 clean additions (`REPOMAP-PRODUCT5-HOSTED-QUAL2-REPAIR10`). The commit carries both
records but no record for the combined 62-addition transition. That transition adds no
debt, and every addition is clean. The audit nevertheless rejects it ("scope transition
lacks exact authority"), and every descendant inherits the rejection.

ADR 0062 recorded that a squash or projection may drop the ancestry that holds
historical authority, and that a verified durable authority migration is then required.
The state between the two hops exists only in published commit
`c55910c65963afcb9fab13f159ae5ba64c57da21`. That commit is not reachable from public
history, so ordinary clones do not contain it.

The following are excluded: rewriting history; appending a combined direct record (the
audit reads records at the historical commit, so a later record cannot authorize it);
rebaselining; suppressions; raising ceilings; changing genesis pins; waivers; trusting
hash labels or chains of registry fields; and fetching objects over the network at
audit time.

## Decision

### 1. Separate, additive authority

A new tracked proof registry, `tools/ci/retained_python_projection_proofs.json`, and a
content-addressed evidence directory, `tools/ci/retained_python_projection_blobs/`,
may explain one exact historical publication edge as an ordered composition of
scope-transition records that already existed at that edge. A proof never creates,
alters, reorders or stands in for a record. It never applies to an uncommitted
candidate transition. Scope records, baselines, genesis pins and tool and selection
policy are unchanged. Absence preserves prior behavior only if no proof version has
ever been committed. The worktree is authoritative only after append-only checks
against HEAD and every committed version; deleting committed authority fails.

### 2. Proof schema (`repomap-retained-python-projection-proofs-v1`)

The top level is a closed object `{"schema", "proofs"}`. Each proof is a closed object:

- `proof`: unique identifier.
- `decision`: repository path of an existing `docs/adr/` document that names the
  `proof` identifier.
- `reason`: non-empty text.
- `commit`, `parent`: 40-hex ids of the historical edge.
- `states`: ordered list of at least 3 closed objects, each holding
  `baseline_sha256`, `ownership_sha256` and `selected_set_sha256` (64-hex). `states[0]`
  is the parent's state, the last entry is the commit's state, and the entries between
  are complete intermediate states.
- `hops`: exactly `len(states) - 1` closed objects, each holding `phase` and
  `source_commit`. Every hop whose old state is an intermediate state (that is, every
  hop after the first) also carries `source_objects`: `{"commit": <exact UTF-8 payload>,
  "trees": {<directory>: <hex payload>}}`, where the directories are `"."` and each
  directory needed to reach the baseline and ownership paths. The first hop must not
  carry `source_objects`.

Proof identifiers and `(commit, parent)` edges are unique. Field names avoid
credential-like words. No field hashes the proof file itself, or any commit or tree
that contains it, so there is no source self-hashing cycle.

### 3. Exact edge binding

A proof applies only to a committed lineage edge that the audit actually visits:
`parent` is a Git parent of `commit`, both descend from genesis, the edge changes the
baseline, and it is not a redundant ancestor merge parent. The edge must require
authority (a restriction or an ownership change) and must have no exact direct record (count matching digest keys without invoking
the transition audit);
a proof for an edge that has direct authority, or needs none, is rejected. The verifier
reads the parent's and the commit's baseline bytes from Git, plus the ownership bytes
at each baseline's `ownership.manifest_path`. It requires each SHA-256 to equal the
declared state, each ownership digest to equal the baseline's embedded
`ownership.sha256`, and each selected-set digest to equal the audit's selection digest.
A proof that is never consumed, for example because it names an edge outside the
audited history, a swapped or wrong parent, or a divergent branch, is rejected.

### 4. Authentication of complete intermediate states

Each intermediate state `i` is the old state of hop `i`. Its baseline and ownership
bytes live in `retained_python_projection_blobs/<sha256>.json`, named by the SHA-256
of their bytes. At audit time they are bound to authority that already exists at the
historical edge, without network access and without unreachable local objects:

1. The registry blob in the edge commit's tree contains the hop's record; its
   `source_commit` value `S` is part of that historical blob.
2. The hop's `source_commit` must equal `S`. Git's SHA-1 object id of the supplied
   commit payload (`"commit <len>\0" + bytes`) must equal `S`.
3. The commit's first header line names its tree. Each supplied tree payload must hash
   to the id that names it, and the path is walked through exact entries (directories
   mode `40000`, files mode `100644`) to the blob ids of the baseline path and the
   ownership manifest path.
4. Each evidence file's Git blob id must equal the included blob id, and its SHA-256
   must equal its file name and the declared state.
5. The ownership SHA-256 must also equal the baseline's embedded digest, the record's
   `old_ownership_manifest_sha256` and `source_manifest_sha256`, and the previous
   record's `new_ownership_manifest_sha256`. The baseline's selection digest must equal
   the adjacent records' selected-set digests. The baseline must satisfy the unchanged
   baseline contract.

Every hop record must carry both `source_commit` and `source_manifest_sha256`.
ADR 0084 newly interprets that source commit as the hop's **old** endpoint. The
ownership path walked in its tree must equal the baseline's
`ownership.manifest_path`. Git object ids are cross-checked with
`git hash-object --stdin -t <type>` (without `-w`); no object store is written.

For the first hop, the old state is the parent's own state from reachable history. Its
record's `source_manifest_sha256` must equal that state's ownership digest.

The evidence directory must contain exactly the referenced files. The supplied trees
must be exactly the directories needed. Unused or missing evidence is rejected.

### 5. Record selection and consumption

Candidate records are those present in the registry at the edge commit and absent from
every parent's registry, comparing `scope_record_key` rather than complete records
(the v1-to-v2 migration added source fields to existing records). Records are
identified by that key and phase, never by list position. For each adjacent pair of states, exactly one candidate record
must carry the pair's ownership and selected-set digests. The record's `phase` and
`source_commit` must equal the hop's. The states must be pairwise distinct (no cycle),
and at least two hops are required. Over all candidate records, the declared sequence
must be the only simple path from the parent state to the commit state; ambiguity is
rejected. Each referenced record is consumed exactly once across all proofs, and no
record consumed by a proof may also authorize a direct committed or candidate
transition. Consumed records count as used for the existing unused-authority rule.

### 6. Replay

Each hop is checked by the unchanged per-transition audit: baseline contract, unchanged
tool and selection policy, clean additions, no new or increased Ruff, mypy,
migration-import or file-length debt, record `changes` exactly equal to the hop's delta,
and status authority read from the historical edge commit. The audit must return
exactly the hop's record. Debt cannot rise in one hop and fall in a later one, because
every hop is checked separately. The hops' change sets must be disjoint by module, and
their union must equal the edge's selection delta exactly. Disjoint changes are intentional
strictness: an add-then-modify chain is rejected even if its net effect is benign. The edge itself must also
keep tool and selection policy, add only clean modules and add no debt.

### 7. Append-only governance

Each committed change of the proof file (descending from genesis) must keep every
earlier proof as an exact, unchanged prefix of the newer list. The worktree must extend
HEAD the same way. Evidence is content-addressed, so changing or deleting it fails
verification. The proof file, every evidence file and every decision document are bound
into the retention inventory's governing inputs.

### 8. Failure semantics

Every proof violation raises `LineagePolicyError`. The ratchet checker classifies that
as a `baseline-lineage` policy finding (exit 1). Missing, extra, malformed or tampered referenced proof/evidence is a policy finding
(exit 1). Other I/O or Git inspection failures are tool failures (exit 2). Nothing is accepted partially. Shallow
history is still rejected before any proof is considered.

### 9. Public safety

Evidence holds only historical retention baselines, ownership manifests and the
minimum Git objects needed for inclusion. Each was inspected and already published on
the public remote. The commit object is reproduced byte-for-byte because its hash
requires every byte. It carries the author identity that every commit object in public
history already carries. Its decoded message includes two already-public identifiers labelled private source
commit/tree; those identifiers are disclosed again, without copying private content.
The exact UTF-8 commit string is transparent; tree payloads expose entry names and
object ids. The provenance manifest records the decoded message and tree names,
checks that no withheld names occur, and confirms author and committer identities
already occur in reachable public history. No status documents, host paths, private
source contents, credentials or runtime data are included. Validation reads no withheld paths.

### 10. Inherited proof `PRODUCT5-PUBLIC-MAIN-PROJECTION1`

- Edge: commit `1adfc7a15e830c8709f76f4e61abb9e24a8c0b17`, parent `d1671f8088531c4be11de65908f762c61f986844`.
- State 0: baseline `e6a4830df94a210d83da9e37bce147eb3891d74a7868e50cfc1c648d858475f4`, ownership `407a9c6fb5e81c3cdbbf44e7b6fe91720e9362826ddd91f641247e88a39e3395`, selection `af0987330c717c5481a103a7ccb0912d9fca8eaef00c7e4c70da35621f5a78e7`.
- State 1: baseline `b209042c529e4e1c90ee26bf28d90427c9fddfff7e36cc4a109a3f9c76f82d64`, ownership `14bcaf3fba2d3ad5e5f0a03e48c98ed2005211978cb45793a11d49f69d34713b`, selection `527ab4103073256609e99cd122bfeca2ce09adc15049224ccd8e1e920920af73`.
- State 2: baseline `1ede422764b6631bd9232ef7e29ea0c96cf30a3c9a4a26a15c4d7e772285ca55`, ownership `32d7af46121ffdcb5031cf72a1d755b29a66d01bebfdc27fbce48429dc9f093c`, selection `06ddb1b1e89cad723f8b53501c43f774cc0f7435cd0a40bb4c9cb70e0bb24b4e`.
- Hops: `REPOMAP-PRODUCT5-PUBLIC-STAGING-REPAIR1` from `ce0ff28cb4a320778e86337099e2df1576e1b617`, then `REPOMAP-PRODUCT5-HOSTED-QUAL2-REPAIR10` from `c55910c65963afcb9fab13f159ae5ba64c57da21`, with that commit's commit object and its `.`, `tools` and `tools/ci` trees.

No direct authority record for the combined edge ever existed, and none is claimed.

## Consequences

- The inherited edge passes only through the replayed, authenticated chain. Every
  existing record, ceiling, genesis pin, policy, coverage floor, workflow and the
  release version are unchanged. Repositories without proofs behave as before.
- The checker is split into Git primitives, proof evidence and the proof ledger.
  Existing import paths for lineage names are preserved.
- Rollback is a normal forward commit that removes the proof file, the evidence and the
  checker extension together. The original rejection then reappears; rollback never
  produces a passing result. Removing only the proof while the checker remains violates
  append-only governance and fails.
- Future projections must carry the proof forward. Dropping it fails closed and is
  visible.
- Residual risk: intermediate baseline bytes are bound through SHA-1 Git object ids
  (plus SHA-256 labels that the proof itself declares). Ownership bytes are also bound
  by SHA-256 values in pre-existing records. Second-preimage forgery against an
  already-fixed object id is out of reach. A colliding pair prepared by the original
  publisher before publication is not excluded by hashing alone, but any such blob
  would still have to pass full baseline validation and per-hop replay.
- This decision would be wrong if any of these held: a proof could change acceptance
  without each hop passing the unchanged audit; the verifier accepted bytes not
  reachable by hash from the edge commit's registry; a record could be consumed twice
  or added after the edge; a deleted or edited proof still passed; or retention debt
  could exist outside the baseline document. Each has a negative test.

## Verification

- Focused synthetic Git-history tests (positive and negative), pure evidence tests, and
  a source-bound test of the inherited public edge, all without network access.
- The existing lineage, record and comparison negative owners pass unchanged.
- The unchanged canonical retained-ratchet and retention-inventory commands run against
  the candidate.

## Alternatives

Rewriting or squashing history, retroactive combined records, rebaselining, waivers,
trusting declared hashes or registry chains alone, fetching at runtime, and relying on
unreachable local objects were all rejected. Each one either relaxes authority or
cannot be reproduced in a clean clone.

## Implementation clarification

The content-addressed directory uses the `projection_blobs` name to avoid a
module/namespace-package collision with `retained_python_projection_evidence.py`
during cross-root type checking. Newly added helpers and test owners enter the
existing zero-debt census and cohorts; all preexisting entries and memberships
remain governed. This changes neither debt ceilings nor enforcement policy.

The public navigation cohorts pending fresh evidence are admitted only after
current clean checks and closed dependency validation. Five test owners use
explicit maintained-module imports in place of opaque path loaders; their fresh
import and isolated-process assertions remain exercised. No dynamic-boundary
exception or suppressing recipe is introduced.
