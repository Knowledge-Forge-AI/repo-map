# RepoMap Architectural Findings And Remediation Map

## Purpose

This register preserves the ARCH0 finding evidence and records the final
ARCH-CLOSE disposition of every bounded remediation. It is a decision and
closure artifact, not authorization for SCALE, protected operations, or new
implementation work.

The evidence baseline is committed source at the ARCH0 predecessor, accepted
ADRs and status records, executable tests inspected as source, and public-safe
measurements already recorded by earlier phases. A referenced test establishes
committed coverage, not a test result from ARCH0.

## Closed vocabularies

Severity is exactly one of `critical`, `high`, `medium`, `low`, or
`informational`:

- `critical`: known corruption, authority bypass, or disclosure with no safe
  supported boundary;
- `high`: blocks the normalized architecture or SCALE resumption;
- `medium`: material correctness, performance, operability, or compatibility
  debt with a bounded workaround;
- `low`: contained maintainability or documentation debt; and
- `informational`: an explicit constraint or accepted cost.

Finding category is exactly one of `authority`, `data model`, `legacy`,
`normalization`, `algorithm`, `performance`, `layering`, `API`,
`configuration`, `storage`, `publication`, `lifecycle`, `privacy`, `platform`,
`testing`, or `documentation`.

Impact uses `none`, `low`, `medium`, or `high`. Priority is ordered first by
correctness and data integrity, then architectural duplication, measured or
source-derived performance cost, operational burden, compatibility,
migration difficulty, testability, and rollback difficulty.

## Blocker disposition

No ARCH blocker remains. The eight original immediate blockers were resolved
by ARCH1 through ARCH8 and are indexed below with their exact closing phase and
implementation commit. Protected-scale performance remains deliberately
unclaimed and requires a separately approved SCALE plan; that evidence boundary
is not an architectural defect or permission to run a protected attempt.

## Findings register

ARCH-CLOSE re-audited all 20 ARCH0 findings against committed source,
migrations, executable tests, operational status records, compatibility and
rollback evidence, and the ARCH8 integrated gate. The detailed rows below
remain the evidence record. This closing index records the exact final
implementation commit and any remaining limitation for each disposition.

| Finding | Disposition | Closing phase | Final implementation commit | Remaining limitation |
| --- | --- | --- | --- | --- |
| `ARCH0-AUTH-001` | `resolved` | ARCH1C | `2fdbfc7954026b3497bf4ed4b1564ba95847f5d3` | Recovered attempts reconcile rather than republish; a future republish contract would require a versioned control migration. |
| `ARCH0-AUTH-002` | `resolved` | ARCH4D | `37843ef364cf8c327d3809d4d4a0c320a1f9e2f6` | None within complete forced-full publication; acquisition remains deliberately non-publishing. |
| `ARCH0-DATA-001` | `resolved` | ARCH5D | `d15ffa667ca8c0389ad07bf83d94363272b56a18` | Historical migrations remain immutable evidence. |
| `ARCH0-DATA-002` | `resolved` | ARCH5C3 | `b6eedddac1136a9047fcbb596da1712c20defb06` | Graph-ID changes remain explicit re-registration or migration, not relocation. |
| `ARCH0-LEGACY-001` | `resolved` | ARCH5E | `d5865b2af43c57a67ea4a870796cffb4aef44321` | Historical schema and status records remain by design. |
| `ARCH0-NORM-001` | `resolved` | ARCH2B | `990f03ee79b4488234877216ef8c0fd580bc312d` | None for retained families. |
| `ARCH0-ALG-001` | `resolved` | ARCH6B | `52893948b63545d7e9bb52eb0bc5a675629edc58` | Preserve the accepted adversarial growth fixtures. |
| `ARCH0-PERF-001` | `resolved` | ARCH6G | `402fca1a5d16b67cfae161b43040675a48ea0946` | Protected-scale throughput remains unclaimed. |
| `ARCH0-LAYER-001` | `resolved` | ARCH1J | `345e442fc268a43efc51aee3cca2e655fdac114f` | None; production SCC and test-support allowlists are empty. |
| `ARCH0-API-001` | `resolved` | ARCH7A2 | `452f914b202b0032ff935b98d72376fed18c7a08` | Version-zero aliases remain only for the announced compatibility interval. |
| `ARCH0-CONFIG-001` | `resolved` | ARCH7G | `0cb86d1c7db7d13e2c3f1fd93ec2ede6b22279a6` | Boundary renderers retain schema-specific projections. |
| `ARCH0-STORAGE-001` | `resolved` | ARCH2B | `990f03ee79b4488234877216ef8c0fd580bc312d` | Trusted transfer receipts are not adversarial server-recomputed integrity proofs. |
| `ARCH0-PUB-001` | `resolved` | ARCH2C | `4b55497220af1b8e479ae6f475599621f8b88aea` | Protected workload attribution remains a later SCALE concern. |
| `ARCH0-LIFE-001` | `resolved` | ARCH7G | `0cb86d1c7db7d13e2c3f1fd93ec2ede6b22279a6` | The accepted self-contained release boundary is Linux containers. |
| `ARCH0-LIFE-002` | `resolved` | ARCH8 | `ae91746fd7573fe7d811ff34d60c095fb0441437` | Recovery remains exact-scope and backup-first; unrelated PostgreSQL is unsupported. |
| `ARCH0-PRIV-001` | `accepted_debt` | ARCH-CLOSE | ARCH-CLOSE publishing commit; exact hash is recorded by its report | Public boundaries are proved safe, but their pure policy vocabulary remains duplicated. |
| `ARCH0-PRIV-002` | `resolved` | ARCH7B | `4fbed2611002c0e8b93457de608ade8669f8e8ef` | Preserve the versioned path-free HTTP schema and hard bounds. |
| `ARCH0-PLAT-001` | `resolved` | ARCH7F | `4c800a92f66efc4734187a41c8792f6a9a3f167c` | Native Windows background-service packaging remains outside ARCH; portable foreground operation remains supported. |
| `ARCH0-TEST-001` | `resolved` | ARCH8 | `ae91746fd7573fe7d811ff34d60c095fb0441437` | Protected-scale acceptance remains unclaimed. |
| `ARCH0-DOC-001` | `resolved` | ARCH-CLOSE | ARCH-CLOSE publishing commit; exact hash is recorded by its report | Historical ADRs and status records remain historical evidence rather than current implementation guidance. |

