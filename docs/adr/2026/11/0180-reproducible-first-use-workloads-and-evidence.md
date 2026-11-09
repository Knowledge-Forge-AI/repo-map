# ADR 0180: Reproducible first-use workloads and evidence

Status: accepted by the parent after independent design review and the
explicit refusal-classification correction; implementation acceptance pending.
Date: 2026-11-09. Phase: `REPOMAP-CLOE-FIRST-USE-WORKLOAD1`.
Source parent: `cc6c91e1e4170d2775540945e5996d734bc0800e`. Public base: `5ad00d162ad8a04430874275246a53227578c533`.

## Context

CI136 attempt 1 qualified source parent `cc6c91e` as an `EXECUTED_PASS`
staging candidate (see the roadmap record). The user asked to carry on with
the roadmap. W7 still lacks a reproducible, inspectable account of the first
useful Local, Server and mixed-material experience: what was run, over which
inputs, at what observed cost, with which refusals, and whether the results
reconcile with independent witnesses.

Current source already contains the parts such a workload needs:

- three first-use integration owners (`ops/first_use_local`, `_server`,
  `_mixed`) that run real guarded Local CLI children, real Server refresh and
  lexical calls over a disposable PostgreSQL, and mixed privacy checks;
- independent sealing witnesses in
  `repomap_test_support/governance3_first_use_sealing.py`, which derive
  `4S+C+m` from fixture bytes and the stored manifest, not from a plan;
- strict, bounded resource-report codecs (`ops/resource_reports/_codec.py`)
  and the read-only `ops sealing-plan` (`cloe-sealing-plan-v1`, 4,096 bytes);
- the canonical integration sandbox, whose only host-visible file output
  besides console and exit status is the bounded `--report` export
  (4,096 members, 64 MiB).

What is missing is a frozen statement of intent, a step-ordered and
attempt-bound observation record, and a pure reconciler that refuses
incomplete or inconsistent evidence. Each existing owner asserts and then
discards its facts.

## Decision

Implement one milestone with three connected epics under the
[first-use workload contract](../../../specs/cloe-first-use-workload-v1.md).

1. **Frozen workload and evidence harness.** A committed census freezes the
   materialized `mixed-v1` generation-1 and generation-2 inventories and the
   fixture source digest. A code-owned recipe fixes the ordered scenario steps,
   manual expected locations, backend-specific expectations and explicit
   opt-in budget expressions, with a declared alias set per scenario. A pure
   `plan` produces a canonical intent that binds the recipe, census, a
   git-free digest of the product source (`src/main`, `pyproject.toml`) and
   the complete canonical candidate source census (all product/tools/support/test
   owners), separately from the fixture census. A
   declared source parent is recorded but never required to exist as a
   commit, so precommit proof needs no future SHA.
2. **Real execution.** Three new integration owners run the recipe in the
   existing canonical sandbox over disposable owned homes, SQLite and the
   temporary PostgreSQL. A test-support driver records preparation, call
   and cleanup separately, with explicitly scoped clocks and CPU. Cost terms
   come from fixture and store witnesses. Physical PostgreSQL work and hard
   RSS are never inferred.
3. **Reconciliation and an inspectable artifact.** A pure reconciler checks
   complete, ordered observations against the intent, census, accepted pins,
   stored manifests and decoded reports. It keeps expected refusals, actual
   failures and skips separate. The in-sandbox owner writes a bounded bundle
   and validates it. When the run uses the existing `--report` export, the
   bundle is exported beside the HTML report, and a checkout-only
   `tools/first_use_workload.py check` re-validates it on the host.

### Selected boundaries

- **Checkout-only.** The tool, records and reconciler live under `tools/`.
  Execution adapters live under `src/test/support/python/`. No installed
  module, console script, CLI option, MCP field, configuration key or package
  data changes. Product code must not import either root.
- **No product source change is planned.** If an expectation fails on the
  incumbent product, that is a finding to report to the parent. The
  expectation must not be edited to match the output, and no product
  correction is folded in silently.
- **Formats.** The five new `cloe-first-use-*-v1` formats are derived
  observations. They carry no graph, publication or resource authority.
  Resource-report v1/v2 and sealing-plan schemas, vocabularies and bounds are
  unchanged and are only decoded.
- **Runner and quality.** There is no runner change, flag, environment key,
  admission class, declaration, full-suite command, local coverage or build.
  The bundle reaches the host only through the existing `--report` export.
  That flag requires coverage. Local proof remains scoped and coverage-free,
  with in-sandbox validation; hosted CI137 supplies the exported bundles.
  Their host validation remains required after CI, before bounded first-use
  acceptance. Publishing the source-tested candidate does not accept that gate.
  New owners enroll cleanly under the incumbent quality roots and ceilings.
