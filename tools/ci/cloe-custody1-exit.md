# REPOMAP-CLOE-CUSTODY1 Exit

Status: local custody audit and existing-contract characterization checkpoint
accepted after scoped proof, static enforcement and independent review with its
wording correction resolved. W0 implementation is not complete.
Hosted candidate accepted: false (NOT ACCEPTED for hosted qualification or
promotion). Hosted execution: NOT_REQUESTED_CONSERVATION.

The [custody disposition](../../docs/specs/cloe-development-custody-v1.md)
preserves the protected development checkout and private-only material. It
keeps the public successor's runtime fixes, verifies moved D12 owners, and
names the private runner failure-evidence family as a required W0 follow-up.
It does not treat a passed public CI run as proof that private work was
incorporated. No namespace, package, default-home or live-data cutover occurs.

README and agent guidance now describe implemented SQLite Local and PostgreSQL,
with bounded host-native MCP acceptance. Managed Cloud remains a target.
Current roadmap prose records CI93 for its exact runtime-setup candidate.

Restored characterization:

- Invalid dependency variants must produce the native-job dependency error.
- Cross-job leakage must produce its specific diagnostic; an unrelated invalid
  runner cannot make the test pass.
- Retry loops refuse, while ordinary quoted/unquoted loop words remain valid
  arguments using the projected native runner command.
- The disposable Trixie restore proof requires a nonempty ICU collation version,
  then compares it with the actual version.

Verification through `tools/run_tests.py`, `--no-coverage --jobs 1`:

- unit: `src/test/unit/python/tools/ci/qualification_command_contracts.unit.test.py`
  — 105 passed;
- int: `src/test/int/python/repomap_kg/runtime/d9_extension_restore.int.test.py::test_d12_trixie_backup_restore_and_collation_refusals`
  — one exact case passed in the existing disposable sandbox;
- source preserved during both runs; host Docker resource sets preserved;
- zero application/SDK builds and zero new external base pulls;
- complete local unit/int/smoke/staging/system/combined runs and coverage were
  intentionally unselected; no complete-suite override was requested;
- sealed static enforcement passed with zero cohort regressions after removing
  one unused import introduced by the test repair; the same 105 unit cases
  passed again. No baseline, inventory, suppression or threshold was relaxed;
- the independent resulting-state review's evidence-wording correction is
  resolved. Final link/privacy and diff checks precede the local commit.

No production Python, runner policy, dependency, metadata, lock, threshold,
exclusion or build grant changed. README's corrected content changes the release
build context. The final publication candidate needs a fresh freeze and any
required new build allocation; spent grants remain spent.

Hosted state remains AVAILABLE under the operator's declaration. No remote
write, automatic lane, public CI trigger, main promotion or deployment occurred.
Complete hosted coverage, static/security and assembled-candidate qualification
remain pending for the eventual batched publication. CI93 qualifies only its
original candidate; local scoped proof does not replace those gates.
