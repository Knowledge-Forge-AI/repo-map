# ADR 0084: Extension-Aware PostgreSQL Backup and Restore

## Status

Accepted for **D9-A only** by the operator on 2026-10-20.
Design phase: `REPOMAP-PRODUCT6-NAVIGATION36-EXTENSION-RESTORE-DESIGN1`.
Implementation phase: `REPOMAP-PRODUCT6-NAVIGATION37-EXTENSION-PROVENANCE1`.
The approval covers format-2 provenance and unsupported-extension refusal guards
while preserving current core restore behavior. D9-B remains **Proposed**;
full extension replay and production pgvector admission remain separate.

## Date

2026-10-20

## Accepted D9-A decision

The operator approved **D9-A only**: format-2 provenance and an extension refusal guard across
every backup-first consumer, with scoped unit and real containerized integration
evidence. Preserve current core restore semantics, existing reason codes and
single-graph selection from coordinated backups. Do not introduce a new CLI flag,
fixed collation, dependency, image or production pgvector enablement.

D9-B, which would execute exact-version extension restores, remains a proposed
target requiring its own accepted scope and executable proof. Combining A and B
is not recommended. The [companion contract](../../../specs/postgresql-extension-restore-contract-v1.md)
defines the proposed fields, support decisions, evidence and remaining gaps.

## Context and governing decisions

[ADR 0051 D9](../08/0051-postgresql-extension-and-database-capability-architecture.md)
requires a new backup manifest version, observed server/artifact and exact
extension facts, complete-set target preflight before creation, exact-version
installation before archive replay and post-restore verification. D10 separately
owns data-bearing exit migration; D15 owns production admission.
[ADR 0033](../07/0033-backup-first-database-lifecycle.md) keeps destructive
lifecycle work backup-first. [ADR 0077](0077-publication-bound-pgvector-candidates.md)
permits only its experimental candidate and separately admitted disposable tests.
[ADR 0071](../09/0071-post-promotion-local-server-cloud-architecture.md) and the
[completion plan](../../../specs/postgresql-intelligence-completion-plan-v1.md)
leave useful optional pgvector and its production obligations open.

At the NAVIGATION36 design checkpoint, the writer format was 1. The whole-database `pg_dump -Fc` command has no schema
filter. A core-only image cannot establish absence of optional or foreign objects
inside a database. The pre-D9-A restore checked archives and target absence, then
streamed the dump to `pg_restore --no-owner --no-privileges`; role reconciliation
follows. That core protocol does not perform the D9 exact-extension preflight/installation sequence.
The single-DB route additionally checks graph schema readiness; coordinated
restore has no equivalent explicit final readiness call in its current seam.

The source census includes single dump/init/drop, coordinated dump/restore,
graph schema upgrade, coordinator-control upgrade and release-cluster upgrade.
The pre-D9-A release path used separate upgrade artifacts and an unconditional synthetic support
result; it cannot be omitted from a shared support decision. Current locks belong
to outer lifecycle ownership. Taking another independent advisory lock inside
`dump_database` would make existing locked callers refuse themselves.

Existing optional restore fixtures use a sibling database in the same cluster,
an existing-role/test-superuser setup and rewritten plain SQL. The coordinated
`slice9` integration owner uses injected runners. Neither proves the production
custom-archive path on a fresh cluster. The source bindings below are static
evidence, not restore qualification.

## Alternatives and recommendation

| Alternative | Benefit | Cost and disposition |
| --- | --- | --- |
| Retain format 1 and current support flags | No compatibility change | Cannot establish D9 extension safety. Retain only the explicitly legacy core path; do not admit an extension from it. |
| D9-A: observe and refuse unsupported capability sets | Smallest reviewable foundation; closes support-flag bypasses without installing extensions | New writer format and deliberate refusal of unverified extension restores; does not complete D9. Recommended first. |
| D9-B: exact-version extension restore protocol | Could satisfy the remaining D9 execution obligations after proof | Adds target preflight, installation, TOC handling and cleanup responsibilities. Proposed target; not approved here. |

The target preserves original archive bytes. A derived TOC list is the leading
proposal for entries already satisfied by exact pre-installation. Actual custom
archive behavior, including extension `IF NOT EXISTS`, schema collisions and
selective restore from a non-seekable stream, must be established by real tests.
There is no claim that every extension entry raises an already-exists error.
If the proposed stream/list transport fails, refuse and return the transport
choice for design; never ignore errors, silently omit objects or rewrite SQL.

## Proposed decisions and invariants