- **Inputs.** The census reads only the four `mixed-v1` alias trees and
  `python-sources-v1.json`. No task/gold/held-out or old-trial content is parsed or used by the
  workload. Canonical source identity may hash opaque tracked bytes only;
  scientific and held-out criteria stay separate.
- **Budgets.** Ordinary steps use the default budgets. Only the
  planned-refusal step passes an explicit recipe value (`4S`, with `S` taken
  from the census).
- **No retries or sweeps.** A failed step is recorded once and is never
  re-run. Cleanup touches only resources the attempt created.

### Alternatives considered

- **An installed `cloe ops workload` command.** Rejected. It adds an installed
  public surface and W8 qualification scope, and the evidence does not need
  to be installed.
- **A plan-only or host-side runner.** Rejected. It would not exercise real
  flows in canonical isolation, and running on the host risks developer homes
  and databases.
- **A new runner flag or environment key to export evidence.** Rejected
  because it is runner policy. The existing `--report` export already
  carries bounded regular files.
- **New fields in resource-report v1/v2.** Rejected. Those vocabularies are
  frozen. A separate derived format is additive and removable.
- **Migrating the three existing first-use owners onto the recipe.**
  Rejected for this milestone. They stay as unchanged incumbent regressions.
  The new owners reuse their helpers and assert only the deltas in the
  contract.
- **Taking expected locations from evaluation golds.** Rejected because it
  breaches held-out separation. Expected locations are hand-authored from the
  public fixture source text.
- **Writing the census at run time.** Rejected, because a census written
  during the run is not frozen before execution. The committed census is the
  freeze, and a materialization that drifts from it is refused as stale.

## Consequences

- Each canonical run of the three owners produces up to three validated
  bundles, retained when `--report` is selected. Hosted staging already runs
  with `--report`, so CI137's staging artifact will carry them, sharing that
  export's member and byte budget with the existing report. A pass means the in-sandbox
  reconciler accepted complete evidence. A host `check` proves format,
  binding, ordering and arithmetic consistency of the retained bytes. It does
  not prove producer authenticity; the bundle carries no signature, as with
  resource reports.
- Index/verdict controls are excluded from the payload index, giving an
  acyclic payload→index→verdict chain. Observations stay non-additive. No report value is summed across steps or
  backends, and no threshold is applied to measured time or CPU.
- The integration population grows by three real owners. The incumbent
  first-use, sealing-plan and resource-report owners stay unchanged as
  adjacent regressions.
- The forecast is about 9,000–10,500 meaningful lines (contract §13), at the
  lower edge of the 10k–100k aim. It is not padded.

## Residuals and limits

- R1: When `--report` is not selected, the inner report root does not exist;
  bundles are written under the test's pytest temporary directory and are
  discarded with the sandbox. In-sandbox validation still gates the test.
- R2: Waited-descendant CPU is cumulative over all descendants the test
  process reaped during a span, including `psql` and harness helpers. It is
  attributable only under the runner's serial default.
- R3: The manual expectations come from fixture text. If the incumbent
  misses one, that is a stop-and-report finding, not an edit.
- R4: The declared source parent is unverified prose. The binding identity
  is the product digest plus the candidate census; the exit record also
  binds the runner's `candidate_identity.source_sha256`.
- R5: Same-UID tampering between write and export is detectable only as a
  digest mismatch against the index, which is not an authenticity claim.
- R6: Native Windows, installed wheels and images, full W6/W7, held-out
  evaluation, physical PostgreSQL governance and the deferred custody
  scenarios of ADR 0177 stay open.

## Rollback

Revert the source. The change touches no stored product format,
configuration, schema, dependency or runner behavior. Retained bundles are
inert derived files and can be deleted by their owner.

## Acceptance

The parent accepts this bounded design after independent review identified
and the parent corrected the refusal-classification defect. This is ordinary
W7 implementation authority under the user's roadmap continuation, not a
claim that the previous rejected bytes passed review. Completion needs:

- exact scoped unit and real containerized integration selectors with
  `--no-coverage`;
- unchanged quality, debt, receipt and coverage gates;
- an exit record;
- independent review of the resulting source;
- a fresh final-source binding before one staging publication and
  CI137 attempt 1.

No design-only CI, main, tag or release, automatic retry or successor follows.
