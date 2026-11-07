# ADR 0148: Offline W5 component correspondence and bounded functional provenance

## Status

Accepted technical design, 2026-11-04, by the roadmap parent after two independent dispatcher design checkpoints and the amendments below. The technical implementation passed scoped verification and resulting-state review; hosted qualification remains pending. Scientific thresholds, held-out evaluation and production admission remain reserved decisions.

## Evidence and choice

CI115 qualifies staging 1275b49/treea0a804e6 with all nine jobs, same-attempt measured/abrupt staging, native AMD and five-scenario system evidence. Actual application starts are 28. Hard coverage floors pass; exact soft 87/82branch gaps are 6/235. Optional15 remains a spent immutable learned run. Its retained pairedV2 bytes exist and replay exactly with the current builder (3,703,442 bytes, SHA-256 3dbaf40b66115b410239510ce9e9ca14c30b6892252160e8784f990e21c1112f). The existing response parser imports without numpy/onnxruntime/tokenizers under an import-blocking isolated probe.

Choose a separate tools-only dossier instead of altering V1/V2 or introducing a duplicated V3 report. It is artifact correspondence, not trusted origin, inference correctness, scientific comparability, live admission or execution authority.

## Epic A: complete offline component reader

Public API: read_raw_component(journal_path, model_directory) -> immutable correspondence summary. Load the canonical journal through maintained load_journal. A supplied model directory must contain exactly declaration.json, report.json, source-manifest.json, sources.zip and terminal.json; partial, extra, unsafe or malformed members refuse. Absence is represented only by the dossier caller omitting that generation's bundle, never by a partially supplied directory.

Add a narrow public archive-input seam in retrieval_semantic_generator_output_receipt.py that delegates to its existing archive parser and returns request.json/admission.json bytes. Preserve every existing archive rule and limit (ZIP_STORED, no encryption/comment, at most 1024 members,32 MiB, existing path and member policy); no second archive parser, sorting rule or compression policy. No underscore imports across new owners. New directory IO uses no-follow, regular-file and bounded stat-stable reads; reject FIFO/device/socket before blocking reads. The existing per-receipt32 MiB bound and request8 MiB/admission512 KiB limits remain; no cap is raised.

Derive expected_controller_admission_sha256 only from canonical declaration.controller_admission_sha256 agreeing with canonical report.component.admission and canonical manifest input_files. Derive expected_source_closure only from canonical declaration.component_source_closure agreeing with source_closure, and canonical manifest source_files['tools/'+name] for every original member. Use the original journal-recorded closure (17 members for optional15), never today's WORKER_SOURCE_FILES or current checkout equality. Bind model attempt to JournalArtifact.attempt_id, not a generation-number rule.

Use existing parse_worker_request, parse_controller_admission and parse_verified_worker_response, with its actual six raw-byte arguments and both expected values. Cross-check all seven component digests: admission/request archive inputs, and the five model members. Also cross-check canonical manifest input_files. Do not reopen the canonical archive unless a specific required crosslink cannot be established from the already validated journal. No archived code is imported/executed. Project only strict counts/digests/status; never return a live VerifiedWorkerResponse or vectors to consumers. Preserve public-safe underlying RepresentationValidationError, PairReportRefusal and WorkerRequestError codes as subcodes; incomplete/invalid/conflicting supplied inputs refuse instead of producing an INVALID or CONFLICT dossier state.

## Epic B: separate correspondence dossier

Schema cloe-w5-component-dossier-v1. API build_component_dossier(journal_paths, result_paths, paired_report_path, model_bundle_paths=None) accepts exactly generation slots 1 and 2 for canonical journals/results and at most one explicit model directory per generation. The canonical journals establish actual generation/attempt; caller slot labels do not substitute for them. Reject bool/duplicate/foreign generation labels.

Rebuild with unchanged build_pair_report_v2 and canonical_json_bytes plus one newline. Compare the actual supplied pairedV2 bytes directly. Missing/unsupported or byte-mismatching old reports stop with a source-mismatch refusal; do not rewrite, rescore, repin or execute archived builders. The optional15 replay preflight proves the retained example currently fits. Detect input drift across the composed read/build/join; do not claim an atomic snapshot or hostile-writer confinement.

