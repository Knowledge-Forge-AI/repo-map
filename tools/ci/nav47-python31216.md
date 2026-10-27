# NAVIGATION47 Python 3.12.16 Remediation Companion Note

Under [ADR 0100](../../docs/adr/2026/10/0100-exact-python-31216-remediation-and-native-proof-hold.md), RepoMap adopts the exact official `python:3.12-slim-trixie` Python `3.12.16` OCI hierarchy in local source:

- Multi-architecture index digest: `sha256:962f801b08c870ac2a51b72bf02dae38c9a4162319e5e882ec244e198188d54e`
- `linux/arm64` manifest digest: `sha256:0ced713d9b8336172d981d8f25f2422b6782bdad019fda4cb653c6ee187430de`
- `linux/arm64` config digest: `sha256:7d0134fc196a9daa289acd038dd1c95b6873cacfaa4d6ea97c51501e0af515a3`
- `linux/amd64` manifest digest: `sha256:6d2b0577e6d1632f077331de8e4780535f54839d163ded7abb4b7dd37b5d37ac`
- `linux/amd64` config digest: `sha256:3a1b98be05abc7ac60c8712a943688620a602c3e0e6bfbc567afbeabe2085b28`

## Fail-Closed Holds

1. **Historical 3.12.15 records preserved, not transferred**: `ARM64_BASELINE_IMPORTS`, `AMD64_BASELINE_IMPORTS` and `HISTORICAL_31215_PYTHON_PAYLOAD_EXCLUSIONS` keep their exact values and now live in `src/main/python/repomap_kg/runtime/release_manifest.py` beside the historical CI68 package record, whose values are unchanged. The standalone `python -I -B` payload contract `python_payload.py` holds only 3.12.16 identities, so no 3.12.15 or cross-architecture import set is reachable from it.
2. **ARM observed, AMD held**: `ARM64_31216_NATIVE_BASELINE_IMPORTS` is an independent literal of the 77 imports emitted by the native Python 3.12.16 component proof. The default map enrolls ARM only. `AMD64_31216_NATIVE_BASELINE_IMPORTS` remains `None`, and the AMD default refuses even with unchanged `_tkinter` bytes. Historical/ARM imports never establish a new native AMD baseline.
3. **Candidate manifest values and spent CI72 grant unchanged**: the CI68 `D12_CANDIDATE_PACKAGE_MANIFEST` (including its historical 3.12.15 `lib_dynload`), `tools/ci/d12_system_build_grant.json` and `tools/ci/d12_system_grant.py` keep their historical values. The 3.12.16 amd64 payload step refuses before any recipe use of that `lib_dynload`.

## Local ARM Component Proof (passed; runtime acceptance held)

`src/test/int/python/repomap_kg/runtime/d12_python31216.int.test.py` is a raw native `linux/arm64` component proof only:

- It refuses a non-ARM daemon before any image read or execution.
- It reads, but never pulls, the exact base that the canonical inner harness (`tools/test_sandbox_inner.py`) pulls once before pytest. Each harness pull is counted by the parent; the approved recovery increased the phase Python-pull cap from one to two. The manager reporting no pull does not mean the phase made zero pulls.
- Before running the image, it checks the retained ARM manifest bytes against `0ced…`, the manifest's config descriptor and the observed image `Id` against `7d01…`, and the observed `RootFS` diff IDs.
- It records the actual run-wide Docker boundary counts before and after the probe and refuses any build, materialization, pull or unmanaged operation.
- The in-container probe prints the raw `--no-exclusion` observation before any assertion, and the host prints it before cleanup or validation. Cleanup is read back from the ledger and the Engine.

The approved offline dependency-cache materialization and dynamic-Psycopg
qualification remain **unexecuted**. Route A permits offline materialization
only; the existing manager uses bridge networking with live APT/pip and no
retained wheelhouse mount. The unexpected online prerequisite below is not
accepted as that proof. No runtime, image, P3, licence, provenance, glibc or
native-AMD acceptance is claimed.

