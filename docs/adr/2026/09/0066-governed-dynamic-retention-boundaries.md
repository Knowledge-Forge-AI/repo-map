# ADR 0066: Governed dynamic retention boundaries

## Status

Accepted bounded design for PR26-STAGING-FIX5-REVISE39. Admission requires
focused implementation evidence; unsupported boundaries remain residual.

## Date

2026-09-12

## Context

Some maintained tests intentionally execute module entry, reload modules, or
independently resolve source identities. Replacing these behaviors with static
imports would remove the contract under test. An unverified declaration cannot
make their dependencies governed.

## Decision

Identify each dynamic source operation by enclosing symbol, operation kind and
SHA-256 of its attribute-free AST. Keep source-byte commitments separately.
Recognize Python reload through import bindings, preserving Docker object reload
as an ordinary method call. Undeclared operations remain uncertainty.
Explicit imported-name aliases are recognized; arbitrary assignment dataflow is
not added to the detector. Exact `__main__` imports refer to the interpreter-owned
active namespace, while unresolved `__main__` submodule names remain blocked.

Introduce only closed, statically verifiable contract recipes. A recipe binds
the exact operation, owner bytes, target module/source identities, applicable
test owner and supported execution arguments. Literal package entry binds both
package initialization and its `__main__` module, including `run_name`.
Unresolvable names, source drift, missing/aliased targets, unused declarations,
unsupported expressions and malformed declarations fail closed. No target code
executes during checking.

Resolved edges enter the existing dependency graph before reachability and SCC
evaluation. Targets must receive effective governance under the existing fixed
point; pending targets cannot lend governance. Same-root atomic membership and
cross-root refusal remain unchanged. Declaration history is monotonic: changing
or retiring a contract requires source/test-bound transition evidence, preserving
prior records. A missing declaration collection cannot erase prior obligations.

FIX2 independent source/module/symbol re-resolution, source bytes, code identity,
executor source and canonical digest contributions remain mandatory. Closed
catalog declarations require independently enumerated catalog evidence and static
target verification. Unsupported generation/substitution recipes remain debt;
an operation fingerprint alone is never permission to ignore execution.

## Evidence and verification

Keep declarations compact and tracked. Bind them with governing inputs and carry
their resolved edges through existing atomic and regression evidence. ADR 0064
continues to own compact serialization and limits. Tests cover source/target
drift, undeclared operations, missing and residual targets, atomic closure,
module-entry arguments, reload discrimination and deterministic commitments.

## Scope and rejected alternatives

This is maintenance policy only. No product architecture, dependency, coverage
threshold, census exclusion, suppression, baseline reset or runtime qualification
is authorized. Ignored-call allowlists, wildcard exemptions, caller-callable
substitution for independent resolution and synthetic coverage execution are
rejected. Integration authoring remains static-only.

## Maintenance coupling and witness limits

A separate witness test must have a source-derived static dependency on its
owner; a unit owner may witness its own operation. Dynamic edges cannot satisfy
this check. This is a minimum applicability check plus a source-drift tripwire,
not proof that an imported function is exercised. Focused test execution and
review of behavioral assertions remain required evidence.

The guarded-symbol recipe deliberately matches the exact resolver AST. Renaming
its local variable or reordering its attribute traversal invalidates the recipe,
even if runtime behavior is equivalent. It is currently specific to this
resolver; reuse requires a separately validated recipe change. The failure is
reported as declaration invalidity and restores uncertainty, not silent admission.

Resolved targets couple the FIX2/3/4 support SCC to tools and product owners,
including `tools/run_tests.py`. A future direct finding in any required target
can block the entire SCC and its downstream owners. This cost follows from
independent source re-resolution and the prohibition on borrowing residual
governance. The phase ledger records the exact resolved target set and reverse
reachable owner counts so maintainers can assess that impact before editing.


## REVISE40 literal coverage fixture refinement

`literal_coverage_fixture` admits only three maintained literal-file export cases:
`uncovered_branch`, `export_refusal`, and `direct_report`. Its parameters use
`literal-coverage-fixture-v1` and bind the owning symbol, pytest temporary root,
relative filename, exact UTF-8 source, optional invocation suffix, namespace,
collector branch mode, and complete compile/exec chain. For `uncovered_branch`,
parameters also bind the asserted executed/missing line and arc observations.
The other two cases leave those observation lists empty: their maintained tails
bind export refusal and direct-report totals (two lines, both covered), respectively. The checker independently constructs the supported
source/write/compile/exec/stop AST and compares the maintained export tail.
The tail is a public source template, not a caller-supplied digest authority.
No generated module executes during validation.

