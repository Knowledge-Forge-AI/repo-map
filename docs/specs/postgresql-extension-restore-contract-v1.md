# PostgreSQL Extension Restore Contract v1

Status: **D9-A implemented; hosted candidate qualification pending**; D9-B remains **Proposed**.
Design phase: `REPOMAP-PRODUCT6-NAVIGATION36-EXTENSION-RESTORE-DESIGN1`.
Implementation phase: `REPOMAP-PRODUCT6-NAVIGATION37-EXTENSION-PROVENANCE1`.
Date: 2026-10-20. Operator approval covers provenance and refusal guards only;
it does not admit extension replay or production pgvector.

[ADR 0084](../adr/2026/10/0084-extension-aware-backup-and-restore.md) owns the
decision request and content-bound source census. [ADR 0051](../adr/2026/08/0051-postgresql-extension-and-database-capability-architecture.md)
remains the accepted capability authority. The D9-A requirements are approved;
the future extension protocol remains proposed. Neither approval nor recorded
metadata establishes executed restore qualification.

## 1. Bounded implementation sequence

**D9-A, recommended first:** add versioned observations, strict reader validation
and a shared support/refusal decision across every backup-first consumer. Preserve
current core restore flags, creation semantics, reasons and graph-selection
behavior. Do not install extensions, enable optional production defaults or
implement derived-TOC replay in this slice. Non-baseline extensions remain
unsupported regardless of complete metadata or experimental fixture availability.

**D9-B, proposed later:** implement and prove the target D9 restore protocol under
a separate accepted assignment. A disposable experimental policy may qualify
tests; it does not become production admission. The remaining transport and
artifact-availability proofs must precede a positive extension restore claim.

## 2. All affected consumers

| Responsibility | Current owner | Required foundation behavior |
| --- | --- | --- |
| Single and coordinated dump | `runtime/backup.py`, `_backup_lifecycle.py`, `backup_manifests.py` | Capture a complete per-DB census and keep the archive/support result bound together. |
| Single init and complete-set restore | `_backup_lifecycle.init_database_from_dump`, `backup_restore_sets.restore_coordinated_backup` | Validate the selected protocol and refuse unsupported capabilities before creating any target. |
| Drop and graph schema upgrade | `backup.py`, `backup_inspection.verify_drop_backup`, `schema_upgrade.py` | Require the shared support result before destructive work; neither checksum nor a manifest boolean alone is sufficient. |
| Coordinator control upgrade | `coordinator/_lifecycle_upgrade.upgrade_coordinator_control` | Reuse held maintenance ownership and the same support predicate. |
| Release-cluster graph/control upgrade | `runtime/release_cluster.py` | Bind its separate upgrade artifact to the same decision; remove unconditional synthetic support bypasses within the approved implementation. Do not pretend its current `schema-upgrade.json` is a format-1 `manifest.json`. |
| CLI, inspection and instructions | `cli/_local_dispatch.py`, `backup_inspection.py`, `backup_records.py`, `backup_manifests.py` | Preserve the distinction between support, unknown provenance and executed qualification; render scope-accurate instructions. |

The low-level dump helper must not acquire another independent advisory lock
inside an already locked caller. Standalone CLI dump obtains outer ownership;
drop, upgrade and coordinated paths reuse their held control-then-graph window.
The held authority is an explicit implementation input, not a caller-supplied
boolean that manufactures a recovery-point observation.

## 3. Format 2 and deterministic private metadata

Keep existing format-1 field names and meanings where applicable, including
`backup_id`, `timestamp`, `scope`, `recovery_point`, `dump_files`, `dump_format`,
runtime/home/container fields, redacted connection, reasons and warnings.
Do not invent a new ID convention or rename `timestamp` to `created_at`.
The new reader validates versions 1 and 2 explicitly; unsupported versions refuse.
The old reader's refusal of version 2 is expected forward-compatibility behavior.

The accepted D9-A additions use strict UTF-8 JSON, finite values, unique keys and bounded
collections. Reject missing required facts, conflicting records, duplicate
database/archive mappings, invalid types, unsafe paths or overflow. Freeze actual
query/TOC/metadata budgets in the bounded implementation assignment before tests;
never receive unlimited output and truncate it afterward.

The D9-A implementation assignment fixes these ceilings before test execution:

