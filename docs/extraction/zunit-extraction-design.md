# Zunit Extraction Design

Status: ZUNIT3 adds selected zunit canonicalization and bounded count-only
dogfooding summaries for public-safe fixtures. Zunit suite, test, hook,
assertion, helper, fixture, mock/stub, and command-under-test evidence remains
source/test intent, not runtime execution. ZUNIT3 does not execute zunit or
zsh, run assertions or commands under test, source helpers, load fixtures,
apply mocks/stubs, change storage, or add CLI/MCP readback.

## Purpose

Zunit extraction should make zsh-oriented test suites useful as static graph
evidence without treating test source as runtime execution. Zunit files are
shell-family and zsh-adjacent, but their suite, case, assertion, hook, helper,
fixture, mock, stub, skip, and todo semantics are test-framework facts. They
should not be flattened into ordinary zsh commands or Bash/Bats test facts.

ZUNIT0 defines:

- how zunit relates to SH0's shared `shell.*` taxonomy and the completed Bash,
  Bats, awk, and zsh phasesets;
- zunit-specific raw observations and planned phase ownership;
- future zunit detection and classification strategy;
- conservative non-executing parser/scanner strategy;
- suite, test-case, hook, assertion, expectation, command-under-test, helper,
  fixture, mock, stub, redaction, dynamic, and false-positive policies;
- public-safe example and implementation fixture strategy;
- the ZUNIT1 through ZUNIT3 roadmap.

ZUNIT1 should add static zunit file classification and basic test-suite/test-case
structure extraction. ZUNIT2 should add assertions, hooks, helpers, fixtures,
mocks/stubs, expectations, skips, todos, and command-under-test modeling.
ZUNIT3 adds selected canonicalization, bounded count-only readback, and public
fixture dogfooding.

## ZUNIT1 Implementation

ZUNIT1 adds a stdlib-only static zunit scanner at
`src/main/python/repomap_kg/zunit_extractor.py` and routes `.zunit` files
through that extractor in discovery, source ingestion, archive routing, and
bulk-ingestion paths.

Implemented ZUNIT1 raw observations:

- `zunit.file`;
- `zunit.suite`;
- `zunit.test_case`;
- `zunit.test_name`;
- `zunit.dynamic_test`.

Every ZUNIT1 observation includes `language="zsh"`, `dialect="zsh"`,
`test_framework="zunit"`, `static_only=true`, `shell_executed=false`,
`zsh_executed=false`, `zunit_executed=false`, `tests_executed=false`,
`assertions_executed=false`, `commands_executed=false`,
`fixtures_loaded=false`, and `mocks_applied=false`.

ZUNIT1 classifies explicit `.zunit` files as zunit test files with the existing
test role. `.zunit` files are not routed through ordinary zsh extraction.
Generic `.zsh` files remain zsh even when they contain zunit-like words such as
`test`, `assert`, `mock`, or `stub`; generic `.sh` files invoking `zunit`
remain shell files.

The scanner recognizes simple file-level `describe "name"` suite declarations
and simple `test "name" {` test-case declarations. It emits bounded
`zunit.test_name` evidence for static names and redacts secret-like suite/test
names. It also emits `zunit.dynamic_test` for fixture-backed generated loops,
dynamic test names, and eval-generated test forms. Generated and dynamic tests
do not imply loop, eval, array, zsh, shell, or framework execution.

ZUNIT1 intentionally did not emit hook, assertion, expectation,
command-under-test, helper, fixture, mock, stub, skip, todo, shell command,
host-mutation, network, or package-manager observations. Comments, quoted
strings, arrays, heredoc bodies, case labels, docs-like examples, and ordinary
helper function names remain false-positive boundaries.

## ZUNIT2 Implementation

ZUNIT2 extends the same stdlib-only scanner with fixture-backed zunit
test-framework semantics. It preserves ZUNIT1 classification and routing:
`.zunit` files remain `language="zunit"` at discovery time and are routed to
the zunit extractor, not ordinary zsh extraction.

Implemented ZUNIT2 raw observations:

- `zunit.setup`;
- `zunit.teardown`;
- `zunit.before_each`;
- `zunit.after_each`;
- `zunit.assertion`;
- `zunit.expectation`;
- `zunit.command_under_test`;
- `zunit.helper`;
- `zunit.fixture_reference`;
- `zunit.mock`;
- `zunit.stub`;
- `zunit.skip`;
- `zunit.todo`;
- `zunit.parameterized_case`;
- `zunit.secret_like`.

