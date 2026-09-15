# ADR 0051: PostgreSQL Extension And Database-Capability Architecture

## Status

Accepted. Docs-only. This ADR decides architecture; it admits no extension,
authorizes no implementation, and changes no schema, image, or dependency.

## Date

2026-08-13

## Context

RepoMap stores its canonical graph in PostgreSQL as ordinary relational tables
with JSONB metadata, as `docs/specs/storage-model.md` records. Schema versioning
is a RepoMap-owned Liquibase-formatted loader: `discover_migrations` walks the
`includeAll` paths of `changelog.yaml`, requires a formatted-SQL header and a
changeset line, and records `(ordinal, changeset_id, migration_path, sha256)` in
`repomap_schema_migrations`. Readiness is exact — `CURRENT` only when applied
ledger rows equal discovered migration rows tuple for tuple.

RepoMap issues no `CREATE EXTENSION` anywhere: not in
`src/main/resources/rdbms/`, not in `repomap_kg.storage`, not in the lifecycle
and administration code. The question this ADR answers is therefore not "which
extension should RepoMap adopt" but "under what proof would RepoMap ever stop
declining to adopt one".

Three facts frame the decision.

First, the only shipped surface with a plausible extension-shaped need is
search. `build_canonical_node_search_sql` and `build_file_source_search_sql`
issue unanchored `ILIKE` predicates with leading and trailing wildcards over
`canonical_nodes.canonical_key`, `.kind`, `.display_name` and `files.path`,
`.language`, `.role`. `build_mcp_search_sql` (`server/ops.py:564`) does the same
over raw-observation `source_id`, `path`, and `payload_json::text`, so the
substring-search surface is broader than canonical-node and file search alone. A
leading wildcard has no general B-tree acceleration. Every other query RepoMap
issues is expressible in core PostgreSQL.

Second, RepoMap holds no accepted performance baseline. PERF-BASE1 (status
00721) ended in a bounded stop with `perf_base1_accepted: false`, explicitly
recording that this phase has no current baseline and that `PERF-BASE1-R1` was
not authorized. There is therefore no measured fact about search latency at any
graph size against which an extension could be justified.

Third, RepoMap's storage spec currently gestures at "full-text search and
trigram extensions for search" and "optional vector extensions later" as
rationale for choosing PostgreSQL. Those phrases were written as reasons to
prefer PostgreSQL over a dedicated graph database. They have never been
decisions, and this ADR declines to let them become one by accretion.

The temptation this ADR exists to resist is that an extension looks cheap.
`CREATE EXTENSION pg_trgm;` is one statement. What that statement actually
commits RepoMap to — a server-side file dependency that migrations now assume,
a restore target that must have matching artifacts, a version identity nothing
currently records, native code in the backend address space, and an upstream
advisory-tracking obligation — is invisible at the call site.

## Problem Statement

Under what architecture may RepoMap admit a PostgreSQL extension, or any
database-server capability beyond the core contract, without weakening
deterministic readback, exact schema readiness, provable restore, least
privilege, or honest reporting of what the database can actually do?

### What would prove this ADR wrong

This ADR is wrong if any of the following is demonstrated:

- A conforming RepoMap deployment cannot be built, migrated, backed up, or
  restored using only the core PostgreSQL contract this ADR declares
  authoritative.
- The fact model in D2 cannot express a real state of a real server, or forces
  two independent facts into one value.
- A capability classified as removable under D10 turns out to require an exit
  migration, or one classified as requiring an exit migration turns out to be
  removable without transformation.
- The ordering in D7 is unimplementable against RepoMap's actual migration
  loader, or admits a sequence in which a migration discovers rather than
  requires a capability.
- A restore that satisfies every preflight in D9 nonetheless fails for an
  extension-related reason the preflight could have detected.
- The exception gate in D15 is satisfiable by a proposal that a reviewer would
  recognize as unsafe, or unsatisfiable by a proposal that is plainly sound.
- The decision to admit nothing is shown to have cost RepoMap a capability it
  demonstrably needed, on measured evidence rather than expectation.

## Definitions

**Core PostgreSQL contract.** The functionality a conforming PostgreSQL server
provides without any `CREATE EXTENSION` issued by RepoMap: SQL types and
operators including `LIKE`/`ILIKE`, B-tree/GIN/GiST/BRIN access methods, JSONB,
recursive CTEs, full-text search types and functions, constraints, and
transactions. This is what RepoMap uses today.

**Template-provided baseline extension.** An extension present in a RepoMap
database because PostgreSQL's own template database contains it, not because
RepoMap created it. `plpgsql` is the only current member. See D1.

**Database capability.** A named, versioned server-side facility that RepoMap
depends on beyond the core contract. Every extension is a capability; not every
capability need be an extension.

**Capability fact.** One observation on one of the orthogonal dimensions in D2.
Facts are recorded independently and never collapsed into a single state value.

**Ownership classification.** RepoMap's relationship to an extension observed in
a database: *required*, *permitted-foreign*, or *unclassified*. Defined in D3.
Presence in `pg_extension` establishes none of them.

**Lifecycle administration.** The authority that provisions databases, roles,
schema, backups, and restores. The only authority permitted to issue
`CREATE EXTENSION`, `ALTER EXTENSION`, or `DROP EXTENSION`. See D4.