Bind the actual pairedV2 byte digest/length once in the header. Per generation bind all six canonical journal member digests and lengths and ResultV2 digest/length. For a supplied component, cross-check V2 component_counts.source.component_digests against the seven verified digests and compare recorded counts where present. The axes are separate: recorded=recorded|not_recorded, supplied=supplied|not_supplied, correspondence=verified|unknown. Missing verification counts remain null, never zero. artifact_correspondence_verified is true when established and null when unknown; V2 independently_revalidated remains false and unchanged. Old unrecorded fields stay unrecorded even when a new sidecar independently obtains values. All acceptance/domain flags remain false.

Dossier output is at most 64 KiB, exactly two generation rows, bounded fixed role labels and closed fields. No self-excluded dossier digest; the external file hash is the binding. A structural reader/check command does not re-open original sources or stores; the builder validates correspondence from explicit source files. Fixed disclosures distinguish these claims. No record_id, text, vectors, principals, SQL, admission scope/phase/gate names or private paths are emitted. Existing V1/V2 report, ResultV2 and journal caps remain unchanged.

## Epic C: one-generation real functional provenance boundary

### Corrected functional diagnostic allocation

The first allocated functional execution failed honestly: five of six ANN
candidate calls completed; the last EXPLAIN did not select the expected index.
It emitted a strict failed ResultV2 and confined transport receipts; no completed
functional acceptance is claimed. Its raw journal was not exported because a
report directory without the canonical --report flag does not request export.
Those original journal bytes are unavailable; their retained ResultV2 digests
are references, not substitutes for the bytes.

For this synthetic functional proof only, permit the exact ANN payload adapter
to append both enable_seqscan=off and enable_sort=off. A sequential-scan control
alone does not exclude a competing non-ANN index plus sort. This is a hypothesis
to be tested, not an attribution of the unavailable original plan. Preserve all
SQL, limits, roles and ef_search settings. Exact-reference, setup, catalog and
cleanup calls receive neither option. Retain the complete six-member journal
through the existing artifact framing and verified stdout capsule. The canonical --report option requires coverage and is excluded; its attempted use was refused before tests or setup, with no materialization spent.

The parent may allocate one corrected diagnostic after this actual change,
fresh scoped unit/core-integration/static proof and independent resulting-source
review. This is a separate deliberate allocation, not rearming the spent first
slot. Maximum one additional pgvector 0.8.7 materialization; no automatic retry,
new model, learned attempt16, application/SDK build, complete suite, local
coverage, scientific acceptance or production admission. Allocate at most two
scoped unit executions and one core integration execution for this correction;
repeat only after a finding and correcting change. Existing static limits stay.

Resulting-source review requires raw artifact framing in a finally independent
of ResultV2 validation, honest receipt-read failure handling, a database-free
completed-path test and runner-side member/result hash verification before
success. Allocate at most two additional scoped unit executions for these
specific post-review corrections; use the remaining core integration and static
slots. No optional execution is spent until the reviewed conditions are met.
Planner disable settings impose cost penalties, not absolute prohibitions.
A completed corrected invocation proves its observed index use, not the causal
explanation or stable planner selection across invocations. Supporting grant
extraction remains deferred to separate campaign binding until adopted there.

The existing one-generation harness cannot feed a two-generation pairedV2 dossier. Stop this real SQL proof at the strict generation 1 ResultV2 and journal. EpicB separately proves two-generation joins on retained/public artifact inputs. Never mix the functional SQL evidence with learned calibration.

Source review distinguishes all actual transport routes. The exact-vector route alone installs reader/read-only PGOPTIONS. The ANN catalog, EXPLAIN, candidate and exact-baseline callbacks use unchanged SQL role prefixes; HNSW query transactions are read-only. Setup and cleanup use their actual owner roles. A blanket planner setting is forbidden because it could contaminate the exact reference while the HNSW index exists.

A test-owned executable adapter may append only `-c enable_seqscan=off -c enable_sort=off` to the existing PGOPTIONS for two fixed call classes: the maintained ANN EXPLAIN and ANN candidate query, including their unchanged role prefix. The unchanged public cal-01 task selects core and companion, requiring one exact payload per call class per binding: at most four distinct precomputed SQL digests, with at most two per class. This corrects the preliminary two-digest assumption while preserving the task and input scope. All other invocations pass through byte-for-byte unchanged, including exact-vector, exact-baseline, catalog, setup and cleanup. Build allowed SQL strings from the same validated queries and frozen builders; never classify by a broad keyword or rewrite SQL. Refuse ambiguous argument forms. The real psql and every existing role/read-only mechanism remain unchanged.