`zunit.dynamic_test` is extended for generated, dynamic, and eval-generated
test forms, and `zunit.parameterized_case` records bounded loop metadata
without executing loops or inferring generated test counts.

Hook observations record the hook name, hook kind, file scope, line evidence,
`body_modeled=false`, and `hook_executed=false`. Hook bodies are not modeled as
runtime side effects; cleanup-looking commands in hooks do not become
`shell.host_mutation`, file-write, network, package-manager, or command
execution evidence.

Assertion and expectation observations are emitted for supported fixture-backed
helpers such as `assert_success`, `assert_failure`, `assert_equal`,
`assert_output`, `refute_output`, `assert_file_exists`, and
`assert_dir_exists`. They record bounded assertion family, mode, argument
count, expectation kind, matcher, and redaction metadata. They do not imply
that an assertion executed, a test passed, output existed, status was known, or
files/directories existed.

Command-under-test observations are emitted for static `run ...` wrappers and
simple direct command forms inside test blocks. Metadata marks
`test_intent=true`, `command_under_test=true`, `command_executed=false`,
`stdout_known=false`, `stderr_known=false`, and `status_known=false`. Dynamic
commands remain bounded dynamic evidence, and ZUNIT2 does not emit shared
`shell.command`, host-mutation, network, package-manager, file-read, or
file-write observations from command-under-test lines.

Helper and fixture observations are syntactic references only. Static
repo-relative helper and fixture paths may include bounded `helper_path`,
`fixture_path`, and syntactic `resolved_path` metadata, but the extractor does
not source helpers, load fixtures, read files, check existence, or inspect the
filesystem. Dynamic, redacted, absolute, or repository-escaping targets remain
bounded dynamic/unknown/redacted metadata.

Mock and stub observations are declaration evidence only. Static targets may
record `target_command`, target kind, argument count, and behavior kind, but
metadata keeps `mocks_applied=false`, `stub_applied=false`,
`target_executed=false`, and `command_executed=false`. Mock/stub declarations
do not become network, package-manager, host-mutation, or target-behavior
proof.

Skip and todo observations record bounded reason metadata and keep
`skip_executed=false`, `todo_executed=false`, and `test_status_known=false`.
Secret-like suite/test names, assertion expected values, command arguments,
helper paths, fixture paths, mock/stub behavior strings, and skip/todo reasons
are redacted and may emit `zunit.secret_like` marker evidence with
`raw_value_stored=false`. Raw fake secret fixture markers are not serialized.

ZUNIT2 did not add canonicalization, readback, storage schema changes, or
CLI/MCP behavior.

## ZUNIT3 Implementation

ZUNIT3 adds selected raw-to-canonical mappings and a bounded summary helper at
`src/main/python/repomap_kg/zunit_readback.py`. The implementation keeps
zunit observations out of ordinary zsh canonicalization even though zunit raw
observations carry `language="zsh"` and `dialect="zsh"` for framework context.

Selected canonical mappings:

- `zunit.file` creates a `zunit.file` node linked from the source file with a
  `defines` edge;
- static `zunit.suite` creates a `zunit.suite` node linked from the zunit file
  with `contains`;
- static `zunit.test_case` creates a `zunit.test_case` node linked from its
  suite with `has_test_case` when the suite is known, otherwise from the file;
- hook observations create bounded `zunit.hook` nodes linked from the file with
  `has_hook`;
- static repo-relative `zunit.helper` and `zunit.fixture_reference`
  observations create file-reference edges with `uses_helper` and
  `uses_fixture`;
- static `zunit.command_under_test` creates command-under-test evidence and a
  `command_under_test` edge to a tool node with non-execution metadata;
- static `zunit.assertion` and `zunit.expectation` create assertion and
  expectation nodes linked from the enclosing test with `has_assertion` and
  `expects`;
- static `zunit.mock` and `zunit.stub` create declaration nodes linked from the
  file with `uses_mock` and `uses_stub`.

The `command_under_test` relationship is intentionally not an `executes` edge.
Its metadata preserves `test_intent=true`, `command_under_test=true`,
`command_executed=false`, `commands_executed=false`, `zunit_executed=false`,
`zsh_executed=false`, and `shell_executed=false`.

