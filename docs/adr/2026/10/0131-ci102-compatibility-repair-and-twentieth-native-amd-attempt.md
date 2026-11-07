# ADR 0131: CI102 compatibility repair and twentieth native AMD attempt

## Status and authority

Accepted by the parent under the current explicit operator request, conditional
on corrected source, scoped proof and independent final review before staging
publication. Phase: REPOMAP-CLOE-CI102REPAIR1. Date: 2026-10-31.

The operator requested: "Ci failed try again". The parent interprets this as
authority to repair the executed CI102 deficiencies and publish one corrected
successor through the existing public staging/PR23 pipeline. It includes one
twentieth native linux/amd64 application start for CI103 attempt1. This is a
recorded interpretation of the current request, not a numerical human reply.
It supersedes ADR0130's prohibition on a twentieth start only for this exact
corrected attempt; all prior starts remain spent.

## Context

CI102 attempt1, run41256071243, tested staging
61932a87b1f9c8364069793fc8520d29958eb1d8 through merge
e18f6ac9ab6c78edaf1cde7b692ddbfe8ebb1240 and tree
8971264ee6a17895a4c2563f14751993658196ea. Six jobs passed. Unit reported six
failures; staging smoke passed, measured integration reported three failures
and five setup errors, and the abrupt leg passed. Main system built one native
AMD candidate and then refused the obsolete btree-only restore expectation.
The candidate is EXECUTED_FAIL and NOT ACCEPTED. Its nineteenth native build
start and verified terminal cleanup are retained independently of success.

The failures cross existing tests and diagnostic contracts affected by ADR0129:
PostgreSQL metadata capabilities, lexical role SQL, the fixed read-only tool
catalog, separately versioned installed migration catalogs, owned disposable
schema reset and PostgreSQL core GIN indexes in backup/restore. Correct those
contracts without removing W3 support, relaxing privacy/credential isolation,
rewriting migrations, suppressing tests or weakening qualification.

CI102 passed both hard coverage gates. Unit statements were57382/65359 and
branches18506/21338; measured integration statements58640/65359 and
branches17328/21338. The requested two-point margins remain87% unit and82%
integration. Extend useful current-slice tests using retained per-file data;
hosted CI alone measures the complete successor populations.

## Decision and scope

Permit one ordinary staging push after completed repair and review, producing
one automatic PR23 synchronize campaign, CI103 attempt1. Reserve exactly one
twentieth native linux/amd64 application start, with total/per-platform cap20.
Keep all19 actual consumption observations, historical grants/reservations,
unused-binding supersessions and every spent-identifier refusal. Both grant
validators must reject CI102's spent final nonce and reservation hash.

Bind the grant to current frozen runtime context, repository, workflow, event,
PR23, staging-before61932a8, unchanged approved main base5ad00d1 and exact merge
parents/tree. A repair limited to test/diagnostic owners may preserve the runtime
context; unchanged context does not make a spent grant reusable. Preserve native
admission, exclusive consumption, write-ahead build intent and exact cleanup.

Supplier pins, Debian stable-slim/Trixie responsibility, dynamic Psycopg linking,
dependencies, SDK/application recipes, runner policy, debt ceilings and all
other security dispositions remain unchanged. Hosted setup may materialize its
unchanged SDK at most once. Scoped disposable-container integration may use
the existing five frozen setup prerequisites. Existing offline project-wheel
packaging tests remain in scope; no new dependency acquisition follows.

## Verification, publication and stop boundary

Require exact scoped unit and containerized integration selectors with
--no-coverage; affected existing owners and regression/negative tests; retained
static enforcement with no debt regression; compilation, topology, length,
export and privacy checks; fresh final source/evidence/grant review; and exact
protected-checkout preservation. No complete local Python suite or Python
project coverage, local application/SDK build, new image or infrastructure is
authorized. Local scoped results do not qualify the whole candidate.

Commit the completed repair once with Samuel Leighton Lair
<sam.lair@knowledge-forge.ai> as author and committer and generate its exact-commit
report. Recheck public refs, current PR23 and latest completed campaign before
the ordinary fast-forward staging push. Stop after verifying CI103 attempt1
starts automatically, with same-candidate qualification pending.

No twenty-first start, automatic retry, rerun, duplicate dispatch, PR-state
change, public-main promotion, tag, package publication, repository rename,
live deployment, extension admission, calibration rerun or held-out query is
included. A later executed failure requires separate next-attempt authority.
Historical source/evaluation artifacts and lineage remain immutable. Rollback
is a reviewed forward repair, never a history rewrite.
