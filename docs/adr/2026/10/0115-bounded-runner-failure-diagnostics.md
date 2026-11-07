# ADR 0115: Bounded runner failure diagnostics without qualification authority

## Status and authority

Accepted before implementation, 2026-10-29, for
REPOMAP-CLOE-RUNNER-RECOVERY1 within the operator-approved W0 source
reconciliation. The parent selected direct implementation with native CLI
assistance following the custody audit at `fc8c35f`. Independent design review
resolved the diagnostic, privacy and cleanup interfaces before source changes.
This decision grants no build, publication, runtime or namespace cutover authority.

## Problem and decision

The public runner can lose the first infrastructure failure when Go restoration
or report persistence raises afterward. Candidate identity is established outside
the guarded runner body. Discovery keeps only a coarse failure signal and removes
its temporary receipt directory. The private precursor contains useful recovery
work, but its arbitrary-text redaction/capture assumptions are not adopted.

Retain bounded typed infrastructure diagnostics separately from qualification.
Keep discovery stdout/stderr handling unchanged (`DEVNULL`): no new pipes,
threads, raw output tails or hashes of child output. Do not serialize exception
messages, args, locals, environment values or traceback paths. The useful new
evidence is the first error's stage, type, native errno and cause types, together
with validated child diagnostics and observed process facts.

The status quo preserves gates but loses failure fidelity. Blind copying the
private prototype risks stale interfaces and unbounded privacy assumptions.
Changing staging qualification formats would combine a policy migration with
this recovery fix. The selected scope preserves all successful qualification
schemas, validators, M/A populations, coverage floors, admission and retry rules.

## Ownership and schemas

`tools/runner_failure_evidence.py` owns safe error projection, strict diagnostic
validation, bounded reads/persistence and `FailureEvidence`. Its maintained owner
must be admitted cleanly under current retention policy, without debt growth.

Both durable diagnostics live in `Path(args.report_dir)/args.suite/'latest'`:

- `runner_failure_report.<invocation_id>.json`;
- `staging_discovery_diagnostic.<invocation_id>.json`.

Invocation-specific names preserve older invocations without deleting their files.
An observed existing target or symlink is refused. The same `FailureEvidence`
instance may update only its own earlier exact, revalidated payload; observed
content/ownership drift refuses the update. Simultaneous reuse of the same report
directory and exact invocation ID is unsupported. No hostile same-user writer
guarantee is claimed.

Use `staging_report_contract.persist_report(..., validate=False)` for its existing
private temporary file, fsync and atomic replace behavior. The new diagnostic
validator runs first; staging validation is not repurposed or weakened. File mode
is `0600`; encoded JSON is at most 32 KiB. Readers require owned ordinary files,
no symlinks, bounded bytes, UTF-8, no duplicate keys and exact schema fields.
Local private-candidate reports remain private; the projection contains no raw
payload and is suitable for a public CI run bound to public candidate identities.

The runner diagnostic fields are exactly:

- `schema`: `repomap-runner-failure-v1`;
- `invocation_id`: a bounded ASCII identifier; canonical producers use UUID hex;
- `candidate_at_start`: null before identity is established, otherwise exactly
  `commit` (lowercase 40/64 hex) and `source_sha256` (lowercase 64 hex);
- `execution_succeeded`: false;
- `partition_state`: `established` or `not_established` from actual state;
- `primary`, `secondary` (at most 16), and `secondary_omitted`.

An error record has exactly `stage`, `type`, `errno`, `causes` and
`causes_truncated`. Stage comes from a closed runner-owned set. Type is an ASCII
identifier up to 64 characters, otherwise `Exception`. Errno is null or a strict
bounded native integer read from the built-in `OSError` slot. Read built-in
exception cause/context/suppression slots, detect cycles and cap the chain at four
cause records (`type`, `errno`). Never call `str(error)` or exception properties.

The discovery diagnostic has exactly schema
`repomap-discovery-diagnostic-v1`, invocation/candidate bindings,
`partition_state: not_established`, `collected_count: null`, `process_exit`,
`receipt_exit`, primary/secondary/omitted errors and optional `child_error`.
Parent-observed process exit overrides child claims. Receipt exit is null unless
the receipt was actually validated against the request. No unverified counts,
population, coverage or fabricated candidate identity are emitted.