### ARCH0-AUTH-001 — publication exclusion spans two authority mechanisms

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH1C implements and proves the shared exclusion and independent graph-claim ordering contract without schema change. |
| Category / severity | `authority` / `high` |
| Evidence | `storage/staged_publication.py::execute_final_transaction` takes the same nonblocking graph advisory transaction lock for both modes before mutation. `_control_ownership.py::claim_once` mints a distinct transaction-order graph claim, `refresh_adapter.py` carries it unchanged, and `publication_fencing.py::build_graph_publication_claim_statements` registers it durably with run/stage creation before staged work. Final preparation revalidates graph authority immediately before merge. |
| Affected components | Direct refresh, coordinator refresh, graph-local publication fencing, control-plane graph leases, commit-unknown reconciliation. |
| Root cause | Direct and coordinator orchestration were integrated incrementally around different exclusion authorities while sharing final merge and receipt SQL. |
| Correctness / performance / operability impact | Resolved for forced-full staged publication. Contention now fails before mutation, and a later graph claim fences an earlier claim even under one singleton epoch. |
| Compatibility / privacy impact | `low` / `none`: enforcement can remain internal and path-free. |
| Implemented remediation | Every control claim receives a transaction-ordered graph capability distinct from singleton succession. Coordinator stage creation monotonically registers the capability in the existing graph-local authority row. Both modes then acquire the same nonblocking advisory transaction lock, and coordinator preparation revalidates the registered claim before the unchanged final merge/receipt transaction. |
| Dependencies / rollback | No graph/control schema or row migration. Startup reconciliation does not relaunch an old publication and therefore does not need the transient capability; if a later upgrade permits recovered attempts to republish, ARCH5 must add a product-owned durable control column and migration. Reverting ARCH1C restores the former direct blocking lock and equal-epoch coordinator projection without DDL rollback. |
| Verification | Unit and PostgreSQL tests prove direct/coordinator contention rejection before mutation, equal-singleton distinct graph claims, exact-owner idempotence, equal-token conflicting-owner rejection, newer-claim stale fencing, cancellation with newer authority retained, commit-unknown behavior, receipt atomicity, and final-row parity. |
| Proposed phase | `ARCH1` |

This finding requires enforcement of the accepted safety intent, not a weaker
publication model. ARCH0 does not authorize changing atomic publication,
receipt authority, or dedicated graph databases.

### ARCH0-AUTH-002 — receiptless mutation creates a second final-state and latest-run authority

| Field | Value |
| --- | --- |
| Implementation status | `resolved` |
| Active phase | `ARCH4D` accepts one receipt-bearing final mutation authority with exact direct/coordinator parity and code-only rollback. |
| Category / severity | `authority` / `high` |
| Evidence | ARCH1A names the three run/publication authorities. ARCH3E closes the caller census. ARCH4A routes complete generations through receipt-bearing staged publication. ARCH4B makes all six partial acquisition/import surfaces explicitly non-publishing and leaves the AST-backed active receiptless-binding census empty. ARCH4C removes `load_file_observations`, `load_canonical_observations`, their facade exports, the row-wise stream and SQL writers, and every legacy stage/final writer path. |
| Affected components | Closed in ARCH4; ARCH8 retains integrated regression acceptance. |
| Root cause | Additive/import loaders remained supported after forced-full staged publication became the production refresh contract; run identity was reused without a distinct import/publication authority. |
| Correctness / performance / operability impact | `high` / `high` / `high`: supported commands bypass stage ownership, fencing, manifest validation, replacement deletion, normal receipts, and staged commit-unknown recovery, and a later import can become generic latest run without becoming latest publication. |
| Compatibility / privacy impact | `high` / `low`: public command behavior must be migrated or retired explicitly; no raw/private payload is required in the migration. |
| Recommended remediation | ARCH1 names latest recorded run and latest receipt-bearing publication separately. ARCH3 inventories every caller. ARCH4 routes complete generations through staged publication, converts other acquisition to versioned acquisition-only input that cannot mutate final graph state, or retires the command through an announced boundary. Do not add partial publication or fabricate receipts. |
| Dependencies / rollback | Preserve current commands behind explicit compatibility adapters through ARCH3. Rollback before shutdown restores those adapters; no schema deletion belongs to this finding. |
| Verification | One test per public/programmatic caller; no receiptless final-table mutation; latest-run/publication divergence fixtures; replacement/additive behavior parity; failure/cancellation/commit-unknown parity; CLI JSON/table compatibility decision. |
| Proposed phase | `ARCH1`, `ARCH3`, and `ARCH4` |

### ARCH0-DATA-001 — graph authority and compatibility projections coexist durably

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH5D removes the persisted legacy staging and final graph projections after ARCH3 reader migration, ARCH4 writer shutdown, and ARCH5 backup-first upgrade rehearsal. |
| Active phase | `resolved by ARCH5D`; ARCH5E separately owns obsolete compatibility API and facade removal. |
| Category / severity | `data model` / `high` |
| Evidence | Historical migrations retain the original graph tables. `2026/07/16-002-arch5d-drop-legacy-graph-schema.sql` rejects null repository identity, narrows the active stage manifest, and drops legacy stage/final tables in foreign-key-safe order. Current readback, baseline, drift, and compatibility behavior use file/raw/canonical/source authority. |
| Affected components | Closed for persisted storage and staging. ARCH5E retains only the separately tracked compatibility API/facade surface. |
| Root cause | Safe canonical migration was additive, so old and new graph projections remained simultaneously writable and queryable. |
| Correctness / performance / operability impact | `medium` / `high` / `high`: identities are intentionally different, but undocumented authority can drift and every retained projection expands work. |
| Compatibility / privacy impact | `high` / `low`: legacy readers are real contracts; both families use the same public-safe projection rules. |
| Recommended remediation | Adopt raw evidence plus one canonical graph plus an explicit file/source index. Mark every other persisted graph family as a compatibility projection and remove it only through the ordered reader-first program. |
| Dependencies / rollback | ARCH3 reader parity, ARCH4 writer shutdown, ARCH5A upgrade authority, and ARCH5C stable identity are complete. Post-DDL rollback restores the verified pre-removal logical backup, reconciles identity, and reapplies forward migrations; historical migrations remain immutable. |
| Verification | Public-safe pre-removal backup, forward DDL, relocation, compatibility readback, no-drift comparison, clean restore, identity reconciliation, and deterministic DDL reapplication. |
| Proposed phase | `ARCH1`, then `ARCH3`–`ARCH5` |

### ARCH0-DATA-002 — database and repository identity do not enforce accepted isolation or relocation

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH1B implements collision-free resolved topology and stable configured identity; ARCH5C1 adds the nullable unique schema slot and backup-first forward upgrade; ARCH5C2A populates identity and reconciles path-keyed family ownership; ARCH5C2B cuts configured and optional compatibility writers over; ARCH5C3 accepts baseline/drift, restore, and forward reconstruction. |
| Category / severity | `data model` / `high` |
| Evidence | ADR 0038 requires one dedicated database per graph and checkout-relocation-stable identity. ARCH1B rejects resolved database and identity collisions. ARCH5C1 adds nullable `repositories.repository_identity` with partial uniqueness. ARCH5C2A resolves one configured graph for the target database, refuses conflicting non-null identity before backup, reconciles arbitrary relocation chains transactionally, preserves historical and staging ownership, merges overlapping final identities and links, retains highest publication authority, and verifies one owner. ARCH5C2B derives the configured identity at refresh, uses the partial unique identity index for staged writes, updates mutable root/name metadata, and retains root-keyed behavior when compatibility callers omit identity. ARCH5C3 proves migration-only no-drift, restores the exact historical row from pre-migration backup, and forward-reconstructs the stable post-refresh baseline without drift. |
| Affected components | Graph routing, repository rows, final-family ownership, forced-full replacement, lifecycle allowlisting, backup/restore, baseline/drift, relocation, privacy. |
| Root cause | Configured graph identity, mutable source location, database routing, and storage-local repository identity evolved as overlapping fields without one resolved identity contract. |
| Correctness / performance / operability impact | `high` / `medium` / `high`: two graphs can share a database, while moving one checkout can create a second repository row and strand old graph data outside the new replacement scope. |
| Compatibility / privacy impact | `high` / `high`: identity/schema migration must preserve existing rows and keep absolute source paths private. |
| Recommended remediation | ARCH1 resolves every effective graph/control database, rejects collisions and template/maintenance database names, defines a separate maintenance connection target, and defines stable configured repository identity separately from source path with exact collision/relocation/ownership and compatibility rules. ARCH5 first bootstraps upgrade authority, then adds the stable identity and migrates or merges path-keyed rows. |
| Dependencies / rollback | ARCH5A and ARCH5B satisfy the upgrade, maintenance-exclusion, backup-first, and retry prerequisites. ARCH5C1 is additive. ARCH5C2A enters only from exact-current C1 schema under maintenance ownership and after verified backup; its fixed transaction is idempotent and fail-closed. ARCH5C2B preserves row-wise compatibility while switching configured writers. ARCH5C3 restores the pre-migration backup and proves deterministic forward reconstruction. |
| Verification | Duplicate explicit/fallback/control database refusal; configured `postgres`/template refusal and separate maintenance connection; row-wise and staged checkout relocation; old-row migration with no stranded families; baseline/drift and readback parity; destructive ownership derivation; no absolute path in public output. |
| Proposed phase | `ARCH1` contract, `ARCH5` migration, with integrated proof in `ARCH7` and `ARCH8` |