| Resource | Maximum |
| --- | ---: |
| Manifest UTF-8 bytes | 8 MiB |
| Output per catalog query | 2 MiB |
| TOC output | 4 MiB |
| Retained observation JSON | 8 MiB |
| Databases per manifest | 256 |
| Extensions per database | 256 |
| Schemas per database | 4,096 |
| Dependency edges per database | 8,192 |
| Configuration entries per database | 1,024 |
| Catalog observation and maintenance acquisition query | 30 seconds |
| TOC command | 60 seconds |
| Client version observation | 5 seconds |
| Owned native process wait during cleanup | 2 seconds |

A stricter existing limit remains applicable. Overflow refuses; it never yields
a partial census with positive support. These limits do not establish D9-B
artifact availability or restore qualification.

| Field family | Required meaning and validation |
| --- | --- |
| `backup_format_version` | Integer 2; never silently upgrade or rewrite a legacy manifest. |
| `restore_protocol` | `core_v1` or future `extension_v2`, per selected restore unit. Format revision alone does not select a new execution protocol. D9-A supports only the current core protocol. |
| `server_provenance` | Observed server version number and text, catalog version, OS/architecture/ABI and exact dump/restore client identities. Distinguish unavailable from observed. `catalog_version_no` comes from `pg_control_system()` with its actual integer type and privileges. |
| `artifact_provenance` | Immutable image/configuration and registry identities when available, extension control/script/library or package provenance and policy binding. A mutable tag, a checksum supplied by the same manifest or an available-version row is not a trust root. |
| `database_catalogs` | Exactly one record per dumped database: graph/control role, creation semantics, observed schemas, complete extension census, dependency/configuration facts and consistency evidence. |
| `creation_semantics` | Source encoding, locale provider, collation/ctype and relevant provider/version facts. Missing or incompatible facts cannot be normalized to C or to a target default and called equivalent. |
| Archive bindings | Existing exact size/SHA-256 plus dump/client identity and a defined TOC representation/digest. Use exact compatible client identity or separately qualified canonicalization; do not normalize away semantically meaningful entries. |
| Support result | Existing `restore_supported` plus stable blocker categories and provenance/completeness state. A positive value means that the selected implementation supports the declared protocol, not that this particular backup has been test-restored. |

Unknown immutable artifact observations may remain explicit on a legacy/core
record; they never establish the extension protocol's D9 artifact precondition.
Incomplete extension census cannot establish that a backup is core-only.
D9-A records non-baseline observations but sets support false. Future extension
support additionally requires the accepted capability policy and executable proof.

## 4. Extension identity, ownership and dependencies

For every installed extension, record exact name/version, portable installation
schema and observed owner, relocatability, baseline origin, declared ownership
classification, dependency identities and resolved configuration metadata.
Portable identities use schema/name/kind rather than database-local OIDs.
Keep OIDs/xmin only in private observation evidence when they serve drift detection.

Preserve D3's `required`, `permitted-foreign` and `unclassified` policy categories.
Template-provided `plpgsql` is a separate D1 baseline fact. Experimental selection
is a separate, explicitly scoped policy context, not a new ownership category
or production grant. Observation never promotes an unclassified capability.
The backup records a declaration's identity; it does not authorize that declaration.

Do not confuse `pg_depend` extension membership (`e`) with prerequisite dependency
edges. Resolve actual extension prerequisites and control metadata, compute the
transitive closure, detect cycles/missing vertices, and derive deterministic
prerequisite-first order with a stable name tie-break. Keep membership/dependent
application-object inventories separate. A one-hop membership query is not a
closure. The implementation needs real multi-level dependency fixtures.

An ordinary non-public schema is not evidence of an extension. Retain its
archive entries and record its ownership/semantics; do not apply a blanket
non-public-schema ban. Special capability objects require their declared policy
and readiness rules. Control and graph requirements must both remain expressible;
the current experimental graph scope is not a permanent ban on control capabilities.

## 5. Catalog and archive consistency

Hold the correct outer lifecycle window through observation, dump and publication.
It coordinates cooperating RepoMap actors. The supported workload also needs an
explicit trusted-administrator DDL-quiescence precondition; advisory locks do not
constrain an unrelated superuser.

