# RepoMap Phase Identity Policy

## Purpose

This policy defines the canonical identity model for RepoMap phases. It keeps
phase IDs usable as stable keys across public documentation, private
manager/worker tasks, private review reports, status indexing, roadmap
sequencing, future CI checks, and curated public Git history.

The policy prevents one semantic identifier from naming multiple phases while
preserving immutable historical evidence and narrowly scoped aliases.

## Scope

This policy applies to tracked public-facing documentation in:

- `README.md`;
- `AGENTS.md`;
- `CONTRIBUTING.md`;
- `COMMERCIAL-LICENSE.md`;
- `CLA.md`;
- `docs/**`.

It defines the public identity boundary for private tasks and reports but does
not authorize inspection or mutation of private control-plane artifacts. The
documentation-history reference rules in
`docs/contrib/documentation-reference-policy.md` remain complementary: commit
SHAs identify private review evidence, while canonical phase IDs identify the
durable development record.

## Definitions

### Canonical Phase ID

A canonical phase ID is the globally unique semantic identifier assigned to
one RepoMap phase. It is independent of private commit identity, stable across
private/public history curation, and used consistently in the phase's primary
status heading, roadmap assignment, active documentation, tasks, prompts, and
new reports.

One canonical phase ID maps to exactly one primary status document. An alias
does not create another canonical identity.

### Phase Namespace

A phase namespace is the readable nonnumeric family identity used to allocate
a related numeric phase series. Examples include:

```text
STORAGE-ROWS
STORAGE-SUMMARY-ROWS
STORAGE-SQL
STORAGE-PKG
PSYCOPG
```

Those examples are distinct namespaces. A focused subtrack must use a distinct
specific namespace rather than restart numbering under its broader parent's
namespace.

### Primary Status Document

A primary status document is the single authoritative status record for one
canonical phase ID. It owns the canonical H1 heading, phase scope, outcome,
verification summary, and successor or closeout decision.

### Supporting Status Document

A supporting status document records evidence for a primary phase, such as a
smoke execution, supplemental audit, or documentation increment. It does not
allocate another canonical ID. Historical supporting records remain
grandfathered under `docs/status/`. New supporting evidence must identify the
primary status path and use an existing purpose-owned directory unless a
separate explicit decision authorizes another status record.

The accepted legacy M1 classification is:

| Role | Status path | Identity interpretation |
| --- | --- | --- |
| Primary | `docs/status/2026/06/29/00009-m1-mcp-readonly-exit.md` | Canonical phase `M1`. |
| Supporting | `docs/status/2026/06/29/00010-m1-codex-smoke.md` | M1 smoke evidence, not a second phase assignment. |
| Supporting | `docs/status/2026/06/29/00011-m1-agent-skill-docs-exit.md` | M1 documentation evidence, not a second phase assignment. |

This exact legacy classification resolves the raw duplicate heading tokens. It
is not permission to add multiple unlabeled primary records for a future ID.

### Historical Alias

A historical alias is scoped interpretive metadata that maps an old label to a
canonical phase in an immutable-history context. It is not a canonical ID, does
not reserve a namespace, and cannot be translated without its discriminator.

## Canonical Identity Rules

### Global Uniqueness

- No two primary status documents may claim the same canonical phase ID.
- No two active roadmap tracks may assign the same canonical phase ID.
- A new phase namespace must be checked against all existing canonical prefixes
  and full IDs before its first use.
- Numeric suffix reuse is allowed only under a distinct noncolliding prefix.
- Phase IDs are case-sensitive; canonical spelling is uppercase.
- An alias never creates a second canonical identity or permits a second
  primary status record.

Duplicate identity is a documentation correctness failure even when filenames,
dates, commit subjects, or status sequence numbers differ enough for a reader
to infer the intended phase.

### Namespace Reservation

A namespace becomes reserved when an accepted primary status document or
roadmap record assigns its first canonical numeric phase. Later phases in the
same semantic family may continue the namespace.

A new family must choose a more specific readable prefix when an existing
namespace is already reserved. Broad prefixes belong to broad tracks; focused
subtracks use focused prefixes. For example, `STORAGE-ROWS` names the broad
row-facade decomposition, while `STORAGE-SUMMARY-ROWS` names the focused
summary-row decomposition.

Do not create distinct namespaces that differ only by punctuation,
singular/plural spelling, word order with the same meaning, or an unexplained
abbreviation. An abbreviation must remain readable, stable, and unambiguous in
roadmap and report contexts.