### ARCH0-LEGACY-001 — legacy node, edge, and evidence families remain active

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH5D removes all persisted legacy stage/final tables; ARCH5E removes the expired compatibility APIs, facades, aliases, flags, result schemas, connector operations, and modules. |
| Category / severity | `legacy` / `high` |
| Evidence | ARCH3 migrates readers; ARCH4 shuts down writers. ARCH5D removes `stage_legacy_edges`, `stage_legacy_evidence`, `stage_legacy_nodes`, `edges`, `evidence`, and `nodes` through one guarded forward migration. ARCH5E removes the derived legacy read modules, public migration facade, legacy CLI and summary modes, connector matrix entries, row/result contracts, and obsolete tests. Canonical graph and file/source readback remain. |
| Affected components | Resolved for runtime schema, public graph APIs, connector tooling, status summaries, modules, and active tests. Historical migrations and status records remain immutable. |
| Root cause | Canonical readback was introduced beside stable legacy contracts without a later consumer migration and retirement epic. |
| Correctness / performance / operability impact | `medium` / `high` / `medium`: dual semantics can diverge and add row construction, COPY, validation, merge, index, WAL, and maintenance work. |
| Compatibility / privacy impact | `high` / `low`: removal before parity is a breaking change; no new private content is required. |
| Recommended remediation | Complete. Preserve the canonical graph API and current file/source index; do not recreate retired compatibility surfaces. |
| Dependencies / rollback | Physical schema rollback remains backup-first restore plus deterministic forward reconstruction. ARCH5E rollback is source-level and must restore a coherent pre-ARCH5E code release against the supported pre-removal database state; historical migrations remain unchanged. |
| Verification | ARCH5D proves relation removal, retained-family integrity, logical restore, identity reconciliation, and forward reapplication. ARCH5E adds an obsolete-module/import census, parser rejection checks, canonical-only summary/schema checks, connector parity, and complete unit/integration verification. |
| Proposed phase | `ARCH3`–`ARCH5` |

`files` and `raw_observations` are excluded from this finding: the former is a
current first-class file/source index and the latter is retained provenance.

### ARCH0-NORM-001 — generic stage code lacks an explicit typed family contract

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH2A defines and proves the exhaustive immutable descriptors. ARCH2B makes them authoritative for family order, ordinal insertion, COPY specification, checksum identity, duplicate validation, validation and merge dispatch, cleanup, publication completeness, and privacy classification while retaining compatibility facades. |
| Category / severity | `normalization` / `high` |
| Evidence | ARCH2A adds typed row shapes and the closed registry. ARCH2B derives the `STAGING_FAMILIES` and `STAGING_COPY_TABLES` compatibility views, removes the independent identity and COPY catalogs and raw ordinal branch, and routes staged rows, checksums, duplicate guards, completeness validation, merge operations, cleanup, publication completeness, and privacy through descriptor-derived views. `arch2a_staging_family_descriptors.unit.test.py` and `arch2b_staging_descriptor_ownership.unit.test.py` prove completeness, ownership, ordinal, DDL, COPY, checksum, validation, merge-order, cleanup, privacy, and trust-boundary behavior. |
| Affected components | All seven active stage families, COPY column order, checksums, duplicate policy, validation, merges, cleanup, and tests. Historical ARCH2 evidence also covers the three pre-ARCH4C legacy families. |
| Root cause | A family-shaped implementation was added in phases without one closed descriptor that carries each family's complete contract. |
| Correctness / performance / operability impact | `medium` / `medium` / `high`: hidden symmetry assumptions can omit a family-specific rule and make profiling or removal difficult. |
| Compatibility / privacy impact | `low` / `medium`: row payload privacy classification must be part of the descriptor. |
| Recommended remediation | Define a closed typed descriptor with family identity, row type, table, COPY columns, technical and semantic ordinals, identity/payload columns, checksum, duplicate/proposal policy, validation, merge dependencies, retention, and privacy. Preserve `source_ordinal` as raw run provenance and `family_ordinal` as stage proposal order. |
| Dependencies / rollback | ARCH1 vocabulary and ARCH2 implementation are complete for this finding. Reverting ARCH2B restores the independent compatibility mappings and branch dispatch; reverting ARCH2A then removes the descriptors. Neither step requires schema or data rollback. |
| Verification | ARCH2A and ARCH2B descriptor ownership tests; focused staging and publication unit tests; PostgreSQL-backed staging, merge, publication, cleanup, and node-evidence tests; complete repository gate. |
| Proposed phase | `ARCH2` |

### ARCH0-ALG-001 — two localized algorithms have quadratic worst cases

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH6A removes repeated CSS/HTML element-index construction, and ARCH6B removes repeated canonical metadata list copying and scanning. |
| Category / severity | `algorithm` / `medium` |
| Evidence | ARCH6A builds one pointer index per matched HTML document and reuses it across linked stylesheets and selectors. Its adversarial size series records 51, 99, and 195 element traversals for 16, 32, and 64 descendants. ARCH6B retains one equality-key index with each accumulated metadata list; 16, 32, and 64 edge proposals record 192, 384, and 768 keyed work units, compared with 480, 1,984, and 8,064 on the red baseline. |
| Affected components | CSS/HTML static matching and duplicate canonical-edge metadata aggregation. |
| Root cause | Resolved: per-candidate index reconstruction and repeated list-copy/membership accumulation favored simple small-fixture code over bounded growth. |
| Correctness / performance / operability impact | `low` / `resolved` / `low`: exact semantics remain covered, and both accepted adversarial series reject quadratic growth. |
| Compatibility / privacy impact | `medium` / `none`: deterministic serialized ordering must remain byte-stable. |
| Recommended remediation | Completed by ARCH6A and ARCH6B. Retain the adversarial size series and exact parity contracts. |
| Dependencies / rollback | Both corrections are source-only and require no data migration. Existing selector, canonical, first-seen order, duplicate, identity, and digest contracts preserve output semantics. |
| Verification | ARCH6A traversal size series and CSS/HTML contracts; ARCH6B fan-in size series, exact order and duplicate semantics, pinned identity and graph digest; complete repository gate. |
| Proposed phase | `ARCH6` |

