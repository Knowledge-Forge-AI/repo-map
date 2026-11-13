# ADR 0194: Repair capture test injection owners and request one CI144 campaign

## Status and authority

Selected for REPOMAP-CLOE-CI143REPAIR1 on 2026-11-13 under the current operator
request, "Ci failed try again". This new request supplies one fresh staging
repair campaign; ADR0193's CI143 allocation remains spent and is never rearmed.
Hosted capacity AVAILABLE remains operator-set and unrescinded. Keep PR23 open
and draft, public main unchanged, and the required public author and committer.

## Failure and decision

CI143 attempt1 executed at public head 9081d5e0c56635ce05086e3758c7622664e37bf4.
One unit test and seven integration cases failed. The capture refactor moved
semantic identity calculation into `_capture_identity` and assembly into
`_capture_candidate`. Tests still patched facade aliases, so their injected
identity/provenance changes never reached those consumers. The four deliberately
late facade engine seams remain unchanged. No production validation defect or
new public behavior is established by this failure.

Reproduce those exact failures, then patch the current lookup owners in the
existing tests. Preserve all identity distinctions and seven provenance refusal
assertions. Explicitly witness the routed observation injection. Keep public
capture, real inventory, validation and source preservation in the integration
proof. Do not add runtime hooks solely for tests or weaken expected refusal.

CI143 hard coverage gates passed: unit 92.8% statements/87.0% branches and
integration 89.2%/80.1%. Desired 87/82 cushions remain a hosted measurement aim;
the integration cushion is not yet established. Static, system and native jobs
passed, but the whole candidate remains EXECUTED_FAIL. No local complete suite
or local Python coverage is selected as a substitute.

## Fresh accounting and binding

Retain the full previous ledger and append actual CI143 consumption, checked
against its hash-bound system/Rust artifacts: one application build, one qualifier
entry and two pinned wheel transfers. Cumulative actual totals become 52/23/48.
Actual Rust component runtime entries become 22, separate from the conservative
charged qualifier entries (including the earlier prework refusal).

The current request selects only CI144 attempt1: one application start, one
existing qualifier entry and two unchanged pinned wheels. Cumulative ceilings
53/24/50 are limits, not consumption. Retire CI143 nonce and reservation forever.
Freeze source identity and original guard pin before rendering the approval,
guard, manifest and reservation DAG; copy pin dictionaries before substituting
the rendered guard. Recompute official application context and native closure.
Keep every historical ledger prefix, spent identity and guard negative. Current
53 caps are valid; old52 and future54 are invalid. Current ordinal144 is valid;
old143 and future145 are invalid. Preserve guard/test physical lengths and all
dependency, type, debt, coverage, native wheel, guest and scenario policies.

## Proof and publication

Run the affected scoped canonical unit and container integration owners with
--no-coverage, strict static/type/retained checks, privacy, suppression, topology,
export, length, compilation and whitespace checks. Independent dynamic_default
review reads the complete changed tests, binding owners, official capture owners,
binding implementation, exact edits, authority/accounting and proof evidence.
Freeze the reviewed tree, commit exact reviewed blobs, retain a local report,
verify current remote refs/PR/completed CI143, then make one normal fast-forward
staging push. Observe automatic CI144 attempt1 for that exact head.

No automatic retry, duplicate dispatch, second push, CI145, main promotion,
release, image/platform acceptance, local build/pull, dependency/lock/runner class,
model study, complete local Python suite or local Python coverage is authorized.
Keep the protected checkout's source, HEAD, staged entries and physical index.
If push outcome is ambiguous, inspect read-only before any further decision.
Hosted qualification remains pending until current candidate reports are audited.
