# Bats Extraction Design

Status: BATS3 implements selected Bats canonicalization, bounded count-only
summary/readback helpers, and public-safe fixture dogfooding. Dynamic,
unsupported, and runtime-sensitive Bats facts remain raw-only.

## Purpose

Bats extraction should make RepoMap's shell-family graph evidence useful for
Bats test suites while preserving the static, conservative safety boundary
defined in SH0 and proven through the BASH0-BASH5 phaseset.

Bats files contain Bash-like syntax, but Bats has test-framework semantics that
should not be flattened into ordinary Bash extraction. Test cases, hooks,
helper loading, `run` wrappers, assertions, refutations, skips, fixture paths,
and Bats variables are test intent. They are not proof that a command ran or
that the host was mutated.

BATS1 adds static `.bats` classification and basic Bats test-structure raw
observations. It does not execute Bats, invoke a shell, model `run` commands or
assertions, classify side effects, add canonicalization, change storage, or add
readback behavior.

BATS2 adds conservative static Bats run/assertion/helper/fixture raw
observations. It treats commands as test intent, not runtime execution, and
does not execute Bats or shell code.

BATS3 adds selected Bats canonicalization and bounded count-only dogfooding for
public-safe fixtures. Bats commands remain test intent, not runtime execution,
and unsupported or dynamic facts remain raw-only.

## BATS1 Implementation

BATS1 adds a stdlib-only static Bats scanner at
`src/main/python/repomap_kg/bats_extractor.py` and routes `.bats` files through
that extractor in discovery and local ingestion paths.

Implemented BATS1 raw observations:

- `bats.file`;
- `bats.test_case`;
- `bats.setup`;
- `bats.teardown`;
- `bats.setup_file`;
- `bats.teardown_file`;
- `bats.load`.

Every BATS1 observation includes `dialect="bats"`,
`test_framework="bats"`, `static_only=true`, `shell_executed=false`, and
`bats_executed=false`.

BATS1 classifies `.bats` files as Bats test files and keeps `.bats` out of
ordinary Bash extraction. Bash helper files such as `test_helper.bash` remain
Bash or shell-family files under the existing classifier; Bats relationships
are represented only where a `.bats` file has a static `load` statement.

The scanner recognizes simple static `@test "name" { ... }` and
`@test 'name' { ... }` test cases, the four standard hook functions, and simple
static Bats `load` targets. Static relative load targets are normalized
syntactically relative to the `.bats` file. The extractor does not read helper
files, check helper existence, execute hooks, or model test bodies.

Computed test names and computed load targets are bounded as dynamic or
unknown evidence when recognized. Comments, strings, arrays, heredoc bodies,
and case labels are suppressed for BATS1 structural extraction. Secret-like
test names or load targets are redacted and raw secret-like values are not
stored.

## BATS2 Implementation

BATS2 extends the same stdlib-only static Bats scanner with test-intent
observations for helper libraries, `run` wrappers, assertions, refutations,
skips, fixture references, helper references, and bounded output/status
expectations.

Implemented BATS2 raw observations:

- `bats.library_load`;
- `bats.run`;
- `bats.assertion`;
- `bats.refutation`;
- `bats.skip`;
- `bats.fixture_reference`;
- `bats.helper_reference`;
- `bats.output_expectation`;
- `bats.status_expectation`.

BATS2 preserves all BATS1 file, test-case, hook, and `load` observations. New
observations include `dialect="bats"`, `test_framework="bats"`,
`static_only=true`, `shell_executed=false`, and `bats_executed=false`.
Observations inside tests or hooks also carry bounded test-context metadata
such as `test_context`, `test_case_name` when known, `test_intent=true`, and
`command_executed=false` where relevant.

`bats_load_library` statements are represented as static or dynamic library
references without assuming the library exists, is installed, or has run.
Simple static `load` targets also emit helper-reference evidence. The extractor
does not read helper files, import helper libraries, or resolve symbols.

