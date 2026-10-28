# CI84 remediation and Debian stable slim policy Exit

Phase REPOMAP-PRODUCT6-NAVIGATION47-CI84REPAIR1. Accepted ADR0104
authorizes conditional qualification and one fifth native AMD application start.
ADR0105 records the operator's subsequent Debian responsibility policy.

Inherited Debian OS vulnerability findings, slim exclusions and existing
package-verification diagnostics are informational. RepoMap maintains current,
digest-pinned official Debian stable slim runtime suppliers. On 2026-10-28,
official metadata identified Debian 13.7 Trixie and the refreshed PostgreSQL
16.15/Python 3.12.16 images. The maintenance helper checks stable/slim provenance
and registry digests without running images. No vulnerability-free or complete
catalogue claim is made. Go and the unchanged SDK are build-only inputs.

The actual remediation replaces the unconditional system failure with conditional
qualification: complete candidate/base inventories, exact supplier bytes,
unchanged package/source/checksum provenance, dynamic Psycopg/libpq ABI,
PostgreSQL/PGDG findings, version tuple, notices, the archive round trip,
all five system scenarios, MCP readback and cleanup remain blocking. The
current empty closure is guarded before a build; a future nonempty closure
requires exact support. Historical diagnostic v1 records remain unchanged.
The new supplement is written before the SystemReport to avoid a hash cycle.

The host captures actual stopped-container archive member hashes before export,
retains a mode-0600 exclusive receipt beside the original proof outside the
sandbox, and verifies the exported bundle against both retained authorities.
Every main-system success requires those authorities. Committed source checks
cover transitive tracked code and refuse unknown Python. This does not claim
protection against a fully compromised canonical runner fabricating observations.
Archive/export/verification failures still perform exact outer cleanup and fail.

Pure validation/data helpers were separated from runtime orchestration imports;
old imports re-export the same contracts. Canonical retention enforcement is
complete with zero cohort regressions and unchanged debt ceilings. Muse source
and correction reviews reported no remaining blockers; the parent separately
verified actual tests, custody, source identity, immutable historical records
and the unchanged helper bodies. Reviewer limitations remain source-only.

## Scoped verification

All test commands use `tools/run_tests.py --suite unit|int --no-coverage
--jobs 1 --report-dir <owned-report-directory> -- <selectors>`.
The following cohorts overlap; their counts are not a unique aggregate.
Containerized integration adds `--pg-container-port 55433
--smoke-image-reference
sha256:ff710677e697054c516f12c53c92166f1aef075f21b2a593f4c615e522112b4e`.
The collector's earlier focused 41-test owner proof also passed; subsequent
real native ARM supplier probes exercised the current complete collector.

### qualification-unit9

Result: `93 passed in 2.37s`.

- `src/test/unit/python/tools/system/d12_debian_policy.unit.test.py`
- `src/test/unit/python/tools/system/d12_qualification.unit.test.py`
- `src/test/unit/python/tools/system/d12_system_evidence.unit.test.py`
- `src/test/unit/python/tools/system/d12_system_session.unit.test.py`
- `src/test/unit/python/tools/system/system_runner_entry.unit.test.py`
- `src/test/unit/python/tools/ci/gate_contract_main_system.unit.test.py`
- `src/test/unit/python/tools/test_sandbox_report_export.unit.test.py`
- `src/test/unit/python/tools/system/d12_qualification_orchestration.unit.test.py`
- `src/test/unit/python/tools/ci/debian_base_refresh.unit.test.py`
- `src/test/unit/python/tools/ci/gate_contract_isolation.unit.test.py`
- `src/test/unit/python/tools/test_sandbox_d12_proof.unit.test.py`

### refresh-bindings-unit3

Result: `380 passed, 16 skipped in 3.57s`.