**Capability readiness.** Whether a declared capability is usable in a given
database at a satisfying version with its dependent objects present. Orthogonal
to schema readiness. See D6.

**Exit migration.** A schema-and-data transformation that converts authoritative
values out of an extension-provided type or storage form so the extension can be
dropped. See D10.

**Semantic contract.** The result set a public RepoMap surface promises for
given inputs — which rows, in which order, with which bounds. Distinct from the
query implementation and from the access path the planner selects. See D11.

## Scope And Non-Scope

In scope: the baseline definition; the capability fact model; ownership
classification; lifecycle authority; database and server scope; readiness
composition; migration ordering; version and drift identity; backup and restore
obligations; rollback classification; the semantics-versus-acceleration
boundary; supply-chain and security classification; performance-evidence policy;
candidate dispositions; and the exception gate by which a future capability
could be admitted.

Out of scope: admitting any extension; installing, enabling, or upgrading any
extension; measuring anything; changing SQL, migrations, the schema manifest,
`pyproject.toml`, lockfiles, Compose, or any container image; implementing the
capability registry, readiness projection, manifest fields, or preflights this
ADR describes; authorizing embeddings, vector schema, model inference, or any
Cypher surface; and modifying ADR 0048, ADR 0049, or ADR 0050.

This ADR does not decide whether RepoMap supports arbitrary conforming
PostgreSQL servers or only its own digest-pinned runtime image. It records that
question as unresolved in Deferred Work, because D1 and D14 pull in different
directions and neither has the evidence to settle it.

## Evidence Hierarchy

ADR 0049 governs. This ADR adds no evidence authority. Three of its rules bind
here:

- An expectation may reject an observation but never becomes one (ADR 0049 D1).
  A capability declaration is an expectation; `pg_extension` is an observation.
- Semantic verification belongs at every acceptance boundary, and a consumer
  that cannot dispatch a declared semantic class fails closed (ADR 0049 D2).
- Candidate identity freezes the environment before execution (ADR 0049 D6). An
  extension version is part of that environment.

Repository facts in this ADR were read on 2026-08-13 from the repository state
accepted by status 00754, the state in which ADR 0050 was accepted. Every such
fact carries a `path:line` citation checkable against that state.

External PostgreSQL facts are load-bearing in the following places, each stated
so a reader can check it against upstream documentation:

| Fact | Where used |
| --- | --- |
| A `DO` block without a `LANGUAGE` clause defaults to `plpgsql`, and `plpgsql` is a default-installed extension recorded in `pg_extension` | D1 |
| `pg_available_extensions` exposes default and installed versions only | D2 |
| Extension functions commonly receive `PUBLIC` execute privileges on creation | D5 |
| `CREATE INDEX CONCURRENTLY` cannot run inside a transaction block; ordinary `CREATE INDEX` takes a lock that blocks writes but permits reads | D7 |
| A bare `CREATE EXTENSION` installs the server's default version | D8, D9 |
| `pg_dump` represents an extension as `CREATE EXTENSION` rather than dumping its member objects | D9 |
| `pg_extension.extconfig` and `extcondition` govern extension configuration tables, and `pg_extension_config_dump` is called by an extension's own script | D9 |
| `DROP EXTENSION` defaults to `RESTRICT` | D10 |
| `tsvector`/`tsquery` implement token and document search, not arbitrary substring matching; no B-tree or `text_pattern_ops` index generally accelerates a leading-wildcard pattern | D11 |
| "Trusted" is an installation-privilege property, and an extension may be SQL-only | D12 |

These were read from PostgreSQL's published documentation on 2026-08-13. Any
functional claim about a specific candidate extension is additional to this
inventory and is not asserted here as verified; see below.

No claim about any specific candidate extension's maturity, performance,
licensing, or vulnerability status is asserted here as a verified conclusion.
Phase DBEXT0's research packet is not committed, and ADR 0049 forbids a durable
claim resting solely on a phase-private packet. Every such fact must be
re-verified from primary sources at admission time under D15.

## Decision

### D1 — The baseline is "no RepoMap-admitted extension", not "zero extensions"

**[invariant]** The core PostgreSQL contract is authoritative. Every **currently
accepted** RepoMap product surface must remain fully implementable, migratable,
backupable, and restorable without any extension RepoMap admits, and a
core-only deployment must remain a conforming deployment.

**[invariant]** This is a floor, not a ceiling, and it is deliberately scoped to
today's surfaces so that it does not contradict D15. A future admitted
capability may back a *new* surface that the core cannot serve — that is the
only thing D15 exists to permit. What it may never do is make an existing
core-only surface, or the baseline deployment as a whole, depend on an
extension. Any proposal that would remove a currently accepted surface from the
core-only deployment is a change to this ADR, not an admission under it.

**[invariant]** RepoMap is nonetheless **not** a zero-extension deployment, and
this ADR refuses to say otherwise. Role reconciliation emits `DO $repomap$ …
$repomap$;` blocks with no `LANGUAGE` clause, whose default language is
`plpgsql` (`src/main/python/repomap_kg/runtime/database_roles.py:134`,
`:141`). A shipped graph migration does the same
(`src/main/resources/rdbms/2026/07/16-002-arch5d-drop-legacy-graph-schema.sql:4`).
`plpgsql` is a default-installed extension and is represented in
`pg_extension`. RepoMap therefore depends on an extension today.

