# ADR 0135: Repair CI105 context regressions and qualify one staging retry

## Status

Accepted by the local prompter under the current operator instruction,
"ci failed. try again", followed by "continue". This is a bounded parent
interpretation of that retry instruction, not a numerical human reply.
Final frozen scoped proof and independent review remain required.

## Date

2026-11-01

## Context

CI105 attempt1 executed for staging9c3e9685609e88b3daf42a899a7a4f49119826ae.
Eight jobs passed. The unit population reported two failures: the new context
budget modules formed an import cycle, and the inherited-lineage regression
test omitted the reviewed W4 forward admission. The zero-cycle policy and the
lineage audit themselves remain correct and must not be weakened.

Hosted unit branch coverage was19329/22346 and integration branch coverage was
18042/22346. Both passed their hard gates but remained below the operator's
desired87/82 margins. Useful new-context validation, selection, ranking,
filesystem and adapter boundary tests should improve those margins. Complete
coverage measurement remains owned by hosted CI.

The retained system report proves one actual native AMD application start for
CI105, with successful qualification and terminal cleanup. All22 observed
starts remain spent. The previous grant cannot authorize a successor.

## Decision

Remove the budget module's reservation-helper re-export and import reservation
helpers from their owning module. Keep primitive serialization independent from
reservation. Update the lineage regression's exact forward-admission list and
retain every existing historical proof and debt ceiling. Add proportional
behavioral tests without changing coverage denominators, thresholds or suites.

The current retry instruction authorizes one reviewed forward correction and
one ordinary staging publication through existing draft PR23. Bind CI106
attempt1 to staging's predecessor9c3e9685609e88b3daf42a899a7a4f49119826ae and
main5ad00d162ad8a04430874275246a53227578c533, rechecking refs and ordinal before
publication. No automatic retry, rerun, PR-state change or main promotion joins
this campaign.

Allocate at most one additional native linux/amd64 application start to the
existing sole system builder: cumulative total/per-platform ceiling23 after22
observed starts. Retain predecessor consumption and reservation records. Use a
fresh nonce, reservation, authority digest and final product-source context.
Allow at most one unchanged hosted SDK materialization. Local application and
SDK builds remain excluded. A failed or canceled start consumes its slot.

## Proof and boundaries

Use exact scoped canonical unit and containerized integration selectors with
`--no-coverage`, followed by retained-Python enforcement, changed-file checks
and one independent dogfood `dynamic_default` checkpoint. Parent integration
owns worker disposition and fresh resulting-state evidence. Scoped proof makes
no complete-population or measured coverage claim;87/82 remains a hosted target.

Preserve the protected contribution checkout, published ancestry, dependencies,
supplier pins, workflow and runner policy, schema, MCP surface, scientific
criteria and held-out queries. No tag, release, repository rename, production
admission or live operation is authorized. Generate the exact-commit report
before publication. Whole-candidate acceptance remains pending hosted results.

## Alternatives and rollback

Adding a cycle allowance would conceal the new architecture regression.
Dropping the lineage assertion would weaken proof continuity. Reusing CI105's
grant would reuse a spent slot. Repeating complete local suites would violate
the operator's scoped-testing decision. Reject these alternatives.

Use ordinary forward corrections; never rewrite the published milestone.
Failure of the new campaign requires diagnosis and fresh operator retry
authority before another publication or application start.