Module initialization and execution-builtin rebinding fail closed. Collectors
must use new in-memory data with configuration loading disabled; unexpected
loads, source-root changes, extra operations, changed assertions, or omitted
cleanup differ from the closed template. Even behavior-preserving changes to
these small probe procedures require explicit recipe revalidation. This is an
intentional maintenance cost, matching the existing guarded resolver contract.

The declaration envelope still has one record per detected operation. Every
member of a closed chain must declare the same recipe and parameters, and the
independently enumerated operation identities must exactly match all peers in
that owner/symbol. Partial or duplicate chains cannot discharge uncertainty.
Generated bytes confer no independent governance credit. The tracked report
and coverage owners remain exact source-bound dependency obligations in the
same effective-governance and SCC calculation. Existing dynamic history is
preserved as an exact prefix.

The first REVISE40 generalized loader/generation/substitution prototype was
rejected because fingerprint membership and string presence did not establish
provenance. It authorized no admission. Unimplemented loader, child-module and
optional-dependency substitutions remain explicit debt, subject to closed
recipes and semantic negative tests; they are not waived or declared impossible.

### REVISE40 false-code identity refinement

`generated_false_code_identity` has two complete-chain declaration records, one
for compile and one for exec. Its closed parameters are `chain` (kind and AST
fingerprint descriptors) and `generated_source_sha256`. The latter must equal the
recipe-owned literal source commitment; it is not caller-supplied authority.
The validator checks literal generated bytes, runtime filename provenance,
`dict(runtime.__dict__)`, selection of `namespace["same_module_alternate"]`, the
TypeError/terminal_owner refusal and exact forwarding to the real runtime helper.
Generated code is never admitted as the true runtime owner. A target that declares
the generated symbol fails; canonical runtime source and package governance remain
independent obligations through the common target/source and dependency checks.

Maintained initialization and helper AST templates close eager initialization,
entry selection and false-refusal substitution. They include `_entries`,
`_psycopg_entry` and `_execute_with_caller_terminal_owner`; changing these contracts
requires an explicit recipe revalidation. Builtin/import rebinding, runtime
attribute/namespace mutation, wrong generated source/code-object/filename,
incomplete chains and target aliases fail closed. The namespace is a local copied
dictionary and neither runtime globals nor an installed module entry is replaced.
The checker only parses source; it never compiles or executes the generated body.

The initial narrow worker candidate exceeded the file limit and did not validate
entry-helper semantics. Parent integration replaced verbose forwarding checks
with explicit maintained AST templates and added a fake-refusal negative control.
These failed/superseded attempts remain evidence, not accepted intermediate states.


## REVISE41 governed dynamic retention boundaries

PR26-STAGING-FIX5-REVISE41 defines narrow, statically verified semantic AST recipes
for the six residual dynamic retention owners under ADR 0066, without waivers,
blanket fingerprints, or census alterations. Admission is gated on complete
semantic AST template verification, independent target resolution, exact lifecycle
and environment restorations, and negative control witness evidence; owners
remain residual dynamic debt until fully measured and verified.


### Conservative `exec_module` detector

The bounded dynamic operation detector in `tools/ci/python_retention_operations.py`
is extended with `"exec_module"` in `DYNAMIC_CALLS`. Detection is receiver-agnostic
and intentionally conservative: any attribute call or direct invocation named
`exec_module` is treated as a dynamic operation regardless of receiver identity.
This accepted overapproximation ensures complete coverage of standard library
loader invocation chains without relying on arbitrary execution permissions or
fragile local receiver typing.

### File loader specification (`file_loader_spec`)

`file_loader_spec` binds the complete loader chain consisting of
`spec_from_file_location`, `module_from_spec`, and `exec_module`. The recipe binds
exact AST structure, target source identity, target path, and the complete runtime-name
domain. These two file-loader contexts do not insert or remove module-cache entries.

