# ADR 0094: Exact native AMD Python payload exclusion

## Status

Accepted by the parent for this bounded source/proof slice under ADR 0092 D4 item 3, after separate independent design review. Source implementation and one reviewed ordinary staging successor with the existing automatic native campaign are admitted. No runtime or image acceptance follows.

## Date

2026-10-25

## Context

CI67 run40197391515 at6792630643684a893417f457dedc2117a754754a passed static,
unit and staging integration gates. Native AMD E-f refused because no frozen
AMD payload exclusion exists. The authentic sealed negative report has zero
seal errors and validation violations. System qualification remains held at
D12 prerequisites before SDK/application build. ADR0092 explicitly reserves a
separate evidence-backed parent admission after review of this artifact.

The actual native x86_64 baseline, independently agreeing with CI66 for the
target bytes and successful import set, has1721 entries,82 ELFs,78 lib-dynload
modules and77 successful fresh-process imports. Only _tkinter fails. Its exact
missing pair is libtcl8.6.so/libtk8.6.so. No retained-payload success is inferred
from this negative baseline or from ARM observations.

## Accepted decision

Extend only the existing frozen PayloadExclusion data to AMD. Preserve every
validation, classification, native guard, exact unlink and retained-payload
verification function byte-for-byte. Preserve the existing ARM entry and import
tuple exactly. Add a separate AMD77 tuple derived from sealed AMD imports,
even though those names independently coincide with ARM. No alias claiming
cross-platform evidence. Bind:

- Python index sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704.
- AMD manifest sha256:e8a38829209aea82774882e5157e1f7c3e8c8393ff53a697b3580896e57f345c.
- AMD config sha256:a33c10a97f11005523814c6eee013986119fe41f3122f444518117536675c8e1.
- Exact regular /usr/local/lib/python3.12/lib-dynload/_tkinter.cpython-312-x86_64-linux-gnu.so.
- SHA2564505ea29e626d11865106c975d7bed84d472bc6a4c0f2aedd670c6a3ecf233a8;
  size62448; ELF64 little-endian x86_64 machine62; module _tkinter.
- Missing tuple(libTcl/Tk case preserved): libtcl8.6.so, libtk8.6.so only.
- All77 exact observed successful module names, bound by their joined-name
  SHA256049267074bee42d4449e7a3ed866076d6529b44106e0e3676f41a5e1da277a1b.

Runtime may unlink only that one classified file in its disposable Python
payload, after exact path, regular-file, byte, size, native, ELF, missing-pair
and full-import-set guards. Every other entry, mode, link and byte must remain;
every retained ELF must resolve with the existing owner checks and all77
retained lib-dynload modules must import. The next native run proves this;
local ARM synthetic/component evidence cannot qualify native AMD.

## Implementation and proof boundary

Write the accepted ADR before implementation. Initial public source scope, extended only by the reviewed amendment below, is
python_payload.py constant data, its existing unit and integration owners,
tools/ci/d12_hosted_candidate.json's mechanically derived source digest, and
tools/ci/nav47-ci67-amd-payload.md. The only executable amendment is the strict hosted trim-proof verification described below; no existing payload or closure-owner function, recipe or runner change.
Record regeneration must retain context membership/count694, Dockerfile,
recipe, platform and SDK fields exactly; only source_sha256 changes to the
actual current source. This expectation is not an image/build admission.
No manual historical source digest or alias to private checkout identity.

Unit proof must assert exact both-platform entries, actual-config admission and foreign-config/emulation refusal; independently build the
AMD observation, classify it, reject old/foreign hashes, size, native/ELF,
extra missing dependency, extra failed import, missing import and symlink or
duplicate target. Keep all ARM/legacy negative proofs. Containerized integration
must exercise real ELF observations, real exact unlink, failure-safe removal
and retained-tree preservation on the actual native SDK. Parameterize native
fixture coverage without claiming AMD platform qualification on ARM.

TDD: at most1 scoped unit RED on the new AMD and hosted-trim cases before constant/helper insertion;
then max2unit GREEN,2integration and2static executions. Repeat a class only
after an actual failure and correcting source change; all attempts retained.
No complete local suite or Python coverage. Exact selectors use canonical
tools/run_tests.py --no-coverage. Full inventory enforcement must pass with zero
regressions and residual paths. No dynamic recipe, cohort, debt or scope waiver.

After independent final implementation review and parent acceptance, exact
commit/report and committed-source/export checks precede one ordinary FF
public staging push. Existing PR13 automatically supplies one fresh hosted
campaign: at most1 unchanged native AMD SDK cold materialization,1 ordinary
managed test-runtime and1 canonical non-consuming E1/E4 node. Native failure
stops at its first cause and preserves authentic sealed evidence, never retry.

## Preserved holds and exclusions