Namespace reservation is semantic. Deleting a planned phase or moving a status
file does not silently release the namespace for unrelated reuse. Reuse or
retirement requires an explicit documentation decision.

### Naming Convention

New canonical phase IDs use uppercase ASCII letters, digits, and single
hyphens. They begin with a letter, include a readable namespace, and include a
numeric phase component. The spelling used at first accepted assignment is
case-sensitive and stable.

Preferred forms are:

```text
PHASE-ID2
STORAGE-SUMMARY-ROWS3
PSYCOPG24
```

New IDs must not use underscores or punctuation-only variants. Existing
accepted legacy spellings such as `GITHUB_API1` remain canonical until an
explicit remediation phase changes them; they are not templates for new IDs.
Existing accepted specialization forms such as `PKG5-LANG` also remain valid
full canonical IDs and are compared as complete tokens.

## Status-Document Consistency

A primary status document must:

- include exactly one canonical phase ID in its H1 heading;
- claim exactly one primary canonical phase identity;
- use the canonical spelling throughout active phase prose;
- use a filename stem consistent with the canonical ID;
- preserve its global five-digit status sequence independently from the phase's
  numeric component;
- be an exit report when newly created under `docs/status/`, with a filename
  ending in `-exit.md` and an H1 title containing `Exit`;
- state a truthful terminal disposition and record scope, outcome, validation,
  deferrals, and the next authorization;
- identify predecessors and successors by canonical ID;
- link or name the canonical status path when a cross-document reference needs
  durable evidence;
- mention a retired alias only in clearly labeled remediation, alias, or
  immutable-history prose.

For new canonical IDs, the filename token is the lowercase canonical ID:

```text
STORAGE-SUMMARY-ROWS3
→ storage-summary-rows3
```

The filename shape for a new primary phase record is:

```text
docs/status/YYYY/MM/DD/NNNNN-<canonical-phase-token>-<descriptive-suffix>-exit.md
```

The directory date comes from the introducing commit's committer timestamp,
using the calendar date encoded in that timestamp's numeric offset. Existing
historical basenames, H1 titles, roles, and non-exit framing remain
grandfathered and are not templates for new records.

For grandfathered IDs containing an underscore, filename comparison converts
the underscore to a hyphen. Existing accepted filenames with a legacy
`phase-` prefix or other harmless descriptive variation do not require a rename
unless the variation creates ambiguity, breaks links, or prevents deterministic
tooling.

A supporting status document may refer to the primary phase ID but must not
present itself as another primary assignment. New supporting evidence should
use a heading such as “Supporting Evidence For `<ID>`” and cite the primary
status path. A non-exit supporting document does not belong under
`docs/status/` without a separate explicit decision.

## Roadmap Consistency

- Every roadmap phase assignment uses the canonical phase ID.
- A completed phase note identifies or points to its canonical primary status
  document when the durable evidence is not otherwise clear.
- Planned future IDs are checked against reserved namespaces and assigned IDs
  before publication.
- One roadmap section must not restart an existing numeric namespace for an
  unrelated or narrower family.
- A documentation rename updates active roadmap references and status paths but
  does not rewrite immutable Git history.
- Retired aliases appear only in explicit historical collision or remediation
  explanations paired with canonical context.

Roadmap planning does not override an already accepted primary status identity.
If a planned ID conflicts with an accepted ID, the planned phase must be
renamed before implementation.

## Historical Alias Rules

The approved alias ledger is:

```text
docs/contrib/phase-id-aliases.md
```

Aliases are scoped interpretive metadata. Every entry must include:

- the exact historical alias;
- one canonical target;
- a durable discriminator, such as status sequence, canonical path,
  date/subject context, or exact private report binding;
- the immutable-history reason for retaining the alias;
- a review condition when the entry may become stale.

A bare colliding alias must not be globally translated. Aliases do not reserve
namespaces and must not appear in new primary status headings, active roadmap
assignments, tasks, prompts, or new report identities. Stale, unused,
ambiguous, malformed, or overbroad entries are policy failures.

Historical aliases may remain in:

- immutable commit subjects;
- existing private reports;
- the approved alias ledger;
- explicit collision inventories and remediation closeouts;
- quoted immutable-history prose that supplies the canonical target and
  discriminator.

## Immutable Git-History Boundary

Historical commit subjects are evidence, not the canonical phase registry.
They are not rewritten merely to align with a later phase-ID normalization.
Active documentation supplies alias context when an immutable subject uses a
retired ID.

