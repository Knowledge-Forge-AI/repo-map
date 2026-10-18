# ADR 0079: Opt-in direct node source evidence view

## Status

Implementation decision for REPOMAP-PRODUCT6-NAVIGATION2-DIRECT-SOURCE1.
The dispatcher-owned work review is complete. The final in-run revisor amended
the candidate within this decision; dispatcher finalization and manager
acceptance remain external. No second independent review follows the revision.

## Date

2026-10-14

## Context

ADR 0078's locator returns a mixed stored-evidence window. Earlier incoming
Markdown links can fill a small window before the selected document's own
observation. The mixed window's ambiguity does not prove contradictory
definitions. SOURCE-LOCATOR1's accepted readbacks and closed pilot remain
accepted; no performance improvement is established.

## Decision

Add one optional `evidence_role` selector to `repomap_node_locations`, with
values `all` (default), `direct`, `reference`, and `unknown`. The `all` view
preserves the existing response shape, order, run selection and bounds.
Filtered views label their returned evidence roles explicitly. Apply the role
predicate in SQLite before deterministic ordering and `LIMIT limit + 1`, in
both the main and separately bounded historical window. Search is unchanged.

Role support comes from persisted canonical producer facts:

- `direct`: an `observed` link with a matching canonical subject kind and
  raw kind: Python module/class/function/method, or Markdown document/page,
  heading/section, ADR metadata/ADR, skill metadata/skill. The Python and
  Markdown definition producers place `observed` on their subject and
  `inferred_from_edge` on the containing file. This is subject evidence,
  not proof of runtime behavior or filesystem freshness.
- `reference`: `inferred_from_edge`, meaning indirect edge context. A
  Markdown incoming link is in this role; its range belongs to the referring
  document. This role includes context on either edge endpoint, a page's outgoing
  links, and definition evidence on its containing file.
- `unknown`: all other combinations, including unsupported `observed` kinds
  or inconsistent subject kinds. Missing raw payloads or source metadata do
  not erase supported canonical producer facts. An unbound `doc_path`
  metadata lead has unknown role and is never direct evidence.

The evidence run is selected using all linked evidence before role filtering,
as in ADR 0078. Accepted references with no direct evidence yield an empty
accepted direct window. Older direct observations remain in history. When
the accepted run has no links, the newest linked historical run remains the
main run, even if its filtered window is empty; earlier matching evidence stays
in history. Filtering never searches for an older run to imply current success.

## Boundaries and consequences

No schema, migration, ingestion, extraction, source acquisition, ranking,
deduplication, dependencies or backend expansion. PostgreSQL retains ordinary
`backend_unsupported`. Visibility, graph/repository binding, read transaction,
sanitization and native fallback remain unchanged. Paths and nullable ranges
come only from stored evidence. Binding aliases and source-relative paths must
be mapped to the user's source root explicitly; keys are not decoded into paths.

Contradictory direct rows remain distinct. `has_more` refers to matching rows;
one returned row with truncation cannot establish uniqueness. Metadata-only,
reference-only, unknown and unavailable provenance remain bounded data states.
Native navigation remains available without RepoMap.

Filtered metadata-only windows report `ambiguity=metadata_only`; an unknown
unbound metadata path cannot establish a stored location for the requested role.
The default view keeps its existing metadata status and ambiguity. A filtered
main window with no usable lead, metadata lead or truncation reports
`status=unavailable` with `reason=historical_locations_only` when its returned
historical window has a usable path. This signal does not promote old evidence
to the selected run. Withheld historical paths do not produce that reason.

## Verification and rollback

Use actual canonicalization/publication fixtures and the callable SQLite read
adapter for mixed documents, small limits, Python subjects, path-only documents,
missing raw/metadata, unknown roles, conflicting ranges, retained and moved
history, isolation, unsupported backend and default/search compatibility.
Update the guarded stdio integration owner; container execution is prohibited
by this task and remains explicitly unexecuted. No backend parity is claimed.
Rollback removes the selector and predicate without storage migration.

Read the handoff first and verify supplied locations directly. Use the direct
view only for unresolved subjects, and reference/default evidence for callers,
mentions, outgoing links and containment context. This does not require
demonstration queries or reopen the closed pilot.