- `src/test/unit/python/repomap_kg/runtime/d12_python31216.unit.test.py`
- `src/test/unit/python/repomap_kg/runtime/d12_release_manifest.unit.test.py`
- `src/test/unit/python/repomap_kg/runtime/arch7f_release_resources.unit.test.py`
- `src/test/unit/python/repomap_test_support/d9_trixie_image.unit.test.py`
- `src/test/unit/python/tools/d12_core_image_profile.unit.test.py`
- `src/test/unit/python/tools/d12_native_python_observer.unit.test.py`
- `src/test/unit/python/tools/d12_python_closure.unit.test.py`
- `src/test/unit/python/tools/d12_inner_preflight.unit.test.py`
- `src/test/unit/python/tools/ci/d12_hosted_evidence.unit.test.py`
- `src/test/unit/python/tools/ci/d12_hosted_qualification.unit.test.py`
- `src/test/unit/python/tools/ci/d12_hosted_reports.unit.test.py`
- `src/test/unit/python/tools/ci/d12_hosted_state.unit.test.py`
- `src/test/unit/python/tools/ci/d12_hosted_admission.unit.test.py`
- `src/test/unit/python/tools/ci/d12_native_python_job.unit.test.py`
- `src/test/unit/python/tools/ci/qualification_native_contracts.unit.test.py`
- `src/test/unit/python/tools/ci/pipe0_topology_contract.unit.test.py`
- `src/test/unit/python/tools/test_sandbox_hosted_adoption.unit.test.py`
- `src/test/unit/python/tools/ci/gate_contract.unit.test.py`

### admission-ci85-unit2

Result: `34 passed in 1.48s`.

- `src/test/unit/python/tools/ci/d12_system_grant.unit.test.py`
- `src/test/unit/python/tools/ci/d12_system_proof_host.unit.test.py`
- `src/test/unit/python/tools/system/d12_system_session.unit.test.py`
- `src/test/unit/python/tools/system/d12_qualification.unit.test.py`

### debian-refresh-int2

Result: `1 passed in 3.42s`.

- `src/test/int/python/repomap_kg/runtime/d12_glibc_disposition.int.test.py::test_native_trixie_glibc_disposition`

### refreshed-python-int1

Result: `1 passed in 2.87s`.

- `src/test/int/python/repomap_kg/runtime/d12_native_python_proof.int.test.py::test_native_python31216_component`

### admission-ci85-int1

Result: `3 passed in 0.35s`.

- `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_system_hold_proof_capture_and_child_secure_writer`
- `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_sandbox_dispatch_blocks_system_suite_without_valid_proof`
- `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_cross_process_flock_and_o_excl_race_and_execute_system_run`

The native suppliers produced complete JSON inventories of 856,977 and 927,172
bytes with 3,649 and 3,558 verification rows. A larger synthetic 4,000-row
bundle passed the real archive extraction and exported verifier under existing
1.5 MB part / 5 MB total limits. Native ARM proof is component evidence only;
AMD final-image compatibility remains pending hosted CI.

Static checks: pinned-environment canonical inventory enforcement, retained
product ratchet/type ownership, zero new direct findings, topology, global
file length, suppression inventory, public export, changed-source compilation
and diff checks passed. The old host Psycopg 3.2.12 diagnostic was invalid for
the pinned 3.3.6 static owner; the unchanged cached sealed environment supplied
the actual accepted check. No dependency installation or image build/pull was
needed for static verification.

Complete local unit, integration, smoke, staging, system and combined suites,
and Python coverage, were intentionally unselected; no complete-suite override
exists. Integration reused the cached SDK and normal five transient pinned
setup pulls per sandbox. No local application/SDK build or unmanaged operation
occurred; exact container cleanup and host resource identity parity passed.

## Hosted boundary

Capacity AVAILABLE. CI84 attempt1 is EXECUTED_FAIL: the system admission stopped
on a stale grant/candidate context before SDK/application work, while the other
eight jobs passed. Its unit line/branch coverage was 87.9666/87.5969%; staging
coverage was 90.1685/82.3417%, exceeding each hard gate by at least two points.
These are historical exact-attempt results, not qualification of this change.

CI85 attempt1 is the sole authorized next campaign on one ordinary staging
push to draft PR13. The real grant/candidate now bind the current frozen
695-file source context, before 57e2023913db899ca5b5c5d72a7662ae00c19833,
base 24d15650a2d4563d188acb8bbf34a0dabf8f3d65 and fresh reservation authority.
The four consumed starts remain retained; the fifth is reserved, not locally
executed. Spent CI69-72 values refuse. Maximum five total/AMD starts, attempt1
only, no sixth/retry, and at most one necessary unchanged hosted SDK
materialization. No new trigger/job, GateRequest/GateResult field, dependency,
coverage threshold, main promotion, release/tag or deployment was introduced.
Main remains public preview v0.0.3. New hosted results and the two-point coverage
target remain pending. Scoped proof does not substitute for hosted image acceptance.
