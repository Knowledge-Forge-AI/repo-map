# ADR 0082: Navigation source admission before processing bounds

## Status

Authorized candidate design for REPOMAP-PRODUCT6-NAVIGATION5-SCOPE-PUSHDOWN1;
dispatcher review and checkpoint remain pending.

## Date

2026-10-15

## Context

ADR 0081 applies source restrictions after bounded candidate reads. Unrelated
literal matches can exhaust those bounds before a small requested subtree is
considered. Larger unscoped fetches would preserve that limitation.

## Decision

For explicit bindings, admit subjects relationally with selected-run direct
evidence before the unchanged node cap. Run selection precedes role/source
selection. A connection-local predicate reuses the locator projection, vector
corroboration, public sanitization and definitive navigation scope predicate.
The configured adapter supplies the same private markers as presentation;
storage does not import server presentation or read source files.

An existential match admits a subject. The subsequent evidence query restricts
subjects to admitted IDs and retains every selected-run direct alternative,
including withheld and conflicting alternatives, before the unchanged evidence
cap. Grouping still precedes output pagination. No JSON SQL extension, schema,
persisted index, dependency or reingestion is required.

Admission decoding has separate per-request limits on predicate evaluations and
JSON bytes. Exhaustion aborts the query and returns incomplete with no page.
Vectors are decoded and charged once per selected run in a request-local,
byte-budgeted cache; metadata is charged per predicate evaluation. Repeated
callback input bytes are disclosed separately from decoding charges. The
locator's projection accepts that decoded vector without changing its defaults.
SQLite internal scan/sort work remains distinct from decoded admission facts
and transferred headers/evidence; this decision promises no latency bound.

## Diagnostics and compatibility

Unscoped behavior and bounds remain unchanged. Scoped scan.nodes/evidence count
admitted subjects/all their direct alternatives, capped at the processing
bounds. Admission checks/bytes are reported separately. Global exclusion is
not counted: scope_excluded_count is null with an explicit basis. Complete
scoped results report post-admission scope exclusions separately (expected zero).
Non-budget callback exceptions retain their Python cause outside SQLite.
A complete empty admitted set is valid; incomplete offsets cannot resume scans.
The public tool and input schema remain unchanged. PostgreSQL retains its
feature-specific unsupported result. Reads use one existing bound transaction;
separate requests retain independent snapshots.

## Verification and rollback

Compare captured-entry complete results, ignoring only documented diagnostic
changes. Use real Python/Markdown publication, an independent full fixture
oracle, production-limit overflow corpora, all-alternative ambiguity/history/
redaction checks, finite stdio, query-count/plan observations and focused
compatibility checks. Synthetic bulk/corrupt mutations must be disclosed.
Rollback restores only this phase's captured preimages; accepted earlier work
is preserved. No Git mutation, runtime migration or source acquisition occurs.

Rejected: cap increases, iterative unscoped paging, evidence pruning after an
existential match, whole-corpus Python materialization, per-node backend reads,
and global exclusion counts inferred from a scoped population.