### ARCH0-PERF-001 — staged ingestion is linear but over-amplified

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH4/ARCH5 remove legacy-family amplification; ARCH6D removes checksum spool replay; ARCH6F releases spools after successful COPY; ARCH6G accepts four attributed fixed-count linear observation passes and required pre-COPY row sources as bounded architecture. |
| Category / severity | `performance` / `high` |
| Evidence | `build_staged_rows` prepares seven current families after legacy removal. ARCH6D eliminates checksum replay. ARCH6F reduces full-fixture spool lifetime to 5, 4, 3, 2, 2, 1, 0 and zero final bytes while retaining exactly five COPY passes and 21,000 rows. ARCH6G attributes exactly one `N`-item file, Go-context, canonical, and raw pass with no unattributed traversal. SCALE10 remains aggregate evidence only and does not override the bounded public-safe results. |
| Affected components | Discovery retention, projection, spooling, checksum, COPY, stage validation, legacy and canonical merge. |
| Root cause | Resolved amplification came from compatibility families, a checksum-only spool replay, and attempt-scoped spool cleanup. The remaining passes belong to distinct file, canonical prepass, canonical dispatch, and raw evidence contracts. |
| Correctness / performance / operability impact | `none` / `accepted bounded medium` / `accepted bounded low`: current work is fixed-count linear, large row sources spill privately, and consumed spools release immediately. |
| Compatibility / privacy impact | `medium` / `medium`: removing projections requires parity; spools must preserve existing private-file controls. |
| Recommended remediation | Complete for ARCH6. Preserve the size series, exact digests, fused spool checksum, early release, and four-pass attribution. Reopen only with a representative measurement that demonstrates a material remaining boundary cost. |
| Dependencies / rollback | ARCH2 descriptors and observability, ARCH4/ARCH5 legacy removal, and ARCH6A through ARCH6G measurements and corrections. Both source corrections are independently reversible without data migration. |
| Verification | Per-boundary elapsed time, client/PostgreSQL memory, spool bytes, COPY bytes, WAL, temp bytes, rows, passes, and output equivalence on synthetic small/medium/full gates. |
| Proposed phase | `ARCH2`, `ARCH4`, `ARCH5`, and `ARCH6` |

### ARCH0-LAYER-001 — package dependency direction contains static cycles

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH1D through ARCH1I remove every committed production SCC, and ARCH1J removes the final production/test-support subprocess exception. Both allowlists are empty and the production import graph is a DAG. |
| Category / severity | `layering` / `medium` |
| Evidence | `docs/contrib/package-dependency-matrix.md` defines the target direction. `architecture/arch1d_dependency_dag.unit.test.py` analyzes every lexical import scope, requires empty SCC and test-support allowlists, and rejects production imports, subprocess targets, and search paths that reference test support. `architecture/arch1j_synthetic_worker_boundary.unit.test.py` pins fixture ownership to the outward test adapter. Neutral telemetry, discovery, protocol, refresh, canonical-filter, configuration-loading, and extractor-configuration contracts remove all former components while compatibility identities remain tested. |
| Affected components | Domain, extraction, graph, operations, coordinator, runtime, CLI, MCP, storage telemetry, compatibility facades, test-support subprocess boundary. |
| Root cause | Incremental facade preservation and function-local reverse imports kept behavior working while crossing intended presentation/domain boundaries. |
| Correctness / performance / operability impact | `low` / `low` / `medium`: cycles obscure ownership, complicate isolated tests, and make changes propagate widely. |
| Compatibility / privacy impact | `high` / `none`: underscore-prefixed and facade names may be de facto consumers and cannot be removed from static import evidence alone. |
| Implemented and remaining remediation | ARCH1D publishes the matrix and removes storage telemetry. ARCH1E removes graph discovery/routing. ARCH1F separates coordinator protocol, refresh, launch, and environment ownership. ARCH1G moves shared canonical filter validation below CLI and MCP. ARCH1H moves configuration loading below runtime and keeps status readback in the operations facade. ARCH1I places neutral extractor contracts below the registry and format implementations and removes the final SCC. ARCH1J moves synthetic-worker fixture selection, target, path, and modes outward to test support. No layering remediation remains under this finding. |
| Dependencies / rollback | ARCH1 only; preserve compatibility re-exports until consumer inventory completes. Revert each seam independently if import or API parity fails. |
| Verification | ARCH1D static graph and production/test-support guards, phase-specific facade and behavior tests, and the complete repository gate. ARCH1J proves empty SCC and test-support allowlists, DAG structure, outward fixture ownership, and retained generic protocol supervision. |
| Proposed phase | `ARCH1` |

### ARCH0-API-001 — public and quasi-public read bounds are inconsistent

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH7A1 bounds and versions canonical node/edge CLI and MCP lists; ARCH7A2 applies the same contract to neighborhood node/edge collections and explanation evidence. |
| Category / severity | `API` / `medium` |
| Evidence | `storage/read_pages.py` owns the shared schema-version 1 page and embedded-result contracts, maximum 200, lookahead, continuation, and collection-specific diagnostics. Direct canonical CLI/MCP lists and neighborhood/explanation collections use it over the existing ordered storage queries. `docs/specs/public-read-contract.md` records the public contract and compatibility aliases. |
| Affected components | CLI JSON/table output, MCP canonical lists, neighborhoods, explanations, storage readback. |
| Root cause | CLI and MCP presentation evolved independently over common SQL builders with different resource policies. |
| Correctness / performance / operability impact | `none` / `medium` / `medium`: large reads can allocate and serialize unbounded results. |
| Compatibility / privacy impact | `high` / `medium`: adding required pagination or truncation changes schemas/semantics and must preserve redaction. |
| Implemented remediation | ARCH7A1 completes canonical list normalization and announces schema version 1 with bounded schema-zero aliases. ARCH7A2 adds independent bounded windows for neighborhood nodes/edges and explanation evidence, collection-specific continuation and truncation diagnostics, table/JSON membership parity, and bounded legacy-object aliases. |
| Dependencies / rollback | ARCH3 canonical parity before ARCH7 API normalization. Retain legacy aliases for an announced compatibility interval. |
| Verification | Schema and envelope tests, table/JSON equivalence, CLI/MCP and psql/psycopg parity, maximum-cardinality rejection before query, stable pagination, lookahead diagnostics, and private-result redaction. |
| Proposed phase | `ARCH7` |

