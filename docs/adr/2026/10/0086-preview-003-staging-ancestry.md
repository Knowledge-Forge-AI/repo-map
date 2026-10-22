# ADR 0086: Preview v0.0.3 staging-ancestry promotion

## Status

Accepted. The operator selected this preview-specific exception on 2026-10-22.
Publication is performed separately by the authorized parent; this record does
not claim that publication or any later hosted run succeeded.

## Date

2026-10-22

## Context

The public release policy says release promotions to `main` are squash merges,
each resulting commit representing one version release. Preview v0.0.2 followed
that convention.

[ADR 0085](0085-public-author-metadata-correction.md) corrected public author
metadata through the original NAV40 staging tip with an exact, immutable proof.
Its checker rejects a candidate unless the corrected NAV40 staging tip is an
ancestor of `HEAD`. Public `staging` contains that tip; public `main` does not.

A squash of the qualified staging candidate onto the existing `main` would
create one new commit whose only parent is the old `main`. That commit would
carry the qualified tree and the proof file but not the corrected tip in its
ancestry. The author-correction check would then fail on `main`. That commit
would also not have been tested. Its tree would match the tested tree, but its
history would not. The hosted qualification ran on the merge of the exact
staging candidate into the exact `main` base, and RepoMap's lineage checks
depend on history.
[ADR 0062](../09/0062-retained-python-enforcement-authorities.md) already
records that a squash may drop ancestry that holds historical authority. Making
squash compatible while preserving those requirements would need a separately
designed and reviewed release-projection mechanism. The operator did not
select that additional scope. This decision preserves ADR 0085's existing
ancestry and immutability requirements.

The current `main` is an ancestor of the qualified staging candidate.
The hosted merge therefore has the same tree as that candidate.
[ADR 0054](../08/0054-staged-promotion-topology-and-logical-ci-gates.md)
requires that any synthesized final merge commit be shown to preserve the
tested candidate tree and the approved base/head relation. Fast-forwarding
`main` to the candidate keeps both by construction, because it synthesizes no
new commit.

ADR 0085 left the v0.0.3 promotion topology pending an operator choice. This
decision records that choice and resolves that pending boundary. It does not
change ADR 0085's proof or its other requirements.

## Decision

For preview v0.0.3 only, promote by advancing `main` by fast-forward to the
exact hosted-qualified staging commit. Do not create a squash or merge commit.
The promoted commit, its tree, and its author and committer metadata are those
that were qualified. The version's commit range enters `main` as staging
history, not as a single squash commit.

The promotion requires all of the following:

- an accepted executed-pass hosted attempt bound to the exact staging candidate
  and `main` base, including the same-attempt staging and system contracts;
- an expected-value lease on each moved ref, with every update a fast-forward;
- no client-issued tag, release object, registry publication, bot-branch change
  or pull request state mutation as part of the promotion.

A moved ref or a rejected update stops the operation. There is no forced
update and no automatic retry.

Documentation describing this promotion may follow the qualified commit on
`staging` as a separate descendant. That descendant is not covered by the
v0.0.3 qualification, and the release commit on `main` does not change. Its own
hosted result, if any, is recorded only after it is observed.

## Scope and non-scope

This exception amends the squash convention for the v0.0.3 promotion and for no
other release. It changes no proof, checker, authority record, projection
evidence, baseline, debt ceiling, coverage threshold, test, workflow,
dependency, package version or package-manager restriction. Versions below
`0.1.0` remain source previews with no package-manager or registry
distribution.

## Consequences

After this promotion, `main` contains the corrected NAV40 staging tip in its
ancestry. A future squash release built on that `main` keeps the tip as an
ancestor, so the ADR 0085 proof continues to verify there. Future releases
therefore return to the squash convention unless a later decision says
otherwise. `main` will carry more than one commit for v0.0.3. Readers
identify a release by its promoted commit and the public release notes, not by
a one-commit-per-version count.

The pull request that carries staging into `main` may change state on the
server when the refs move. Neither a closed pull request nor a missing or
extra automatic run authorizes a duplicate dispatch or a new pull request.
Either one needs separate authority.

## Rejected alternatives

- **Squash onto the current `main`.** This breaks the ADR 0085 ancestry check
  and produces a commit that was not tested.
- **Merge commit onto the current `main`.** A new merge commit is not the
  tested commit. The hosted test merge has server-generated commit metadata
  rather than the canonical steward author identity. A fast-forward needs no
  extra commit.
- **Re-found, edit or alias the author proof.** This breaks proof immutability
  and the exact-edge assurance.
- **A permanent change to the release convention.** The operator selected an
  exception for v0.0.3 only.