Do not create fake replacement commits solely to restate an old phase under a
new label. A documentation remediation commit records the canonical mapping
without pretending the earlier subject changed.

## Private Report Boundary

Existing private `git-show-report` artifacts may retain:

- the historical phase label used when generated;
- exact private commit identity;
- immutable commit subject;
- the exact status path used at generation time;
- private patch and verification evidence allowed by the control-plane policy.

For reports generated after a phase rename:

- use the canonical phase ID as the report identity;
- optionally include an explicit historical-alias field when reviewing an old
  commit;
- retain the exact private commit binding where trusted review requires it;
- do not silently rewrite an existing report.

Private reports remain outside public documentation. Establishing or migrating
their `repo-map_ctrl` structure is separate authorized work.

## Future Phase-ID Scanner Contract

A future repository-owned scanner should inspect only Git-tracked public
documentation in the policy scope. Scanner implementation is not part of this
policy phase.

### Inputs And Classification

The scanner should:

- obtain its file list from Git;
- identify primary and explicitly supporting status documents;
- extract candidate H1 phase IDs before scanning secondary prose;
- classify canonical IDs, historical aliases, generic family/range prose,
  quoted immutable commit subjects, examples, and false positives separately;
- recognize exact grandfathered spellings and approved supporting-record
  classifications;
- load exact alias entries from the tracked alias policy.

It must not treat every uppercase token containing a digit as a canonical phase
ID.

### Required Checks

The scanner should:

- reject duplicate canonical IDs across primary status documents;
- reject multiple primary status documents for one canonical ID;
- verify H1/filename consistency under the normalization rules;
- verify active roadmap assignments and status references use canonical IDs;
- detect duplicate or deceptively similar namespace assignments;
- reject retired aliases outside approved historical contexts;
- validate the canonical target and discriminator of every alias entry;
- fail stale or unused aliases and supporting-record exceptions;
- detect active links to retired status paths;
- recommend the canonical replacement for each violation.

### Diagnostics

Diagnostics must be deterministic and include:

- repository-relative file path;
- line number;
- candidate token;
- classification and violated rule;
- canonical replacement or required discriminator;
- bounded public-safe context.

Diagnostics must not include private paths, private report content, secrets, or
raw untracked data.

### Prohibited Scanner Behavior

The scanner must not:

- inspect untracked files, private reports, or unrelated repositories;
- follow URLs;
- rewrite documentation automatically;
- use a Git commit SHA as public canonical identity;
- depend only on a token regular expression;
- globally translate an alias without its discriminator;
- infer that a commit subject overrides the canonical status record.

Deterministic tests should use public-safe synthetic headings, filenames,
roadmap entries, aliases, and supporting-record fixtures.

## Registry Decision

RepoMap does not need a separate machine-readable phase registry now. Primary
status documents, canonical roadmap records, this policy, and the scoped alias
ledger provide sufficient tracked authority. A future scanner can derive
canonical IDs deterministically from those records.

Introduce a separate registry only if derivation becomes ambiguous or costly,
if multiple tools require a stable serialized index, or if status/roadmap
structure can no longer express primary and supporting relationships clearly.
Any future registry must be generated or reviewed against the canonical docs;
it must not silently become a competing source of truth.

## STORAGE-ROWS Collision Resolution

The motivating collision is closed:

- `STORAGE-ROWS0` through `STORAGE-ROWS10` identify only the earlier broad
  `storage/rows.py` decomposition;
- `STORAGE-SUMMARY-ROWS0` through `STORAGE-SUMMARY-ROWS7` identify only the
  later focused `storage/summary_rows.py` decomposition;
- active links use the renamed summary-row status paths;
- old Family B labels remain only as scoped historical aliases in the approved
  alias and remediation contexts;
- immutable commit subjects and existing private reports remain unchanged.

The resolution demonstrates the policy rule: retain the semantically accurate
reserved broad namespace and assign a specific namespace to the focused
subtrack.

## Maintenance And Review

Before accepting a new phase family or identifier, the author and reviewer
must check existing primary status headings, roadmap assignments, namespaces,
and aliases. The phase status and commit body should record the chosen ID and
docs-only or source verification boundary.

Policy or alias changes require focused documentation review. A future scanner
finding is not waived by convenience; collisions must be resolved semantically,
and exceptions must remain exact, documented, reviewable, and removable.
