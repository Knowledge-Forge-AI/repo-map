# REPOMAP-CLOE-MIGRATION1 Exit

Status: local implementation checkpoint complete after independent dispatcher
review, parent corrections, fresh scoped proof and a final independent source
review. Hosted candidate accepted: false (NOT ACCEPTED for publication or
promotion qualification). Hosted result: NOT_REQUESTED_CONSERVATION. CI93
remains evidence only for its own candidate; this checkpoint is retained for
the next batched roadmap milestone.

ADR0114 adds explicit, confirmed `ops config-migration-apply`, `-rollback` and
`-finalize` commands and the matching `repomap_kg.ops.config_migration` API.
They convert one explicit, owned, private legacy home's configuration filenames
to CLOE. The commands require `--repo-map-home`; without `--yes` they are dry
runs. Every read is a bounded, non-following descriptor read. The same bytes are
hashed, parsed, merged and backed up, without backend builders, a driver,
source roots or databases.

Publication hard-links the CLOE name and then unlinks the legacy name, never
replacing. It is journaled and each step is fsynced. The owned dual-link state
is explicit, and every intermediate state is classified from fresh observations
before any action. Rollback restores exact names, bytes and modes. Finalize
deletes the retained private backups and ends rollback. Drift, edits, foreign
names and residue refuse without clobbering, and the evidence is retained.

`local setup` refuses while a migration directory exists. The planner's v1
schema is unchanged. `apply_supported: false` now means a plan is not apply
authority, and its text was corrected. No multi-file atomicity or exclusion of
uncooperative writers is claimed. The platform is limited to Linux and macOS.

Proof (tools/run_tests.py, --no-coverage, --jobs 1, exact selectors, no complete
suite, no coverage, no application or SDK build):

- unit: 231 passed. Two earlier same-selector attempts ended 229 passed/2
  failed, then 230 passed/1 failed. The retained-projection owner needed this
  phase's admission appended (corrected). An MCP stdio regression timed out
  only under the scratch runner, where its child inherited the shell's stdin.
  It passed in isolation on the candidate and on unchanged HEAD, and in a full
  ad hoc candidate run. With stdin set to /dev/null it passed. No product code
  changed for it.
- int: 39 passed in the cached disposable sandbox, with exact host resource
  sets preserved.

Closeout corrections after the independent work review:

- Persisted identities no longer depend on `st_dev`, which can change across
  a reboot. The journal binds the home inode. Recorded inodes are matched on
  the opened home's current device, and content proofs are unchanged.
- An embedded NUL in the home path is now a `repo-map-home-unsafe` refusal,
  not an exception.
- A created but unbound operation directory is reported as retained.
- ADR0114 now lists `EINVAL` and the `config-migration-io-error` fallback for
  the link probe, names `listdir`, and documents dry-run probe contention.

Same-selector reruns on the corrected candidate:

- unit: 235 passed, including 4 new cases;
- int: 39 passed, with host resource sets preserved;
- the sealed static owner passed with zero cohort regressions;
- the publication checks passed.

Parent acceptance correction:

- Four focused unit regressions confirmed that unjournaled restore scratch
  could be discarded before a missing or corrupt required backup was refused.
  Dry runs also advertised that unrecoverable state as ready to roll back.
- Rollback now proves the required backup during whole-operation preflight,
  before any journal or cleanup write. Refusal preserves the scratch and all
  configuration entries. Four unit and eight real CLI cases cover dry-run and
  confirmed behavior, both backup failures and both backends.
- Fresh proof on that correction: 239 scoped unit cases and 47 containerized
  integration cases passed, with source and host resource sets preserved.
  Final sealed static enforcement also passed with zero cohort regressions.
- The final independent source review accepted the correction and the
  closeout fixes. Parent acceptance is limited to this local implementation
  checkpoint and its scoped proof.
- Deferred, non-blocking review observation: pathologically nested TOML may
  raise a recursion error during preflight rather than return a structured
  refusal. No migration writes have begun at that point. General parser
  resource-limit and error-normalization hardening remains separate.

Unit selectors:

- src/test/unit/python/repomap_kg/ops/cloe_config_migration.unit.test.py
- src/test/unit/python/repomap_kg/ops/cloe_config_recovery.unit.test.py
- src/test/unit/python/repomap_kg/ops/cloe_config.unit.test.py
- src/test/unit/python/repomap_kg/ops/config_redaction.unit.test.py
- src/test/unit/python/repomap_kg/runtime/cloe_setup.unit.test.py
- src/test/unit/python/repomap_kg/runtime/local_runtime.unit.test.py
- src/test/unit/python/repomap_kg/runtime/local_home_authority.unit.test.py
- src/test/unit/python/repomap_kg/cli/package_structure.unit.test.py
- src/test/unit/python/repomap_kg/cli/sqlite_local_import_boundary.unit.test.py
- src/test/unit/python/tools/ci/retained_python_projection.unit.test.py

Integration selectors:

- src/test/int/python/repomap_kg/cli/cloe_config_migration.int.test.py
- src/test/int/python/repomap_kg/cli/cloe_config.int.test.py
- src/test/int/python/repomap_kg/cli/cloe_runtime.int.test.py
- src/test/int/python/repomap_kg/cli/local_runtime.int.test.py::CliLocalRuntimeIntegrationTests::test_local_setup_creates_runtime_files_under_temp_repo_map_home
- src/test/int/python/repomap_kg/cli/local_runtime.int.test.py::CliLocalRuntimeIntegrationTests::test_local_setup_dry_run_does_not_create_repo_map_home
- src/test/int/python/repomap_kg/cli/local_runtime.int.test.py::CliLocalRuntimeIntegrationTests::test_local_setup_reuses_existing_config_and_env_without_leaking_secret
- src/test/int/python/repomap_kg/cli/local_runtime.int.test.py::CliLocalRuntimeIntegrationTests::test_local_setup_table_output_is_redacted_and_local_only

Unit coverage includes the following:

- a crash injected at each of the 45 apply, 26 rollback and 13 finalize
  mutation boundaries, each followed by recovery;
- in-process OSError recovery;
- the partial-state matrix;
- edit, foreign-name and alias drift;
- revalidation races;
- post-link identity mismatch, which never unlinks the source;
- lock contention;
- journal tampering;
- a device-number change between apply and recovery;
- residue;
- directory-removal races;
- redaction.

Integration exercises the real CLI and API on synthetic Server and Local homes:
dry run, apply, config-check, rollback, reapply, finalize and the no-op
repeats. It also covers a guarded driver-free process, source-root and
database tripwires, real dual-link recovery, edited-after-apply refusal, and
the setup guard.

Four new product owners and three test owners are admitted through one exact
forward-only scope record. No baselines, thresholds or exclusions were changed.
The runtime local.py stays at 400 lines. Package, import, executable and
default-home names, wire and schema identities, dependencies, D12 grants, the
protected private checkout's final state and public main are unchanged. No live home was
touched.