**[invariant]** Those two citations are **representative, not exhaustive**. The
dependency is broad and runs through ordinary data-path SQL generation, not just
administration: `storage/repository_identity.py`,
`storage/publication_fencing.py`, `storage/staging_merge.py`,
`storage/canonical_staging_merge.py`, and `storage/staging_cleanup.py` all emit
language-unspecified `DO` blocks as well. Any future statement of RepoMap's
`plpgsql` dependency must be derived from the source rather than from this list.

**[invariant]** `plpgsql` is classified as a **template-provided baseline
extension**: present because PostgreSQL's template database contains it, not
created by RepoMap, and required by current behavior. It is exempt from the
admission gate in D15 and must appear in any allowlist D3 produces. A model
that omitted it would classify every ordinary RepoMap database as anomalous on
its first observation.

**[invariant]** "No extension is admitted" and "no extension is present" are
different statements. Documents, code, and diagnostics must not use one to mean
the other.

### D2 — Capability facts are orthogonal dimensions, never one lifecycle value

**[invariant]** An extension's state is recorded as independent facts on
separate dimensions. A single ordered enum is rejected as a modelling
primitive, because the underlying facts have different subjects — some are
properties of a server image, some of a cluster, some of one database, and some
of RepoMap policy — and are not mutually exclusive.

| Dimension | Subject | Records |
| --- | --- | --- |
| `observation` | the check itself | Whether the fact was successfully determined, or the check failed |
| `artifact_availability` | server or image | Whether control and script files are present for the extension |
| `available_versions` | server or image | Which versions are installable, and which update paths exist |
| `cluster_preload` | cluster | Whether the library is named in `shared_preload_libraries` |
| `database_installation` | one database | Whether a `pg_extension` row exists, with `extversion`, schema, and owner |
| `ownership` | RepoMap policy | The D3 classification |
| `dependent_objects` | one database | Whether RepoMap objects depending on the capability are present and valid |
| `capability_operational` | one database | Whether the capability is usable for its declared purpose |
| `drift` | derived | Any mismatch between required, permitted, and observed |

**[invariant]** These are not alternatives. An extension is routinely
*available* and *installed* simultaneously; a library may be *preloaded*
cluster-wide while its SQL objects are absent from a given database; and
availability is an image fact while installation is a database fact.

**[invariant]** Failure to observe is recorded on the `observation` dimension,
never as an extension state. "Unknown" describes RepoMap's knowledge, not the
server. Any consumer encountering an unsuccessful observation fails closed for
the decisions that depend on it.

**[invariant]** `pg_available_extensions` exposes default and installed versions
only. It does not establish that a specific required version, or an update path
to it, exists. `available_versions` must be determined from the versions and
update paths the server actually offers, not inferred from a default.

**[invariant]** An overall readiness answer is *derived* from these facts. It is
a projection, never a stored primitive, and no fact may be reconstructed from
it.

### D3 — Presence never creates ownership

**[invariant]** Observing an extension in a RepoMap database establishes only
that it is installed. RepoMap's relationship to it is a separate, policy-owned
classification:

| Classification | Meaning |
| --- | --- |
| *required* | RepoMap depends on it; its absence is a capability failure |
| *permitted-foreign* | Known and tolerated; RepoMap neither depends on it nor manages it |
| *unclassified* | Observed and not covered by policy |

**[invariant]** *Unclassified* is a real, reportable outcome and fails closed
for decisions that require a known capability set. It is neither silently
allowed nor treated as forbidden, because RepoMap does not own every database it
may be pointed at, and an operator's extension is not automatically an error.

**[invariant]** RepoMap never adopts, manages, upgrades, or drops an extension
it did not create. Discovering an extension does not make RepoMap responsible
for it, and does not make it available for RepoMap's use.

**[invariant]** A *required* classification names the extension, its **policy
version constraint**, and its dependency closure. Transitive extension
dependencies are classified explicitly; a dependency is not admitted by
implication from the extension that requires it.

**[invariant]** A policy version constraint and a realized version are different
things and this ADR keeps them apart throughout. The *constraint* may be exact
or explicitly bounded, and is what an admission record states. The *realization*
— what `pg_extension.extversion` holds in one database, what a backup manifest
records, and what a restore must reproduce — is always a single exact version.
D8, D9, and D15 refer to the realization; D3 refers to the constraint.

### D4 — Only lifecycle administration may change extension state

**[invariant]** `CREATE EXTENSION`, `ALTER EXTENSION`, and `DROP EXTENSION` are
lifecycle-administration operations exclusively. They are never issued by
read/status paths, refresh or publication paths, the coordinator, MCP or HTTP
surfaces, or as an incidental side effect of any query.

**[invariant]** No capability role is granted superuser or `CREATE` on the
database in order to make extension DDL possible. This is a property RepoMap
currently has and must not trade away: a capability role is created with `LOGIN`
only (`database_roles.py:137`) and then **reconciled to** `LOGIN NOSUPERUSER
NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS` by `ALTER ROLE`
(`:166`–`:167`), and `CREATE` on `public` is revoked from `PUBLIC` (`:64`).

