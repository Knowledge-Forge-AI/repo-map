# REPOMAP-CLOE-RUST-FOUNDATION1 Exit: Dependency-free extractor capability foundation

Status: **accepted local foundation checkpoint; hosted successor qualification
and parser-class selection pending.**
Base: staging `7bb9ef67dc7a4e4ffe422bf69a2334230bf194fa`. This record uses the
public export's `tools/ci` exit convention because the export carries no
`docs/status` archive.

## Scope and disposition

[ADR 0154](../../docs/adr/2026/11/0154-extractor-capability-receipt-foundation.md)
and [the foundation contract](../../docs/specs/cloe-extractor-capability-foundation-v1.md)
implement the dependency-free W6 prerequisite common to every parser decision:

- closed cap-v1, effect, provenance and five-fact lifecycle vocabularies with
  strict primitive validation;
- the closed legacy baseline: the 25 distinct entrypoints the discovery
  dispatch calls (26 call sites) and the exact emitters of 26 product extractor
  names, resolved from source without hashes, loaders or wildcards;
- strict canonical receipts with an external digest, separate declarations and
  observations, explicit incomplete/refused/unavailable states and transitions
  in which observed facts only accumulate;
- bounded no-follow descriptor-relative storage with exclusive creation,
  stable-stat readback and exact owned cleanup;
- a parent-witness contract with no positive path, and pre-dispatch
  canonicalization refusal of reserved capability-claim metadata, receipt
  references and Rust language assertions.

Legacy discovery and canonicalization output is unchanged for observations
without those claims. Markdown code fences and HTML documents, whose `language`
describes embedded content, are not Rust assertions, so a `rust` fence keeps
its legacy evidence. `canonicalization/main.py` gains two wiring edits and
stays at 728 lines. No parser, dependency, lock, workflow, runner policy, Rust
raw kind, graph key, `.rs` classification, CLI or MCP change is made.

Deliberately absent native proof: there is no native observer, helper,
parser import, confinement, cleanup witness, ARM/AMD component execution or
measured parser comparison. Those follow only an approved parser class and its
resulting ADR. Contract doubles prove contract logic only.

## Verification

Developer diagnostics through the parent-owned scoped wrappers with
`--no-coverage`; they are not qualification evidence. Unit command:
`tools/run_tests.py --suite unit --no-coverage --jobs 1 --` followed by:

- `src/test/unit/python/repomap_kg/extractors/contracts/vocabulary_contracts.unit.test.py`
- `src/test/unit/python/repomap_kg/extractors/contracts/legacy_registry.unit.test.py`
- `src/test/unit/python/repomap_kg/extractors/contracts/receipt_codec.unit.test.py`
- `src/test/unit/python/repomap_kg/extractors/contracts/bounded_io.unit.test.py`
- `src/test/unit/python/repomap_kg/extractors/contracts/witness_claim_guard.unit.test.py`
- `src/test/unit/python/repomap_kg/architecture/arch1d_dependency_dag.unit.test.py`
- `src/test/unit/python/repomap_kg/canonicalization/package_structure/core_shared_dispatch.unit.test.py`
- `src/test/unit/python/repomap_kg/extractors/package_structure.unit.test.py`
- `src/test/unit/python/repomap_kg/canonicalization/core_file_email.unit.test.py`

Integration command: `tools/run_tests.py --suite int --no-coverage --jobs 1
--pg-container-port 55433 --` (automatic container sandbox) followed by:

- `src/test/int/python/repomap_kg/extractors/contracts/receipt_storage.int.test.py`
- `src/test/int/python/repomap_kg/extractors/contracts/canonical_claim_refusal.int.test.py`