### ARCH0-CONFIG-001 — configuration resolution crosses operational layers

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH1B establishes the shared pure resolver and collision-free topology; ARCH7E and ARCH7G complete role-separated credentials, least-capability projections, and deployment rendering. |
| Category / severity | `configuration` / `high` |
| Evidence | `ops/resolved_config.py` and the ARCH1B resolver produce one typed topology with unique effective graph databases, distinct control and maintenance targets, and exact graph/control ownership. ARCH1H removes the operations/runtime cycle. ARCH7E defines separate read/status, refresh/publication, coordinator-control, and lifecycle-administrator roles. ARCH7G renders the same resolved model and projects only each unit's required secret, mount, and database capability. |
| Affected components | RepoMap home, graph registrations, roots/excludes, PostgreSQL database/role/secret resolution, refresh policy, mode selection, runtime and service artifacts, lifecycle ownership. |
| Root cause | Resolved: one source format previously mixed resolution, validation, ownership, credential capability, rendering, and public projection across operational layers. |
| Correctness / performance / operability impact | `resolved` / `low` / `resolved`: collisions fail closed, local and container projections share one resolved topology, and long-running units do not receive lifecycle-administrator authority. |
| Compatibility / privacy impact | `medium` / `high`: public/private projections and credential ownership must remain explicit. |
| Recommended remediation | Complete. Preserve the pure resolved model, collision refusal, exact ownership, distinct maintenance target, role-separated credentials, and least-capability render projections. |
| Dependencies / rollback | ARCH1B is source-only; ARCH7E role SQL is declarative and idempotent; ARCH7G composition is removable as one release boundary without changing graph/config identity. Existing config keys remain compatible. |
| Verification | Cross-entrypoint equivalence; explicit/global/control database collision refusal; path mapping; missing/invalid and role-separated secret cases; direct/coordinator generation equality; local/container golden renders; least-privilege privilege tests. |
| Proposed phase | `ARCH1` and `ARCH7` |

### ARCH0-STORAGE-001 — stage checksums are trusted transfer receipts

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH2B accepts the current checksums as client-computed trusted transfer receipts at the repository-owned local transport boundary. It explicitly does not claim server-recomputed or adversarial end-to-end cryptographic integrity. |
| Category / severity | `storage` / `medium` |
| Evidence | `staging_checksums.py::FamilyChecksum` and `checksum_family` identify the result as a trusted transfer receipt without server recomputation. Descriptor checksum strategy names the same boundary. `arch2b_staging_descriptor_ownership.unit.test.py` proves that a same-count, same-identity, same-normalized-length payload mutation changes the payload receipt while count-only validation remains a separate proof. Owner-conflict, rollback, commit-unknown, and publication tests retain their established behavior. |
| Affected components | Stage manifest, checksum receipt, validation, diagnostics, integrity claims. |
| Root cause | Checksums were designed for deterministic in-process transfer evidence, not an adversarial storage boundary. |
| Correctness / performance / operability impact | `accepted low` / `low` / `low`: same-count mutation changes the client receipt but is not independently detected by server count validation. This is accepted for the owned local transport boundary and is not represented as adversarial integrity. |
| Compatibility / privacy impact | `none` / `medium`: digests must remain aggregate and path-free. |
| Recommended remediation | Complete. Preserve the trusted-transfer-receipt terminology. Any future server-derived digest is a separate measured hardening phase and must not be inferred from the current receipt. |
| Dependencies / rollback | ARCH2 typed descriptor and trust-boundary decision complete. Reverting ARCH2B restores the prior aggregate-evidence wording without changing the checksum algorithm or stored receipts. |
| Verification | Same-count mutation fixture, owner-conflict and commit-unknown fixtures, digest parity, bounded diagnostics, and complete repository gate. |
| Proposed phase | `ARCH2` |

### ARCH0-PUB-001 — the dominant staging partition is insufficiently decomposed

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH2C adds opt-in public-safe attribution for every retained family and requested staging boundary, including bounded aggregate resource categories. |
| Category / severity | `publication` / `high` |
| Evidence | `staging_observability.py` defines a closed identifier-free event schema and 16 required categories. Descriptor-owned instrumentation attributes preparation, row count, normalized bytes, spool bytes, checksum, and COPY across all ten families. Orchestration attributes statistics, completeness validation, semantic guards, merge, receipt, cleanup, WAL and temporary-byte upper bounds, process memory, and safely available current-backend PostgreSQL memory. `arch2c_staging_observability.unit.test.py` proves schema, privacy, bounds, failures, and resource fallbacks. The PostgreSQL integration fixture proves identical summary/final state/receipt, at most 96 events, and exactly four additional aggregate queries. No Argo CD or private graph run occurred. |
| Affected components | Stage construction, family checksum, COPY, statistics, validation, merge eligibility, operational reporting. |
| Root cause | Safety and ownership instrumentation preceded sufficiently fine performance attribution. |
| Correctness / performance / operability impact | `none` / `bounded low` / `resolved high`: instrumentation is opt-in and non-authoritative, with bounded event and query overhead; publication output remains unchanged. |
| Compatibility / privacy impact | `none` / `high`: measurements must expose only categories, bounded counts, and aggregate resources. |
| Recommended remediation | Complete for ARCH2. Preserve the closed public-safe contract while ARCH6 uses the measurements to select pipeline changes. |
| Dependencies / rollback | ARCH2 descriptors are complete. Reverting ARCH2C removes only opt-in in-memory instrumentation and its cleanup execution wrapper; no schema, data, graph, receipt, or configuration rollback is required. |
| Verification | Public-safe synthetic attribution, exhaustive family/category tests, timer and terminal aggregate reconciliation, four-query and 96-event bounds, final-state/receipt parity, cleanup attribution, complete repository gate, and no-source-value serialization tests. |
| Proposed phase | `ARCH2` and `ARCH6` |

### ARCH0-LIFE-001 — generated local cluster is not a complete release deployment

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH7G composes and accepts PostgreSQL, one-shot initialization/upgrade, HTTP health/status, read-only MCP integration, the foreground coordinator, and one-shot lifecycle administration from the immutable ARCH7F artifact. |
| Category / severity | `lifecycle` / `high` |
| Evidence | The generated Compose topology uses the immutable ARCH7F application and PostgreSQL artifacts; persistent database storage; read-only config, environment, and enabled-source mounts; narrow coordinator and lifecycle-admin writable volumes; per-unit secrets; loopback-only HTTP publication; PostgreSQL health; and completed one-shot graph/control schema gating. Fresh-cluster acceptance proves HTTP readiness, bounded read-only MCP readback, coordinator readiness, one-shot status, restart recovery, and packaged query/dump/restore clients without host Python, Go, PostgreSQL, or `psql`. |
| Affected components | Container image, Compose, HTTP/MCP/coordinator units, readiness, database roles/secrets, graph/control administration, root mounts, release packaging. |
| Root cause | Runtime orchestration and release-artifact packaging were separate bounded epics. |
| Correctness / performance / operability impact | `none` / `none` / `resolved high`: the generated release cluster is self-contained apart from its documented container-runtime, persistent-storage, secret, configuration, and source-mount prerequisites. |
| Compatibility / privacy impact | `medium` / `high`: mount translation, secret projection, HTTP output, role capability, and destructive authority must be explicit. |
| Recommended remediation | Complete for ARCH. Preserve the immutable release matrix, explicit service topology, least-capability mounts and secrets, local-only publication, health and schema gates, and fresh-artifact acceptance. ARCH8 broadens the public-safe integrated acceptance ladder without reopening deployment authority. |
| Dependencies / rollback | ARCH7 follows the accepted authority/configuration contracts. Rollback removes the complete composition and release-cluster commands together while preserving the immutable image, source migrations, development adapters, graph/control databases, and backup artifacts. |
| Verification | Render and capability tests cover all units, mounts, networks, secrets, fixed clients, exact schema gates, deterministic database construction, idempotent fresh initialization, supported backup-first graph/control upgrade, and bounded status. Fresh-cluster smoke proves query/dump/restore, HTTP privacy/readiness, MCP readback, coordinator readiness, one-shot administration, toolchain absence, and persistence across restart. ARCH8 owns direct/coordinator publication and the complete public-safe recovery matrix. |
| Proposed phase | `ARCH7` |