Psycopg C3.3.6 stays dynamically linked to system libpq. No dependencies,
Tcl/Tk package installation, runtime library replacement, SDK/recipe change,
app build or image matrix expansion. Local SDK build/pull and AMD emulation
remain excluded. App ledger maximum0/used0 under2total,1perplatform,no-retry;
P3/incumbent comparison, platform/image/application/system acceptance stay
open. Global libpq/version maps stay unset until independently established.
System prerequisite hold is not removed. Final closure, builder package set,
native libpq ABI/path/license and all later AMD facts remain unobserved.
Complete local suites and local Python coverage remain excluded; hard85/85
unit,80/80integration and aims87/87,82/82 stay hosted measured. No manual CI
dispatch/rerun/cancel, PR/main/tag/history mutation or live/graph changes.

## Alternatives and rollback

Generic ignoring of unresolved ELFs, weakening validation or removing the
native/system jobs is rejected. Installing Tcl/Tk adds an unapproved dependency
closure. Repeating unchanged CI cannot change the deterministic refusal.
Remain at the current published candidate if this exact admission is refused.
Rollback is an ordinary reviewed forward revert of only the new AMD data and
its mechanical expectation; never rewrite public history or activate images.


## Reviewed amendment: strict hosted trim-proof validation

The first independent design review correctly refused the constant-only plan:
canonical closure_facts retains baseline_failed=["_tkinter"] on a successful
exact trim, but the hosted positive validator currently rejects that history.
That would deterministically reject an otherwise successful next campaign.
It also identified a misleading existing "amd64 gets no exclusion" test that
actually supplies the ARM config. No implementation has occurred.

Admit these additional existing files only:
- tools/d12_python_closure.py: append one pure hosted-closure verification
  helper alongside the existing canonical _check. Existing program/contract_argv,
  _report, _check and closure_facts functions remain byte-for-byte unchanged.
- tools/ci/d12_hosted_reports.py: replace only the positive closure predicate
  with that helper and add its static import. Every unrelated validator,
  metadata pin, refusal path and first-failure rule stays unchanged.
- src/test/unit/python/tools/d12_python_closure.unit.test.py: exact AMD config
  positive, explicit foreign ARM config and emulated AMD refusals, plus helper
  negatives; preserve existing ARM/legacy cases.
- src/test/unit/python/tools/ci/d12_hosted_reports.unit.test.py and its existing
  sibling d12_hosted_fixtures.py: canonical full positive trim report and
  mutations proving the actual aggregate accepts only valid exact closure.

Every file stays<=400 lines. The report owner is398 lines, so centralize the
strict new proof in the existing closure owner, replacing its old7-line
predicate with a helper call. No new module, census member, recipe, dependency,
scope-transition or debt authority is needed. The tools and test files are
outside CONTEXT_PATHS; source membership/count694 stays unchanged.

The pure helper must preserve the original positive closure requirements:
unresolved==[], strict positive ELF count and retained.preserved is True.
Preserve the genuinely clean legacy shape with baseline_failed==[] when no
exclusion/trim evidence is claimed. A claimed trim, exclusion, removed target,
nonempty baseline_failed or baseline_unresolved must enter the strict path;
it must never fall back to a clean result by omitting or falsifying a flag.

For that strict path require a mapping contract, exclusion_applies is True,
native == "native", the verified AMD config, exact current program SHA256,
strict integer exit0, result=="trimmed" and reasons==[]. Resolve only the
current frozen amd64 entry, bound to the existing verified AMD Python metadata.
Raw baseline must be present; classify it through the UNCHANGED payload.classify
and re-use canonical _check to verify the actual exclusion and retained proof.
Require baseline_failed exactly[entry.module] and baseline_unresolved exactly equal to payload.unresolved(raw baseline elves), retaining the actual ldd order; independently require sorted(baseline_unresolved) equal to the sorted frozen-pair lines. The native AMD positive fixture must use libtk before libtcl, as observed. Reject any inconsistent redundant
summary fields. Require excluded_absent is True; retained ELF hashes, entry
count/digest preservation, imports/lib-dynload and targets/owners remain governed
by canonical _check. Cross-check reported retained/closure ELF counts and
imports against the retained mapping so forged summaries cannot bypass proof.
Unknown/malformed input returns violations, never raises out of the validator.
No unconditional allowance of _tkinter, stripped baseline, missing baseline,
truthy-string booleans, foreign config, extra missing library or weak shortcut.

Add positive full trim and clean tests, and negatives for every required field,
extra failed import/missing dependency, omitted or false apply flag, forged
exclusion, raw baseline mismatch, current program hash, absent target claim,
retained bytes/counts/imports/owners/digests, malformed structures and native/
config drift. The single scoped RED selects the changed payload, closure and
hosted report unit owners before BOTH payload data and helper/caller edits.
All original guards/refusal tests stay. Final full retained-inventory enforcement
must pass, without declaring old strict data ignored or adding debt.

Provenance corrections from first review:
- AMD manifest is accepted ADR0092 D4.2 verified OCI metadata; the sealed report
  proves native base config identity but reports config_digest_verified:false.
  Runtime checks config/native; it does not fetch or check the child manifest.
- CI66 comparison is retained parent evidence from sealed artifact12596226833;
  CI67 native facts from12600453502 bind the same target bytes and77 imports.