| Run | Result | Disposition |
|---|---|---|
| unit 1 | 171 passed, 5 failed | Registry raised the base error type for non-string names (source fix); two test expectations corrected |
| unit 2 | 176 passed | After correction |
| integration 1 | 11 passed, 1 failed | Linux reports a directory symlink as `ENOTDIR`; refusal held but the code differed from macOS (source fix plus unit case for both errno paths) |
| unit 3 | 178 passed | After correction |
| integration 2 | 12 passed | After correction |
| checks 1 | topology, file length, suppression, public export, changed-source compileall, whitespace and both diff checks pass | The generic new-or-changed 400-line flag reports only pre-existing `canonicalization/main.py` at its unchanged 728 lines |
| privacy scanner 1 | 0 findings over 26 exact paths | |
| static 1 | failed: inventory retained set does not match ratchet selection | Expected parent gate below; no later Ruff/mypy profile result was produced |
| unit 4 | 178 passed | After review corrections: shared receipt-prefix constant in the claim guard and descriptor release when `fstat` fails right after exclusive creation |
| unit 5 | not executed | The intent was recorded, then the wrapper's exclusive log creation collided with a pre-created log file before any test process started; it consumed one allocation |
| unit 6 | 184 passed | After the independent-review revision below |
| integration 3 | 12 passed | After the independent-review revision below; Docker resource sets preserved |
| checks 2 | topology, file length, suppression, public export, whitespace, both diff checks and the new-or-changed length check pass | `canonicalization/main.py` stays at its preserved 728-line ceiling; every other changed Python file is at most 360 lines |
| privacy scanner 2 | 0 findings over 26 exact paths | Only these two result rows were filled in afterwards |
| parent RED | 2 failed as expected | Batch materialization and shared-directory preconditions, before correction |
| parent static 2 | failed | Unused scope authority and one new-test mypy error; corrected |
| parent static 3 | passed | Every retention root enforced; residual sets and cohort regressions empty |
| parent unit GREEN | 188 passed | Corrected resulting executable source |
| parent integration GREEN | 13 passed | Containerized, no builds/pulls, exact cleanup and resource equality |
| parent final checks | passed | Topology/export/length/suppressions/compile/diff checks |
| parent final scanner | 0 findings | Exact changed-owner scope, full redaction |
| second independent source review | PASS, no blockers | Full frozen code/diff and hash-bound proof inspected; advisories dispositioned below |

At the first dispatcher handoff, integration 2, checks 1 and scanner 1
preceded the unit 4 corrections; unit 6, integration 3, checks 2 and scanner 2
bound its revision. That handoff exhausted its initial six-unit/three-integration
allocation and left the ratchet gap open. The separately declared parent
allocation and resulting checks below supersede those historical pending gates.

### Independent review revision

The independent work review recommended revision. Its findings were disposed:

- F1 (legacy regression, accepted): the Rust assertion refused legacy
  `markdown.code_fence` observations whose fence info word is `rust`. The guard
  now exempts `markdown.code_fence` and `html.document` from the Rust assertion
  only; reserved metadata names are still refused on them. The integration
  fixture now contains a `rust` fence and asserts no refusal and retained
  evidence; unit cases cover both kinds.
- F2 (receipt transitions, accepted): transitions now refuse any change or
  removal of earlier observed facts, with unit cases for each rewrite.
- F3 (documentation, accepted): the census omitted only the file inventory
  observation and the Python module index; 25 is the count of distinct
  entrypoints over 26 call sites.
- F4 (registry owner precision, partly accepted): `markdown_anchor_index` now
  names its defining module. The document adapter keeps the `office` facade
  because it dispatches both the plain and the ODF implementation through it.
- F5 (resolver blind spots, accepted): `**` splats and attribute `extractor=`
  values now fail the source-resolution owner instead of being skipped; no
  product construction uses either form today.

The first producer implementation had no retained pre-implementation RED;
the later parent correction has the two RED cases recorded above. Proof runs
preserved source and index at their entry/exit checks and proved cleanup;
integration preserved Docker resources. A producer tooling-path error briefly
created two support files outside the contribution checkout. They were moved
back, final protected source/HEAD/physical-index equality was independently
verified, and the transient violation is retained in private custody. Final
equality is not a claim that no temporary write occurred.