### ARCH0-LIFE-002 — database upgrade, ownership, and recovery authority are incomplete

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH7G deploys the versioned lifecycle authority and ARCH8 proves complete multi-graph/control recovery and restart through the packaged one-shot administration path. |
| Category / severity | `lifecycle` / `high` |
| Evidence | ARCH5 establishes ordered checksummed graph/control migrations, exact verified backup-first adoption, deterministic cross-plane maintenance ownership, fresh-target retry, stable repository identity, rollback acceptance, and legacy decommissioning. ARCH7C1 resolves the exact graph/control ownership set before local dump, source init, dump restore, graph upgrade, or drop and refuses every unrelated safe name before external access. ARCH7C2 holds the required maintenance authority from before recovery-point capture through verification and destruction. ARCH7D1 through ARCH7D3 provide private atomic streaming artifacts, exact coordinated sets, checksum-first deterministic restore, and invocation-bounded cleanup. ARCH7E reconciles declarative least-privilege roles. ARCH7F installs the exact migration and client resources. ARCH7G initializes PostgreSQL with UTF-8/C defaults, creates every product database from `template0` with explicit UTF-8/C attributes, deploys idempotent graph/control initialization and backup-first supported forward upgrade, and gates long-running services on exact-current schema readiness. |
| ARCH7D3 evidence | `restore_coordinated_backup` accepts only the exact stable coordinated manifest, verifies every unique dump/checksum before runtime inspection, proves every target absent before mutation, restores sorted graphs then control, and removes invocation-created targets in reverse order after failure. |
| ARCH7E evidence | Deterministic role reconciliation runs after graph/control init, upgrade, and restore. Real disposable-PostgreSQL tests prove read/status, refresh/publication, and coordinator-control grants and cross-database refusal. HTTP/MCP and coordinator worker/store tests prove that long-running processes do not load or receive the lifecycle-administrator credential. |
| Affected components | Existing graph/control databases, fresh init/restore, partial failure and retry, legacy DDL, multi-graph backup/restore, destructive drop, cluster provisioning and upgrade. |
| Root cause | Lifecycle was built around a conservative single development-runtime database and container ownership before versioned schema state, exact configured database ownership, and multi-graph/control recovery were modeled. |
| Correctness / performance / operability impact | `resolved high` / `bounded` / `resolved high`: exact ownership, versioned lifecycle, private atomic coordinated recovery, role reconstruction, immutable resources, deterministic database construction, and deployed gating are implemented. |
| Compatibility / privacy impact | `high` / `high`: existing installations and backup manifests must migrate without exposing database names or paths publicly; destructive authorization and dump permissions are security-sensitive. |
| Recommended remediation | Complete for ARCH. Preserve the ARCH1/ARCH5 migration authority, ARCH7C admission/exclusion, ARCH7D recovery boundary, ARCH7E role contract, ARCH7F installed-resource boundary, and ARCH7G deterministic deployed lifecycle. |
| Dependencies / rollback | Dedicated topology and the stable-identity contract from ARCH1 precede upgrade work. ARCH5 bootstraps applied-version and maintenance authority before applying the stable-identity migration or any legacy DDL. Preserve current single-database adapters until new operations pass; every destructive migration has a verified backup and rehearsed restore/forward rollback. |
| Verification | Upgrade from every prior supported graph/control version; concurrent direct/import/coordinator admission refusal; active attempt/stage drain/quarantine and maintenance-lock ownership; MCP/readiness during upgrade; failure injection between legacy DDL and ledger update; retry after partial init/restore; exact-current readiness; duplicate/control/maintenance-name refusal; cross-locale/encoding deterministic order and restore tests; concurrent writer between dump and drop plus stable recovery-point proof; all-owned coordinated backup and ordered restore; large-dump bounded-memory, pre-manifest kill, incomplete-set rejection, atomic publication, and mid-stream failure tests; restrictive modes under permissive umask; unrelated safe-name drop refusal; checksum and privacy gates. |
| Proposed phase | `ARCH1`, `ARCH5`, and `ARCH7` |

### ARCH0-PRIV-001 — privacy projection is enforced in several boundary modules

| Field | Value |
| --- | --- |
| Implementation status | `accepted_debt`: every public boundary has path-free, bounded, malicious-fixture coverage, while the pure policy vocabulary remains duplicated across schema-specific adapters. |
| Active phase | Closed by ARCH-CLOSE as non-blocking maintainability debt. No unsafe projection or missing public boundary was found. |
| Category / severity | `privacy` / `medium` |
| Evidence | Extractor redaction is implemented by `src/main/python/repomap_kg/extractors/shared/redaction.py::secret_name_redaction_reason` and `secret_value_redaction_reason`. Config projection is covered by `src/test/unit/python/repomap_kg/ops/config_redaction.unit.test.py::OpsConfigRedactionUnitTests.test_status_outputs_redact_local_config_and_private_graph_fields`. MCP sanitization uses `src/main/python/repomap_kg/server/mcp_core.py::private_storage_payload` and `public_storage_error_message`; coordinator projection uses `src/main/python/repomap_kg/coordinator/contracts.py::is_public_safe_text` and `project_public_error`. |
| Affected components | Extraction diagnostics, configuration status, CLI JSON/table, MCP, coordinator/worker errors, telemetry, runtime/service status. |
| Root cause | Each public boundary added its own projection to meet a shared privacy policy. |
| Correctness / performance / operability impact | `none` / `low` / `accepted low`: duplicated pure helpers carry maintenance risk but do not create a second authority or untested public surface. |
| Compatibility / privacy impact | `medium` / `high`: normalization must not widen outputs or turn private placeholders into stable identity. |
| Recommended remediation | Accepted debt. A later public-safe refactor may define shared vocabulary while retaining boundary-specific schemas; it must not centralize secret retrieval, raw payload access, or widen any output. |
| Dependencies / rollback | No change is required for ARCH or SCALE resumption. A future refactor remains source-only, one boundary at a time, behind the existing golden/malicious fixtures. |
| Verification | Extractor, configuration, CLI, MCP, coordinator/worker, telemetry, runtime, HTTP, and acceptance tests cover malicious paths, identifiers, tokens, raw exceptions, bounded diagnostics, and unchanged allowlisted fields. ARCH8 retains the cross-surface privacy gate. |
| Proposed phase | `ARCH7` |