**[invariant]** RepoMap never downloads, fetches, compiles, or installs an
extension artifact at any time — not during indexing, refresh, query, migration,
backup, or restore. Artifact acquisition belongs to image construction.

**[invariant]** Lazy creation on first use is prohibited outright. It would
require granting DDL authority to a query path, and would turn an incidental
read into a schema mutation.

### D5 — Scope is two independent declarations, and grant facts are stated accurately

**[invariant]** A future capability declares **two independent** scope facts,
because they are not alternatives:

| Declaration | Values | Subject |
| --- | --- | --- |
| Database scope | `graph`, `control`, or `both` | Which databases install the extension |
| Preload requirement | required, or not required | The cluster |

**[invariant]** A capability may require cluster preload *and* be installed in
one or both databases; the two say different things about different subjects.
Cluster preload is a configuration change requiring a server restart and is
never a per-database setting. Modelling preload as a fourth mutually exclusive
database-scope value is rejected, because it cannot express the ordinary case
and contradicts the separate `cluster_preload` and `database_installation`
dimensions in D2.

**[invariant]** Database scope is realized by **which databases have the
extension installed**, not by connection privileges. Database `CONNECT` does not
govern who may execute an extension's functions.

**[invariant]** The current grant model must be described correctly. The
read/status role receives `GRANT CONNECT` in the block common to both database
kinds (`database_roles.py:68`); it is not mutually excluded. Mutual exclusion
applies to the refresh and coordinator-control roles: graph grants revoke
control `CONNECT` and grant refresh `CONNECT, TEMPORARY` (`:177`–`:178`), and
control grants do the reverse (`:196`–`:197`). Any statement that "graph and
control CONNECT grants are mutually exclusive" is false and must not be used to
justify a scope boundary.

**[invariant]** Likewise, role reconciliation does not drop roles. It refuses to
reconcile when a capability role owns objects, raising `database capability role
owns objects` (`:153`), and otherwise alters the existing role (`:166`).
Extension objects must be owned by lifecycle administration; an extension owned
by a capability role would make that role permanently unreconcilable.

**[invariant]** Admitting a capability requires an explicit object-privilege
decision: installation schema, object owner, whether default `PUBLIC` execute
privileges are revoked, and which roles may call which functions. Extension
functions commonly receive `PUBLIC` execute privileges on creation; inheriting
that default silently would widen RepoMap's least-privilege model.

### D6 — Capability readiness is orthogonal to schema readiness

**[invariant]** Extension state is never encoded in a schema-readiness status
value. `GraphSchemaStatus` (`storage/main.py:38`) and `ControlSchemaStatus`
(`coordinator/_control_schema.py:42`) are differently shaped contracts — the
former has `UNMANAGED`, the latter `PRELEDGER`. Neither may be overloaded.

**[invariant]** Neither status is derived *solely* from ledger comparison, and
this ADR states the actual derivation rather than a tidier one. Both first apply
pre-ledger structural checks: graph readiness decides `UNINITIALIZED` and
`UNMANAGED` from table and ledger presence, and control readiness
(`coordinator/_control_schema.py:105`) checks the exact table set, the presence
of `jobs`, and the schema comment — each of which can return `DIVERGED` before
any ledger row is read. Only after those checks does either compare applied rows
to expected rows.

**[invariant]** `DIVERGED` therefore retains its exact current meaning, which is
a **disjunction**: for graph, that the applied ledger is neither the expected
ledger nor a strict prefix of it; for control, that same ledger condition **or**
any of the three pre-ledger structural mismatches. Capability problems are
reported as their own named conditions — a missing required capability, an
unsatisfied version constraint, an unclassified installed extension, a
capability whose dependent objects are absent — and are never added to either
disjunction.

**[invariant]** Overall database readiness is a **composite** derived from
schema readiness and capability readiness together. It fails closed: a database
with a `CURRENT` schema status and an unsatisfied required capability is not
ready.
This is a real gap today, since managed-schema readiness inspects no extension
catalog at all and would report `CURRENT` regardless of what is installed.

**[invariant]** Any capability requirement must be expressible for both the
graph and the control database. A design that works only for `storage/main.py`
is incomplete.

### D7 — Ordering is fixed, and a migration requires rather than discovers

**[invariant]** The sequence is exactly:

1. server or image provenance verified and accepted;
2. required extension version proved available on that server;
3. lifecycle administration creates or updates the extension;
4. installation and version verified;
5. product migration that uses extension types, functions, or operator classes;
6. dependent indexes and materializations built;
7. composite readiness accepts the capability.

**[invariant]** Steps 1 through 4 precede step 5. A migration may **require** an
already-installed capability at a stated version; it must never be the place
where availability is discovered. A missing capability at migration time is a
fail-closed error under D6, not a migration failure that looks like a broken
changeset.

**[invariant]** Step 3 is named explicitly because omitting it produces an
ordering that cannot be executed. "Admission" is a policy act; `CREATE
EXTENSION` is a database act; they are different steps and both are required.

**[invariant]** `CREATE EXTENSION` does not belong in a numbered migration file
while that file is also the place availability is discovered. Whether extension
creation may ever appear in a migration once steps 1 and 2 are satisfied is left
to D15, because it interacts with the ledger checksum model in ways this ADR
does not need to settle in order to admit nothing.

