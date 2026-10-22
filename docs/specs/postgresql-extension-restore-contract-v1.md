# PostgreSQL Extension Restore Contract v1

Status: D9-A's public staging predecessor is hosted-qualified by
[CI56](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/39540435586).
The operator separately approved bounded D9-B on 2026-10-21. This is its
implementation candidate, `REPOMAP-PRODUCT6-NAVIGATION40-EXTENSION-RESTORE1`; new hosted qualification is pending.
Production pgvector/D15 admission and configuration-data replay remain separate.

[ADR 0084](../adr/2026/10/0084-extension-aware-backup-and-restore.md) records the
decision. [ADR 0051](../adr/2026/08/0051-postgresql-extension-and-database-capability-architecture.md)
remains the capability authority. The
[staging milestone note](../../tools/ci/nav40-extension-restore.md) records the
bounded publication scope. Metadata and scoped evidence do not establish complete
hosted qualification.

## 1. Bounded implementation sequence

**D9-A, recommended first:** add versioned observations, strict reader validation
and a shared support/refusal decision across every backup-first consumer. Preserve
current core restore flags, creation semantics, reasons and graph-selection
behavior. Do not install extensions, enable optional production defaults or
implement derived-TOC replay in this slice. Non-baseline extensions remain
unsupported regardless of complete metadata or experimental fixture availability.

**D9-B, separately approved on 2026-10-21:** implement and prove the bounded target
D9 restore protocol under NAVIGATION40. A disposable experimental policy may qualify
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
inside the exact target container. Any qualified internal route must use equivalent
private local storage. The current bounded `extension_v2` implementation refuses
container-internal execution because its Engine identity cannot be established;
no positive internal-route support or native proof is claimed. Admitting that
route requires separately proven identity and custody; `core_v1` is unchanged. Verify uploaded bytes/digest and close handles before replay.
Track exact container/runtime and temporary-resource ownership; clean up in
`finally` without masking the initiating failure. Never use a host bind, shared
temporary path, broad deletion or an unowned target file.

Real tests must prove selected custom-archive restore from that non-seekable input.
If this transport does not work, refuse and revise the design before deployment;
there is no automatic SQL rewrite, silent archive spooling or filtering fallback.
`--exit-on-error` is proposed for this new protocol and must be tested. It is not
silently added to the retained legacy core protocol in D9-A.

### 7.1 Selected D9-B engineering mechanisms (NAVIGATION40 correction2)

Recorded before the corresponding code, within the obligations above. They
select mechanisms only; they do not claim implementation, proof or qualification.

- **Source facts and target baseline.** The source `creation_semantics.template`
  stays the observed `unknown`; PostgreSQL does not record the historical template.
  Source encoding, provider, collation, ctype, ICU locale and collation version are
  compatibility inputs, separate from target policy. The only selectable target
  template is `template1`. `template0` cannot be observed logically without
  changing `datallowconn`, and filesystem or statistics heuristics are not a
  baseline. The caller policy binds each admitted Engine image content ID to a
  clean-reference SHA-256. That digest covers a bounded canonical logical baseline
  over every PostgreSQL 16 database-local catalog. Volatile statistics columns
  are excluded, and ACLs are normalized to role OIDs. Large-object and
  user-mapping rows are covered through their public metadata. An unexpected local
  catalog set refuses. The reference comes from a separate clean cluster of the
  same admitted artifact, never from the target. Before the first creation,
  preflight reads template1's attributes and digest without mutation.
  Source locale facts must equal template1's, as template1 requires, including a
  collation version observed on both. The digest is revalidated before each
  `CREATE DATABASE`. Each new database must show the same digest before
  installation. A modified template refuses before any creation. Digest equality
  detects drift; it does not exclude superuser changes between checks.
- **Lifecycle authority.** Reuse canonical key `0x5245504F`, endpoint and namespace
  resolution. Hold it exclusively on the maintenance database for the invocation,
  serializing `extension_v2` restore actors. Also hold it on each created target
  through a dedicated connection, from just after creation until finalization or
  compensation. This excludes canonical maintenance windows and shared maintenance
  activity on that database. Custody names only databases actually locked.
  Endpoint or lock failure refuses for every runner. While that connection exists,
  cooperating actors cannot drop or rename the database. Identity is revalidated
  through it at each mutation seam: OID, system identifier, container, stamp.
  Compensation issues `DROP DATABASE ... WITH (FORCE)` only while it is held.
  Lost custody, an outcome-unknown creation or a mismatch retains the target and
  ledger for intervention. Between `CREATE DATABASE` and target lock acquisition,
  only maintenance-database serialization and the trusted-administrator,
  single-lifecycle precondition apply. Legacy `core_v1` restore and provisioning
  do not take that lock. No hostile-superuser or ABA guarantee is claimed.