Raw-only ZUNIT3 kinds:

- `zunit.test_name`;
- `zunit.dynamic_test`;
- `zunit.parameterized_case`;
- `zunit.skip`;
- `zunit.todo`;
- `zunit.secret_like`.

Dynamic, redacted, unsafe, repository-escaping, and unsupported helper,
fixture, command, assertion, expectation, mock, and stub facts remain raw-only
or bounded evidence. They do not fabricate precise file, tool, host, network,
package, service, status, output, or mutation targets.

`summarize_zunit_evidence()` returns count-only data:

- raw kind counts;
- file, suite, test, hook, helper, fixture, command-under-test, assertion,
  expectation, mock, stub, skip, todo, parameterized-case, dynamic/unknown, and
  redaction counts;
- zunit-linked canonical node and edge counts by kind;
- safety markers showing raw payloads, source snippets, test bodies, expected
  outputs, command strings, helper bodies, fixture contents, mock bodies, secret
  values, and path examples are omitted.

ZUNIT3 dogfoods the public-safe fixtures in `src/test/fixtures/shell/zunit/`
through extraction, canonicalization, summary generation, and storage-row
preparation. It does not add a storage schema change or a CLI/MCP readback
surface.

## Design Principles

Zunit extraction should be:

- static;
- conservative;
- zsh-aware without pretending to know runtime zsh state;
- test-framework-aware without treating test intent as proof of execution;
- compatible with SH0 shell-family metadata;
- compatible with the completed zsh extraction phases without routing zunit
  files through ordinary zsh extraction wholesale;
- redaction-first;
- honest about dynamic behavior;
- useful for graph evidence without running zunit, zsh, helpers, mocks, or
  commands under test.

Future extraction should prefer bounded unknown observations over false
precision. Dynamic test names, helper paths, mock targets, assertions,
fixtures, command-under-test tokens, zsh expansions, and eval strings must not
become fabricated precise files, commands, services, package managers, network
targets, or host mutations.

## Non-Execution Policy

ZUNIT0 inherits SH0's static boundary and adds test-framework-specific
constraints. Future zunit extraction must not:

- execute zunit files, zunit suites, tests, hooks, helpers, mocks, stubs,
  assertions, skips, todos, or commands under test;
- invoke `zunit`, `zsh`, Bash, POSIX shell, Bats, awk, package managers,
  plugin managers, network tools, or external commands;
- call subprocess to inspect zunit or zsh parsing, expansion, test discovery,
  hooks, assertions, mocks, or runtime behavior;
- source zunit helpers, zsh profiles, plugins, completion files, or fixture
  setup files;
- evaluate command substitutions, process substitutions, globs, parameter
  expansions, arrays, aliases, eval strings, mocks, stubs, or dynamic test
  constructs;
- inspect runtime `$ZDOTDIR`, `$fpath`, `$path`, zunit state, plugin state,
  test temporary directories, fixture directories, or mock state by running a
  shell or framework;
- mutate host filesystem, environment, shell profiles, services, scheduled
  jobs, plugin directories, package state, process state, container runtime, or
  network state;
- store raw secret-like values, private source snippets, raw expected outputs,
  raw command bodies, helper bodies, fixture contents, or long command strings.

Every future zunit observation should include metadata equivalent to:

- `language="zsh"`;
- `dialect="zsh"`;
- `test_framework="zunit"`;
- `static_only=true`;
- `shell_executed=false`;
- `zsh_executed=false`;
- `zunit_executed=false`;
- `tests_executed=false`;
- `assertions_executed=false`;
- `commands_executed=false`;
- `fixtures_loaded=false`;
- `mocks_applied=false`.

## Relationship To SH0, Bash, Bats, Awk, And Zsh

Zunit belongs in the shell-family roadmap, but it should be modeled as a test
framework layered over zsh-style source. It may reuse shared `shell.*` kinds
where those kinds honestly describe shell-family syntax:

- `shell.script`;
- `shell.function`;
- `shell.assignment`;
- `shell.export`;
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

Shared observations emitted from zunit source must carry zunit context metadata
and preserve non-execution semantics. A command under test, hook body command,
mock body, helper reference, or assertion expression is source/test intent, not
proof that a command ran, a test passed, a helper loaded, a file existed, a host
mutated, a package manager ran, or a network call occurred.