Two distinct maintained contexts are governed:
1. `helper_contract_probe`: In `helper_branches.unit.test.py`, dynamic probe generation
   in temporary directories is replaced with maintained governed fixtures in
   `src/test/support/python/repomap_test_support/contract_loader_fixtures/`. The test verifies callback discovery,
   nested resolution, single-match resolution, 0-match refusal (`found 0`),
   2-match refusal (`found 2`), and missing-class failure (`AttributeError`).
   Probe files are enrolled under the clean test-support governing profile and have
   effective governance; pending targets cannot lend governance.
2. `conftest_refusal` and `conftest_inspection`: In `test_iso1_runner.unit.test.py`,
   the loader exercises `src/test/int/python/conftest.py`. Under module name
   `"conftest"`, import-time guard enforcement raises `pytest.exit.Exception`
   demanding the authenticated container sandbox. Under module name
   `"repomap_int_conftest_inspection"`, inspection import succeeds without activating
   the container guard. Neither test changes the module cache.

### Optional-import substitution (`optional_import_substitution`)

`optional_import_substitution` governs tests that verify behavior when optional
scale-tools dependencies are absent. The recipe binds the complete chain:
`spec_from_file_location`, `module_from_spec`, `sys.modules` subscript assignment,
and `exec_module`.

The recipe strictly enforces:
- A closed literal domain `{"psutil", "docker"}` independently derived and verified.
- Exact hook forwarding: `builtins.__import__` is patched to raise `ModuleNotFoundError`
  only for modules in the closed domain, forwarding all other imports to real `__import__`.
- Target source provenance and alternate namespace: the module is loaded under an
  isolated alternate name (e.g. `_repomap_without_scale_tools` or `_scale28_missing_*`).
- Outcome discrimination:
  - `src/main/python/repomap_kg/__init__.py`: package is successfully importable without
    scale tools.
  - `tools/scale12_resource_sampling.py`: module execution raises `RuntimeError` matching
    `"scale-tools"`.
- Mandatory restoration of `sys.modules` and `builtins.__import__` even on execution failure.

### Literal coverage fixture extension (`caller_mod` and `decision_mod`)

`literal_coverage_fixture` is extended to support literal file-backed nested coverage
collection cases `caller_mod` (in `test_runner_coverage_child.unit.test.py`) and
`decision_mod` (in `test_runner_coverage_child_export.unit.test.py`).

The recipe binds:
- Maintained literal UTF-8 source written to test scratch directories.
- Exact collector lifecycle: real `coverage.Coverage` instances with branch configuration,
  execution via `importlib.import_module`, and clean stop/save/combine cycles.
- Accurate observation tails: line and arc aggregation, including untaken branch arcs
  (e.g. `(2, 4)` missing while `(2, 3)` executed) in `decision_mod`.
- Parent session collector identity: contributions must derive from actual session
  collectors rather than fabricated shards.
- Complete cleanup of temporary files and `sys.modules` aliases.

### Complete owner context and transition evidence

The maintained `python_retention_owner_*` source templates are parsed as inert AST
contracts. They bind imports, initializers, callback arguments, temporary-root
setup and cleanup, and measurement calls in addition to the operation-local
function template. A changed declaration SHA cannot admit a changed surrounding
program. The helper callback dispatch body is independently matched as well.
The helper runtime-name domain includes both `Selected` and `Missing` identities;
the sampling domain includes both exact missing-dependency alternate names.

Optional substitution uses nested `monkeypatch.context()` and `patch.dict` scopes,
so the import hook and previous module-cache contents (including a prior `None`
entry) survive success, refusal and early loader failure. Nested coverage fixtures
likewise preserve prior search-path and module state. These nested/reporting
fixtures are not evidence of an actual portable subprocess; ADR 0067 owns that
separate synthetic proof.

Published declarations remain an exact historical prefix. The existing export
owner gains an explicit covered-branch assertion and appended superseding records
to reattest its changed runner dependency. Unpublished draft declarations and
failed focused/static attempts remain in the private verification archive.

### Terminal maintenance clarification

The literal owner and operation templates are governance surface, not disposable
test scaffolding. They must not be regenerated from a changed owner merely to
make validation pass. Each intentional template change requires semantic review,
negative controls, and explicit source-bound declaration transitions. Closeout
adds unique recursive callback discovery without changing the admitted dynamic
loader target or runtime-name domain. Child fixture declarations reject unknown
keys; branch expectations remain enforced by the complete maintained AST.
