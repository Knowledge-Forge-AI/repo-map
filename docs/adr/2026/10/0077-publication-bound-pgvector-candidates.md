# ADR 0077: Publication-Bound pgvector Candidates

## Status

Experimental implementation contract for REPOMAP-PRODUCT6-PG-INTELLIGENCE1
and REPOMAP-PRODUCT6-PG-INTELLIGENCE2, extended by
REPOMAP-PRODUCT6-PG-INTELLIGENCE3-IDENTITY-READBACK1 for metadata discovery.
Production extension admission is **refused pending evidence** under ADR 0051
D15. Landing the experimental exact path does not admit or enable pgvector.
Independent candidate review remains a publication prerequisite. No normal database,
runtime image, configuration home or portable bundle is changed.

## Date

2026-10-08

## Decision and scope

Add an explicitly selected PostgreSQL investigation read-store operation over
precomputed, publication-bound canonical-node embeddings. Exact cosine distance
is the reference. Candidate results expand through current canonical node and
evidence rows in the same database snapshot. Similarity is heuristic discovery;
it never creates a canonical edge. SQLite and ordinary PostgreSQL operations
remain core-only. No model runtime or inference API is introduced.

The first implementation accepts bounded public-safe precomputed imports from
an explicit enrichment principal. It does not accept private embedding imports
in this slice. Synthetic fixture vectors establish mechanics only, not semantic
quality, learned-model usefulness or step-6 completion.

PG-INTELLIGENCE2 authorizes a read-only `repomap_similar_nodes` MCP entry point.
The caller supplies a configured graph, canonical seed key, rebuild identity,
expected profile digest and dimensions, with explicit selection. A source
binding qualifies an ambiguous seed. The backend resolves the latest complete
portable receipt, then verifies that exact receipt again while selecting both
the stored seed and candidates in one SQL statement. A publication change
between receipt readback and retrieval refuses the request. No query vector,
inference, source acquisition or canonical edge is introduced.

Seed identity is resolved from accepted source evidence before applying the
partial embedding import. Multiple source identities require qualification;
missing canonical nodes and missing embeddings have distinct bounded outcomes.
Refusals distinguish missing canonical seed, missing embedding, ambiguous seed,
profile mismatch, stale rebuild, foreign publication and receipt changes.
Only the selected canonical-key/source-binding pair is excluded. Model/profile,
dimension and rebuild mismatches cannot fall back to another import.

Disposable extension-enabled test materialization is authorized separately from
D15 production admission. It must use verified immutable pgvector 0.8.7 source,
the existing pinned core PostgreSQL base, and canonical sandbox ownership and
resource accounting. Only an explicitly selected test population may require
the extension. Test mechanics, privilege and a disposable logical restore do
not constitute production restore certification, HNSW value or learned quality.

## D15 admission record

### PG-INTELLIGENCE3 identity readback contract

REPOMAP-PRODUCT6-PG-INTELLIGENCE3-IDENTITY-READBACK1 authorizes the
read-only `repomap_embedding_profiles` MCP operation. It requires an explicitly
configured visible graph, strict boolean `selected` (default false), and an
integer limit from 1 to 100 (default 20). Disabled calls perform no store I/O;
selection observes availability and never installs or enables the capability.
Only public-dev graphs with public-dev source bindings may query PostgreSQL.
SQLite reports explicit unavailability without opening its database.

Discovery validates the latest complete run's portable receipt, without falling
back to an older receipted run. A final SQL statement fences that exact receipt
and generations against the latest complete run while reading immutable rebuild
metadata and verifying every imported record's accepted node/source evidence.
Extension 0.8.7 and optional schema readiness remain separate from core readiness
and are rechecked in that statement. Publication drift refuses the read.