Record before/after catalog and relevant dependent-object fingerprints and compare
them to archive metadata. A difference refuses publication or support; equality
is only a drift detector. It does not prove absence of transient DDL, changes to
extension members, or changes outside the observed inventory. No OID/xmin ABA
guarantee is claimed. A shared exported snapshot may be part of a later proven
protocol; it is not a substitute for declared lifecycle/DDL ownership.

Observe extension identities, schema/owner facts, member/dependent-object identities
and configuration metadata under that consistent boundary. Compare only facts the
actual archive representation exposes. Establish extension creation SQL, schema
entries, baseline omissions and comment/ACL behavior with real `pg_dump -Fc` and
`pg_restore -l`/script rendering. A fixture that rewrites plain SQL is insufficient.
Unknown snapshot coverage or catalog/archive inconsistency cannot satisfy D9.

## 6. Target preflight before any target creation

For a coordinated restore, validate the entire selected graph/control set before
the first `CREATE DATABASE`. For single-graph extraction, validate that configured
graph and the selected archive unit, without claiming a complete-set restore.
Preserve current extraction behavior; no new opt-in flag is proposed.

The future extension protocol requires:

1. Strict manifest, scope, archive integrity, TOC and policy-binding validation.
2. Observed target server/client/platform compatibility, source creation-semantics
   compatibility and trusted immutable artifact availability. Major-version
   equality alone does not establish ABI/library or locale compatibility.
3. Every exact required version and prerequisite being installable in its recorded
   schema. A non-null fixed-schema constraint must match; non-relocatable alone
   does not imply a non-null fixed schema. Compare actual policy requirements.
4. Lifecycle creation/installation privileges and approved owner identities;
   target absence and held lifecycle ownership for every selected database.
5. Declared principal readiness with no mutation of arbitrary source roles.

Available-version/control rows are necessary metadata, not proof that a library
loads or that installation will succeed. Preflight requires a qualified artifact/
platform policy, not an assertion generated from those same rows. It must refuse
when an ADR 0051 D9 prerequisite cannot be established. Revalidate at mutation
boundaries; preflight never promises that later external drift is impossible.
No opportunistic acquisition, compilation, package installation or runtime fallback.
Support for arbitrary external servers remains outside this initial scope.

## 7. Future per-database extension restore protocol

The required order is: create the new database with validated creation semantics;
install prerequisite extensions as lifecycle administration at each exact recorded
version/schema; verify version/schema/approved owner and a bounded functional
probe; apply the verified original archive; reconcile approved grants; verify
schema, dependent objects, capability readiness and role constraints.

Do not replace source locale semantics with fixed UTF8/C defaults. A controlled
template may be selected only when its baseline and creation attributes are
verified. Do not assume template0 is immune to administrator modification.
No blanket owner rewrite of `public` or other bootstrap objects is proposed.

The proposed derived TOC permits exclusions only for precisely identified objects
already satisfied by verified pre-installation. Bind original archive, original
listing, selected/excluded entry identities, reasons and derived-list digest.
Preserve every required application/data/type/index/constraint/function/sequence
entry. Unknown, duplicate or ambiguous entries refuse. No prefix matching that
can discard unrelated objects; no silent filtering, ignored SQL errors or archive
rewriting. Preserve or explicitly disposition extension comments/ACLs as well.

`-L` needs a second input while the original archive is streamed. Materialize
the bounded derived list as a 0600 file in an invocation-owned 0700 directory
inside the exact target container; the internal route uses equivalent private
local storage. Verify uploaded bytes/digest and close handles before replay.
Track exact container/runtime and temporary-resource ownership; clean up in
`finally` without masking the initiating failure. Never use a host bind, shared
temporary path, broad deletion or an unowned target file.

Real tests must prove selected custom-archive restore from that non-seekable input.
If this transport does not work, refuse and revise the design before deployment;
there is no automatic SQL rewrite, silent archive spooling or filtering fallback.
`--exit-on-error` is proposed for this new protocol and must be tested. It is not
silently added to the retained legacy core protocol in D9-A.

## 8. Principals, configuration data and privacy

Keep the existing `--no-owner --no-privileges` normalization explicit: it does
not preserve arbitrary source object owners/ACLs and does not make an untrusted
archive safe. Restore accepts only authorized, trusted-source recovery artifacts.
Expected extension owners and any mapping come from accepted lifecycle policy;
unapproved owners refuse rather than being silently adopted.