- Separate manifest format from restore protocol. Format 2 adds observations;
  `core_v1` preserves existing core execution semantics. `extension_v2` identifies
  a future implemented and separately qualified D9 protocol. In D9-A every
  non-baseline extension remains unsupported, even when fully observed.
- Preserve all existing format-1 fields, identifier/timestamp conventions,
  applicable optional fields and readable archives. Old readers may reject
  format 2; preserve a compatible reader and original recovery material.
- Observe every installed extension, portable schema/owner identity, exact
  version, dependencies and configuration metadata. Presence does not declare
  ownership or grant lifecycle authority. Preserve D3's required,
  permitted-foreign and unclassified distinction; template baseline and
  experimental selection are separate facts.
- Do not classify an ordinary non-public core schema as an extension. Record
  it and preserve its archive entries. Capability policy, not its name, decides
  whether special dependent objects are supported. Control requirements remain
  expressible as D6 requires; no permanent control-database extension ban is added.
- Acquire or reuse outer control-then-graph maintenance ownership. Catalog/dump
  consistency additionally assumes trusted-admin DDL quiescence. Before/after
  fingerprints detect some drift but do not prove that no transient DDL occurred.
  Missing consistency evidence cannot become a positive D9 claim.
- Gate every destructive backup-first consumer on the same bounded support
  decision, including release-cluster and coordinator paths. A dump checksum,
  non-empty TOC or newly recorded metadata is not an executed restore proof.
- Keep lifecycle administration separate from capability roles. Preserve the
  existing no-ownership/no-escalation role contract and configured distinct
  optional reader/writer semantics. Do not restore arbitrary source owners or
  ACLs, provision arbitrary archive roles or change baseline schema ownership.
- Keep manifests, catalogs, role identities, receipts and dumps private. No
  historical row-principal list is added to a summary. Public examples and tests
  use synthetic identities; operational diagnostics remain bounded and redacted.
- Compensating cleanup is not cross-database atomicity. Record creation intent,
  distinguish failure from unknown outcome, and prove exact invocation ownership
  before dropping a target. Never delete a shared role or a target by name alone.

## NAVIGATION36 design evidence

One independent work review found eleven material issues. Closing amendments
and the parent resulting-state review corrected source/ACL claims, lock ownership,
route coverage, compatibility, provenance, transport and evidence boundaries.
The parent additionally removed unverified SQL prototypes, dependency-membership
confusion, unnecessary historical-row metadata and claims of fingerprint proof.
There was no second independent review after amendments. The independent reviewer
had no shell and could not read the scratch reference packet; parent source-hash
and primary-reference checks supply those separately identified checks.

No tests, SQL, database connection, build or runtime inspection were executed
for this docs-only phase. D9-A acceptance requires its exact scoped unit and
real metadata/refusal integration owners. D9-B additionally requires a fresh
target cluster, absent-role cases, a different target default extension version,
unchanged archives, real missing artifacts, non-empty configuration metadata,
complete-set refusal before any creation and cleanup-failure/unknown-outcome
cases. The companion contract distinguishes real boundaries from mocks.

## Consequences, rollback and deferrals

The proposed foundation makes unsupported observations explicit while retaining
current core behavior. It costs a versioned writer/reader contract and integration
work across all support consumers. Keep original format-1 backups unchanged;
never relabel a format-2 archive as format 1. Rolling back the binary does not
make an old reader understand new recovery metadata.

Full extension restores, configuration-data support, D10 exit migration, D12
image evidence, D13 comparison, D15 admission, corpus rights, human labels and
model/runtime admission remain open. `utility_not_measured`; roadmap step 6 is
not complete. This proposal starts no production or private-runtime operation.

## Historical NAVIGATION36 source bindings

The following SHA-256 values identify inspected source content, not private Git
history or executed proof. These bindings describe the inspected preimplementation source, not the NAVIGATION37
resulting source. NAVIGATION37 retains separate exact-commit and source evidence.

