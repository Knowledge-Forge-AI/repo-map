# ADR 0042: Daily ADR and Status Archive Layout

## Status

Accepted

## Date

2026-07-19

## Context

RepoMap's ADR and status archives use repository-global sequence numbers, but
their month-only directories make the large status archive increasingly hard
to navigate. Historical status records also predate the current preference for
terminal exit reports. Their varied framing is part of the project record and
must not be used as a reason to reclassify, rename, or semantically rewrite the
archive.

The archive needs a deterministic placement rule that survives later edits and
moves. The rule must preserve local date intent for records introduced near a
calendar boundary, keep public references durable across private and curated
Git histories, and retain independent ADR and status numbering.

## Decision

RepoMap uses these archive layouts:

```text
docs/adr/YYYY/MM/NNNN-<slug>.md
docs/status/YYYY/MM/DD/NNNNN-<existing-basename>.md
```

ADRs remain under `docs/adr/`. Status documents remain under `docs/status/`.
ADR directories use the introduction year and month; status directories use
the introduction year, month, and day.

For each logical document, placement is derived from the commit that first
introduced it. The timestamp authority is that commit's committer timestamp.
The calendar date is interpreted exactly in the timestamp's recorded numeric
offset; it is not converted to UTC or to the reviewing machine's timezone.
Later edits, renames, moves, title changes, acceptance changes, or corrections
do not alter the assigned introduction date.

## Historical Archive Preservation

The migration preserves every historical status document under
`docs/status/`. Each historical record keeps its existing five-digit number,
filename basename, H1 title, and semantic role. Records that do not use an
`-exit.md` suffix or an H1 containing `Exit` are grandfathered historical
records. They are not renamed, retitled, split, merged, or moved to another
document class.

Historical status records are not reclassified into evidence, epic,
specification, testing, contributor, or newly invented archive directories.
The migration creates no compatibility stubs or symlinks.

Existing ADR numbers, filename basenames, and H1 titles also remain stable.

## Forward Status Convention

Every new primary phase record created under `docs/status/` is an exit report
with this shape:

```text
docs/status/YYYY/MM/DD/NNNNN-<phase>-<slug>-exit.md
```

A new exit report:

- uses the next repository-global five-digit status number;
- ends in `-exit.md`;
- has an H1 title containing `Exit`;
- states a truthful terminal disposition;
- records scope, outcome, validation, deferrals, and the next authorization;
  and
- preserves RepoMap's privacy and public-history boundaries.

A future non-exit document must use an existing purpose-owned directory or
receive a separate explicit decision. Historical deviations do not authorize
new deviations.

## Counter Semantics

ADR numbers remain a repository-global, monotonic four-digit sequence. Status
numbers remain a repository-global, monotonic five-digit sequence. Assigned
numbers are stable and are not compacted, reused, or changed by an archive
move. The ADR and status sequences are independent.

New numbers are allocated from accepted `main` after the relevant archive has
been rechecked. Multiple records introduced in one commit share the same
introduction date but retain distinct sequence numbers.

## Migration Contract

DOC-LAYOUT0 performs one atomic path and active-reference migration:

- move existing ADRs to their introduction `YYYY/MM` directories;
- move existing status documents to their introduction `YYYY/MM/DD`
  directories;
- preserve historical numbers, basenames, H1 titles, content, and archive
  ownership except for narrowly required current path-reference changes;
- update active references, indexes, contributor guidance, roadmaps, and
  current layout examples;
- retain obsolete paths only where they are deliberately historical,
  synthetic, or immutable evidence; and
- validate coverage, uniqueness, placement, references, fragments, and
  privacy from the complete staged state.

Git history and the atomic migration commit are the durable old-to-new record.
No redirect stubs, symlinks, committed migration map, durable migration
framework, dependency, or history rewrite is introduced.

## Scope and Non-Scope

This decision governs ADR and status archive placement, introduction-date
semantics, numbering stability, the DOC-LAYOUT0 migration, and the forward
status exit convention.

It does not:

- reinterpret the semantic role of any historical status document;
- normalize historical filenames or H1 titles;
- retrofit historical content to the current exit-report template;
- create a generic replacement directory for non-exit documents;
- change source, test, schema, migration, storage, CLI, MCP, or runtime
  behavior; or
- rewrite Git history or immutable commit subjects.

## Active and Historical References

Current documentation references use the new canonical paths. Markdown links
and fragments remain valid after the move. Old-layout occurrences may remain
only when review classifies them as deliberate historical evidence, synthetic
fixtures or examples, or immutable Git/report evidence. Such occurrences are
not current canonical path guidance.

Public documentation continues to use semantic phase IDs, status paths, ADR
paths, roadmaps, and public repository identities rather than private
development commit identities.

## Alternatives Considered

### Retain the month-only layout

Rejected. It preserves the current navigation pressure and does not establish
the accepted daily status organization.

### Perform the accepted path-only migration

Accepted. It improves archive organization while preserving document identity,
content, numbering, and ownership.

### Classify and move non-exit records elsewhere

Rejected. Historical variation does not justify semantic reclassification,
and moving records to evidence, epic, specification, testing, contributor, or
new generic directories would change archive meaning beyond this phase.

### Retrofit every historical record to exit framing

Rejected for DOC-LAYOUT0. Renaming historical basenames and H1 titles would
rewrite the record rather than reorganize it. Broader historical framing
cleanup is deferred unless separately authorized.

## Consequences

- ADR paths gain separate year and month directory components.
- Status paths gain separate year, month, and day directory components.
- All historical status records remain discoverable under `docs/status/`.
- Historical non-exit framing remains visible as grandfathered project
  history.
- New status records have a stricter, reviewable exit-report contract.
- Active references must be updated whenever archive records move.
- The archive can be validated deterministically from Git introduction
  evidence without depending on private commit identities in public text.

## Deferred Work

DOC-LAYOUT0 does not add an executable archive-layout validator or perform a
semantic classification of historical records. Any future validator or
historical framing cleanup requires separate authorization.