Entries expose only validated rebuild/profile identities, the versioned profile,
row count and bounded source binding/snapshot identities. Profile digests must
equal the digest recomputed from the complete profile. Malformed or ambiguous
readback refuses rather than adopting a tuple. Foreign repositories are excluded
before metadata projection; stale rebuilds cannot qualify. Distinct rebuilds
sort by rebuild identity in C collation; a bounded extra row reports `has_more`.
There is no recommended or automatically selected rebuild. Callers explicitly
choose a returned tuple for the existing `repomap_similar_nodes` operation.
SQL-ineligible repository rebuilds are disclosed through `has_excluded_rebuilds`,
including stale or invalid rows alongside eligible entries. Identity validation
covers the ordered `limit+1` page; an invalid extra row refuses that result too.
It does not validate identities beyond the page, and a larger limit can expose
a refusal. Evidence checks may examine every bound rebuild before paging;
the output bound is not a query-work or scalability guarantee. Discovery's
`publication_unaccepted` refusal for missing/malformed portable receipts differs
deliberately from the existing seed query's bounded storage error. Neither path
falls back to a historical publication.
No vector, source content, enrichment principal or private runtime identifier is
returned. At most 500 imported node/source records per rebuild remains partial
coverage, and synthetic fixtures establish no semantic usefulness.
Metadata requiring redaction refuses as `privacy_refused` in both profile
discovery and explicitly selected `repomap_similar_nodes` results, returning
unavailable with no profiles, candidates or provenance rather than rewriting
tuple or digest-bearing values in place. Whole-payload sanitizer equality
refuses whenever `sanitize_jsonable` would alter any field via full
private-path substring markers, secret-key or credentialed-URL/text redaction,
or `>500`-character string truncation (so clean `canonical_key`, `path` or
`evidence_key` strings longer than 500 characters also refuse even where
query/import validation permits up to 4,096 characters). At the exact
structured path `candidates[].evidence[].evidence_key`, screening bypasses only
generic `"key"` field-name suffix redaction while still sanitizing the string
value for private paths, secret/credentialed-URL text and `>500`-character
truncation. Local usernames are matched as word-bounded metadata tokens across
`profiles` and `provenance` metadata only—never `candidates` graph content or
evidence, and explicitly ratifying an unconditional skip of caller-echoed graph
content at `provenance.seed.canonical_key` (which remains subject to
whole-payload path, secret-text and length sanitization)—with exact
structured-path exemptions only for validated opaque identity grammars and
exact fixed protocol strings so discovery and selected similar-node reads agree
on the same clean tuple.

Real pgvector qualification requires a separately admitted disposable PostgreSQL
16 / pgvector 0.8.7 environment and portable seed fixtures, including stdio MCP
under a SELECT-only principal, current/stale/foreign publications, explicit
tuple comparison, and privacy refusal for both discovery and explicitly selected
`repomap_similar_nodes` tuples. This public navigation projection includes read
contracts and unit owners; optional image provisioning and pgvector integration
owners are outside its scope. No production extension installation is admitted
here.

This record uses ADR 0051's dimensions and exception gate. Pending evidence is
an admission refusal, not implicit discretion to enable production.

1. **Product query and core alternative.** Versioned cosine nearest candidates,
   filtered and expanded through accepted graph evidence. Existing ILIKE search
   cannot compare imported embeddings. Core PostgreSQL arrays plus arithmetic
   can serve this bounded exact reference over at most 500 records. The exact
   slice alone therefore does not establish D15 item 1 necessity. pgvector's
   distinct proposed value is its HNSW/ANN access path, pending a measured D13
   comparison against exact/core retrieval and a predeclared adoption threshold.
   Typed vectors alone do not justify admission. Useful learned retrieval versus
   the incumbent still requires evaluation.