- Keep independent AMD tuple source literal. Equal names may be compiler-merged
  as objects; test equality/content and source provenance, never tuple identity.
- Local SDK uses CPython3.13. It validates frozen3.12 data and real native SDK
  ELF fixture lifecycle, not actual frozen3.12 AMD unlink. Existing default-map
  main refusals happen before observation. Native hosted E1/E4 alone proves the
  pinned payload and retained closure. Add a default-map native refusal case.
- Existing ADR0092 signed package resolution and disposable runtime-probe
  additions remain pre-authorized lane behavior. No new Tcl/Tk or dependency
  class is admitted by this slice; do not prohibit existing approved operations.
- Parent source scan found no workflow hash pin for d12_hosted_reports.py.
  Inventory references are cohort/candidate declarations, not permission to
  ignore the check. All direct callers and authoritative hash references must
  still be inspected before implementation.

All earlier build/admission/remote/privacy/suite holds remain unchanged.
The helper recognizes an authentic strict trim; it does not waive runtime,
native, image, P3, incumbent, application or system admission.

## Parent disposition of second independent review

The second review closed the substantive B1/B2 design findings, and retained
NOT ACCEPTED with two exact mechanical corrections. Parent resolves them here;
the review outcome itself is preserved, never relabeled as a green review.

BLK-1: Q already contains ADR0093-ci63-pg-config-and-native-report-export. Parent
verified0094 free in BOTH checkouts and selects the exact public/private path
docs/adr/2026/10/0094-exact-native-amd-python-payload-exclusion.md. That accepted
ADR is added to the public write scope and saved before implementation.

BLK-2: Native ldd order is libtk then libtcl. Require the stored raw unresolved
list exactly equal to payload.unresolved(raw elves), and independently compare
its sorted value to the frozen sorted pair. Preserve raw order; use tk-first
positive fixtures and an assertion that the real observed order is accepted.
An exact-pair check must not compare the raw list directly to sorted tuples.

Parent also adopts the advisory corrections: any closure carrying contract or
baseline keys takes the strict canonical path; a contract-bearing clean report
uses _check(entry=None), with only the minimal legacy synthetic shape retaining
the old predicate. The caller passes its trusted VERIFIED AMD Python config;
the closure owner must not import ci.* (its existing AST guard remains). Assert
the frozen AMD index/manifest/config against the existing verified metadata in
the hosted-report unit owner. Re-apply _report's complete baseline shape check
and convert KeyError/TypeError/ValueError/AttributeError/IndexError to violations
containing "closure invalid". Real trimmed counts are81 ELFs and1720 entries.
New-helper RED uses attribute access at runtime, never import-time failure.
Default-map integration asserts refusal removes nothing on either native SDK.

Use a canonical full trim fixture for positive hosted qualification/evidence
unit paths, and include their existing exact unit owners in scoped GREEN. This
proves the unchanged seal/evidence chain with synthetic data, not native AMD.
Keep each file<=400 lines and declared scope unchanged beyond the exact ADR.
README, roadmap and all other documentation/source remain out of scope.
Final implementation acceptance still requires a complete independent review
of the actual code, ADR, raw attempts and Exit, plus fresh parent verification.

## Parent review disposition

The first design checkpoint was NOT ACCEPTED. Its B1 hosted-trim mismatch and B2 foreign-config coverage findings are resolved by the reviewed amendment above. The second checkpoint retained two mechanical findings; Root resolved them explicitly before admission, retaining the original rejection without relabeling. All native/P3/incumbent/application/system holds remain; no dependency or complete-suite authority is added.

## Final current-source proof allocation

The initial source checkpoint consumed its two unit GREEN allocations before
the scoped static owner identified two test-only annotations. Both annotations
were corrected; the second integration and static attempts bind the corrected
source, but the unit receipt predates it. The checkpoint closed NOT ACCEPTED
at the freshness fence, normally and without interruption. Its review and all
original receipts remain unchanged.

Under the current human-authorized CI67 remediation and ordinary scoped-test
authority, the parent admits one sequential final-proof checkpoint. Its only
actor edits are removal of the RED-only ARM-derived fallback from the hosted
fixture, an assertion that the AMD entry's source references the separate AMD
tuple, and correction of the misleading foreign-ARM-config test name. No
product function/data or other implementation changes are admitted.

Additional allocation: one exact scoped unit execution, one exact containerized
integration execution and at most two scoped static executions (the second
only after an actual static failure and correcting source). Run static before
unit/integration. Maximum cumulative counts are one RED, three unit GREEN,
three integration and four static, with no counter reset. No complete local
suite, Python coverage, local SDK/app build, dependency or new hosted trigger
is added. Frozen product/context/recipe/SDK and all holds stay unchanged.

The full actual final patch, current exact receipts, accepted ADR and Exit must
be delivered verbatim inline to independent review; scratch readability or a
producer summary supplies no substitute. Parent acceptance, exact commit/report
and the single authorized public staging campaign remain pending that review.