`run` observations record the static command token when visible, argument
counts, `run -N` expected status flags, negation, and
`--separate-stderr`. They are command-under-test evidence only. BATS2 does not
emit normal shell command, side-effect, host-mutation, network, or package
manager observations from `run` lines.

Assertion/refutation observations cover common bats-assert and bats-file forms,
including status, equality, output, line, file, and directory expectation
families. BATS2 emits bounded output and status expectation observations where
safe. Large, dynamic, and secret-like expected values are not stored raw.

Skip observations record bounded or redacted reasons and enclosing context when
known. Fixture references cover static repo fixture paths and Bats temp
directory variables without creating, reading, checking, or mutating files.

Dynamic library names, `run` targets, load targets, expected values, and fixture
paths are represented with dynamic or unknown metadata. Comments, strings,
arrays, heredoc bodies, and case labels remain false-positive boundaries.

## BATS3 Implementation

BATS3 maps a selected safe subset of Bats raw observations into the existing
canonical graph layer and adds `src/main/python/repomap_kg/bats_readback.py` for
count-only fixture dogfooding summaries.

Canonical mappings implemented:

- `bats.file` creates a `bats.file` node and a `file -> defines -> bats.file`
  edge;
- static `bats.test_case` creates a `bats.test_case` node and a
  `bats.file -> contains -> bats.test_case` edge;
- static `bats.load` creates `bats.file -> loads -> file` helper-file
  references;
- static `bats.library_load` creates `bats.file -> depends_on ->
  external:bats.library:*` evidence;
- static `bats.run` creates `bats.test_case -> tests_command -> tool:*`
  command-under-test evidence with `command_executed=false`;
- static `bats.assertion` and `bats.refutation` create `bats.expectation` nodes
  and `asserts` or `refutes` edges without storing raw expected output text;
- static repo `bats.fixture_reference` observations create bounded file
  reference edges;
- static `bats.helper_reference` observations create bounded helper-reference
  evidence.

Raw-only Bats observations in BATS3:

- hooks: `bats.setup`, `bats.teardown`, `bats.setup_file`,
  `bats.teardown_file`;
- `bats.skip`;
- `bats.output_expectation`;
- `bats.status_expectation`;
- Bats-owned `shell.secret_like` and dynamic-invocation evidence;
- dynamic test names, loads, libraries, run targets, expected values, fixture
  paths, and Bats temp-directory references.

BATS3 adds small graph-key helpers for `bats.file`, `bats.test_case`, and
`bats.expectation`. It does not add storage schema changes, CLI/MCP readback,
or live/private graph refresh behavior.

The bounded summary reports raw kind counts, Bats file/test/hook/load/run/
assertion/fixture/helper counts, dynamic/unknown counts, redacted secret-like
counts, canonical node/edge counts, and safety markers. It does not include raw
payloads, source snippets, expected output strings, heredoc bodies, path
examples, or secret values.

## Design Principles

Bats extraction should be:

- static;
- conservative;
- test-framework-aware;
- compatible with SH0's shell-family model;
- compatible with the completed Bash extraction phases;
- redaction-first;
- honest about dynamic behavior;
- side-effect-aware without treating test intent as runtime execution;
- useful for graph evidence without running tests.

Future extraction must never execute Bats files, invoke `bats`, invoke Bash to
parse tests, run helper libraries, run setup/teardown hooks, run `run`
commands, run assertions, or inspect behavior through subprocesses.

## Relationship To SH0 And Bash

Bats should reuse shared `shell.*` raw observation kinds when they honestly
represent shell-family facts:

- `shell.script`;
- `shell.function`;
- `shell.source`;
- `shell.command`;
- `shell.command_argument`;
- `shell.external_command`;
- `shell.pipeline`;
- `shell.command_chain`;
- `shell.redirect`;
- `shell.heredoc`;
- `shell.process_substitution`;
- `shell.command_substitution`;
- `shell.dynamic_invocation`;
- `shell.env_read`;
- `shell.env_write`;
- `shell.file_read`;
- `shell.file_write`;
- `shell.host_mutation`;
- `shell.network_call`;
- `shell.package_manager`;
- `shell.secret_like`.