- **Artifact and client identity.** The target identity is the Engine `Image`
  content ID; when it is missing, the restore refuses, and `Config.Image` is never
  consulted. Optional registry manifest digests come only from inspecting that
  exact content ID. `extension_v2` requires exact pg_dump and pg_restore versions
  recorded at the source and exact pg_restore and psql versions observed at the
  target. The container and image content ID are revalidated at mutation seams.
- **Native custody.** Owned input files use exclusive no-follow creation, recorded
  identity, complete writes and fsync. Removal is identity-verified in `finally`
  and preserves the initiating `BaseException`. The container TOC script reports
  directory and file identities immediately after exclusive acquisition. Cleanup
  removes only proven identities. After unknown acquisition, a bounded existence
  probe either reports absence or retains and reports the path.
- **Replay bounds.** Whole-archive `extension_v2` replay requires explicit caller
  policy bounds: a deadline and an output ceiling, with no default. They are
  outside the trust digest and are not capacity qualification. TOC limits do not
  apply, and `core_v1` replay is unchanged.
- **Optional rows and grants.** Historical rebuild rows remain data. Each row must
  match its own run's canonical receipt: recomputed receipt and profile identities,
  generations, bundle, snapshot and row count. Any non-empty historical principal
  is accepted. Node and evidence binding is required for rows of the current
  accepted publication. Grants use a bounded projection parsed from
  `candidate_schema_sql`; restore verifies both positive and negative privileges.


### 7.2 Preimplementation refinement: recovery binding and container command custody

Selected by the parent within approved bounded D9-B before correction3 code.
Implementation, independent review and new-candidate qualification remain pending.

**Stable backup declaration, current target qualification.** The stored policy
binding identifies the accepted source capability declaration: policy identity,
protocol selection and exact extension rules, including versions, schemas,
ownership, prerequisites, artifact expectations and optional role contracts.
Restore-target qualification inputs (admitted Engine IDs, server/client/platform
sets and clean template references) and operational replay bounds are separate
current restore inputs. They must not enter that stable declaration digest.
A later independently qualified target can therefore be considered against the
original unchanged backup without re-dumping or rewriting its manifest. Source
observations and archive bindings stay mandatory and are checked against current
independent qualification; a changed declaration, tampered source fact, missing
qualification or unavailable target still refuses before creation. This does not
admit new extension artifact variants or production/D15 policy. The first public
extension protocol must define the digest representation explicitly; legacy
format1 and `core_v1` behavior remain unchanged.

**Container-side command lifetime.** A killed host `docker exec` client is not
proof that its container process or PostgreSQL session ended. New extension
restore commands require bounded, invocation-owned control of their actual
container-side execution, using only existing qualified image facilities. Bind
immutable container identity and exact process/start identity, private control
resources and a unique invocation/session identity. A deadline or interruption
must settle the owned remote execution and any correlated database work, or
retain a specific unknown-outcome record and refuse further mutation. Never
signal a reused/unowned PID, an unrelated session or a replaced container. Host
process, remote process, PostgreSQL outcome and resource removal are distinct
proofs. Preserve the initiating exception with bounded secondary diagnostics.
No package/image acquisition or fallback to a positive host-only cleanup claim is
allowed. The existing query/TOC/cleanup ceilings and explicit replay bounds stay
owned separately; existing core command execution is unchanged.

Required scoped native evidence includes a real container command timeout or
interruption through the production bounded path, remote/process/backend outcome
and exact cleanup receipts, unchanged-archive restore on an independent target,
and later target qualification using the original backup. Setup injection and
native fault/observation boundaries must be distinguished. Unknown effects remain
conservative, with retained private evidence; preflight does not claim absence of
external administrator drift or an ABA guarantee.

**Correction3 technical refinement (recorded before the corresponding code).**
The `extension_v2` policy binding is the exact record `d1_baseline`, `d3_policy`,
`policy_id`, `declaration_format` = `repomap-extension-declaration-v1` and
`declaration_sha256`. The digest is SHA-256 over sorted-key compact UTF-8 JSON of
`format`, `policy_id`, `allow_extension_v2` and every extension rule with all its
fields, ordered by name and database roles. The stored record must equal the record
of the current policy. A record without this format, such as an earlier experimental
`policy_sha256`, refuses; it is not migrated.