The first scoped execution passed all three SDK payload contract nodes, but the
native component refused before image execution: the canonical runner had
already materialized one dependency runtime before pytest. That prerequisite
uses the online manager path and did not satisfy Route A's offline condition.
It is retained as an execution deviation; neither cache qualification nor
native payload evidence is accepted. The cache-materialization allowance and
the one Python pull remain spent. No application or SDK build occurred.

The operator approved one bounded recovery using the existing
`--smoke-image-reference` option and exact ARM config ID above. The second
integration execution selected only the failed native node and passed. All
nine terminal build/pull counters were zero; no further dependency cache, SDK
or application image was assembled. Host identity parity and source custody
passed. Both integration executions and Python pulls are spent; no further
retry is authorized.

The actual Python 3.12.16 ARM observation retained 77
successful fresh `LD_BIND_NOW=1` imports. Exactly the frozen `_tkinter` file was
removed: entry count 1721 to 1720,
with no surviving digest/mode changes, no unresolved retained dependencies and
complete shared-library owners. The module-list SHA-256 is
`049267074bee42d4449e7a3ed866076d6529b44106e0e3676f41a5e1da277a1b`.
The source adopts that observed ARM tuple literally. AMD remains unobserved
and refused. The retained manifest/config and observed Engine ID/rootfs were
matched; no new registry-manifest or compressed-blob observation is claimed.
The final combined unit execution passed **292 tests in 8.69s** with `--no-coverage`. The final scoped static execution passed all ten checks, including source profile, historical authority, candidate identity, retained ratchet, type ownership, non-product profile, CI topology, full inventory and native-bind shell checks. Its exact owned container was removed and host resource identities matched; it performed no builds, pulls or installs. These results do not discharge the held offline-cache or image/P3 gates. Independent resulting-state review is required before accepting the partial source checkpoint.

## Executed Scoped Selectors

- Unit (combined affected-owner GREEN): 18 owners — the existing 14, the two new `d12_python31216.unit.test.py` owners under runtime and test support, and `tools/ci/d12_hosted_admission.unit.test.py` plus `tools/ci/d12_hosted_qualification.unit.test.py` under the unit test root because they import the changed hosted fixtures.
- Integration recovery: only `src/test/int/python/repomap_kg/runtime/d12_python31216.int.test.py::test_python_31216_native_arm64_component_proof`, with the exact image override above. The three unchanged SDK payload contract nodes passed in the first execution and are not repeated. Exclude `d12_dynamic_linkage.int.test.py`, `d12_core_image_refresh.int.test.py`, `d12_system_admission.int.test.py` and every owner that materializes a runtime cache or builds an application image. The canonical harness still performs its five frozen prerequisite pulls and existing Go helper compile; the extra-pull decision names those explicitly.

The combined unit execution first found two synthetic fixture defects (290 passed, two failed). The current-recipe refusal is now tested before exact historical recipe replay; the positive AMD simulation uses temporary, restored test-only enrollment. Six unchanged session fixture functions moved into `src/test/unit/python/tools/system/d12_system_session_fixtures.py`; all 18 selectors remain unchanged. The first scoped static execution found long lines and three unused imports. Their corrections preserve executable ASTs except those unused imports, and the second execution passed. No coverage or debt ceiling changed.

Fresh allocations are now spent: unit 3/3 (including RED), integration 2/2, static 2/2, Python pull 2/2 and dependency materialization 1/1 (offline condition unsatisfied). SDK/application builds, complete suites, Python coverage and remote mutations remain zero. The original four application starts and spent CI72 grant remain unchanged. Publication stays held.

## Subsequent component composition

The observations and allocations above remain historical receipts. A separately
approved online diagnostic subsequently passed both scoped dynamic-Psycopg
tests on the native ARM dependency runtime, observing system libpq 17.11.
This is separate from the application candidate's PGDG libpq 18.6 selection;
neither observation qualifies an application image.

The ordinary integration population also collects the raw component owners.
On native AMD they now verify and explicitly report refusal of ARM admission
before any image access. That result supplies no native AMD payload or image
qualification. On ARM the owner reads the exact passive raw base regardless
of the dependency runtime selected by the harness. Both observed run-wide
Docker projections remain visible, and the probe must add zero operations.
Prior prerequisite work cannot be relabelled as this probe's work. No marker,
deselection rule, skip, coverage or debt ceiling changed.