Every Bats observation should include:

- `dialect="bats"`;
- `test_framework="bats"`;
- `static_only=true`;
- `shell_executed=false`;
- `bats_executed=false`.

Bats extraction may reuse Bash scanner helpers later for tokenization,
redaction, shell commands, redirects, heredocs, and dynamic markers. Reuse
should preserve Bats context metadata so a command inside a test body, hook, or
`run` wrapper remains test intent rather than ordinary Bash runtime evidence.

`.bats` files belong to the BATS series, not to the Bash extractor. Bash helper
files loaded by Bats can still be Bash files, but Bats-specific helper
relationships should be represented where the `load` or `bats_load_library`
appears.

## Bats-Specific Raw Kinds

Use Bats-specific kinds where shared `shell.*` facts would be misleading or too
lossy:

| Kind | Planned Phase | Meaning |
| --- | --- | --- |
| `bats.file` | BATS1 | A Bats test file or suite-like source. |
| `bats.test_case` | BATS1 | An `@test` block with a static or bounded test name. |
| `bats.setup` | BATS1 | A per-test `setup` hook. |
| `bats.teardown` | BATS1 | A per-test `teardown` hook. |
| `bats.setup_file` | BATS1 | A per-file `setup_file` hook. |
| `bats.teardown_file` | BATS1 | A per-file `teardown_file` hook. |
| `bats.load` | BATS1 | A Bats `load` helper reference. |
| `bats.library_load` | BATS2 | A `bats_load_library` reference. |
| `bats.run` | BATS2 | A `run` wrapper command-under-test. |
| `bats.assertion` | BATS2 | A positive Bats assertion. |
| `bats.refutation` | BATS2 | A negative/refuting Bats assertion. |
| `bats.skip` | BATS2 | A `skip` declaration or conditional skip. |
| `bats.fixture_reference` | BATS2 | A static or bounded fixture/temp path reference. |
| `bats.helper_reference` | BATS2 | A helper function/library relationship. |
| `bats.output_expectation` | BATS2 | Bounded output or line expectation evidence. |
| `bats.status_expectation` | BATS2 | Bounded status expectation evidence. |
| `bats.test_metadata` | BATS2 | Tags, comments, or metadata markers if later fixtures justify them. |

BATS3 should add selected canonicalization and bounded readback. It should not
attempt to canonicalize every Bats raw kind.

## Detection And Classification Strategy

Future Bats classification should be evidence-based.

Classify as Bats when:

- extension is `.bats`;
- a shebang explicitly mentions Bats, if such a file is encountered and tested;
- a future fixture proves another unambiguous Bats marker.

Use path patterns as context, not as sole classification:

- `test/*.bats`;
- `tests/*.bats`;
- `spec/*.bats`;
- `test/bats/*.bats`.

Helper files are different:

- `test_helper.bash`;
- `helpers/*.bash`;
- files referenced by `load`;
- files referenced by `bats_load_library`.

Do not classify ordinary `.bash` files as Bats merely because they live in a
test directory. Do not classify `.bats` as Bash. If a Bats test loads Bash
helpers, represent the helper relationship in Bats extraction and let any
separately classified Bash helper remain Bash.

Use existing RepoMap role values; likely roles are test-like or source-like
depending on current classifier conventions. Do not add new global role values
unless a later implementation phase explicitly needs and tests them.

## Parser And Scanner Strategy

BATS1 should start with a stdlib-only static scanner/tokenizer:

- no Bats invocation;
- no shell invocation;
- no parser dependency;
- line-aware and heredoc-aware scanning for `@test`, hook functions, `load`,
  and simple Bats commands;
- optional reuse of Bash scanner helpers only when static and context-safe;
- bounded unknown observations for unsupported syntax;
- fixture-backed recognition only;
- false-positive avoidance over high recall.

