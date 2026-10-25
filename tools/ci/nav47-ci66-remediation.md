# REPOMAP-PRODUCT6-NAVIGATION47-CI66REPAIR1: CI66 remediation

## Observed hosted result

[CI66](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/40185389219)
was the automatic `pull_request` campaign for public `staging` commit
`8937ba8bb0afd92e8b4067d4399160b7cdcc4e8d` on PR #13 (`staging` to `main`).
Its test merge was `36e7b825720425b75142b5c1883da243771b7a3e`.

- `unit-tests` passed: 13,717 passed and 40 skipped. Coverage was 57,060/60,921
  statements and 17,403/19,864 branches (93.66% and 87.61%).
- `staging-integration-gate` passed: 1,808 passed and 12 skipped. Measured M and
  abrupt-behavior A both passed, including cleanup. Coverage was 54,897/60,921
  statements and 16,335/19,864 branches (90.11% and 82.23%).
- `pre-review-static` ran its aggregate: 18 checks passed; `actionlint` and
  `python-retention-inventory` failed.
- `source-and-export-policy`, both CodeQL jobs and the SBOM scan passed.
- `d12-native-amd64` retained valid sealed negative evidence: no seal or
  validation errors, but the native payload refused the sole unresolved
  `_tkinter` module requiring `libtcl8.6.so` and `libtk8.6.so`.
- `main-system-gate` refused at its D12 prerequisites before any system SDK or
  application build. No runtime, platform or image admission follows.

These coverage measurements exceed the 87/87 unit and 82/82 integration aims.
They describe CI66; the successor requires its own hosted qualification.

## Corrections

### Native workflow quoting

ShellCheck reported SC1083 through `actionlint` for unquoted `HEAD^{tree}` in
the native bind step. The workflow and its maintained native job fragment now
quote the literal Git selector. The argument's value and tree-peeling behavior
are unchanged, as are triggers, job ordering, pins and build/admission limits.
No suppression is added.

### Portable SQL helper annotations

Two integration helpers annotated their query parameter with Psycopg `Query`.
That alias includes `Template`; the selected `Connection.execute` overload
accepts `QueryNoTemplate`. The helpers now use the latter existing alias,
matching their actual calls without casts or suppressions. SQL, parameters,
authority/fencing checks and transactional behavior are preserved.

The exact pinned alias definitions are in
[Psycopg 3.3.6 abc.py](https://github.com/psycopg/psycopg/blob/3.3.6/psycopg/psycopg/abc.py).
No dependency version or lock changes are included.

### Test-owner dependency closure

Three maintained test owners contained undeclared dynamic-loading operations:
the D12 state unit owner, C-distribution integration owner and Python payload
integration owner. They now use static module references where possible.
Psycopg still initializes before `psycopg_c`; real C implementation, version,
origin and refusal checks remain.

The payload integration owner still inspects two actual SDK shared extensions,
native identities, real ELF dependencies and package ownership. Its `__main__`
refusal runs in an ordinary fresh `python -B -m` child through the existing
registered `cli_module` launcher. Existing unmeasured
isolation remains confined to the exact stdlib `-I -B -c` probes. The ordinary
product child retains inherited runner coverage capabilities; local execution
uses `--no-coverage`, so its hosted measurement remains pending.

### Closed resolver proof revision

The active `v003.pr26.staging.contract1.fix1.11` record pinned an older
`resource_test_images.py` digest. Its owner and test still matched, but this
target drift invalidated the declaration and blocked dependent cohorts.

The replacement `v004.pr26.staging.contract1.fix1.11` is appended with the old
history retained as an exact prefix. It binds current owner/test evidence and
the current target digest. The resolver's executable AST, guarded recipe,
closed domain and target set remain unchanged. Owner documentation identifies
the refreshed custody; unit proof checks current resource-target source/code
identity and refuses drift or foreign origin without executing Docker/builds.

The 32 reported regressions were failed cohorts, including dependent and atomic
group cascades. They are not 32 independent source errors or unused definitions.
No recipe, validator, cohort membership, scope authority or debt ceiling is
relaxed to discharge them.

## Verification and limits

A read-only local diagnostic initially omitted the hosted product `MYPYPATH`
and caused product type-check tool failures. That invalid-environment result
was retained. The corrected diagnostic reproduced the hosted 32-cohort failure
with product checks passing. Neither diagnostic ran tests, built images or
changed source. Pure AST inspection identified the stale target declaration.

Exact canonical unit and containerized integration selections use
`--no-coverage`. Their actual commands, attempts and results are recorded in
the phase commit. Local attempts were:

- Unit 1 passed 141 tests, with 16 public-projection skips, before the later
  integration-test corrections. Unit 2 passed the same population on the final
  executable candidate.
- Integration 1 passed 12 and failed
  `test_real_walk_special_entries_and_main_guard_refusals`: the new child
  returned exit 1 without JSON, causing an indexing error. The test then adopted
  the existing registered launcher with an explicit project source path.
- Integration 2 passed 12 and failed that same test's reason assertion: it
  still expected the in-process fake-machine text. The assertion was corrected
  to compare the fresh child's actual native architecture against the requested
  unsupported architecture. Integration 3 passed all 13 tests.
- Static 1 passed all nine scoped checks. The two failed integration attempts
  remain failures in the retained history; neither is relabeled as passing.

These correcting changes have distinct source fingerprints in the raw
receipts. Local static verification includes canonical full inventory
enforcement and ShellCheck of the exact reported native bind script. It does
not constitute a complete pre-review or `actionlint` campaign. Hosted CI owns
the successor's complete populations and coverage.

The hard 85/85 unit and 80/80 integration gates, and 87/87 and 82/82 aims, stay
unchanged. Complete local suites and local Python coverage are unselected.
Product code, dependencies, frozen D12 source/record, SDK/application recipes
and the ARM `_tkinter` exclusion are unchanged. Dynamic C Psycopg 3.3.6 with
system libpq remains required. AMD payload disposition, P3/incumbent comparison
and application/system admission remain held. The application ledger stays at
`maximum_total: 0`, with zero attempts used; the original two-total,
one-per-platform, no-retry ceiling remains unchanged.