Each new container command runs by immutable container ID under a POSIX `sh`
supervisor. The supervisor exclusively creates a 0700 control directory and a 0600
`pid starttime token` record, sets a unique `application_name`, then `exec`s the
command, so the recorded process is the command. After every command a separate
bounded settlement exec reads that record. It signals only a live process whose PID,
start time and environment token all match, waits at most 2 s, and removes only that
control path. An absent control directory is fenced by settlement so that a late start
cannot run. Settlement never writes into or removes an existing directory without a
matching record; that state remains unknown and retained. After a
failed PostgreSQL client command, correlated sessions are terminated by exact
`application_name` and current role, then their absence is read back. Settlement
uses a 10 s host deadline and a 4096-byte output ceiling; session settlement uses a
5 s statement timeout and a 2 s termination wait. An unobserved or unsettled outcome
must be retained in a concrete private execution record. Later commands, including
compensation, must refuse while the relevant outcome remains unknown. A failed
`CREATE DATABASE` becomes not-created only after settlement and absence observed
under the held maintenance lock. Extension replay uses no parallel `pg_restore` jobs.
The preflight archive listing retains the existing 60 s/4 MiB TOC limits.

### 7.3 Execution custody completion requirements

Recorded before further implementation in NAVIGATION40 correction4. The correction3
candidate is not accepted: its preflight, process-descendant and reused-command
exceptions do not satisfy section 7.2. The following complete those existing
obligations without admitting a new protocol, artifact or production capability.

- Every container execution used by `extension_v2`, including client-version
  probes and reused baseline role reconciliation, must use its immutable container
  binding and bounded execution custody. Host `docker inspect` creates no container
  process and retains its existing bounded host handling. Legacy `core_v1` behavior,
  flags, secret transport and role semantics remain unchanged.
- An unsettled preflight command requires a durable private execution record that
  identifies the invocation, immutable container and exact retained resources. It
  must distinguish command state from target ownership and must not represent the
  maintenance database as an invocation-created target. Outstanding unknown state
  refuses subsequent restore attempts until settled or explicitly handled.
- A retired shell leader does not prove that its descendants stopped. Either
  settle actual owned execution, including relevant children, or record the remaining
  uncertainty and refuse continuation. Preserve the qualified trusted-administrator
  model; this is not a hostile-administrator or ABA guarantee.
- Positive host retirement requires explicit evidence. Neither a successful client
  exit nor the absence of exception context proves that host cleanup completed.
  A typed runner observation or conservative unknown classification is required.
  The existing `_backup_process.py` is an authorized causal owner for this fix;
  existing core success/error behavior and every process budget remain unchanged.
- Compensation must refresh execution outcomes that arise during cleanup itself
  before attempting another command and before persisting its final record. Guard
  ownership-query and cleanup I/O failures, preserve the initiating exception and
  retain bounded secondary diagnostics and the exact unresolved state.

Required scoped evidence distinguishes native observations from injected triggers
and parser-only handling. Check timeout/interruption, child-process uncertainty,
preflight retention and compensation failures before disposable-container teardown.
No new utility, image, dependency, full local suite or local coverage is authorized.

**Correction4 technical refinement (recorded before the corresponding code).**
These select mechanisms for the requirements above; they claim no proof.

- *Typed host retirement.* `run_bounded_process` accepts an optional typed
  retirement observation. It becomes `retired` only after the owned process group
  was signalled and its leader reaped without error. A pending, started or
  interrupted retirement is host `unknown`. Callers that pass none keep their exact
  output, errors, deadlines, ceilings and 2 s retirement wait.
- *Piped input.* The bounded runner may also feed bounded stdin bytes through a
  non-blocking pipe under the command's own deadline. Role reconciliation uses it,
  so its secret-bearing SQL is not written to disk. The stdin-file path is unchanged.
- *Client probes and role reconciliation.* With the stdlib runner, each `--version`
  probe runs supervised by immutable container ID within the existing 4096-byte and
  5 s limits. A settled failure keeps the existing `unavailable` observation; an
  unsettled one refuses. The core role helper still renders and validates its SQL.
  Its single container exec is routed through the same custody with the existing
  30 s observation deadline, 2 MiB ceiling, error code and label. A caller-supplied
  runner keeps the shared core path; `core_v1` callers are untouched.