Parser candidates for later evaluation include:

- Tree-sitter Bash;
- bashlex;
- any Bats-specific grammar option evaluated later;
- Bash parser helpers introduced by future shell-family work.

Bats syntax is Bash-like but test constructs alter the meaning of common
tokens. A line-oriented scanner will miss complex nested constructs. A full
parser may be useful later, but dependency, packaging, license, platform
behavior, line-range preservation, error recovery, and testability need a
dedicated evaluation phase.

## Core Bats Constructs

### Test Cases

Recognize:

```bash
@test "reports status" {
  run ./bin/tool --version
  assert_success
}
```

Future `bats.test_case` metadata:

- test name or description;
- source path;
- line range if available;
- body_modeled=false or command_count if later phases count commands;
- `static_only=true`;
- `bats_executed=false`;
- `shell_executed=false`.

Do not execute test cases. Dynamic or computed test names should become bounded
unknown observations rather than fabricated names.

### Hooks

Recognize hook functions:

- `setup() { ... }`;
- `teardown() { ... }`;
- `setup_file() { ... }`;
- `teardown_file() { ... }`.

Future hook metadata:

- hook name;
- line range;
- scope: `per_test` or `per_file`;
- `static_only=true`;
- `bats_executed=false`;
- `shell_executed=false`.

Do not treat hook bodies as having run. Commands inside hook bodies may later
be represented as test setup/cleanup intent, not as normal runtime side
effects.

### Helper Loading

Recognize:

```bash
load 'test_helper'
load './helpers/common'
bats_load_library bats-support
bats_load_library bats-assert
bats_load_library bats-file
```

Future `bats.load` observations should preserve the target token, resolve
simple relative helper paths syntactically where safe, and mark dynamic loads
as bounded dynamic or unknown. BATS1 should not read helper files.

BATS2 `bats.library_load` observations record the library name when static and
safe, or bounded dynamic metadata otherwise, without assuming dependency
installation, availability, or execution.

### `run` Wrappers

`run` is test intent. It is not proof that the command executed.

For:

```bash
run git status --short
run -0 ./bin/tool --version
run ! curl https://example.invalid/api
```

BATS2 emits `bats.run` with:

- command token when static;
- argument count;
- expected_status for `run -0`, `run -1`, and similar forms;
- negated=true for `run ! ...`;
- command_executed=false;
- test_intent=true;
- `static_only=true`;
- `bats_executed=false`;
- `shell_executed=false`.

BATS2 deliberately does not emit normal `shell.command` or
`shell.external_command` evidence from `run` lines. A later phase may add
canonical command-under-test evidence only when the graph/readback model can
preserve non-execution semantics.

### Assertions And Refutations

Recognize assertion and refutation helpers such as:

- `assert_success`;
- `assert_failure`;
- `assert_equal "$status" 0`;
- `assert_output "expected"`;
- `assert_output --partial "fragment"`;
- `refute_output "unexpected"`;
- `assert_line --partial "line"`;
- `refute_line "line"`;
- `assert_file_exists "path"`;
- `assert_dir_exists "path"`.

BATS2 `bats.assertion` and `bats.refutation` metadata:

- assertion name;
- assertion_family: `status`, `output`, `line`, `file`, `directory`,
  `equality`, or `unknown`;
- mode: `exact`, `partial`, `regex`, `negated`, or `unknown`;
- argument_count;
- redaction metadata;
- raw_value_stored=false for secret-like expected values;
- `static_only=true`;
- `bats_executed=false`.

Do not store large expected output blobs. Do not store raw secret expected
values.

### Skips

Recognize:

```bash
skip "requires network fixture"
```

BATS2 `bats.skip` observations record a bounded/redacted reason, the
enclosing test case if known, and `bats_executed=false`. A skip statement in
source is test intent, not proof the test was skipped in a run.

### Variables

Recognize Bats-specific variables as environment or framework context:

- `$BATS_TEST_NAME`;
- `$BATS_TEST_FILENAME`;
- `$BATS_TEST_DIRNAME`;
- `$BATS_TMPDIR`;
- `$BATS_RUN_TMPDIR`;
- `$BATS_FILE_TMPDIR`;
- `$BATS_TEST_TMPDIR`;
- `$status`;
- `$output`;
- `$lines`.

Temporary-directory variables should be marked dynamic/temp rather than repo
files. `$status`, `$output`, and `$lines` are assertion context, not ordinary
external environment reads.

## Fixture And Path References

BATS2 `bats.fixture_reference` observations cover common static paths:

- `${BATS_TEST_DIRNAME}/fixtures/...`;
- `./fixtures/...`;
- `test/fixtures/...`;
- `$BATS_TMPDIR/...`.

Static repo-relative fixture paths can become bounded file references in BATS3.
Bats temp-dir variables should remain dynamic/temp. The extractor must not
create, inspect, or mutate files.

## Side-Effect Strategy

Bats should reuse shell/Bash side-effect categories but add test-context
metadata:

- `test_context="test_case"`;
- `test_context="setup"`;
- `test_context="teardown"`;
- `test_context="setup_file"`;
- `test_context="teardown_file"`;
- `test_intent=true`;
- `bats_executed=false`;
- `shell_executed=false`.

A command inside `run` is a command-under-test, not proof of host mutation. A
command inside `setup` or `teardown` is setup/cleanup intent, not proof of
runtime execution. BATS2 keeps this distinction raw-only and does not reuse Bash
side-effect helpers for Bats test bodies.

Avoid normal host-mutation canonicalization from Bats until BATS3 defines
bounded readback and test-intent semantics.

## Redaction Policy

Bats inherits SH0 and Bash redaction rules for names or values containing:

- `password`;
- `passwd`;
- `secret`;
- `token`;
- `key`;
- `credential`;
- `apikey`;
- `pat`;
- `authorization`;
- `auth`.

Bats-specific sensitive contexts include:

- expected output strings;
- `assert_output` and `refute_output` arguments;
- heredoc-like expected output;
- fixture file contents if a future phase ever inspects fixtures;
- environment setup in hooks or test bodies;
- `run` arguments such as `--token`, `--password`, and `-H Authorization:...`.

Rules:

- do not store raw secret-like expected outputs;
- preserve assertion, test, helper, or key names and redaction reason;
- mark `raw_value_stored=false`;
- avoid over-matching ordinary words like `path` as `pat`;
- use fake values only in fixtures and prove they are absent once
  implementation tests exist.

## Dynamic And Unknown Policy

Future extractors should treat these as bounded dynamic or unknown:

- dynamic test names;
- computed `load` targets;
- computed `bats_load_library` arguments;
- `run "$cmd"`;
- `run "${command[@]}"`;
- `eval` inside tests;
- command substitution in assertions;
- loops generating tests;
- helper functions defined conditionally;
- assertions invoked through variables.

Policy:

- emit bounded dynamic/unknown observations;
- record `dynamic_reason`;
- do not infer precise command, helper, assertion, fixture, or library targets;
- do not execute or expand;
- do not read loaded helpers to resolve symbols unless a later phase explicitly
  scopes safe same-repo static resolution.

## False-Positive Strategy

Future scanners should suppress Bats facts from:

- comments;
- quoted strings;
- heredoc bodies;
- here-doc expected output bodies;
- ordinary Bash functions that are not Bats hooks;
- strings containing `@test`;
- comments containing `run rm -rf`;
- arrays containing assertion-like text;
- case pattern labels;
- nested braces inside strings or heredocs.

Prefer missing a construct over extracting dangerous false positives.

## Canonicalization And Readback Targets

BATS3 follows BASH5's selective model:

- Bats files map to `bats.file` canonical nodes;
- static `bats.test_case` observations map to test-case nodes;
- hook observations remain raw-only evidence;
- `bats.load` and `bats.library_load` map to helper/library dependency edges
  when static and safe;
