# NAVIGATION47 Trixie glibc disposition checkpoint

Phase: `REPOMAP-PRODUCT6-NAVIGATION47-CI73TRIXIE1`.
Source maintenance proof retained; full candidate **NOT ACCEPTED**; publication held.

[ADR 0101](../../docs/adr/2026/10/0101-trixie-glibc-risk-disposition.md)
implements the operator's instruction to keep Debian Trixie and accept the
glibc risk. The finite record in `d12_glibc_risk_disposition.json` accepts
21 enumerated findings as unresolved under Samuel Leighton Lair, bound to
glibc `2.41-12+deb13u4` and the approved PostgreSQL/Python indexes. Scores and
affected/unknown source claims remain visible. Changed, additional or missing
records and changed component identities refuse.

The stdlib-only assessor checks the exact record SHA-256, native platform,
actual image config ID, both libc package rows, loaded libc file/ownership,
package byte consistency and notice hash. D12 post-build evidence retains the
result for both application and service images. A missing service image ID
refuses; direct callers supply the observed ID. No image or other component
is accepted by this disposition. Dynamic Psycopg 3.3.6 and the existing
application candidate's system libpq 18.6 selection are unchanged.

## Observed verification

The corrected source passed 117 scoped unit tests, both native ARM component
integration nodes, and all nine static checks. Three sequential `claude_only`
dispatchers completed normally with independent review; none was interrupted.
The parent checked raw observations, tested source identities, exact probe
cleanup, terminal operation counters and host resource identity parity.

The glibc integration node accepted the real native ARM observation and
refused one changed-version input. The Python node again observed 77 imports,
removed only the exact frozen `_tkinter` file, preserved surviving bytes and
modes, and retained no unresolved libraries. Both nodes used network-less,
run-owned probe containers. No application/SDK build or dependency-runtime
materialization occurred. The canonical harness's five frozen setup pulls per
integration invocation are separately counted; zero inner pull counts do not
mean zero harness acquisition. Unchanged canonical Go prerequisites ran.

An earlier integration execution passed both tests but failed the canonical
cleanup gate after a transient unattributed host-container replacement. Its
failure is retained. No foreign container was removed. One guarded scoped
repeat required the original host baseline twice before reservation and then
passed with complete host parity. The first static execution's four owned
type errors were corrected; its failure is also retained. Debt and coverage
ceilings are unchanged.

Exact unit owners, through `tools/run_tests.py --suite unit --no-coverage --jobs 1 --`:

- `src/test/unit/python/tools/system/d12_glibc_risk.unit.test.py`
- `src/test/unit/python/tools/system/d12_system_evidence.unit.test.py`
- `src/test/unit/python/repomap_test_support/d12_python31216.unit.test.py`

Exact integration nodes, through `tools/run_tests.py --suite int --no-coverage --jobs 1
--pg-container-port 55433 --smoke-image-reference
sha256:7d0134fc196a9daa289acd038dd1c95b6873cacfaa4d6ea97c51501e0af515a3 --`:

- `src/test/int/python/repomap_kg/runtime/d12_glibc_disposition.int.test.py::test_native_trixie_glibc_disposition`
- `src/test/int/python/repomap_kg/runtime/d12_python31216.int.test.py::test_python_31216_native_arm64_component_proof`

Both nodes explicitly verify ARM admission refusal on an AMD daemon before
image access and emit distinct refusal records. An ordinary pytest pass on
AMD therefore does not establish a positive component observation. Evidence
consumers must distinguish proof and refusal prefixes. The actual local
executions above exercised native ARM. Their per-probe operation delta must
be zero even when earlier prerequisites made the run-wide baseline nonzero.

Static verification covered source shape, candidate census/lineage,
historical authorities, candidate identity, retained ratchets, type ownership,
the nine changed non-product Python owners, CI topology and full inventory
enforcement. The cached SDK ran read-only without network, build, pull or
installation; its exact owned container was removed and host parity passed.

## Remaining boundaries

Complete local unit, integration, smoke, staging, system and combined suites,
Python coverage and compileall were intentionally unselected. No complete-suite
override exists. Scoped results do not establish hosted coverage or its 82%
integration cushion.

Hosted state remains AVAILABLE. No remote mutation or trigger occurred in
this phase. CI73 remains the latest public failure: admission rejected a grant
bound to CI72 before any application build. The four historical application
starts remain spent; that grant is not renumbered or rearmed.

Native AMD Python 3.12.16 payload proof, final candidate byte/licence/
provenance evidence and non-glibc P3 classifications/dispositions remain open.
The already owned incumbent comparison gap is unchanged. A future staging
publication needs a useful authorized native evidence route and any applicable
fresh build grant. Public main, release tags, production admission and live
deployment remain separate.