| Source | Content SHA-256 |
| --- | --- |
| [src/main/python/repomap_kg/cli/_local_dispatch.py](../../../../src/main/python/repomap_kg/cli/_local_dispatch.py) | `sha256:336a563f263458dc9f352537e0d1be7f4ddb403c625c62b18bb59401070da067` |
| [src/main/python/repomap_kg/coordinator/_lifecycle_upgrade.py](../../../../src/main/python/repomap_kg/coordinator/_lifecycle_upgrade.py) | `sha256:5153429fb18f3e91228a156d30ca81f73329bd83adcf0ad41494f333005cfae8` |
| [src/main/python/repomap_kg/coordinator/local_lifecycle.py](../../../../src/main/python/repomap_kg/coordinator/local_lifecycle.py) | `sha256:d11c31001ec65a417d655738d10f1e98a0f2c15e20c8fc633e542319a77c145a` |
| [src/main/python/repomap_kg/runtime/_backup_lifecycle.py](../../../../src/main/python/repomap_kg/runtime/_backup_lifecycle.py) | `sha256:24c6490ec5c32c50555719198298191bf6b55e1cee6ca082aceaa70adacf16c7` |
| [src/main/python/repomap_kg/runtime/_backup_manifest_records.py](../../../../src/main/python/repomap_kg/runtime/_backup_manifest_records.py) | `sha256:e03191055059e919b182d2e9ba5215c65f5414b5dff6e2e8944ac4641e6a8d07` |
| [src/main/python/repomap_kg/runtime/_backup_operations.py](../../../../src/main/python/repomap_kg/runtime/_backup_operations.py) | `sha256:b84a916176bfb4d18a9789c952829947ade6ff5c12172af4bc593e6cdedb7b7e` |
| [src/main/python/repomap_kg/runtime/backup.py](../../../../src/main/python/repomap_kg/runtime/backup.py) | `sha256:7220acac812a9b2150714d793fabfb1dbd62298541c5c21426eb50b7eb2204a7` |
| [src/main/python/repomap_kg/runtime/backup_commands.py](../../../../src/main/python/repomap_kg/runtime/backup_commands.py) | `sha256:c5ab18fdd2fb577acb3f7bd6a03ca9aacd27f5ec4678543daf25ec86f4748048` |
| [src/main/python/repomap_kg/runtime/backup_inspection.py](../../../../src/main/python/repomap_kg/runtime/backup_inspection.py) | `sha256:2f5607e748c8c0e6ee0d611183850c80395b842bd3cb0b3192864f35aadd8b8a` |
| [src/main/python/repomap_kg/runtime/backup_manifests.py](../../../../src/main/python/repomap_kg/runtime/backup_manifests.py) | `sha256:d6d25d50f0aed60f0df74242d9890074f9f98eac26068879a152393c7369a9e9` |
| [src/main/python/repomap_kg/runtime/backup_records.py](../../../../src/main/python/repomap_kg/runtime/backup_records.py) | `sha256:da9d1ac1c7c165ba30ec797c206e3adf357837e6d52bc48b48f484a9e20d4e34` |
| [src/main/python/repomap_kg/runtime/backup_restore_sets.py](../../../../src/main/python/repomap_kg/runtime/backup_restore_sets.py) | `sha256:b5a2d2e776b24381a57c5d27a795d526203978aa81270365f46f0df12816a242` |
| [src/main/python/repomap_kg/runtime/database_role_contract.py](../../../../src/main/python/repomap_kg/runtime/database_role_contract.py) | `sha256:4f6e4b1e0d5cc75cf333aa8a4266317c6269a85ed90f6e5b788b68d8a953b0c7` |
| [src/main/python/repomap_kg/runtime/database_roles.py](../../../../src/main/python/repomap_kg/runtime/database_roles.py) | `sha256:912572200192afade846ae169bf9f012bf8f57bb7bb478fb3f1210db768c6111` |
| [src/main/python/repomap_kg/runtime/maintenance.py](../../../../src/main/python/repomap_kg/runtime/maintenance.py) | `sha256:4ec1889132036b7ce5a6cd42095b63c5e85b2ecaecc2aced745efa7c5eac23d8` |
| [src/main/python/repomap_kg/runtime/provisioning.py](../../../../src/main/python/repomap_kg/runtime/provisioning.py) | `sha256:c15af0b00d3adc49bc22075e5eb3529121d8b73f79e169cfccc8ed0091f4e23e` |
| [src/main/python/repomap_kg/runtime/release_cluster.py](../../../../src/main/python/repomap_kg/runtime/release_cluster.py) | `sha256:4ac019c70a449000d031a09d84b43439bbd886d30c072098fc7faacc2b6a6e4b` |
| [src/main/python/repomap_kg/runtime/schema_manifest.py](../../../../src/main/python/repomap_kg/runtime/schema_manifest.py) | `sha256:827bc9cb75f7cba04b0fbaea1997d7387c1803e3e0601eb48a1e283457b9a173` |
| [src/main/python/repomap_kg/runtime/schema_upgrade.py](../../../../src/main/python/repomap_kg/runtime/schema_upgrade.py) | `sha256:348a063393587c1a41b7d2f9bfc59ff122f0a1ff245a973c5b0deedd9f6d61d3` |
| [src/main/python/repomap_kg/storage/semantic_candidate_import.py](../../../../src/main/python/repomap_kg/storage/semantic_candidate_import.py) | `sha256:afbaf1c8d7e6be7085be205f2a12d48662a46ac7f3208bc0d09a8900bcb8df9a` |
| [src/test/int/python/repomap_kg/runtime/arch7e_database_roles.int.test.py](../../../../src/test/int/python/repomap_kg/runtime/arch7e_database_roles.int.test.py) | `sha256:7520cfd5f378a62f11ed6dd18950db7a0758281fe92b3d450939fc27e3400da5` |
| [src/test/int/python/repomap_kg/runtime/slice9_coordinated_backup_restore.int.test.py](../../../../src/test/int/python/repomap_kg/runtime/slice9_coordinated_backup_restore.int.test.py) | `sha256:f50b3b1429c66aab760ff67ebd278aabb2b1c48111922fa90fbc421d199b75d1` |
| [src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py](../../../../src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py) | `sha256:760a6fca29296805215757f21c8e2a5eb2725df9e345a728715c4a4d7e33fbeb` |
| [src/test/support/python/repomap_test_support/semantic_candidate_cleanup.py](../../../../src/test/support/python/repomap_test_support/semantic_candidate_cleanup.py) | `sha256:7a64815e3a7a26a3f47bf5fcc2a695913ea0db939b791440cda015348898eac6` |
| [src/test/support/python/repomap_test_support/semantic_candidate_restore.py](../../../../src/test/support/python/repomap_test_support/semantic_candidate_restore.py) | `sha256:6f82ee9267a5fc32764b19f68532a7dc79cd8f32d5bb47ae9abfb92627b87a58` |
| [src/test/unit/python/repomap_kg/runtime/arch5b_provisioning_recovery.unit.test.py](../../../../src/test/unit/python/repomap_kg/runtime/arch5b_provisioning_recovery.unit.test.py) | `sha256:1f66bc98a9e8e2a230cf3083850e1041418f66fd9192edacf6f2f6b15b02e4d5` |
| [src/test/unit/python/repomap_kg/runtime/arch7d2_exact_coordinated_backup_sets.unit.test.py](../../../../src/test/unit/python/repomap_kg/runtime/arch7d2_exact_coordinated_backup_sets.unit.test.py) | `sha256:cc40905e81833fb20e11e504c3081536743699dcfb868810dee1227ff165c720` |
| [src/test/unit/python/repomap_kg/runtime/arch7d3_deterministic_complete_set_restore.unit.test.py](../../../../src/test/unit/python/repomap_kg/runtime/arch7d3_deterministic_complete_set_restore.unit.test.py) | `sha256:2aa7d94ad2b1330494c2566ededf90202266f8885d90ad2398159dd48ddae9ea` |
| [src/test/unit/python/repomap_kg/runtime/arch7e_declarative_database_roles.unit.test.py](../../../../src/test/unit/python/repomap_kg/runtime/arch7e_declarative_database_roles.unit.test.py) | `sha256:973c5b560748eefc1ded2bd8933b3af94eec0d6e083ce5e9580e7d7f2bf2e99f` |

