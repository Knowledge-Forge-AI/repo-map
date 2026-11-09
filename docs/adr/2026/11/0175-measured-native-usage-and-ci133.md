# ADR 0175: Measured native usage and one CI133 attempt

Status: Accepted for bounded implementation and one CI133 attempt.
Date: 2026-11-08.
Phase: REPOMAP-CLOE-CI132REPAIR1.
Supersedes: ADR 0067 only for the exact usage helper admission and two
additional abrupt declarations below. Preserves ADR 0173 native ownership.

## Context

CI132 exposed a runner adapter that lacked the approved collect_usage option.
Forwarding the option alone would inject a factory that native usage ownership
correctly rejects. The test helper is outside the closed command admission;
its two intentional abrupt cases cannot guarantee orderly child measurement.
The other cycle, reader-fixture and exact Debian manifest failures have
independent repairs. The operator explicitly selected the reviewed bounded
runner repair and one CI133 staging attempt before implementation.

## Decision

Add a private native lifecycle observation interface to _worker_launch's
run_worker_spec and _protocol_execution._run_protocol_worker. The public
protocol facade, wire contract, CLI and MCP are unchanged. An observer requires
collect_usage and cannot accompany an injected factory or launch ticket.
Both existing ownership guards remain effective. Validate before launch.

The sole native owner constructs ManagedProcess and its ChildUsageReaper.
Notify launched(pid) inside owned cleanup before the first poll or wait.
Notify settled(frozen_facts) after actual wait, group cleanup and stream/reader
settlement. No process object escapes through observation. A callback neither
constructs nor substitutes, polls, waits, reaps or signals a process. This is
trusted coordination, not a hostile-Python sandbox. Failure preserves the
primary error, performs owned cleanup and cannot manufacture a proven record.
Interrupt cleanup returns factual disposition while preserving kill-first
ordering, deadline and incumbent second-BaseException semantics. Missing,
failed or interrupted proof remains unproved, never inferred from PID absence.

Admit only -m repomap_test_support.usage_worker from exact committed support
and product roots, with existing interpreter identity, ordered PYTHONPATH
equality and closed capability/job/attempt and seven-case argument validation.
No arbitrary script, source root or ambient coverage variable is admitted.
The five normal cases remain measured M under role portable. The measured
adapter forwards collect_usage and observes the native PID to retain both
token registration and process_observer.observe_launch with actual augmented
argv/environment. No injected process factory or receipt-headroom wrapper is
used on this path. Registered child receipts remain strict. A forced timeout
in M may fail the invocation's measurement; it is not reclassified as A.

The helper's grandchild-waited, grandchild-remaining and block cases permit at
most one fixed stdlib-only fixture descendant, running the existing interpreter
with -I -S -B -c under a minimal environment without coverage/bootstrap paths,
PYTHONPATH or registration state. This non-product fixture classification
follows SCALE28. It does not exclude maintained source or permit arbitrary
unregistered product children. Waited CPU and exact group cleanup remain
observed. Probe arguments are required only for those three cases, with an
absent leaf under a canonical private test-owned parent outside measurement
trees. Create exclusively with no symlink following and mode0600; never
truncate an existing file. Other cases forbid the probe argument.

Use runner_abrupt_evidence as the sole unregistered A owner. Preserve the
three existing declarations and add exactly these integration nodes from
repomap_kg/coordinator/usage_reaper.int.test.py:

- test_sigkill_still_yields_rusage_and_a_negative_return_code:
  role usage-self-sigkill, returncode -9, checkpoint pre_hello.
- test_a_parent_interrupt_kills_the_whole_group_and_preserves_the_original:
  role usage-parent-interrupt, settled child returncode -9, checkpoint pre_hello.

Both launch_owner fields are
common_lore_index.coordinator._portable_worker_launch.run_worker_spec. Native
construction and observation pass through _worker_launch and
_protocol_execution. For self-sigkill the intended fault is usage_worker._prepare
self-SIGKILL, observed by the native reaper; cleanup belongs to ManagedProcess
and _run_protocol_worker readers. For parent interruption the intended fault
is the test's third _InterruptingEvent.is_set call in the post-job-start loop;
termination and cleanup belong to _usage_interrupt.interrupt_cleanup and the
owned ManagedProcess.kill_tree group SIGKILL.

Select exact node ID, test-owner hash, command/case, active invocation and
source commitment before launch. Bind the A launch ID to the real native PID.
Choose no child measurement before this exact A launch; never issue or revoke
an M token. No A bootstrap role or incomplete registered-receipt exception is
added. Interpreter/path/argument/probe validation holds even without coverage.
All A data, including parent hits, stay outside M.

The self-kill checkpoint is an unbuffered owned stderr line:
REPOMAP_ABRUPT_CHECKPOINT pre_hello <pid>. Require exact native PID, an
untruncated result and the line within4096 retained bytes. Block writes its
private integer PID witness after creating its fixed descendant and before
hello. The parent's first event check requires hello, so this checkpoint
precedes interruption without a scheduling assumption. It does not prove job
body execution. Preserve the original KeyboardInterrupt. Receive real native
settlement even when there is no result. A recording fault omits the record
and attaches a bounded note; aggregation then fails for the missing record.
Wrong identity, status, witness or unproved cleanup fails closed.

## Verification and publication limits

Prove native refusal/order/failure cleanup, exact command/probe admission,
M observer registration, all seven real process cases, abrupt declarations,
source/owner identity, missing records and unchanged receipt rejection with
exact scoped unit and containerized integration selectors without coverage.
No complete local suite or local Python coverage is authorized. Adapter doubles
are behavioral proof, not complete M/A qualification. Preserve strict clean
enrollment,400-line ceilings and all debt; permit only necessary private
helper extraction with lineage. No dependency, lockfile or image addition.

CI132 started zero application candidates. Actual cumulative starts remain42
and cap43 is unchanged. Expire its unstarted reservation and never reuse its
nonce. After fresh context/grant binding, scoped proof, static/privacy/history
checks and independent dynamic_default review, permit one ordinary staging
push for CI133 attempt1. Native Rust/wheel caps advance12/28 to13/30 for the
same two hash-bound wheels. No retry, second push, CI134, extra local/native/
SDK/application build, main/tag/release or history rewrite is authorized.

Hard unit85/85 and integration80/80 floors, desired87/82 margins and the full
maintained-source denominator remain unchanged. No guarantee of recovery of
the missing59 integration branches is made. Parent-interrupt and sigkill-only
arcs are not M coverage forecasts. Hosted CI owns measured qualification; a
failed floor is EXECUTED_FAIL and requires fresh corrective disposition.
Other native/image/installed/P3/release holds remain separate.

## Alternatives, rollback and consequences

Keyword-only forwarding still violates factory ownership. Factory exemptions,
skips, dynamic A classification, relaxed receipts and denominator changes
were rejected. Holding current runner policy was the operator's alternative.
The selected approach preserves real native ownership and closed accounting
at the cost of private observation and exact A evidence complexity.

Retain source and receipt preimages. Roll back observation, helper admission,
witness changes and the two declarations together; hold publication rather
than silently discarding measurement. The independent cycle/reader/Debian
repairs remain separately owned. Final source proof and hosted acceptance
are not conferred by this accepted implementation decision.
