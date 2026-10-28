# REPOMAP-PRODUCT6-NAVIGATION47-AMDPROOF1: native Python 3.12.16 component diagnostic

This source checkpoint implements [ADR 0102](../../docs/adr/2026/10/0102-native-python31216-component-diagnostic.md).
It records reviewed source and proportional local ARM proof. Native AMD and
hosted results remain pending; the full image candidate is NOT ACCEPTED.

## Source scope

- `tools/d12_native_python_observer.py` runs one network-less container on the
  exact raw Python config. It uses its own create, readback, cleanup and verify
  sequence, with run-boundary projections and ledger and Engine readback. The
  `steps.python31216_component` record is installed before execution. It is
  `observed` only after verified cleanup and a zero operation delta. If create
  fails after ledgering and the owner's own rollback already removed the
  container, the sole new ledger record is closed as removed. Otherwise it is
  cleaned up exactly. An uncaught inner failure leaves one redacted
  `inner_error` record; stderr is kept only as a byte count and SHA-256.
- `src/test/support/python/repomap_test_support/d12_native_python_proof.py` holds
  the pure validators. They cover the public metadata envelope (SHA-256
  `9781988ca058dcee40e7818be04843aedfdaec43fd5ab5fb1816fdb4a7fd2ce1`), the
  index, platform manifest, config and rootfs. They also verify observed image
  attributes, the selected override, the inner probe and the raw and trimmed
  payload facts.
- `tools/d12_dependency_preflight.py` calls the observer once in E1 exploration,
  right after native engine facts and before trust and closure. The legacy chain
  keeps its stage refusal prefixes, its report and sealer, and its qualification
  semantics. A component failure never adds an E1 refusal. Only the current
  exploration admission runs the hook; build and system admissions do not.
- The native job and its canonical fragment add one literal
  `--smoke-image-reference sha256:3a1b98be05abc7ac60c8712a943688620a602c3e0e6bfbc567afbeabe2085b28`.
  The command contract now refuses unknown, abbreviated, duplicate, equal-form
  and foreign pin inputs. Everything else stays the same: one runner, its node,
  variable expansion, triggers, actions, SDK and timeout.
- `d12_native_python_proof.int.test.py::test_native_python31216_component` is
  a local native ARM proof of the same observer. On a non-ARM daemon it records
  the ARM refusal before any image access, as a non-qualification record.

## Observed local verification

The affected 17-owner unit cohort passed 444 tests with 39 existing skips.
After a fixture-only typing correction, its exact observer owner passed all
34 tests again. The native ARM integration node passed, and all nine static
checks passed, including the 13 changed Python owners, inventory enforcement,
lineage, historical authorities, candidate identity, retained ratchets,
type ownership and CI topology. No debt or coverage ceiling changed.

The parent separately validated the actual ARM record against the current
payload source SHA, exact OCI hierarchy, native machine, 77 retained imports,
sole frozen Tk removal, survivor bytes/modes, fresh linkage and library owners.
Probe cleanup, zero operation delta and full host resource identity parity
passed. Cached SDK only; no application/SDK build or dependency-runtime
materialization. Five unchanged canonical harness setup pulls are accounted
separately from zero inner pull counts. Canonical Go prerequisites ran.

Earlier failures are retained: the intended missing-pin RED, four new test
expectation failures, a duplicate module-name mypy refusal and two fixture
type findings. Corrections changed the test expectations, canonical observer
import and fixture field typing; no gate was weakened. The parent inspected
these narrow corrections without a second independent dispatcher review.
Both sequential claude_only design/implementation dispatchers closed normally.

Exact unit selectors used tools/run_tests.py --suite unit --no-coverage --jobs 1 --:

- `src/test/unit/python/repomap_test_support/d12_native_python_proof.unit.test.py`
- `src/test/unit/python/tools/d12_native_python_observer.unit.test.py`
- `src/test/unit/python/tools/ci/d12_native_python_job.unit.test.py`
- `src/test/unit/python/tools/d12_inner_preflight.unit.test.py`
- `src/test/unit/python/tools/d12_owner_exploration.unit.test.py`
- `src/test/unit/python/tools/d12_exploration_admission.unit.test.py`
- `src/test/unit/python/tools/ci/d12_hosted_admission.unit.test.py`
- `src/test/unit/python/tools/ci/d12_hosted_evidence.unit.test.py`
- `src/test/unit/python/tools/ci/d12_hosted_qualification.unit.test.py`
- `src/test/unit/python/tools/ci/d12_hosted_reports.unit.test.py`
- `src/test/unit/python/tools/ci/qualification_native_contracts.unit.test.py`
- `src/test/unit/python/tools/ci/qualification_command_contracts.unit.test.py`
- `src/test/unit/python/tools/ci/ci_topology.unit.test.py`
- `src/test/unit/python/tools/ci/pipe0_topology_contract.unit.test.py`
- `src/test/unit/python/tools/ci/pipe0_topology_gates.unit.test.py`
- `src/test/unit/python/tools/d12_builder_headers.unit.test.py`
- `src/test/unit/python/repomap_test_support/d12_python31216.unit.test.py`

The later 34-test confirmation selected only
`src/test/unit/python/tools/d12_native_python_observer.unit.test.py`.
The exact integration command was:

```text
tools/run_tests.py --suite int --no-coverage --jobs 1 --pg-container-port 55433 --smoke-image-reference sha256:7d0134fc196a9daa289acd038dd1c95b6873cacfaa4d6ea97c51501e0af515a3 -- src/test/int/python/repomap_kg/runtime/d12_native_python_proof.int.test.py::test_native_python31216_component -s
```

Complete local unit, integration, smoke, staging, system and combined suites,
Python coverage and compileall were intentionally unselected. No complete-suite
override exists. Local scoped results do not establish hosted coverage or the
82% integration aim. The retained 143162-byte ARM fixture is test-only data.

Hosted state is AVAILABLE. One staging publication and its automatic campaign
are authorized and pending at this commit. The single native AMD component
has not yet been observed; inspect the campaign's sealed report separately
from the overall job or workflow conclusion. Existing system qualification
may remain red. No application build, rerun, main promotion or tag is granted.

## Held

The AMD 3.12.16 default baseline stays `None` and is not enrolled. Image
acceptance, P3, application builds (zero), the whole preflight, default
enrollment, D15, main promotion and tags all remain held and separate. A
component observation is diagnostic only. It is never counted as image or
dependency-runtime qualification.