- *Descendants.* The supervised command and every descendant inherit the exported
  invocation token. On each path that would otherwise settle, settlement scans the
  container's `/proc` for live processes whose environment carries that exact
  token, excluding itself. It SIGKILLs one only while its PID and start time still
  match the scanned identity, rescans for up to 2 s, then reports `DESCENDANTS`
  `none`, `killed` or `remaining`; an unscanned path reports `unknown`. Settlement
  requires `none` or `killed`. Supervised commands do not change credentials, so
  their environments stay readable to the same exec user.
- *Sessions.* PostgreSQL sessions inherit the exported `application_name`. They
  are settled after any failed command, or after descendants were killed,
  whether or not the leader is a PostgreSQL client. A fenced command needs none.
- *Durable execution record.* An unsettled preflight outcome is written atomically
  to a 0700 `.restore-exec-record-<id>` directory as a 0600 `record.json`. Its
  `record_type` is `repomap-extension-exec-record-v1`, with phase, invocation ID
  and immutable container ID. Its `owned_targets` list is empty. Each unknown
  command keeps its label, token, separate host/remote/descendant/session/control
  observations and exact control path. Intent-ledger entries carry the same
  command records. While a record or intent ledger exists, `extension_v2`
  preflight and execution refuse before any container command. Operator inspection
  removes it. A failed record write is a secondary diagnostic beside the primary.
- *Compensation.* Unknown outcomes are re-read before each target and immediately
  before the ledger write. Held-identity verification runs inside the guarded
  drop handling: an exception retains that target, and an interruption also stops
  later drops. Either way the initiating exception survives.

**Correction4 review refinement (recorded before the corresponding code).** The
independent work review found, and a native check in the disposable container
then confirmed, that the descendant mechanism above broadens cleanup. In the
qualified PostgreSQL image the postmaster is the container's PID 1, so it reaps
every reparented orphan. To the postmaster, any reaped exit other than 0 or 1 is a
crashed server process, so it terminates every session. That included an unrelated
held connection. These replace the corresponding parts of the bullets above:

- *Descendant order.* Settlement signals token-bearing descendants leaf-first,
  while their live parent can still reap them. It signals the supervised leader
  only once no other token-bearing process remains. It never signals a
  token-bearing process whose parent is PID 1. It never signals the leader while
  such an orphan exists, or while a live child of the leader or of a token-bearing
  process lacks the token. That child may be unreadable or may have changed its
  environment. These cases report `DESCENDANTS remaining` or `unknown`; they are
  retained, never signalled. An orphan that has already lost its token, or has
  changed credentials, is outside the qualified trusted-administrator model.
- *Sessions with remaining descendants.* When descendants are `remaining`,
  correlated sessions are not terminated, because a terminated orphaned client
  exits abnormally. They stay `unknown` and retained.
- *Retained control resources.* Any durable execution record or intent ledger
  lists every command whose outcome is unsettled, plus every settled command whose
  control path was not removed. Each entry gives that exact control path, and
  every settlement diagnostic names it too. Only unsettled outcomes refuse further
  commands and compensation, as before.

### 7.4 Reaping and process-creation quiescence

Recorded before correction5 source changes, within the same bounded D9-B scope.
The final correction4 source still skips zombie processes during its census and
discloses a possible fork between the last scan and leader termination. These are
questions to verify natively before acceptance, not evidence of a reproduced fault.

A terminated child may remain waitable until its parent reaps it. Such a child
must not count as absent when deciding whether terminating the parent can broaden
cleanup. A momentarily childless census while a parent remains able to fork also
does not establish safe termination. Establish the required quiescence using
existing qualified facilities, or retain the precise uncertainty without signalling
that parent. Preserve the existing refusal, private-record and primary-error rules.

Use a paused invocation-owned parent, actual child state and an unrelated held
session to distinguish reaping from termination in the disposable native proof.
If the suspected path is refuted, retain that evidence rather than making an
unnecessary product change. No new image, init process, dependency, core behavior,
complete local suite or local coverage is authorized by this verification.

**Correction5 technical refinement (recorded before the corresponding code).** A
native check on the correction4 source established the concern. The leader stopped
itself after its psql child's session became visible. In one case the child exited 3
and stayed a zombie of that leader, yet settlement reported `none` and killed the
leader. In the other case settlement killed the live child while its parent could not
reap it, then killed the leader. Both times the PID 1 postmaster reaped the adopted
child and crash-restarted, ending an unrelated held session. These mechanisms
supplement the correction4 bullets:

- *Census.* Settlement counts every process in the container's `/proc`, including
  zombies, which it attributes by PPid. A terminated child of a token-bearing process
  stays present until it leaves `/proc`.
- *Reaping.* While a token-bearing process has a zombie child, that parent is never
  signalled. Settlement waits within the same 2 s rescan window for the reap. If the
  zombie remains, it reports `DESCENDANTS unreaped`, and the outcome is retained.
- *Reapable parents only.* Settlement signals a token-bearing descendant only while its
  parent is a live, unstopped token-bearing process. A child of a stopped parent stays
  `remaining`.
- *Quiescence before SIGKILL.* Before any SIGKILL, settlement stops the target with
  SIGSTOP, unless it is already stopped. It then confirms the stopped state within 1 s.
  It sends the kill only if a census taken while the target is stopped shows no child of
  it in any state. A stopped process cannot fork, so that census stays true until the
  kill. Otherwise settlement resumes the target, but only if settlement stopped it. It
  retries the leader at most three times. A leader still not killed is `REMOTE alive`,
  `DESCENDANTS unknown`.
- *Explicit pause state.* While settlement holds its own stop, a `halt` file inside the
  exact control path names that PID and start time. Settlement removes the file after
  the kill or the resume. A retained control path therefore names any pause left by an
  interrupted settlement. Settlement never resumes a stop that it did not introduce.
- *Sessions.* Correlated sessions are not terminated when descendants are `remaining` or
  `unreaped`. Every report first checks for a token-bearing process whose parent is
  PID 1, whatever order `/proc` lists processes in. This includes reports whose control
  record is unproven. Any such process is `remaining`.
- *Operator recovery.* A retained child under a stopped leader is released by resuming
  that leader so that it reaps the child. Killing the leader would hand the child to
  PID 1.

**Correction5 close refinement (recorded before the corresponding code).** The
independent work review found that the reapable-parent rule was checked only against
the pass-wide census. One pass can hold several stops of up to 1 s each, so a later
target could be stopped and killed after its parent had exited and PID 1 had adopted
it. These rules supplement the bullets above:

- *Fresh parent check.* Immediately before stopping a descendant, and again after
  confirming its stop and immediately before the kill, settlement re-reads the
  target. Its PPid must still name the parent from the census, and that parent must
  still be live, with the same start time, and neither stopped nor traced. Otherwise
  settlement does not signal the target.
- *Exact resume.* Settlement resumes its own stop only while the target keeps its
  start time and its census parent. If PID 1 adopted the target during that stop,
  it stays stopped. Its `halt` file stays in the retained control path, and the
  report is `remaining`. The pause is created exclusively, so a `halt` file that
  already exists prevents any new stop.
- *Observed leader child.* If a leader attempt fails after the stopped leader was
  seen with a child, a leader still alive after three attempts reports `DESCENDANTS
  remaining`, not `unknown`. Its correlated sessions are not terminated.

This refinement is wrong if a stopped process can still create a child. It is also
wrong if a zombie can leave its parent other than by being reaped or adopted. If either
holds, the census before the kill does not prove quiescence. Two windows remain,
without pidfd. A parent can exit between the final re-read and a signal, the same
probe-then-signal window as PID reuse. A live parent can also exit after the kill
without reaping the killed child. Settlement does not stop that parent, because a
stopped parent cannot reap. Either case hands an abnormal exit to PID 1. This
refinement does not claim to exclude them.

### 7.5 Conservative descendant retention

Parent decision before correction6 code, within the same approved bounded D9-B.
Correction5's disclosed exit-before-reap window is not accepted. A fresh parent
identity check cannot guarantee that the parent remains alive to reap a child
that settlement has killed. This is an ordinary execution failure, distinct from
hostile PID reuse. No pidfd, new dependency, init process or image is needed to
avoid inducing that failure: retain the uncertain execution instead.

Settlement must not signal any non-leader invocation process, whether live,
stopped, adopted or unreaped. It may observe bounded natural completion/reaping.
While such a process or an uncertain child remains, keep the exact private control
state, report remaining/unreaped/unknown accurately and refuse continuation.
Do not terminate correlated PostgreSQL sessions for any of these states, including
unknown. Native target effects are not disproved by host-client retirement.