Capability roles retain current LOGIN/no-escalation/NOINHERIT and zero-ownership
requirements, including across the cluster where current role reconciliation
checks them. Bootstrap/lifecycle ownership is observed separately. Baseline role
provisioning remains the existing post-restore responsibility using private
configured credentials. Do not provision or delete arbitrary archive principals
during preflight. Missing required custom principals refuse before database creation.

Optional ACLs must follow `semantic_candidate_import.candidate_schema_sql` for
the configured distinct reader and enrichment writer, with its actual column
set and required reads on the five core public tables. The writer has the
existing SELECT/INSERT permissions, without invented UPDATE/DELETE grants or
new refresh-publication grants. `enrichment_principal` is excluded from writer
INSERT columns so new rows use current_user; archived row values remain data.
Privileges apply to supported SQL object kinds; operators are not standalone
EXECUTE grant targets. No unrelated default-privilege policy change is proposed.

Inspect every extconfig/extcondition pair, preserving positional pairing and
resolving relation/sequence identities and filters. Do not infer emptiness from
an extension/version name. The initial protocol refuses non-empty configuration
metadata before creation while recording the private observation. Future support
requires an accepted plan for seed rows, filtered data, sequence state and foreign-
key ordering. A real non-empty fixture must prove the initial refusal.

Manifests/receipts/catalogs are private. Retain only configured role declarations
and catalog facts required for decisions; do not copy distinct historical row
principals into the manifest. Synthetic integration assertions can verify row
provenance and data equality without exporting private row values. Never retain
passwords, DSNs, raw private stderr or operational identifiers in public evidence.

## 9. Legacy compatibility, failures and rollback

Version 1 remains readable and explicitly unrecorded for capability provenance.
Do not synthesize version-2 facts or call a TOC-only absence result D9 proof.
The proposed new guard refuses an explicitly non-baseline extension in a legacy
archive before creation. Non-public core schemas alone do not trigger that guard.
Preserve existing core flags, reason codes, creation defaults and graph selection
in D9-A. A stronger legacy refusal or default change needs an explicit amendment,
compatibility evidence and separate decision; it is not bundled as hardening.

Version 2 retains originals and identifies its protocol. A legacy binary may
refuse it. Keep a compatible reader and sufficient original recovery material;
never downgrade metadata by deleting observations or relabeling the version.

Record intent before mutating calls and distinguish not-created, created and
outcome-unknown. A lost CREATE acknowledgment is not evidence of absence.
Hold lifecycle authority and bind exact server/cluster/database ownership before
cleanup. If ownership cannot be reconciled, retain bounded private evidence and
require intervention; never drop a concurrently created or replaced target by
name alone. Continue cleanup of independently proven owned targets as appropriate.

Attempt all known invocation-owned target cleanup in reverse order; preserve
the initiating error and report bounded secondary cleanup failures. Never drop
shared roles, unrelated/preexisting databases or use CASCADE. Handle interruption
and unknown outcomes explicitly. Cross-database cleanup is compensation, not
transactional atomicity. D10 data-bearing exit migration remains separate.

Dry-run performs only authorized read-only inspection and reports which checks
actually ran. An offline plan cannot report target preflight complete. It performs
no role/database/extension mutation; any private scratch files have exact cleanup
ownership and are not confused with runtime changes.

## 10. Scoped implementation evidence and remaining qualification

Current owners to preserve/update as affected:

- `src/test/unit/python/repomap_kg/runtime/arch7d2_exact_coordinated_backup_sets.unit.test.py`
- `src/test/unit/python/repomap_kg/runtime/arch7d3_deterministic_complete_set_restore.unit.test.py`
- `src/test/unit/python/repomap_kg/runtime/arch5b_provisioning_recovery.unit.test.py`
- `src/test/unit/python/repomap_kg/runtime/arch7e_declarative_database_roles.unit.test.py`
- `src/test/int/python/repomap_kg/runtime/slice9_coordinated_backup_restore.int.test.py`
- `src/test/int/python/repomap_kg/runtime/arch7e_database_roles.int.test.py`
- `src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py`

