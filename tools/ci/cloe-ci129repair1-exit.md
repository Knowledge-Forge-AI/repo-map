# CI129 Remediation and CI130 Publication Exit

Phase: `REPOMAP-CLOE-CI129REPAIR1`.

CI129 executed and failed for its published source. Its unit lane had 17
failures; integration had four failures and missed the independent 80% branch
floor by 38 branches. Unit branches passed 85%, below the desired 87% margin.
The system scenarios, native component checks and remaining lanes passed;
those component results do not qualify the failed whole candidate.

## Remediation

Server retention imports its POSIX lock capability only on Server use. Missing
capability refuses before lock creation. Explicit Local directory synchronization
continues through the Local layout guard without creating a Server lock, including
when the layout is refused. Default Server writes keep their private lock.

Borrowed publication descriptors are copied by the test publisher before their
spools close. Historical Local cleanup fixtures remain historical records;
current Server fixtures use private namespaces. CLI tests require the now-supported
native PostgreSQL context path. Cancellation before publication reports
`not_started`. The host-proof fixture preserves the candidate's exact JSON bytes.

New real integration cases cover corrupted referenced bundle bytes, a cooperating
process holding the Server retention lock, SQLite refusal by the Server recovery
CLI, PostgreSQL statement exhaustion and a native empty-node result. Refused
retained settlement preserves metadata and database run counts.

## Scoped verification

All 21 original failures were reproduced before correction. The corrected feature
cohort passed 105 unit cases and all four original integration cases. Four added
integration cases also passed. Commands use `tools/run_tests.py --suite unit|int
--no-coverage --jobs 1 -- <selectors>`; PostgreSQL and SQLite integration run inside
the existing disposable container sandbox.

Unit owners under `src/test/unit/python/repomap_kg/`:

- `ops/multi_source_refresh_guard.unit.test.py`
- `ops/sqlite_local_cleanup.unit.test.py`
- `ops/sqlite_local_reconcile.unit.test.py`
- `ops/sqlite_local_retention_layout.unit.test.py`
- `storage/sqlite_local_locking.unit.test.py`
- `ops/retained_attempt_locking.unit.test.py`
- `ops/portable_refresh_outcome_custody.unit.test.py`
- `retrieval/context_assembly.unit.test.py::test_unsupported_modes_and_postgresql_refusal_need_no_storage`

Additional unit owner:
`src/test/unit/python/tools/ci/d12_system_proof_host.unit.test.py`.

Integration selectors under `src/test/int/python/repomap_kg/`:

- `cli/cloe_config_migration.int.test.py::test_cli_import_defers_fcntl_and_migration_refuses_before_home_writes`
- `ops/first_use_server.int.test.py::test_first_use_server_context_and_native_fts_lifecycle`
- `ops/resource_view_server.int.test.py::test_server_sigint_is_sent_only_to_owned_child_after_post_ack_byte`
- `retrieval/context_cli.int.test.py::test_cli_context_select_and_pack_over_sqlite_and_postgres_homes`
- `ops/server_retained_attempt_recovery.int.test.py::test_real_corrupt_referenced_bundle_is_held_without_metadata_or_new_run`
- `ops/server_retained_attempt_recovery.int.test.py::test_real_retention_lock_busy_holds_metadata_and_run_count_steady`
- `ops/server_retained_attempt_recovery.int.test.py::test_cli_refuses_sqlite_home_before_server_recovery`
- `retrieval/context_postgres_expansion.int.test.py::test_postgres_statement_cap_and_native_empty_node_are_closed_packets`

Final campaign binding requires the five tests in
`src/test/unit/python/tools/ci/d12_system_grant.unit.test.py`, a fresh execution
of the host-proof unit owner, and these three exact integration nodes in
`src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py`:

- `test_system_hold_proof_capture_and_child_secure_writer`
- `test_sandbox_dispatch_blocks_system_suite_without_valid_proof`
- `test_cross_process_flock_and_o_excl_race_and_execute_system_run`

Static enforcement, source topology, file length, public export, changed-source
compilation, whitespace, privacy and suppression checks remain required on the
final source. Final counts and receipts belong to the exact commit report.

## Publication boundary

Hosted capacity is `AVAILABLE`. The current manual retry request permits one
ordinary staging publication through the existing draft pull request, selecting
CI130 attempt 1 after final proof and independent `dynamic_default` review.
CI129 consumed application start 40, native AMD command 9 and wheel transfers 22;
the fresh ceilings are 41, 10 and 24 respectively. CI129's spent authority remains
denied. No automatic retry, second push, main promotion or release is authorized.

Complete local unit, integration, smoke, staging, system and combined suites are
intentionally unselected. Local coverage, new application or SDK builds, native
parser qualification and acquisitions are unselected. Hosted CI owns complete
qualification and the desired 87% unit / 82% integration branch margins. No
threshold, denominator, exclusion, test policy or debt ceiling changes here.

Remote publication and complete CI130 results remain pending until their exact
commit-bound receipts exist. Local scoped success is source evidence only.