The child may write `child_error.json` beside its temporary receipt after argv
paths and helper imports are available. Its internal envelope is exactly
`schema: repomap-discovery-child-error-v1` and a safe error record. Invalid argv
or missing helper/import may produce no child diagnostic. A missing record yields
`child_error: null`; a present invalid record also adds at most one fixed-stage
secondary. It never replaces the parent primary or process exit. The parent
persists its diagnostic before owned temporary-directory removal; this is the
explicit diagnostic sink. Discovery function and injectable seam signatures stay
unchanged. Request and successful receipt schemas remain unchanged.

## Trigger and precedence

The first actual runner infrastructure exception remains primary. Later report,
rendering, validation or required cleanup exceptions are bounded secondaries.
Required cleanup errors still prevent success, and become primary if no earlier
infrastructure exception exists. An ordinary assertion failure or coverage-floor
failure remains represented by its existing report, not an invented exception.
An instrumentation flag without an actual exception creates no failure diagnostic
by itself; its existing incomplete-measurement error remains authoritative. If
that incompleteness blocks a selected leg, strict final report validation can
raise an actual `StagingReportValidationError`. That separate exception is
retained as validation, never invented as an instrumentation exception. Incomplete
raw observations still cannot qualify.

Guard candidate establishment in Decision B and smoke-refusal reporting. A smoke
identity failure writes its existing raw refusal report with null candidate,
retains the diagnostic under that smoke invocation, and leaves the caller's
failure exit unchanged. Do not reuse an unstarted Decision-B invocation ID.

Use closed stages for candidate/source identity, discovery startup/collection/
receipt/cleanup, M/A execution or measurement, report validation/persistence/
rendering, Go/measurement cleanup, smoke reporting and diagnostic persistence.
Replace runner-generated validation exception text with fixed stage/type output.
Existing pytest test-record contents retain their existing report/privacy owner.

Guard each ordinary cleanup, rendering and final-persistence exception separately
so one failure does not skip remaining attempts. Preserve existing control-flow
signal mappings: a cleanup `KeyboardInterrupt`/`SystemExit` is retained, remaining
cleanup is attempted, then that signal is re-raised. Existing per-leg handling
is unchanged. Hard termination cannot guarantee evidence persistence.

Discovery captures its primary exception before exact group settlement. Cleanup
failure is secondary if an earlier error exists, otherwise primary. Raise the
original failure after diagnostic persistence; never return a partition after
cleanup uncertainty. Diagnostic persistence failure emits only safe fixed/type
output and cannot replace the original ordinary failure or permit success.

Existing incomplete raw staging observations may still be persisted through the
existing unvalidated writer. `validate_report`, `execution_succeeded`, `qualifies`
and manager acceptance are unchanged and must reject diagnostic-only artifacts.

## Verification and boundaries

Reproduce the actual lost-cause path before the fix: failed discovery followed by
failed Go cleanup currently raises the Go error instead of returning failure with
the discovery error primary. Prove typed cause/secondary retention, raw-text and
`__str__` tripwires, bounded validation and I/O, nullable identity, diagnostic
persistence failure, cleanup continuation and unchanged positive qualification.

Use exact canonical scoped unit and containerized integration selectors with
`--no-coverage`. Integration exercises a real canonical runner subprocess with an
invalid scoped selector and actual artifact I/O before partition, plus real
controlled discovery-child failure and owned cleanup. Do not call a mocked
boundary integrated or invent passed tests/counts for a failed collection.

No dependency, metadata, lock, runner-policy, threshold, exclusion, suppression,
complete-local-suite, coverage, app/SDK build, image refresh, live home/database,
remote or history mutation is included. Keep the protected checkout unchanged.
Final source review, fresh proof and clean enrollment precede the local commit.
Publication requires the final batch freeze and any fresh build allocation;
spent grants stay spent. Optional pgvector companion/profile propagation remains
separate W5 work. No package/import/default-home change occurs here.