2. **Implementation, source and security.** Native C backend extension, policy
   version exactly `0.8.7`, upstream
   [versioned control file](https://github.com/pgvector/pgvector/blob/v0.8.7/vector.control)
   and [license](https://github.com/pgvector/pgvector/blob/v0.8.7/LICENSE)
   checked 2026-10-08. The PostgreSQL license permits redistribution with its
   notices. The [versioned changelog](https://github.com/pgvector/pgvector/blob/v0.8.7/CHANGELOG.md)
   fixes a parallel HNSW build overflow in 0.8.2, a 32-bit IVFFlat build overflow
   in 0.8.6 and an IVFFlat build overflow in 0.8.7. Earlier versions are not
   accepted. The upstream advisory page currently lists no published advisories;
   that is not evidence of absence of vulnerabilities. The existing pinned
   Server base remains PostgreSQL 16.14; upstream now lists 16.15. No image
   refresh is authorized here. Exact artifact digest/platform observation and
   affected/fixed determination for the full extension-enabled image are pending;
   production admission cannot pass D12 on source facts alone.
3. **Ownership and closure.** `vector` becomes required only for a separately
   selected candidate capability. It is not required by the baseline. No SQL
   extension dependency is declared by the upstream control file; template
   plpgsql remains baseline. Foreign installations are never adopted, updated
   or dropped. This slice only probes an exact installation in `repomap_vector`.
4. **Scope and privileges.** Graph database only; control requires no vector.
   No cluster preload. Lifecycle administration owns `repomap_vector` and
   `repomap_enrichment`, their objects and extension; capability roles own none.
   Revoke PUBLIC schema access and extension-function EXECUTE. Explicitly grant
   type/schema/function use to the read principal and enrichment principal;
   grant enrichment INSERT on its own tables only, and read SELECT only.
   Import provenance defaults to `current_user`; the writer's column-level
   INSERT grant excludes `enrichment_principal`, and the import omits it. A
   lifecycle restore can explicitly preserve the saved principal. There is no
   session-dependent CHECK. PostgreSQL's [column privileges](https://www.postgresql.org/docs/16/sql-grant.html)
   and [defaults](https://www.postgresql.org/docs/16/ddl-default.html) support
   this boundary; actual COPY/privilege assertions remain unexecuted here.
   Refresh, coordinator-control and portable semantic workers gain no grants.
   No principal receives database CREATE or superuser for this feature.
5. **Rollback.** Authoritative-representation axis: derived (discardable imported
   embeddings); behavioral/schema axis: query-capability. Disable selection,
   revoke enrichment writes, retain a public-safe import artifact if desired,
   remove the enrichment tables, then remove a lifecycle-owned extension with
   RESTRICT. Never use CASCADE or remove foreign objects. Canonical graph data,
   keys, constraints and publication authority are unaffected. Enrichment has
   its own optional schema version and is absent from ordinary graph migrations.
6. **Restore.** Existing authoritative backup manifests do not satisfy D9.
   Production installation into a restore-bearing graph is prohibited until
   a new extension-aware manifest records observed server/platform, immutable
   artifact provenance, every extension's exact version/schema/owner, dependency
   closure and extconfig/extcondition. Restore must prove availability and
   lifecycle privileges before creating any database; install exact recorded
   versions in each empty database, verify them, apply the dump, then verify
   dependent objects/readiness. Rebuild derived vectors only against the restored
   accepted receipt. A source-level manifest design is not an executed restore
   proof; implementing and exercising this remains an admission blocker.
7. **Readiness.** Keep schema readiness separate. Capability facts distinguish
   selected, observed installation/version/schema, dependent schema version and
   operational result. Disabled, absent, unsupported and observation failure
   are explicit capability-unavailable reasons. A graph can remain core-ready
   while the optional query is unavailable. Control has no requirement. Reads
   never install, migrate, import, refresh, publish or acquire sources.
   Only probe errors become `observation_failed`. Errors after a successful
   probe raise a bounded storage query error; SQL or privilege defects cannot
   masquerade as an unavailable extension.
8. **Ordering and locks.** Verify an immutable extension-enabled image and
   exact version availability; lifecycle install and verify; explicitly create
   the optional schema; import a bounded rebuild; derive readiness. Artifacts
   are image-construction inputs, never downloaded by product code. Rebuild
   import reads existing runs/node/evidence in one repeatable-read snapshot;
   later publication invalidates it at query time without canonical write grants.
   No ordinary migration includes extension creation. No concurrent
   index build is selected. Table-size/build/update observations remain pending;
   no maintenance-window claim is inferred from tiny fixtures.
9. **Evidence and threshold.** Predeclared mechanics threshold: exact results
   equal exhaustive cosine ordering with canonical-key tie breaks, no stale or
   foreign-publication/model/dimension result, no write during read, and intact
   baseline without the extension. This is a correctness baseline, not a
   performance/adoption baseline. Learned-model evaluation and accepted D13
   workload baseline remain pending. No ANN acceleration is admitted.
10. **Core-only rollback.** Selection defaults disabled. Missing extensions or
    enrichment cause explicit unavailability, never text-search substitution.
    Removing optional objects restores the same core-only graph/CLI/MCP contract.

## Embedding and publication contract

`canonical-node-v1` represents an accepted node's `canonical_key`, `kind` and
`display_name` as UTF-8 JSON with sorted keys, compact separators and unescaped
Unicode. Its input digest is `sha256:` followed by the SHA-256 of those bytes.
This metadata-only representation needs no raw source; adding source text or
changing serialization requires a new representation version. The named
enrichment principal asserts that the vector and digest correspond to that
representation. This first import validates digest shape and publication/source
evidence, but does not independently recompute the input digest or verify a
generator's semantic claim. Result provenance labels that assertion explicitly;
fixture digests and synthetic vectors are not content-integrity or quality proof.

Bind model and generator identities/versions, representation v1, dimensions,
L2 unit normalization, cosine metric, graph/repository identity, complete
accepted publication receipt and generations, source binding/snapshot identity,
public privacy class, input digest and rebuild identity. An enrichment writer
imports an immutable bounded batch; a duplicate rebuild identity is refused.
Each batch is capped at **500 node/source records**. One query uses exactly one
rebuild, so publications larger than that have partial imported coverage only;
multiple source records for a node also consume that bound. Results explicitly
report this limit. This is not publication-wide coverage or a scale proof.
It cannot modify canonical rows or publish. Latest complete publication must
match the supplied receipt, including portable evidence. A newer publication
invalidates an older rebuild at read time even if node keys are unchanged.
Running, cancelled, failed and uncertain attempts never authorize enrichment.

The read-store resolves configured graph identity and privacy before storage;
the storage query checks publication, profile and evidence in one MVCC snapshot.
Exact distance is calculated in a materialized candidate relation before final
ordering, so a future approximate index cannot silently change the reference.
Results report provenance, coverage limitations and bounded evidence expansion.

## Comparative work and consequences

HNSW measurements await a real exact boundary and an admitted disposable image;
IVFFlat is optional. Record recall, result differences, latency, build/update
cost and footprint on identical data/filters before considering adoption.
No scalable-performance claim is made from fixtures.

JSONB is deferred for the concrete workload of node-evidence expansion by
publication and canonical key. Existing relational joins already express its
identity, run and scope constraints. There is no measured deficiency warranting
a metadata GIN index or schema conversion in this slice.

This bounded path permits code and unit evidence to advance while admission
and real database proof remain explicit blockers. Step 6 and pre-v0.1.0
intelligence value remain in progress.

## Public projection evidence boundary

The public navigation projection retains the read-only MCP catalog, its direct
semantic query dependencies and synthetic unit owners. Optional pgvector image
provisioning, experiment companions, vector publication/restore integration
owners and runner changes are not included. Their absence is not an executed
vector proof or D15 admission. Real SQL, seed, privilege and restore behavior
requires separately recorded runtime qualification of the exact candidate.