### ARCH0-PRIV-002 — HTTP health and status disclose local and configured identifiers

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH7B removes the identifier-bearing HTTP projection, separates configuration health from storage and required-schema readiness, and enforces graph, diagnostic-count, and serialized-response bounds. |
| Category / severity | `privacy` / `high` |
| Evidence | `server/http.py` exposes schema-version 1 `/livez`, `/healthz`, `/readyz`, and `/status` projections containing only allowlisted status values and bounded counts. It does not serialize RepoMap home, graph, repository, database, or raw diagnostic values. Readiness probes at most 200 configured graph databases through the existing read-only PostgreSQL status path, reports storage and required-schema state separately, and caps every serialized response at 8 KiB. The generated Compose healthcheck uses `/readyz`. |
| Affected components | `GET /livez`, `GET /healthz`, `GET /readyz`, `GET /status`, generated Compose healthcheck, cluster status, and the removed local/configured metadata projection. |
| Root cause | The HTTP surface reused configuration/status projections that were considered locally safe without applying the repository's path-free public artifact policy to every field. |
| Correctness / performance / operability impact | `none` / `bounded low` / `resolved`: configuration health remains independent of PostgreSQL, while readiness reports disconnected storage and unavailable required schema separately through bounded probes. |
| Compatibility / privacy impact | `high` / `resolved high`: schema version 1 intentionally removes the disclosure-bearing fields. `/status` remains informational HTTP 200; the dedicated health and readiness endpoints use 503 for failed checks. |
| Recommended remediation | Complete. Preserve the four-signal split, path-free allowlist, hard count/response bounds, and the distinction between HTTP status and MCP. Exact-current migration and complete cluster startup gating remain lifecycle/deployment work rather than a reason to expose identifiers here. |
| Dependencies / rollback | No schema, migration, dependency, graph, or database change. Source rollback must not restore identifier disclosure in a release artifact. ARCH7G supplies PostgreSQL health and completed one-shot initialization/upgrade gating. |
| Verification | Success and error projections; absolute/home/database/repository/private graph identifier probes; malicious diagnostic redaction; one-snapshot status; 200-graph probe cap; 8 KiB response cap; storage-down and unavailable-required-schema readiness; local-bind enforcement; generated-healthcheck routing. |
| Proposed phase | `ARCH7` |

### ARCH0-PLAT-001 — Go extraction and native services are not release-symmetric

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH7F packages the matching Linux arm64/amd64 helper in the accepted immutable container release. Native Windows background-service packaging remains an explicit out-of-scope limitation; supported Windows and WSL foreground behavior is unchanged. |
| Category / severity | `platform` / `high` |
| Evidence | `src/main/python/repomap_kg/extractors/languages/go_helper.py::resolve_go_helper_command` requires an explicit or package-local platform helper. ARCH7F `runtime/commands.py::render_server_dockerfile` cross-builds the selected Linux arm64/amd64 helper with CGO disabled and installs it at the controlled package path; fresh images on both architectures execute that helper through the production protocol and contain no Go toolchain. `service_package/platforms.py` continues to support launchd and systemd-user adapters while Windows native background packaging is deferred. |
| Affected components | Go helper distribution, Linux container image, macOS/Linux service adapters, Windows foreground operation. |
| Root cause | GO proved the protocol and source workflow; release packaging was deferred. ASYNC accepted platform-neutral foreground behavior separately from native service managers. |
| Correctness / performance / operability impact | `resolved` / `none` / `resolved for the Linux container`: mismatched or missing helpers still fail closed, and the accepted container platforms now receive the matching helper deterministically. |
| Compatibility / privacy impact | `medium` / `low`: helper protocol/version and controlled path must stay stable. |
| Recommended remediation | Complete for ARCH. Preserve digest-pinned multi-stage helper construction, the controlled package path, fail-closed resolution, and separation of service-manager adapters from coordinator semantics. Do not reopen native Windows background packaging in ARCH. |
| Dependencies / rollback | ARCH7F release packaging. Source rollback removes the packaged helper and returns container Go extraction to fail-closed unavailable behavior; Python-only extraction remains a bounded fallback only when configuration explicitly excludes Go, never silently. |
| Verification | Helper matrix, protocol/version rejection, Linux fresh-image Go fixture, path containment, no ambient PATH or runtime build. |
| Proposed phase | `ARCH7` |

### ARCH0-TEST-001 — functional evidence exceeds algorithmic and deployment evidence

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH8 executes a closed integrated acceptance catalog and the public-safe small, medium, self-host, and full-repository ladder. |
| Category / severity | `testing` / `high` |
| Evidence | `tools/arch8_acceptance.py` binds 28 acceptance requirements to 36 unit and integration evidence files and runs them through the repository-owned all-suite gate with Go and container smoke retained. It includes every graph migration prefix, control pre-ledger adoption, rollback/retry, direct/coordinator publication and contention, deterministic replay, baseline/drift, cancellation, commit-unknown recovery, relocation, acquisition-only behavior, removed-API refusal, bounded reads, HTTP privacy, least privilege, packaging, cleanup, and measurement boundaries. A fresh disposable release cluster performed packaged-client backup and exact empty-topology restore of two graph databases plus control, verified control-last recovery and exact-current readback, and recovered PostgreSQL/HTTP/coordinator health after abrupt simultaneous restart. Static repeated discovery on the mixed fixture corpus and complete RepoMap tree was deterministic. One explicitly public full repository completed two receipt-bearing forced-full publications with equal file/observation counts and bounded public-safe telemetry. |
| Affected components | Algorithms, pipeline amplification, public compatibility, migrations, container deployment, SCALE acceptance. |
| Root cause | Phase tests proved bounded functional slices; the architecture now needs cross-slice characterization and fresh-artifact evidence. |
| Correctness / performance / operability impact | `resolved` / `resolved for ARCH` / `resolved`: protected-scale performance remains outside ARCH8 and requires a separate SCALE plan. |
| Compatibility / privacy impact | `high` / `high`: acceptance data must be synthetic/public-safe until the final protected gate. |
| Recommended remediation | Complete for ARCH. Preserve the closed catalog, public-safe ladder, measurement taxonomy, full repository gate, and no-target-execution boundary before any separately approved protected work. |
| Dependencies / rollback | ARCH1 through ARCH7 supply the executable evidence; ARCH8 integrates it. Reverting the ARCH8 harness removes only the aggregate gate and records, not the accepted product behavior or underlying tests. |
| Verification | Gate itself: deterministic repeated results, resource ceilings, no private values, direct/coordinator parity, full publication and recovery. |
| Proposed phase | `ARCH1`–`ARCH8`; resolved by `ARCH8` |

### ARCH0-DOC-001 — historical intent is not a reliable as-built map

| Field | Value |
| --- | --- |
| Implementation status | `resolved`: ARCH-CLOSE makes this normalized as-built specification set the current architecture index and classifies historical targets explicitly without rewriting history. |
| Category / severity | `documentation` / `medium` |
| Evidence | This register, ADR 0041, the normalized as-built architecture, authority/legacy inventory, complexity ledger, roadmap, and ARCH epic log now record the implemented ARCH1–ARCH8 exits and ARCH-CLOSE decision. The intended-versus-implemented matrix identifies historical-only claims; committed source, migrations, and executable tests remain authoritative over older prose. |
| Affected components | Contributor onboarding, phase planning, authority decisions, legacy classification, deployment expectations. |
| Root cause | Append-only phase records correctly preserve history, but no later document normalized the complete implemented system. |
| Correctness / performance / operability impact | `resolved` / `low` / `resolved`: contributors have one current index and explicit historical boundaries. |
| Compatibility / privacy impact | `medium` / `low`: historical records must not be rewritten or treated as current contracts. |
| Recommended remediation | Complete. Keep this normalized document set current and preserve historical ADR/status evidence as append-only context rather than current implementation guidance. |
| Dependencies / rollback | Documentation-only closeout; rollback reverts the current-index updates without changing source, migrations, graph state, or historical records. |
| Verification | Path and symbol checks, exact status-token audit, intended-versus-implemented matrix review, ARCH8's executable catalog, complete repository/platform gate, and independent architecture/privacy review. |
| Proposed phase | `ARCH0` and `ARCH-CLOSE` |