Complete local unit, integration, smoke, staging, system and combined
populations, local candidate coverage and application/SDK builds are
intentionally unselected; no complete-suite override exists.

## Hosted CI and gates

Hosted capacity is AVAILABLE; no remote action, push or campaign belongs to
this checkpoint, and no CI121 grant or start 32 exists. Hosted execution is
`NOT_REQUESTED_CONSERVATION`: accumulate this prerequisite into the substantial
milestone before publication. Retention admission, independent review
and parent scoped proof are complete. Pending: separate parser-class selection
and hosted qualification of the
eventual substantial W6 milestone. CI120 remains EXECUTED_FAIL at native SDK
preparation; successful product lanes do not qualify that native boundary.

The final checkpoint adds 3,165 physical Python lines: 1,467 product,
1,317 unit/integration tests and 381 test support, plus the narrow existing
source edits, documentation and clean-owner records. It remains below the
10k–100k meaningful-LOC milestone target. W6 and v0.1.0 are not complete;
this prerequisite is not published alone.

## Parent correction and clean admission

The parent closed two additional contract gaps: batch construction checks
exact list/tuple type and length before materializing input; every receipt IO
operation requires an effective-user-owned directory with no group/other
access. The owning principal and privileged host processes remain trusted;
check-then-unlink is not an atomic hostile same-user boundary. Unit and
integration owners cover shared descriptors, unchanged foreign data and
incomplete cleanup after a directory-mode change.

Two targeted parent unit tests failed on the earlier code before correction.
The parent added eight clean retained selection rows, preserving every old
row, numerical debt, tool/import/length section and ownership manifest. An
unnecessary scope authority record was rejected and removed: clean additions
need no restricted-scope authority, and the inherited scope registry is
byte-identical. A new-test mypy error was corrected without policy changes.
The third static execution passes all roots with enforcement complete,
empty eligible-minus-enforced sets and zero cohort regressions. Earlier static
failures remain retained diagnostics.

Final parent proof uses the exact unit and integration selectors above with
`--no-coverage`: **188 unit passed** and **13 integration passed**. The
integration uses the existing diagnostic image override with its exact Engine
ID retained privately; builds and pulls are zero, source is preserved and
Docker resource sets are equal. Targeted RED selectors were
`witness_claim_guard.unit.test.py::test_batch_rejects_unbounded_iterables_before_consumption`
and `bounded_io.unit.test.py::test_shared_directory_is_refused_before_open_returns`
under the unit contract directory listed above. Both failed before correction.
The parent allocation permits at most nine unit and five integration intents;
eight unit intents (one aborted before tests) and four integration executions
are spent. All three static executions are spent; the last passes. No complete
local suite, coverage or build was added. Second independent source review is
complete with PASS and no blockers; no hosted qualification follows from
these diagnostics.

## Final review disposition and limits

The parent accepted the second review. A read-only AST census of all 724
product Python files found 41 direct language/dialect write sites. Current
legacy raw emitters with content-derived language values are the two exempt
kinds; discovery/feed and shell emitters use their fixed classification or
named-dialect paths. The census covers supported source shapes, not arbitrary
Python aliasing or future emitters. New emitters still require review.

Directory admission checks POSIX ownership and mode bits. The trusted creator
must ensure there are no additional ACL grants; ACL inspection is not
implemented. Operational filesystem faults may propagate `OSError`; typed
policy/codec refusals remain categorical. A future native controller must
bound and sanitize all diagnostics before capability admission. No native
admission is available in this foundation.

The static artifact has a parent integrity association linking its original
intent/result, immutable wrapper, command owner and full report hashes.
Documentation changed after static execution; Python and retention JSON pins
remain identical. These are scoped developer diagnostics, not a signed
execution attestation or whole-candidate qualification.