**[invariant]** **Lock consequence, stated accurately.** `_migration_script`
wraps the entire pending suffix and its ledger inserts in one `BEGIN`/`COMMIT`
(`storage/main.py:328`). `CREATE INDEX CONCURRENTLY` cannot run inside a
transaction block, so it is unavailable to this loader. An ordinary
`CREATE INDEX` takes a lock that **blocks concurrent writes while permitting
reads** — it is not `ACCESS EXCLUSIVE`. On a large table this is still a
maintenance-window decision, and it must be argued from measured table size
rather than from an exaggerated lock claim.

### D8 — Four identities, tracked separately

**[invariant]** These are distinct and must not be conflated:

| Identity | Source |
| --- | --- |
| PostgreSQL server identity | The running server's version and platform |
| Extension artifact provenance | The image or package that supplied the control and script files |
| Installed extension version | `pg_extension.extversion` in one database |
| Product schema version | The RepoMap migration ledger |

**[invariant]** A required capability states an **exact or explicitly bounded**
policy version constraint, per D3. "Whatever the server defaults to" is not a
constraint, and is precisely what a bare `CREATE EXTENSION` produces. Whatever
the constraint, the installed version in any given database is one exact value,
and it is that exact value — not the constraint — that is recorded, backed up,
and reproduced on restore.

**[invariant]** Upgrades run `ALTER EXTENSION … UPDATE` under the same
backup-first, verified-afterwards discipline as a schema migration, and are
recorded.

**[invariant]** Drift between a recorded requirement and an observed
installation is a capability-drift condition under D2 and D6, reported on its
own dimension.

### D9 — Restore safety is proved, never inferred from dump success

**[invariant]** `pg_dump` represents an extension as `CREATE EXTENSION` rather
than dumping its member objects. The restore target must therefore possess the
extension's own files. A successful dump proves nothing whatever about the
target, and a bare `CREATE EXTENSION` on restore silently accepts the target's
default version.

**[invariant]** The current backup metadata is insufficient for any
extension-bearing claim, and this ADR records why rather than overstating what
exists. `RuntimeContainerMetadata` carries container id, name, a **nullable**
image string, and a labels flag (`runtime/backup_records.py:40`); it records no
PostgreSQL server version. The TOC summarizer recognizes only `TABLE` and
`TABLE DATA` (`runtime/backup_manifests.py:193`); an extension TOC entry is
counted in the aggregate entry total but is neither identified nor surfaced, so
no restore decision can be made from it. Coordinated restore verifies checksums
and target absence and then begins creating databases, with no extension check.

**[invariant]** Admitting any capability into a restore-bearing database
requires a **new manifest version** recording: observed server version; artifact
provenance; every installed extension with its exact `extversion`, schema, and
owner; the dependency closure; and whether any extension holds configuration
tables.

**[invariant]** Restore must preflight, **before the first database is
created**: artifact availability on the target; server-platform compatibility;
that each recorded exact version is installable; and that extension creation or
update will be permitted.

**[invariant]** Preflight alone is insufficient, and the restore **order** is
part of the decision. Proving a version is installable does not install it, and
the dump's own bare `CREATE EXTENSION` would then take the target's default. For
each database the order is therefore: create the empty database; have lifecycle
administration install or update each required extension to the manifest's exact
recorded version; verify `pg_extension.extversion` equals that version; and only
then apply the dump. After the dump is applied, dependent objects and capability
readiness are verified. A restore that reaches `pg_restore` without the exact
recorded versions already installed is not a conforming restore, however many
preflights it passed.

**[invariant]** This applies to every rollback class in D10, not only to
data-bearing ones. An index-only capability still fails a restore if the target
lacks the operator class the index references.

**[invariant]** Extension configuration tables are inspected, not assumed
absent. `pg_extension.extconfig` and `extcondition` determine whether
extension-owned rows enter RepoMap's authoritative dump. A promise that RepoMap
will not call `pg_extension_config_dump` is not equivalent, because that
function is extension-author metadata executed by the extension's own script,
not a RepoMap switch.

### D10 — Rollback is classified on two axes, and "optional" is a claim about removal cost

**[invariant]** A capability is classified on two independent axes.

*Authoritative representation dependency:* `none`, `derived`, or `data-bearing`.

*Behavioral and schema dependency:* `none`, `query-capability`, or
`integrity-or-write-path`.

**[invariant]** The second axis exists because an extension can bind write-path
semantics without holding any authoritative value: check and exclusion
constraints, generated columns, defaults, row policies, triggers, partition
expressions, collations, expression indexes, and views can all depend on an
extension while every stored value remains readable. Such a dependency is
neither mere query-capability loss nor a data-representation dependency, and a
one-axis model cannot express it.