## NAVIGATION37 implementation evidence

D9-A now writes format 2 and reads formats 1 and 2 explicitly. Shared support
evaluation and actual archive TOC checks guard restore, drop and graph/control
upgrade consumers. Non-baseline extensions remain unsupported; ordinary core
user schemas and selected-graph restore retain the core protocol. Observed
catalogs, client versions, artifact bindings and namespaced held maintenance
custody are distinct from unavailable facts and executed restore qualification.
Bounded SQL responses and POSIX command IO refuse incomplete observations;
maintenance acquisition has a 30-second query/lock deadline on its own connection.

Three sequential dispatcher attempts were drained. The latter two completed
independent source reviews, but native revision results ended with interrupted
errors; transport completion is not acceptance. The final review's eight findings
were dispositioned with resulting-source amendments and causal parent checks.
Its reviewer could not inspect Git state or retained scratch evidence. The
parent supplied source, Git, metadata and executed-evidence checks; there was
no second independent review after the final amendments.

Final private scoped checks: 179 unit cases and 33
containerized core integration cases passed. Exact selectors are retained in the
phase record. Static checks cover all 39 changed Python paths. Complete local
suites and Python coverage were unselected; canonical Go preflight component
coverage is separate. New public-candidate hosted qualification and coverage
remain pending. This establishes the bounded D9-A implementation checkpoint,
not D9-B replay, complete D9, D15 admission or roadmap step 6 completion.