## Prioritization and bounded remediation

### ARCH1 — authority contracts and package-layer normalization

Owns `ARCH0-AUTH-001`, `ARCH0-AUTH-002`, `ARCH0-DATA-001`, `ARCH0-DATA-002`,
`ARCH0-LAYER-001`, and the authority foundations of `ARCH0-CONFIG-001`,
`ARCH0-LIFE-002`, and `ARCH0-PRIV-001`. It fixes dependency direction, run and
mutation authority, graph/control ownership, the stable repository identity and
migration contract, configuration/privacy boundaries, and cross-mode exclusion
without changing schema, existing repository rows, or canonical graph
semantics.

### ARCH2 — typed staging-family and ordinal-contract normalization

Owns `ARCH0-NORM-001`, `ARCH0-STORAGE-001`, and the instrumentation portion of
`ARCH0-PUB-001`. It makes family differences explicit and proves row, COPY,
checksum, validation, and merge parity. It retains separate run provenance and
stage proposal ordinals. ARCH2A through ARCH2C complete this scope with one
typed contract per family and public-safe attribution for every relevant
staging boundary.

### ARCH3 — canonical parity and compatibility adapters

Owns reader/caller-parity prerequisites for `ARCH0-AUTH-002`,
`ARCH0-DATA-001`, `ARCH0-LEGACY-001`, and `ARCH0-API-001`. It implements
bounded adapters or views for every supported legacy reader and inventories
row-wise callers while migrating baseline/drift semantics before writes stop.

### ARCH4 — legacy write shutdown

Owns `ARCH0-AUTH-002`, the first destructive-direction step of
`ARCH0-LEGACY-001`, and the largest compatibility component of
`ARCH0-PERF-001`. It stops receiptless final mutation and new legacy
node/edge/evidence writes only after ARCH3 gates pass; it keeps rollback and
existing tables available.

### ARCH5 — legacy schema and API decommissioning

Completes `ARCH0-LEGACY-001`, the existing-row portion of `ARCH0-DATA-002`, and
the upgrade prerequisite of `ARCH0-LIFE-002`. It first establishes
version-tracked backup-first graph/control upgrade and recovery, then applies
the additive stable-identity schema/data migration, and only then removes
legacy staging/merge/final runtime schema through forward migrations.
It then removes the expired compatibility API/facade boundary. Historical
migration files remain. ARCH5 is complete.

### ARCH6 — algorithmic and representation simplification

Owns `ARCH0-ALG-001`, the pipeline portion of `ARCH0-PERF-001`, and measured SQL
shape hypotheses. It fixes proven quadratic paths, reduces redundant
materialization/serialization, and retains deterministic output and atomic
publication.

### ARCH7 — lifecycle, readback, public contract, and deployment normalization

Owns `ARCH0-API-001`, `ARCH0-CONFIG-001`, `ARCH0-LIFE-001`,
`ARCH0-LIFE-002`, `ARCH0-PRIV-001`, `ARCH0-PRIV-002`, and
`ARCH0-PLAT-001`. It produces a complete fresh-artifact container-cluster
contract with exact database ownership, bounded streaming recovery, private
backup modes, least-privilege roles, and storage/schema readiness without
giving long-running services lifecycle-admin capability.

### ARCH8 — normalized multi-repository dogfood

Owns integrated verification for `ARCH0-TEST-001` and `ARCH0-PUB-001` across
public-safe small, medium, and full repository gates. It does not include a
protected Argo CD attempt.

### ARCH-CLOSE

Owns the final audit for `ARCH0-DOC-001`, re-audits every other finding,
accepts or rejects remaining debt explicitly, updates the as-built baseline,
and decides whether the exact SCALE resumption gates are satisfied.

## SCALE resumption mapping

The recommendation is: **Resume SCALE only after the complete ARCH
normalization epic.**

| SCALE resumption criterion | Required remediation/evidence |
| --- | --- |
| Legacy write amplification removed or explicitly retained | `ARCH0-LEGACY-001`, ARCH3–ARCH5 |
| Typed family contracts implemented | `ARCH0-NORM-001`, `ARCH0-STORAGE-001`, ARCH2 |
| Algorithmic blockers corrected | `ARCH0-ALG-001`, ARCH6 |
| Non-trivial internal import cycles eliminated | `ARCH0-LAYER-001`, ARCH1, and ARCH-CLOSE DAG proof |
| Direct CLI and MCP embedded collections bounded | `ARCH0-API-001`, ARCH7 implementation, and ARCH8/ARCH-CLOSE proof |
| Pipeline boundaries observable | `ARCH0-PUB-001`, ARCH2 and ARCH6 |
| Small and medium repository parity | `ARCH0-TEST-001`, ARCH3–ARCH8 |
| Full public-safe repository gate | `ARCH0-TEST-001`, ARCH8 |
| Migration compatibility and rollback | `ARCH0-DATA-001`, `ARCH0-LEGACY-001`, `ARCH0-LIFE-002`, ARCH3–ARCH5 |
| Baseline and drift stability | `ARCH0-DATA-001`, `ARCH0-DATA-002`, `ARCH0-LEGACY-001`, `ARCH0-TEST-001`, ARCH3 reader migration, ARCH5 identity migration, and ARCH8 proof |
| One final mutation and latest-publication authority | `ARCH0-AUTH-002`, ARCH1, ARCH3, and ARCH4 |
| Dedicated topology and relocation-stable identity | `ARCH0-DATA-002`, `ARCH0-CONFIG-001`, ARCH1 contract, ARCH5 migration, and ARCH8 proof |
| Exact owned-database and destructive allowlist | `ARCH0-DATA-002`, `ARCH0-CONFIG-001`, `ARCH0-LIFE-002`, ARCH1 ownership contract, ARCH7 lifecycle enforcement, and ARCH8 proof |
| Direct/coordinator parity and exclusion | `ARCH0-AUTH-001`, ARCH1 and ARCH8 |
| No publication-safety regression | `ARCH0-AUTH-001`, `ARCH0-STORAGE-001`, ARCH2 and ARCH8 |
| Bounded end-user deployment path | `ARCH0-LIFE-001`, `ARCH0-LIFE-002`, `ARCH0-PRIV-002`, `ARCH0-PLAT-001`, ARCH7 |

Only after ARCH-CLOSE accepts all gates may a new numbered SCALE phase define
one protected attempt. ARCH0 provides no publication, parity, baseline, drift,
SCALE closure, or GO result.

## Deferred improvements

- Native Windows background service packaging remains outside ARCH; Windows
  foreground behavior and Linux-container deployment remain the supported
  boundaries.
- SQL aggregation shapes in `storage/sql_sources.py` require `EXPLAIN
  (ANALYZE, BUFFERS)` evidence on public-safe data before classification as a
  defect.
- Broad compatibility facades require a consumer census before any export is
  called dead.
- The file/source index remains first-class until field, read-latency, and
  baseline/drift parity prove a replacement.

## Implementation authorization

Accepted ADR 0041 and the RepoMap operator's 2026-07-16 direction authorize
autonomous remediation through ARCH-CLOSE. This register controls scope and
status; it does not override ADR review triggers, compatibility requirements,
or phase verification gates.