**[invariant]** Removal is never a bare `DROP EXTENSION`. `DROP EXTENSION`
defaults to `RESTRICT`, so dependent objects — including an index on an
extension's operator class — must be removed first, in order. `DROP EXTENSION …
CASCADE` is excluded from ordinary classification and from ordinary operation;
its blast radius is a function of the whole dependency graph and cannot be
reasoned about from the extension's name.

**[invariant]** Every admitted capability carries an **operational removal
plan**: dependency inventory, removal order under `RESTRICT`, any data
conversion, preload and restart requirements, backup before removal, and restore
verification afterwards.

**[invariant]** A `data-bearing` capability is not "not removable" — its values
can be converted by an explicit **exit migration**. The honest property is that
it is *format-coupled*: not removable without transformation.

**[invariant]** **A capability requiring an exit migration to make authoritative
data or schema usable without the extension is not "optional" in the ordinary
sense.** A feature flag that disables the surface does not make the storage
format reversible. Admitting such a capability is a durable-format decision
equivalent to a schema migration plus a backup-format change, and requires an
accepted ADR that updates the backup, restore, and readiness contracts in the
same decision.

### D11 — Semantics, implementation, acceleration, and storage model are four separate things

**[invariant]** These layers are distinct and decisions at one do not license
changes at another:

| Layer | Owns |
| --- | --- |
| Semantic contract | Which rows a surface returns, in which order, within which bounds |
| Query implementation | The SQL RepoMap issues |
| Access-path acceleration | Indexes and operator classes available to the planner |
| Storage model | How authoritative values are represented |

**[invariant]** **The planner's choice between semantically equivalent access
paths is not a user-visible fallback.** If an index is unusable or the planner
prefers a sequential scan, the result set is identical and slower. That is
permitted, unremarkable, and not a correctness event. Requiring a particular
plan would be a promise RepoMap cannot keep.

**[invariant]** What is prohibited is **semantic** weakening: silently replacing
an exact predicate with an approximate or similarity-based one, changing which
rows qualify, or degrading ordering or bounds. If a declared capability-backed
semantic surface is unavailable, the surface either uses a core path returning
the identical set, or fails closed with a bounded named error.

**[invariant]** Bounded deterministic readback is unconditional. Any future
capability preserves existing ordering, limit, offset, and truncation contracts.
No capability may introduce result nondeterminism into an existing bounded
surface.

**[invariant]** **Core full-text search is not a substitute for substring
search.** `tsvector`/`tsquery` implement token and document search with
stemming and stop words; they do not implement arbitrary substring matching.
Neither B-tree, `text_pattern_ops`, nor an ordinary expression index accelerates
a leading-wildcard pattern, and lowercasing normalizes case without solving the
access path. Any proposal claiming a core mechanism suffices must say which
mechanism, for which exact product query, and must not conflate a different
product query with an implementation of the current one.

**[invariant]** The current `ILIKE` behavior is the authoritative implemented
query surface and remains unchanged by this ADR. Adopting full-text search would
be a *different product query* requiring its own decision, not an optimization
of this one.

**[invariant]** An acceleration that leaves the semantic contract unchanged
still requires the ordinary migration, backup, lifecycle, readiness, and
evidence gates. It is not "free" and may not be described as freely addable or
removable.

### D12 — Supply chain is classified, and no property is presumed

**[invariant]** A capability declares its implementation class. The classes are
distinct and carry different obligations:

| Class | Notes |
| --- | --- |
| PostgreSQL-supplied, trusted | Installable by a non-superuser database owner |
| PostgreSQL-supplied, elevated | Requires superuser to install |
| Third-party, SQL-only | No native code |
| Third-party, native | Compiled code in the backend address space |
| Preload-requiring | Needs `shared_preload_libraries` and a restart |

**[invariant]** "Trusted" is a PostgreSQL **installation-privilege** property.
It is not a supply-chain judgement, a vulnerability history, or a code-quality
claim, and it never substitutes for review.

**[invariant]** "Extension" does not imply native code. Extensions may be
SQL-only. The universal claim that admitting any extension adds native code to
the backend is false and is not used here; native-code exposure is disclosed per
capability, not presumed.

**[invariant]** Vulnerability review is **version-scoped**. A capability's
admission record states affected and fixed versions determined against the exact
pinned server image at admission time. "This extension has a CVE" is not a
finding; it treats a versioned defect as a permanent property. This ADR
deliberately asserts no CVE conclusion about any named candidate, because no
affected-version determination against the pinned PostgreSQL 16.14 image was
made in this phase.

**[invariant]** License evidence is recorded from primary sources, never
presumed from a family name or a registry classifier, consistent with ADR 0050
D8.

**[invariant]** Extension binaries originate only from RepoMap's built,
digest-pinned server image. This is a **normative supply-chain rule enforced by
image construction and mount policy** — not an inference from the absence of a
package manager. The checkout proves only that the release image is built `FROM`
the digest-pinned PostgreSQL image (`runtime/commands.py:94`), that pip,
setuptools, and `ensurepip` are removed and asserted absent (`:90`–`:92`,
`:117`–`:118`), and that the Go toolchain is asserted absent (`:124`). It does
not establish what the Debian base image contains, and this phase did not
inspect the image.

### D13 — No capability is adopted on unmeasured performance

**[invariant]** Performance statements carry the ADR 0050 D16 labels:
`[architecture decision]`, `[measured fact]`, `[pilot hypothesis]`,
`[unmeasured assumption]`. No capability is adopted on the basis of the last
two.

**[invariant]** As of 2026-08-13 RepoMap holds **no** `[measured fact]` about
search or query performance at any graph size. PERF-BASE1 (status 00721) ended
in a bounded stop with `perf_base1_accepted: false`, recorded that DBEXT0 has no
current baseline, and recorded that `PERF-BASE1-R1` was not authorized.

**[invariant]** No future phase may reuse the identity `PERF-BASE1`. A rerun
requires a separately authorized successor identity. Nothing in this ADR
authorizes `PERF-BASE1-R1`.

**[invariant]** A baseline is necessary but not sufficient. A capability
proposal must also state a **measurable acceptance threshold** in advance —
what improvement, on what dataset, would count as success — not merely a list of
evidence fields to fill in.

**[invariant]** An upstream performance claim is never evidence for RepoMap
adoption.

### D14 — Candidate dispositions

**[invariant]** No candidate below is admitted. Each disposition records the
architectural reason, and each reason is narrowed to what is actually supported.

| Candidate | Disposition | Reason |
| --- | --- | --- |
| Core PostgreSQL / current `ILIKE` | **Authoritative** | Implemented, sufficient for every current product query, unchanged by this ADR |
| `pg_trgm` | **Not admitted** | The only candidate matching a shipped product query, but there is no measured need. Reconsiderable only under D15 with an accepted baseline, and only for an acceleration that leaves the semantic contract identical, or for a separately authorized similarity product query |
| `ltree` | **Not admitted** | RepoMap has no rooted-hierarchy product contract requiring materialized paths. Reconsiderable only if such a contract is demonstrated. It is not claimed that `ltree` would force the graph to become a tree — an `ltree` value is a path, not a global single-parent constraint; the reasons are absence of need and column-type lock-in |
| `pgvector` | **Not admitted** | Data-bearing and format-coupled under D10. Reconsiderable only if vector or embedding search is itself separately authorized as a product capability |
| Apache AGE | **Not admitted** | Would constitute an alternate authoritative graph store and a second source of truth. Its session initialization and privilege requirements conflict with RepoMap's least-privilege pooled connections. Adoption would require a dedicated storage-backend ADR, not an extension decision |
| Operational and diagnostic extensions | **Not admitted** | Operational observability is a separate concern from graph semantics. Library preload is cluster-wide while the SQL objects are per database, so both must be modelled. Gates include privacy of recorded query text, access control, measured overhead, and operational value — a performance baseline alone is not sufficient, and no single example generalizes to the class |

**[invariant]** Nothing in this table is a queue. A disposition of "not
admitted" does not schedule reconsideration, and reconsideration requires D15
regardless of what this table says is architecturally plausible.

**[invariant]** No embeddings, model inference, vector generation, vector
schema, client-library dependency, or Cypher surface is authorized by this ADR
under any disposition.

### D15 — The exception gate

**[invariant]** A future capability is admitted only by an accepted ADR carrying
a complete admission record. An incomplete record is a refusal, not a deferral
to judgment; the core-only incumbent wins.

The record states:

1. the exact product query or contract requiring the capability, and why the
   core contract cannot serve it — naming the specific core mechanism evaluated
   and why it is insufficient, per D11;
2. the D12 implementation class, artifact provenance, license evidence from
   primary sources, and an affected-and-fixed-version vulnerability
   determination against the exact pinned image;
3. the D3 ownership classification, policy version constraint, and dependency
   closure;
4. the D5 database scope and preload requirement, installation schema, object
   owner, and object-privilege decision including `PUBLIC` revocation;
5. the D10 two-axis rollback classification and the operational removal plan,
   including any exit migration;
6. the D9 manifest-version change, restore preflight, and exact-version restore
   ordering, before any admission into a restore-bearing database;
7. the D6 readiness representation for both graph and control databases,
   including how a missing capability is reported;
8. the D7 ordering as it applies concretely, including lock and
   maintenance-window analysis argued from measured table size;
9. the D13 evidence: an accepted baseline, a predeclared measurable acceptance
   threshold, and a result-set equality proof where the capability is an
   acceleration;
10. the deterministic rollback to the core-only configuration.

**[invariant]** Policy admission and database enablement are separate acts with
separate records. An accepted ADR admits a capability; lifecycle administration
enables it in a specific database at a specific version. Neither implies the
other.

**[invariant]** No capability is admitted by landing code that uses it, by a
migration that creates it, or by an operator enabling it on a server.

## Alternatives Considered

### Rejected

**Core-only, permanently.** Rejected in its "forever" form only. Permanence buys
no safety that an exact exception gate does not already provide, and it would
bind RepoMap against evidence that does not yet exist. The present decision is
core-only *until superseded by an accepted ADR*, which is materially different
from a permanent prohibition.

**Adopt a small required baseline of supplied extensions.** Rejected. It would
make RepoMap unusable on a conforming server lacking contrib packaging, in
exchange for capabilities no current product query needs.

**Extension-per-feature with no central policy.** Rejected. It produces exactly
the accretion this ADR exists to prevent, and leaves restore, readiness, and
rollback undecided at the point where each is cheapest to decide.

**Allow every extension installed on an owned database.** Rejected by D3.
Presence is not ownership, and an allowlist that admits whatever is present
admits nothing.

**Adopt `pg_trgm` acceleration now.** Rejected by D13. There is no accepted
baseline, so the benefit is unmeasured; and D11 makes clear that the semantic
contract would not change, which means the only possible justification is a
measurement that does not exist.

**Apache AGE as the canonical graph store.** Rejected by D14. This would be a
storage-backend decision, and routing it through an extension policy would
decide RepoMap's authoritative storage as a side effect.

**Pre-adopt a semantic capability now and implement later.** Rejected. A
declared but unimplementable capability is an expectation masquerading as a
contract, which ADR 0049 D1 forbids.

### Accepted

**Core-authoritative, with an exact exception gate.** Accepted as D1 and D15.
This is the smallest present commitment consistent with leaving a legitimate
future path open.

**Orthogonal capability facts with derived readiness.** Accepted as D2 and D6.
It is the only model that expresses server, cluster, database, and policy facts
without forcing them into one value, and it keeps the existing ledger
contracts intact.

**Classification before adoption.** Accepted as D3, D10, and D12. Deciding
ownership, rollback cost, and supply-chain class before anything is installed is
what makes a later admission reviewable rather than retrospective.

## Consequences

Positive: RepoMap keeps a fully portable core-only deployment, an intact and
exact migration-ledger contract, and its least-privilege role model. The
capability fact model gives readiness, backup, and restore a vocabulary for
extensions before the first one exists, which is the only point at which those
contracts can be written without a migration. The gate makes a future admission
a reviewable decision rather than an accumulated one.

Negative: the model is heavier than "just create the extension". A future
admission now costs a manifest version, a restore preflight, a readiness
projection, a removal plan, and measured evidence. RepoMap also forgoes any
search acceleration until a baseline exists, and its leading-wildcard `ILIKE`
predicates continue to have no general B-tree acceleration available to them.
Which plan PostgreSQL actually selects for any given search query is the
planner's choice under D11, and this ADR neither predicts nor promises it.

Neutral: no code, schema, SQL, image, or dependency changes. Every existing
database remains conforming. `plpgsql` continues to be used exactly as it is
used today, now named rather than unnoticed.

## Migration And Adoption

No migration is performed. Should later phases be authorized, the order implied
by this ADR is:

1. implement the D2 capability fact model as pure observation, creating no
   extension anywhere, and resolve whether the pinned image supplies contrib
   control files;
2. decide the schema-manifest treatment of extension objects per Deferred Work;
3. extend the backup manifest and restore preflight with extension identity
   (D9), which is a prerequisite to admitting any capability into a
   restore-bearing database;
4. establish an accepted query-performance baseline under a new phase identity
   (D13), which is a prerequisite to any acceleration proposal;
5. then, and only then, consider a specific capability through D15.

Steps 3 and 4 are both prerequisites for different reasons. Admitting before
step 3 would silently weaken the accepted restore contract. Admitting before
step 4 would adopt on expectation, which D13 forbids.

## Refresh And Revisit Conditions

Revisit when: an accepted performance baseline exists, making acceleration a
`[measured fact]` for the first time; a product contract requires semantics the
core cannot express; the pinned server image's available extension set changes;
PostgreSQL changes the behavior of any external fact relied on here; or the
unresolved server-portability question in Deferred Work is settled.

External facts recorded here were read on 2026-08-13 and must be re-verified
from primary sources at admission time rather than carried forward.

## Deferred Work

Identified, not authorized:

- Whether RepoMap supports arbitrary conforming PostgreSQL servers or only its
  own digest-pinned runtime image. D1 implies the former and D12 implies the
  latter; neither has the evidence to settle it, and the answer changes what
  `artifact_availability` means.
- Whether the pinned `postgres:16-bookworm` image supplies contrib control
  files under `SHAREDIR/extension`. This phase prohibited image inspection.
- The authoritative location, format, and checksum discipline of a capability
  requirement declaration, and the syntax by which a migration would state a
  requirement.
- The schema-manifest treatment of extension objects. The current manifest
  inventories every qualifying object in `public` **regardless of ownership**:
  it filters on `nspname = 'public'`, `relkind`, and a named exclusion list, and
  consults neither `pg_depend` nor `pg_extension`
  (`runtime/schema_manifest.py:40`–`:42`). An extension installed into `public`
  would therefore have its members silently drawn into the manifest, which is a
  live defect the moment any extension is admitted, not merely a design
  question. Three inventories are likely needed — application objects,
  extension identity and members derived from `pg_extension`/`pg_depend`, and
  extension configuration data — but how extension members are separated or
  excluded, and which inventory the pre-ledger adoption comparison should use,
  are undecided.
- Whether `pg_restore -l` surfaces a missing-extension condition before mutation
  or only at apply time.
- Whether the disposable reference database used by pre-ledger adoption must be
  built with the same capability set as its target for the comparison to be
  valid.
- Whether extension creation may ever appear in a numbered migration once
  availability is separately proved, given the ledger checksum model.

## Explicit Authorizations And Prohibitions

Authorized by this ADR: nothing beyond recording the decision and aligning
`docs/specs/storage-model.md` with it.

Prohibited without a further accepted phase: issuing `CREATE EXTENSION`,
`ALTER EXTENSION`, or `DROP EXTENSION` anywhere; installing extension packages;
modifying the PostgreSQL image, Compose, SQL, or migrations; adding a vector
schema or generating embeddings; introducing an alternate graph store or Cypher
surface; granting any capability role superuser or database `CREATE`; adding
runtime package installation or compilation; creating a phase named
`PERF-BASE1`; and adopting any capability on unmeasured performance.