Use zunit-specific observations where shared `shell.*` or zsh-specific facts
would be misleading:

- suites and test cases are test-framework structure;
- assertion and expectation syntax is test intent;
- command-under-test wrappers must not become ordinary runtime execution;
- mocks and stubs are test doubles, not actual target command behavior;
- skips and todos are test metadata, not branch execution;
- fixtures and temporary directories need test-context semantics;
- helpers may be zsh files, but loading them from a zunit suite should remain a
  zunit relationship.

Bash, Bats, awk, zsh, PowerShell, generic shell, and existing classification
behavior remain unchanged by this design phase.

## Zunit-Specific Raw Kind Policy

Use zunit-specific observations for facts that are test-framework-specific or
would otherwise imply unsafe runtime semantics.

| Kind | Planned Phase | Purpose |
| --- | --- | --- |
| `zunit.file` | ZUNIT1 | File-level zunit suite evidence. |
| `zunit.suite` | ZUNIT1 | Suite or file-level grouping evidence when visible. |
| `zunit.test_case` | ZUNIT1 | Static test case evidence. |
| `zunit.test_name` | ZUNIT1 | Bounded name evidence for static, dynamic, or redacted names. |
| `zunit.dynamic_test` | ZUNIT1/ZUNIT2 | Computed or generated test structure. |
| `zunit.setup` | ZUNIT2 | Suite or case setup intent. |
| `zunit.teardown` | ZUNIT2 | Suite or case teardown intent. |
| `zunit.before_each` | ZUNIT2 | Per-test setup-like hook intent. |
| `zunit.after_each` | ZUNIT2 | Per-test teardown-like hook intent. |
| `zunit.hook` | ZUNIT2 | Other framework hook evidence. |
| `zunit.assertion` | ZUNIT2 | Assertion helper or assertion expression evidence. |
| `zunit.expectation` | ZUNIT2 | Bounded expected status/output/file/state evidence. |
| `zunit.command_under_test` | ZUNIT2 | Command intent wrapped by a zunit helper or fixture pattern. |
| `zunit.helper` | ZUNIT2 | Static helper load/reference evidence. |
| `zunit.fixture_reference` | ZUNIT2 | Static fixture/temp path reference evidence. |
| `zunit.mock` | ZUNIT2 | Mock declaration evidence. |
| `zunit.stub` | ZUNIT2 | Stub declaration evidence. |
| `zunit.skip` | ZUNIT2 | Skip metadata. |
| `zunit.todo` | ZUNIT2 | Todo/pending test metadata. |
| `zunit.parameterized_case` | ZUNIT2 | Parameterized or generated case evidence when safely bounded. |
| `zunit.secret_like` | ZUNIT2/ZUNIT3 | Zunit-owned redaction marker evidence. |

ZUNIT1 should focus on `zunit.file`, `zunit.suite`, `zunit.test_case`,
`zunit.test_name`, and bounded dynamic test/load markers. ZUNIT2 should focus
on hooks, assertions, expectations, commands under test, helpers, fixtures,
mocks, stubs, skips, todos, and redaction. ZUNIT3 should focus on selected
canonicalization, bounded readback, and fixture dogfooding.

## Detection And Classification Strategy

Future zunit classification should be explicit and conservative:

- classify fixture-backed zunit test files such as `.zunit` files only after
  ZUNIT1 implements tests for that extension;
- classify files with explicit zunit shebang or launcher evidence only when
  fixture-backed and unambiguous;
- treat paths such as `test/zunit/`, `tests/zunit/`, `spec/zunit/`, and
  `zunit/` as context, not sole evidence;
- recognize zunit framework tokens only in file types and paths that are already
  plausible zunit candidates, or when the syntax is explicit enough to avoid
  reclassifying ordinary zsh;
- keep zunit helper files that are plain `.zsh` under zsh classification unless
  a zunit file references them with a future zunit helper/load observation;
- do not classify Bash, Bats, awk, PowerShell, generic `.sh`, Makefiles, docs,
  task runners, plugin manager files, or shell scripts invoking `zunit` as
  zunit source merely because they mention zunit.

`.zunit` and other zunit-specific files should not be routed through ordinary
zsh extraction as plain startup/config scripts. Later phases may reuse zsh
scanner helpers for shell-compatible syntax, but emitted observations must keep
test-framework metadata and non-execution flags.