The slice9 integration location does not make its injected pg_restore boundary
real. The implemented D9-A provenance owners are
`src/test/unit/python/repomap_kg/runtime/d9_manifest_provenance.unit.test.py` and
`src/test/int/python/repomap_kg/runtime/d9_manifest_provenance.int.test.py`.
D9-B additionally needs a focused restore unit owner and
`src/test/int/python/repomap_kg/runtime/d9_extension_restore.int.test.py`.
The D9-A owners exist; the D9-B restore owner remains future work. Freeze exact selectors and stopping rules
in each accepted implementation assignment, including coordinator/release callers
whose actual owners are affected. Do not convert the whole legacy population.

Use canonical `tools/run_tests.py --suite unit --no-coverage -- <exact owners>`
and `tools/run_tests.py --suite int --no-coverage --pg-container-port 55433 -- <exact owners>`.
Optional SQL nodes use the existing separately admitted `--pg-test-profile pgvector`
only in their bounded assignment. No complete-suite or local-coverage override is
provided. NAVIGATION36 executed no source checks. NAVIGATION37 executed exact scoped unit
and core containerized integration owners; complete suites remain unselected.

D9-A requires real catalog/TOC observations and refusals across both single/set
and all backup-first consumers, valid core/user-schema compatibility, legacy
readability and exact support propagation. Unit injections prove orchestration
and bounded parser errors; they do not qualify a real SQL or artifact boundary.

D9-B must prove all of these real boundaries:

1. Fresh target cluster with required roles absent, preserving current baseline
   post-restore provisioning and refusing missing custom principals before creation.
2. Exact installed version when the target's default differs from the recorded
   version; catalog and functional readback before unchanged-archive replay.
3. A real core-only/missing-artifact target and incompatible platform/version
   observations, with complete-set refusal before any CREATE DATABASE.
4. Unchanged custom archive plus verified private derived TOC and actual streamed
   replay, including schema/extension/comment/ACL behavior and every required entry.
5. Actual non-empty extconfig/sequence metadata and refusal. A versioned synthetic
   SQL-only fixture can be proposed within owned sandbox authority; if unavailable,
   name the gap rather than simulate it as real or acquire a new dependency.
6. Exact existing optional grants, spoof/UPDATE/DELETE refusals and preserved
   synthetic archived row provenance without additional summary payloads.
7. Multi-level extension dependencies, source/target drift, inconsistent manifests,
   wrong owner, incompatible creation semantics and stale artifact-policy bindings.
8. Mid-restore failure, failed cleanup, lost acknowledgment, interruption, externally
   replaced targets and TOC cleanup failure, with exact ownership/resource evidence.

The same-cluster, preinstalled-extension, rewritten-plain-SQL fixture remains
diagnostic. Hosted core CI does not establish optional-profile or D15 admission.
No performance, model usefulness, rights, labels or production claim follows.

## Primary references

PostgreSQL 16 documentation checked 2026-10-20; independently written synthesis.
These references establish engine semantics, not this project's executed proof.

- [pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html)
- [pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html)
- [CREATE EXTENSION](https://www.postgresql.org/docs/16/sql-createextension.html)
- [pg_extension](https://www.postgresql.org/docs/16/catalog-pg-extension.html)
- [Extension packaging and configuration relations](https://www.postgresql.org/docs/16/extend-extensions.html)
- [pg_depend: dependency kinds](https://www.postgresql.org/docs/16/catalog-pg-depend.html)
- [System information/control functions](https://www.postgresql.org/docs/16/functions-info.html)

## NAVIGATION37 bounded result

The final private selection passed 179 unit and 33 core
integration cases. Additional owners `d9_postreview_boundaries.unit.test.py`,
`d9_final_boundaries.unit.test.py` and `d9_final_catalog_boundaries.int.test.py`
cover strict archive/provenance validation, raw TOC names, exact endpoint custody,
bounded process cleanup, SQL condition pairing and real acquisition settings.
Real SQL tests demonstrate refusal of null, missing and extra configuration
conditions, preserve valid filter bytes, and exercise nonzero and bounded
overflow responses before manifest publication. Core backup/restore and all
backup-first consumer refusal checks use the canonical container sandbox.

SQL and native process observations complement injected orchestration tests;
they do not turn an injected restore into executed archive replay. The final
selection uses `--pg-test-profile core` and `--no-coverage`. Optional pgvector
qualification, complete-population coverage and D9-B target admission remain
separate. See ADR 0084 for review and post-review amendment limits.