Only the recorded supervisor leader may be stopped or killed: its PID/start/token
must still match, it must not be adopted by PID 1, and a census after its confirmed
stop must prove it has no child in any state. A child discovered at this boundary
causes conservative retention, never a descendant kill. Every introduced pause
keeps its exact PID/start record until its own kill or identity-checked resume is
confirmed; an unproven resume keeps that record. Never resume an externally
introduced stop or a process adopted by PID 1. Preserve the qualified stable
Docker-exec runtime and single-binary client model; this is no hostile-host or
atomic-PID guarantee. Source and tests must state that boundary honestly.

The corresponding unit fixture must retain original process handles and use their
PID-reuse-checked signalling for cleanup, instead of signalling historical numeric
PIDs after a wait thread has reaped them. Unit metadata remains simulated; native
Linux child and bystander observations remain in disposable integration tests.

These supersede every earlier descendant-signalling mechanism. Healthy direct
client commands and compensation of proven-settled failures stay supported.
Unknown failures already require operator intervention under the approved scope.

**Correction6 technical refinement (recorded before the corresponding code).**
These select mechanisms within the invariant above; they claim no proof.

- *Observation only.* The census still counts every process, including zombies
  by PPid. For up to the same 2 s it waits for token-bearing non-leader processes
  to finish and for zombie children to be reaped naturally, and sends them nothing.
  A token-bearing process whose parent is PID 1 is `remaining`, whether or not it
  is the recorded leader. A live untokened child of a token-bearing process is
  `unknown`. At the deadline a live token-bearing non-leader is `remaining` and a
  zombie child is `unreaped`. `killed` is no longer a descendant observation: the
  parser reads it as `unknown`, and only `none` settles descendants.
- *Leader retirement.* The leader is considered only after a census reports
  `none`. It needs the recorded PID, start time and token and PPid 0, the exec
  shim outside the container's PID namespace. A leader under PID 1 or any
  in-container parent is never signalled; it stays `alive`, retained, and is
  reported `remaining` when adopted by PID 1 and otherwise `unknown`.
  Settlement stops it unless it is already stopped, first recording that stop
  exclusively in `halt`. Once the stop is confirmed within 1 s, a census must show
  no child of the leader in any state. A fresh read must then still show it
  stopped, with the same start time and the same PPid as before the stop. Only then
  is it sent SIGKILL. `halt` is removed only after the leader is seen no longer
  live. An existing `halt` record prevents every signal.
- *Child at the stop boundary.* A child found by that census is sent nothing.
  Settlement resumes only its own stop, and only while the leader keeps its start
  time and pre-stop PPid. It removes `halt` only once it sees the leader running
  again. It reports the leader `alive` and the control path `retained`, with the
  fresh census result, or `remaining` if the child has gone by then. A leader that
  was adopted, changed identity or still looks stopped keeps its `halt` record. A
  stop not confirmed within 1 s is resumed the same way and retried at most three
  times; then the leader is `alive` with `DESCENDANTS unknown`.
- *Externally stopped leader.* A stop that settlement did not introduce is never
  resumed. Such a leader is killed only after the same childless census and fresh
  identity and PPid read; otherwise it stays stopped and is retained.
- *Sessions.* Correlated sessions are terminated only after a failed command whose
  descendants are `none` and whose remote outcome is settled. `remaining`,
  `unreaped`, `unknown` and any unsettled remote outcome leave them `unknown`.

Under the qualified Docker exec runtime the leader's parent is the runtime's exec
shim, outside the container's PID namespace (PPid 0), and that shim reaps it.
Settlement requires that PPid before the stop and again before the kill, and the
native integration owner observes it on the live leader rather than assuming it. A
shim crash or PID reuse between the final read and the kill is outside that
runtime model; it is not an ordinary execution failure, and this is no atomic-PID
or hostile-host guarantee. This refinement is wrong if settlement can signal any
non-leader invocation process, or if a stopped leader can gain a child in that
interval. That would need a child subreaper, outside the single-binary client
model. It is also wrong if an ordinary exit of any process during settlement can
hand a process that settlement signalled to PID 1.

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
The D9-A owners exist. NAVIGATION40 adds D9-B restore owners under review;
their presence does not establish acceptance. Freeze exact selectors and stopping rules
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

## Subsequent hosted and implementation checkpoints

CI56 attempt1 executed and passed all eight jobs for staging
`157e5b88048bdc605cab1f037089c705ab555ce8`. It supersedes the historical D9-A
pending record above for that candidate. It does not qualify this later D9-B
candidate. See the [NAVIGATION40 milestone](../../tools/ci/nav40-extension-restore.md).