## Parser And Scanner Strategy

ZUNIT1 should start with a stdlib-only static scanner/tokenizer:

- no zunit invocation;
- no zsh or shell invocation;
- no parser/runtime dependency;
- line-aware, comment-aware, string-aware, and heredoc-aware scanning;
- basic brace/function tracking only where reliable;
- fixture-backed recognition for suite/test declarations and simple helpers;
- bounded unknown observations for unsupported syntax;
- false-positive avoidance over high recall.

Parser candidates such as Tree-sitter Bash/zsh grammars, a zsh parser, a small
custom zunit tokenizer, or other static parsers remain later-phase evaluation
topics. Parser adoption must consider dependency, license, packaging,
determinism, line-range quality, and cross-platform behavior in a dedicated
phase.

## Core Zunit Constructs

ZUNIT0 treats concrete syntax examples as public-safe design inputs for future
fixture-backed implementation. Future phases should verify exact supported
forms before extracting them.

Potential suite and test-case examples:

```zsh
# Static extraction example only. Do not execute.

describe "example tool"

test "reports version" {
  run ./bin/example --version
  assert_success
}
```

Potential setup/teardown examples:

```zsh
setup() {
  export EXAMPLE_MODE="fixture"
}

teardown() {
  rm -rf "$ZUNIT_TMPDIR/example"
}
```

Potential assertion and expectation examples:

```zsh
assert_success
assert_failure
assert_equal "$status" 0
assert_output --partial "version"
refute_output "FAKE_ZUNIT_OUTPUT_TOKEN"
```

Potential helper, fixture, mock, and stub examples:

```zsh
source "./helpers/common.zsh"
fixture_path="./fixtures/input.txt"
mock_command git status --short
stub_command curl --fail https://example.invalid/status
```

The exact forms above are not runtime commitments. They are design targets for
future scanner tests.

## Suite And Test-Case Policy

Future `zunit.file` observations should record file-level zunit evidence,
classification evidence, and non-execution metadata.

Future `zunit.suite` observations should record suite name, suite kind, line
range when reliable, and `suite_executed=false`. Suite names that are dynamic,
long, or secret-like should be bounded or redacted.

Future `zunit.test_case` observations should record:

- test name or redacted/bounded name evidence;
- `test_name_kind` such as `static`, `dynamic`, `redacted`, or `unknown`;
- source path;
- line range when reliable;
- enclosing suite if statically known;
- `body_modeled=false` initially or bounded counts in later phases;
- `test_intent=true`;
- `zunit_executed=false`;
- `tests_executed=false`;
- `shell_executed=false`;
- `zsh_executed=false`.

Generated or parameterized tests should become `zunit.dynamic_test` or
`zunit.parameterized_case` evidence with a `dynamic_reason`. Future extractors
must not execute loops, eval strings, arrays, command substitutions, or zsh
expansions to discover generated tests.

## Hook Policy

Future hook observations should distinguish:

- `zunit.setup`;
- `zunit.teardown`;
- `zunit.before_each`;
- `zunit.after_each`;
- `zunit.hook` for other framework hooks.

Metadata should include hook name, hook scope such as `suite`, `test_case`,
`file`, or `unknown`, line range when reliable, `body_modeled=false`,
`hook_executed=false`, `zunit_executed=false`, `zsh_executed=false`, and
`shell_executed=false`.

Commands inside hooks are setup/cleanup intent only. They should not become
ordinary runtime command execution, host-mutation proof, package-manager
evidence, network calls, or filesystem effects unless a later phase explicitly
adds bounded test-intent side-effect modeling.

## Assertion And Expectation Policy

Future `zunit.assertion` observations should record:

- assertion name;
- assertion family such as `status`, `output`, `line`, `file`, `directory`,
  `equality`, `mock`, `stub`, `unknown`;
- mode such as `exact`, `partial`, `regex`, `negated`, or `unknown`;
- argument count;
- enclosing test case when statically known;
- bounded redaction metadata;
- `assertion_executed=false`;
- `zunit_executed=false`;
- `shell_executed=false`.

Future `zunit.expectation` observations should summarize expectation kind and
count without storing large expected-output bodies or raw secret-like values.
Secret-like or long expected values should set `raw_value_stored=false` and
record redaction reason.