Record each invocation's fixed route label, SQL digest, whether the option was appended and the resulting safe option family in a test-owned receipt. This per-call record is primary transport evidence; any SHOW observation is explicitly a separate session. Prove confinement and exact-reference exclusion with unit tests, then independently review the actual adapter and every callback before each separately allocated optional execution. This is the explicitly disclosed functional-only setting allowed by ADR0146, with no calibration/performance or production policy claim.

The real composed proof uses explicitly synthetic 384-dimensional unit vectors and a test-only synthetic profile, with no BGE inference or worker-admission receipt claim. Candidate rows, exact search, index creation/catalog/EXPLAIN/query/cleanup, fusion and grading use matching real public publication identities. It stops at the strict generation 1 journal and ResultV2. The two-generation dossier uses separate public artifact fixtures and retained evidence. Never mix these claims. Epic C passed independent source review and the separately allocated corrected functional diagnostic. Its raw journal/ResultV2/stdout-capsule and actual index/cleanup observations were cross-checked; no scientific or production acceptance follows.

The functional planner transport records are the option evidence. The maintained plan summary's default planner_forced field does not observe this test transport and is explicitly labelled accordingly. Session SHOW readback is separate from EXPLAIN execution. Failures before journal admission are ordinary test failures with no journal or ResultV2. After admission, execution failures attempt failed framing while preserving the primary error; finalization/IO failure may prevent framing. A completed journal without a validated emitted ResultV2 is not completed proof. Functional synthetic identities are retained separately and must never be joined with learned generation evidence.

The original allocation permitted one separately parent-ledgered pgvector 0.8.7 materialization and canonical no-coverage optional execution. That slot is spent and failed; only the explicit corrected allocation above permits one additional diagnostic after source review and core checks. If settings do not reach the real calls or the planner still does not select the HNSW index, retain not_run/index_not_selected as a named uncompleted proof boundary. No further setup/run beyond the corrected allocation, forced calibration, SQL policy change, fake completed credit, skip or xfail follows. Parent must explicitly disposition any required gap before declaring this technical phase complete. No new learned attempt16 or application/SDK build.

## Exact owners and verification

New source owners (split further only for real responsibility and <=400 lines):
- tools/retrieval_semantic_raw_component_io.py, retrieval_semantic_raw_component_anchors.py, retrieval_semantic_raw_component.py.
- tools/retrieval_semantic_component_dossier.py, retrieval_semantic_component_dossier_contract.py, retrieval_semantic_component_dossier_io.py.
- The existing generator output-receipt owner receives only the public archive-input seam.

Scoped unit owners:
- src/test/unit/python/tools/retrieval_semantic_raw_component_io.unit.test.py
- src/test/unit/python/tools/retrieval_semantic_raw_component_anchors.unit.test.py
- src/test/unit/python/tools/retrieval_semantic_raw_component.unit.test.py
- src/test/unit/python/tools/retrieval_semantic_component_dossier.unit.test.py
- src/test/unit/python/tools/retrieval_semantic_component_dossier_integrity.unit.test.py
- src/test/unit/python/tools/retrieval_semantic_component_dossier_cli.unit.test.py
- src/test/unit/python/tools/retrieval_semantic_component_dossier_imports.unit.test.py
- Epic C verified functional scope: src/test/unit/python/tools/w5_functional_planner_adapter.unit.test.py and w5_functional_supply.unit.test.py.

Integration owners:
- src/test/int/python/repomap_kg/retrieval/component_dossier.int.test.py (real temporary journal/ResultV2/model-artifact IO; two generations, positive/refusal and drift paths; no inference).
- src/test/int/python/repomap_kg/retrieval/component_dossier_cli.int.test.py (actual tool process, exclusive outputs, no runtime/archived-code import).
- Epic C verified functional scope: src/test/int/python/repomap_kg/retrieval/semantic_observed_ann.int.test.py (the single separately selected requires_pgvector functional boundary).
- Shared public-only synthetic artifact and functional adapters under src/test/support/python/repomap_test_support/w5_component_*.py, each focused and <=400 lines.