- `bats.run` maps to command-under-test evidence with explicit non-execution
  metadata;
- assertions and refutations map to bounded `bats.expectation` nodes;
- static repo fixture references map to file references;
- dynamic/unsupported facts remain raw-only.

Bounded readback is count-only:

- Bats files;
- test cases;
- hooks by kind;
- load/helper references;
- run command count;
- assertion/refutation counts by family;
- skip count;
- fixture reference count;
- dynamic/unknown count;
- secret-like redacted count;
- canonical nodes and edges produced.

Readback must not include raw source snippets, full expected output strings,
raw secrets, heredoc bodies, unbounded path lists, or private absolute paths.

## Fixture Strategy

Public-safe BATS0 design examples live under `docs/examples/bats/`.

Future implementation fixtures should live under `src/test/fixtures/shell/bats/`
and start in BATS1 or a concrete implementation phase.

Suggested future fixtures:

- `basic.bats`;
- `hooks.bats`;
- `helpers-and-loads.bats`;
- `run-and-assertions.bats`;
- `dynamic.bats`;
- `redaction.bats`;
- `false-positives.bats`.

BATS0 examples and future fixtures must:

- be clearly labeled static extraction examples only;
- remain non-executable by default;
- use redacted placeholders or fake values only;
- use `.invalid` domains if URI-like strings appear;
- put mutating-looking commands in test bodies or hooks only as non-executed
  static examples;
- contain no real private paths;
- contain no real secrets, credentials, tokens, or private key material.

## BATS1 Acceptance Sketch

BATS1 should cover classification and basic test structure:

- classify `.bats`;
- ensure `.bats` is not routed to Bash extraction as ordinary Bash;
- emit `bats.file`;
- emit `bats.test_case`;
- emit hook observations;
- emit simple `bats.load`;
- preserve Bash-compatible structural evidence only if safe and clearly marked;
- emit bounded dynamic/unknown evidence for computed loads or unsupported
  constructs;
- use public-safe fixtures;
- execute no tests or shell code;
- add no runtime/parser dependency;
- pass the combined final gate.

## BATS2 Acceptance Sketch

BATS2 should cover Bats helpers, assertions, and `run` modeling:

- `bats.library_load`;
- `bats.run`;
- assertion/refutation observations;
- skip observations;
- fixture references;
- redaction for expected outputs and run arguments;
- dynamic/unknown boundaries;
- test-intent side-effect policy if scoped;
- execute no tests or shell code.

## BATS3 Acceptance Sketch

BATS3 should cover canonicalization, bounded readback, and dogfooding:

- selected raw-to-canonical mappings;
- bounded summary helper;
- public-safe fixture dogfooding;
- test-intent semantics preserved;
- dynamic and unsupported facts raw-only;
- fake secret non-leakage;
- no storage schema redesign unless a dedicated later phase explicitly accepts
  it.

## Known Gaps

- Parser choice remains undecided.
- BATS0 does not decide whether BATS1 should reuse Bash extractor helpers
  directly or factor shared scanner utilities first.
- Cross-file helper/source resolution remains future work.
- Exact canonical node names for test cases, hooks, and assertions remain for
  BATS3.
- Bats ecosystem helper coverage is limited to design examples until BATS2.

## BATS0 Acceptance

BATS0 is accepted only if:

- Bats extraction design exists;
- relationship to SH0 `shell.*` taxonomy and completed Bash phases is explicit;
- Bats-specific raw-kind policy is explicit;
- Bats detection/classification strategy is explicit;
- parser/scanner strategy is explicit;
- non-execution policy is explicit;
- redaction policy is explicit;
- dynamic/unknown policy is explicit;
- run/assertion/helper strategy is explicit;
- fixture strategy is public-safe;
- BATS1 through BATS3 roadmap is documented;
- no Bats extractor implementation lands;
- no classification behavior changes;
- no shell or Bats tests are executed;
- no runtime/parser dependency is added.
