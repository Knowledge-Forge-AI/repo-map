# ADR 0147: W5 observed-operation and paired-cost disclosure staging campaign

## Status

Accepted parent-owned conditional campaign allocation under the standing
roadmap continuation. Activation remains conditional on final independent
source review, scoped proof, grant replay proof, and an exact-commit report.
This ADR authorizes neither a retry nor public-main promotion.

## Context

ADR 0146 defines the observed-operation sibling journal field, paired-report
v2, context identity, and faithful cost disclosure. CI114 qualified its
predecessor and authenticated 27 cumulative application starts. ADR 0146 did
not allocate a successor hosted campaign. This ADR binds one successor
candidate after those connected source and proof owners are complete.

## Decision

Permit one ordinary synchronization of existing draft PR23 from `staging` to
`main`, expected to produce CI115 attempt 1. The candidate is phase
`REPOMAP-CLOE-SEMANTIC1-CI115`, with base `5ad00d162ad8a04430874275246a53227578c533` and the pre-synchronization staging ref
`14f9d4e250e2cdcd0f0af89049dd36aeb048b728`. The parent must recheck these refs and the hosted workflow
ordinal immediately before binding and publication.

Permit at most one new native `linux/amd64` assembled-product application
start, taking the authenticated cumulative total from 27 to a
maximum of 28. Preserve the complete historical ledger, including
the legacy zero-total/one-platform stop fields. CI114's spent nonce and
reservation remain rejected; the successor receives a fresh approval, nonce,
reservation and ledger-before digest. No automatic retry, CI116 rearm, or
start 29 follows.

The D12 context is recomputed at binding time from the frozen repository
identity. The SDK recipe and candidate record are revalidated against that
identity; no application or SDK build is performed locally. Public author and
committer metadata remain Samuel Leighton Lair
<sam.lair@knowledge-forge.ai>.

## Activation and verification

Activation requires the final resulting-source review, exact scoped unit and
containerized integration proof, retained-Python/static/privacy/export/
topology/length checks, grant/replay proof, protected-checkout custody, and an
exact candidate commit report. Hosted CI owns complete populations, coverage,
the staging integration gate, and assembled-system qualification.

The source census binding for this preparation is `21fa1ee4bcbbda78c41e3c29ec62f6d21a698396effe5ced3eed28e2d700bfee`;
the D12 identity is `{"context_file_count": 763, "dockerfile_sha256": "33eacec000a233ae3b71b25c83dfda44260460ccdce14dd1d188e6b3e7e072ed", "recipe_sha256": "df178bd40dd24acbbffea12b37d5e5dcb9c5461d40a97c199ad725271f8feced", "source_sha256": "4623e6eb35616a779cfbbab30cd968f618cd101a282039ad8a0cfa7500c10e3e"}`. These are
private binding inputs, not a claim that hosted qualification has run.

## Boundaries

No new model, dependency, input, corpus, label, held-out execution, production
index/extension, local complete suite, local coverage, application/SDK build,
remote dispatch, duplicate trigger, PR mutation, tag, release, main promotion,
or history rewrite is included. The operator's hosted-CI capacity state and
remote-write authority remain required by `docs/contrib/ci-agent-policy.md`.