Assertions and expectations are source evidence. They are not proof that a test
ran, a command succeeded, output was produced, a file existed, or a mock was
called.

## Command-Under-Test Policy

Future `zunit.command_under_test` observations should model test intent, not
runtime execution.

Metadata should include:

- static command token when visible and safe;
- argument count or bounded argument summary;
- expected status if encoded by a zunit helper;
- negation if visible;
- enclosing test or hook context if known;
- `test_intent=true`;
- `command_under_test=true`;
- `command_executed=false`;
- `commands_executed=false`;
- `zunit_executed=false`;
- `zsh_executed=false`;
- `shell_executed=false`.

Do not emit ordinary host-mutation, network, package-manager, service, process,
filesystem mutation, or runtime `executes` evidence from command-under-test
lines in early zunit phases. If later canonicalization maps static commands to
tool nodes, the relationship must preserve command-under-test/non-execution
metadata.

## Helper And Fixture Policy

Future `zunit.helper` observations should record helper references without
executing or sourcing helper files. Static relative helper targets may be
normalized syntactically only when safe and repo-relative. Absolute,
home-relative, repository-escaping, command-substituted, computed, or
secret-like helper targets should remain dynamic, unknown, or redacted.

Future `zunit.fixture_reference` observations should distinguish:

- static repo-relative fixtures;
- framework temporary directories;
- computed paths;
- redacted or unknown paths.

The extractor must not read fixtures, check whether paths exist, create temp
directories, inspect helper contents, or resolve helper functions across files
unless a later phase explicitly scopes safe same-repository static resolution.

## Mock And Stub Policy

Future `zunit.mock` and `zunit.stub` observations should record test-double
declarations as intent only.

Metadata should include:

- mock or stub target when static and safe;
- target kind such as `command`, `function`, `external`, `dynamic`,
  `redacted`, or `unknown`;
- argument count or bounded behavior summary when safe;
- enclosing suite/test context when known;
- `mock_declared=true` or `stub_declared=true`;
- `mocks_applied=false`;
- `target_executed=false`;
- `zunit_executed=false`;
- `shell_executed=false`.

Mocks and stubs must not be used to infer actual command behavior, package
operations, network calls, host mutations, or filesystem changes.

## Skip, Todo, And Metadata Policy

Future `zunit.skip` observations should record bounded or redacted skip reasons
and enclosing context. Future `zunit.todo` observations should record bounded
todo/pending metadata. Neither kind proves a branch executed or a test result
occurred.

Future metadata observations should avoid raw payloads and large free-form
strings. Count-only readback should be preferred until canonicalization needs
stronger modeling.

## Redaction Policy

Zunit inherits SH0, Bash, Bats, awk, and zsh redaction rules for names or values
containing:

- password;
- passwd;
- secret;
- token;
- key;
- credential;
- apikey;
- pat;
- authorization;
- auth.

Zunit-specific sensitive contexts include:

- expected output strings;
- assertion/refutation arguments;
- command-under-test arguments such as `--token`, `--password`, and
  Authorization headers;
- fixture names or paths with secret-like components;
- helper paths with secret-like names;
- environment setup in hooks or tests;
- mock/stub behavior strings;
- private repository URLs in helper or plugin examples.

Rules:

- do not store raw secret-like values;
- preserve field/key/helper/assertion names and redaction reason;
- set `raw_value_stored=false`;
- avoid over-matching ordinary words such as `path` as `pat`;
- fixtures should use fake markers that implementation tests prove absent from
  serialized raw observations, canonical graph records, storage rows, summaries,
  and reports.

## Dynamic And Unknown Policy

Future extractors should emit bounded dynamic or unknown observations for:

- dynamic suite names;
- computed or generated test names;
- parameterized test loops;
- computed helper paths;
- computed fixture paths;
- dynamic mock or stub targets;
- dynamic assertion helper names;
- `run "$cmd"` or equivalent command-under-test wrappers;
- array-derived commands;
- `eval "$text"`;
- command substitution in assertions or expected values;
- zsh parameter expansion flags and glob qualifiers inside zunit source;
- sourced helpers whose targets are computed or repository-escaping.

Dynamic observations should record `dynamic_reason`. They must not infer
precise command, helper, fixture, package, URL, service, environment, file, or
host-mutation targets.