No diff to retrieval_semantic_pair_report.py, retrieval_semantic_pair_v2_report.py, their validation/projection owners or existing V1/V2 tests. Add pinned fixed-fixture byte rebuild tests and retained optional15 replay; old tests remain selected as adjacent regression owners. One unit owner covers each closed refusal family and underlying subcode; tamper member/archive/request/admission/source/cross-report identities; missing vs invalid vs zero; bool/nonfinite/type/size/path/FIFO/symlink/drift/exclusive-write failures. Isolated subprocess import guard rejects numpy, onnxruntime, tokenizers and archived-code execution. Canonical scoped unit/core integration use --no-coverage; no complete local suite or Python coverage.

Supporting campaign maintenance is a behavior-preserving extraction: strict scalar/hex predicates may move from the400-line tools/ci/d12_system_grant.py into its existing73-line d12_system_grant_io.py, retaining import aliases and every policy/cap/spent/superseded case. Public test fixture-only helpers may move from the400-line grant unit/admission int owners into a focused w5-independent d12_system_grant_examples.py test-support owner. No blank-line cap evasion or new admission policy. Register new clean retained owners without changing any debt ceiling. Future campaign binding is separate from spent CI115.

## Alternatives and authority

Status quo recorded-only counts remain useful but leave the identified verification gap. A V3 clone or V2 mutation duplicates/churns frozen interfaces. Caller-provided expected hashes or current-checkout equality either assert their own truth or reject legitimate old evidence. New archive grammar or executing archived code is rejected. A permanent query/planner/representation change is outside this technical phase.

Parent routine selection of this corrected technical design follows independent review and the operator's current roadmap instruction. Before source implementation, record accepted ADR/spec and explicit scoped proof allocation; optional pgvector allocation and final source review are separate. Before publication, fresh exact-candidate source/grant/report proof and one new campaign allocation are required. Scientific criteria, held-out tasks, broader/model/input/runtime dependencies, production admission, live deployment, main/tag/release and repository rename remain operator decisions.

## Binding review amendments

The original optional15 canonical declarations were inspected for both generations: `component_source_closure` equals `source_closure`, has17 bare-name members and matches each `source_files['tools/'+name]` entry in the canonical manifest. That manifest is a superset. The admission/request digests independently agree across canonical declaration/report/manifest. The archived request digest versus canonical report is a mandatory refusal condition. No current-checkout source equality is substituted.

The unchanged V2 builder rereads paths. Capture all source member digest, size and device/inode identities before it runs, then re-read and compare afterward, including raw model members and paired bytes. Join journal member and ResultV2 bindings to the rebuilt V2 source_provenance. This detects drift; it is not an atomic filesystem or hostile-writer guarantee.

Use the seven V2 role spellings, including source_manifest and sources_archive. The new CLI documents refusal exit3. Its check command is structural and does not reauthenticate original sources. Its import guard covers the new reader and dossier owners and their whole import closure, with no model runtime imports or archived-code execution.

Grant maintenance exposes public scalar predicate names in the existing IO owner and retains underscore aliases in the policy owner. Move only campaign-independent test builders; all live-candidate/campaign-pin/spent-nonce assertions stay in their tests. No authority, debt, cap or runner-policy change.

## Verification allocation

The parent allocates at most 12 exact scoped unit executions,6 exact scoped core integration executions and 8 scoped static executions for this technical batch. Run the narrowest selection first; repeat only after a finding and correcting change or on the final frozen candidate. All tests use canonical run_tests.py with --no-coverage. Full unit, integration, smoke, staging and system suites and Python coverage remain unselected. The optional pgvector proof requires a separate parent ledger after adapter review and core acceptance. Application/SDK builds and learned attempt16 remain unallocated locally.

The technical batch must reach implemented, reviewed behavior before publication. CI115 is spent and cannot be reused. A future hosted campaign needs a new exact-candidate reservation, fresh source/report proof and one ordinary staging publication under the standing operator authority; there is no duplicate trigger, automatic retry or main/tag/release action.

The proposed fixture-helper extraction was declined: both existing grant test owners remain within 400 lines, so no new examples owner is needed.