## False-Positive Boundaries

Future scanners should suppress zunit extraction from:

- line comments and block comments if supported by future scanning;
- quoted strings;
- heredoc bodies;
- arrays containing assertion-like or command-like strings;
- ordinary zsh functions that are not zunit hooks;
- strings containing suite/test/assertion-looking text;
- README code blocks and documentation examples outside zunit-classified files;
- case pattern labels;
- completion descriptions that look like commands;
- plugin manager declarations that merely mention zunit;
- zsh glob qualifiers or parameter expansions that resemble grouping syntax.

Prefer missing a construct over extracting dangerous false positives.

## Canonicalization And Readback Targets

ZUNIT3 should follow the BASH5, BATS3, AWK3, and ZSH4 pattern:

- selected raw-to-canonical mappings only;
- raw-only list for dynamic, unsupported, or runtime-sensitive facts;
- bounded count-only summary helper;
- public-safe fixture dogfooding;
- secret non-leakage assertions.

Potential canonical mappings:

- zunit files as suite/file nodes;
- static suites and test cases as test nodes linked from the file;
- static helpers as helper/file dependency edges when repo-relative and safe;
- static fixture references as bounded file references;
- command-under-test evidence as test intent with `command_executed=false`;
- assertions and expectations as bounded expectation evidence without raw
  output blobs;
- mocks and stubs as test-double evidence without applying them;
- skips and todos as bounded metadata or raw-only evidence;
- dynamic and unsupported facts as raw-only.

Readback should be count-only first:

- zunit file count;
- suite count;
- test-case count;
- hook counts by kind;
- assertion and expectation counts by family;
- command-under-test count;
- helper and fixture reference counts;
- mock and stub counts;
- skip and todo counts;
- dynamic/unknown count;
- secret-like redacted count;
- canonical node and edge counts.

Readback must not include raw source snippets, raw expected outputs, raw command
strings, raw secrets, unbounded path lists, private absolute paths, helper
bodies, fixture contents, or mock bodies.

## Fixture Strategy

Public-safe ZUNIT0 examples live under `docs/examples/zunit/`.

Implementation fixtures should start in ZUNIT1 or later under:

```text
src/test/fixtures/shell/zunit/
```

Suggested future fixture files:

- `basic.zunit`;
- `suites-and-cases.zunit`;
- `hooks.zunit`;
- `assertions-and-commands.zunit`;
- `helpers-fixtures-mocks.zunit`;
- `dynamic.zunit`;
- `redaction.zunit`;
- `false-positives.zunit`.

Fixtures and examples must:

- be clearly labeled static extraction examples only;
- not require execution;
- remain non-executable by default;
- use redacted placeholders rather than real or realistic secret values;
- use `.invalid` domains for URI-like examples;
- avoid real private paths;
- avoid real credentials, tokens, private keys, or operational policy scripts;
- keep mutating-looking commands in test bodies or hooks with clear
  non-execution boundaries.

## Roadmap

ZUNIT1 acceptance sketch:

- classify explicit zunit files such as `.zunit` when fixture-backed;
- avoid routing zunit files through ordinary zsh extraction;
- emit `zunit.file`, `zunit.suite`, `zunit.test_case`, and
  `zunit.test_name`;
- emit bounded dynamic test evidence where safe;
- preserve zsh/generic shell/Bats/awk/Bash behavior;
- no execution;
- no parser/runtime dependency;
- combined final gate passes.

ZUNIT2 acceptance sketch:

- emit hook observations;
- emit assertion and expectation observations;
- emit command-under-test observations with non-execution metadata;
- emit helper and fixture references;
- emit mock and stub observations;
- emit skip/todo observations;
- redact secret-like names and values;
- preserve dynamic/unknown boundaries;
- no zunit, zsh, shell, helper, mock, assertion, or command execution.

ZUNIT3 acceptance sketch:

- add selected zunit raw-to-canonical mappings;
- add bounded count-only zunit evidence summary/readback helper;
- dogfood public-safe fixtures through extraction, canonicalization, summary,
  and storage-row preparation;
- preserve test-intent and non-execution semantics;
- leave dynamic, unsupported, and runtime-sensitive facts raw-only;
- prove fake secret non-leakage;
- avoid storage schema redesign unless a later dedicated phase accepts it.
