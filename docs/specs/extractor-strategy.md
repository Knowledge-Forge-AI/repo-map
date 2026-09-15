# RepoMap Extractor Strategy

## Goal

Extractors should turn source files into deterministic, evidence-backed facts.
They should not try to understand every possible runtime behavior. They should
instead emit honest facts with confidence labels.

## General Extractor Contract

An extractor receives:

- repository root;
- file path;
- file content;
- language and role hints;
- active profile settings.

It emits raw JSONL observations. Each observation should include:

- observation kind;
- stable source identity;
- file path;
- line range when known;
- extracted name or value;
- related target when known;
- confidence;
- extractor name and version;
- metadata for language-specific details.

The initial versioned JSONL schema is documented in
[Raw Observation Schema](raw-observation-schema.md).

## Dependency And Capability Governance

Extractor dependencies, declared capabilities, and the extraction admission
boundary are governed by
[ADR 0050](../adr/2026/08/0050-extractor-dependency-and-capability-architecture.md).
This strategy conforms to it and does not restate it.

Three points from that decision bound everything below. Extraction never
evaluates target repository code and never contacts the network, at any
setting rather than merely by default. Capability is declared per
language-dialect as an unordered set, never as an ordinal tier, and is a
separate axis from confidence. Every non-standard-library parser, grammar,
resolver, or toolchain must pass the adoption gate in ADR 0050 D7, and the
existing dependency-free implementation wins whenever that evidence is
incomplete.

Candidate libraries named in this document are directions admissible for
evaluation, not selections. RepoMap has adopted no extractor dependency.

## Shell Extractor

Shell support is first-class because many infrastructure repositories route
behavior through shell scripts.

The shell extractor should identify:

- shebang and shell family;
- functions;
- sourced files via `source` and `.`;
- command invocations;
- environment variable reads and writes;
- file reads, writes, copies, moves, and deletes when obvious;
- redirections;
- pipelines;
- subprocess boundaries;
- calls to Python, Ruby, Nix, Docker, Git, Homebrew, and other tooling;
- host-mutating commands such as package installation, service changes, and
  privileged operations.

Shell edges should often be `heuristic` rather than `extracted`, especially when
commands are dynamic.

The initial shell extractor is intentionally conservative and dependency-free:
it emits line-backed `shell.command` observations for simple command invocations
and `shell.source` observations for static `source` and `.` includes, and
`shell.env` observations for static environment variable reads/writes. It also
emits first-pass `shell.host_mutation` observations for obvious package
management, service management, system activation, and filesystem mutation
command shapes. Filesystem mutation classification is intentionally limited to
obvious `rm`, `mv`, and `cp` shapes that touch host paths such as `/...` or
`~...`, or use a recognized privilege wrapper. It skips comments, shell control
keywords, invalid shell syntax, dynamic source paths, and absolute or
repository-escaping source paths. Commands target tools as `tool:<command>`;
sourced files target `file:<repo-relative-path>`; environment facts target
`env:<VARIABLE>`; host mutations target `host:<category>`. Parser-backed shell
expansion remains a future slice.

Candidate parser families include `mvdan/sh`, Tree-sitter Bash, and bashlex.
No selection has been made, and any selection must pass the ADR 0050 adoption
gate. Two constraints apply before language coverage, AST quality, license,
packaging, and testability are even compared.

First, admissibility attaches to an invocation mode, not to a library.
`mvdan/sh` separates parsing from expansion from interpretation; only its
parse-only mode could be admissible, because expansion and interpretation
evaluate shell code.

Second, candidates must be compared per dialect rather than per family. Bash,
zsh, awk, Bats, and zunit are separate grammars that this project already
extracts separately, and a candidate that covers Bash well may not address the
others at all. "Supports shell" is not a capability claim.

The future shared shell-family substrate is documented in
[Shell-Family Extraction Design](../extraction/shell-family-extraction-design.md).
That design keeps the default taxonomy under `shell.*`, uses dialect metadata
for Bash, Bats, awk, zsh, and zunit facts, and preserves the static
non-execution boundary before any Bash-specific implementation phase begins.
Bash-specific dialect detection, raw-kind boundaries, fixture strategy, and the
BASH1-BASH5 roadmap are documented in
[Bash Extraction Design](../extraction/bash-extraction-design.md).
BASH1 adds evidence-based Bash classification and conservative static
structural raw observations for scripts, shell options, functions, assignments,
exports, source includes, command-substitution markers, dynamic invocation
markers, and redacted secret-like assignments. Command/argument extraction,
redirects, heredocs, side effects, canonicalization, and readback remain later
BASH phases.
BASH2 adds conservative static Bash command, argument, external-command,
pipeline, command-chain, redirect, heredoc, and process-substitution raw
observations. It preserves order and bounded metadata but does not execute shell
code, model full control/data flow, or classify host mutations and operational
side effects. BASH3 adds conservative static Bash side-effect observations for
environment, file, redirect-derived file effects, network, package manager,
service, scheduled-job, container/runtime, infrastructure, security, credential,
permission, ownership, archive, symlink, shell-profile, and umbrella host
mutation patterns. It keeps read-only commands distinct from mutating commands
and preserves the static non-execution boundary. BASH4 adds conservative static
Bash advanced-safety observations for aliases, indexed and associative arrays,
traps, arithmetic expressions, test expressions, case patterns, and deeper
dynamic boundaries. It does not execute shell code, expand aliases or arrays,
evaluate traps/tests/arithmetic, canonicalize Bash facts, or add readback.
BASH5 adds selected Bash canonical graph mappings and bounded count-only
dogfooding summaries for public-safe fixtures. Dynamic, unsupported, and
runtime-sensitive Bash details remain raw-only, and no shell code is executed.
Bats-specific extraction strategy is documented in
[Bats Extraction Design](../extraction/bats-extraction-design.md). BATS0 keeps
Bats test-framework semantics distinct from ordinary Bash extraction and
defines future `.bats` classification, test-case, hook, helper-load, `run`,
assertion, fixture, canonicalization, and bounded-readback phases without
changing behavior. BATS1 implements the first static slice: `.bats`
classification plus `bats.file`, `bats.test_case`, hook, and `bats.load` raw
observations. It does not execute Bats or shell code, route `.bats` through
ordinary Bash extraction, model `run` commands or assertions, classify side
effects, canonicalize Bats facts, or add readback. BATS2 adds static
`bats_load_library`, `run`, assertion/refutation, skip, helper-reference,
fixture-reference, output-expectation, and status-expectation raw observations.
It treats commands as test intent, does not execute Bats or shell code, and
does not classify Bats test-body commands as host mutations. BATS3 adds
selected Bats canonical mappings and bounded count-only summaries for
public-safe fixtures. `bats.run` canonical evidence remains command-under-test
intent with `command_executed=false`; dynamic and runtime-sensitive Bats facts
remain raw-only.
Awk-specific extraction strategy is documented in
[Awk Extraction Design](../extraction/awk-extraction-design.md). AWK0 defines
awk's shell-adjacent relationship to the shared taxonomy, awk-specific raw
kinds, file/shebang/dialect detection, conservative scanner strategy,
IO/pipe/`system()` safety boundaries, redaction, fixtures, and the AWK1-AWK3
roadmap. AWK1 implements the first static slice: `.awk` and awk-shebang
classification plus `awk.program`, `awk.begin`, `awk.end`,
`awk.pattern_action`, `awk.function`, `awk.variable_assignment`,
`awk.field_reference`, `awk.record_reference`, and `awk.dynamic_expression`
raw observations. It does not execute awk, extract embedded awk one-liners from
shell scripts, model IO/pipes/`system()`, canonicalize awk facts, or add
readback. AWK2 adds static `awk.builtin_call`, `awk.user_function_call`,
`awk.file_read`, `awk.file_write`, `awk.pipe_read`, `awk.pipe_write`,
`awk.system_call`, `awk.redirect`, `awk.include`, `awk.extension`, and
`awk.secret_like` observations. AWK2 treats IO, command pipes, and `system()`
as source intent only: no files are opened, no commands are executed, and no
host mutation is proven. AWK3 adds selected awk canonical graph mappings and
bounded count-only dogfooding summaries for public-safe fixtures. Awk IO,
pipes, and `system()` remain source intent, not runtime execution or
host-mutation proof, and dynamic or unsupported awk facts remain raw-only.
Zsh-specific extraction strategy is documented in
[Zsh Extraction Design](../extraction/zsh-extraction-design.md). ZSH0 defines
zsh dialect boundaries, startup/profile, option, autoload/fpath, zstyle,
plugin/completion, glob/parameter expansion, side-effect, redaction, dynamic,
fixture, and ZSH1-ZSH4 roadmap policy. It does not implement zsh extraction,
change classification behavior, execute zsh or shell code, or add a
parser/runtime dependency. ZSH1 adds static zsh classification and basic
structural raw observations for scripts, startup files, options, functions,
assignments, exports, source includes, command-substitution markers, dynamic
markers, and redaction. It does not execute zsh, load plugins, model
commands/pipelines/redirects, canonicalize zsh facts, or add readback. ZSH2
adds static zsh command, argument, external-command, pipeline, chain, redirect,
heredoc, autoload/fpath, zstyle, zmodload, bindkey, compinit, completion,
plugin, theme, and prompt raw observations. It treats startup, plugin,
completion, and command evidence as source/configuration intent, not runtime
execution. ZSH3 adds static zsh array, associative-array,
parameter-expansion, glob, path-reference, dynamic-boundary, and source-intent
side-effect raw observations. It does not expand globs or parameters, execute
commands, load plugins, prove host mutation, canonicalize zsh facts, or add
readback. ZSH4 adds selected zsh canonical graph mappings and bounded
count-only dogfooding summaries for public-safe fixtures. Zsh startup,
plugin, completion, command, network/package, file, and host-mutation evidence
remain source/configuration intent, not runtime execution or host-mutation
proof, and dynamic or unsupported zsh facts remain raw-only.
Zunit-specific extraction strategy is documented in
[Zunit Extraction Design](../extraction/zunit-extraction-design.md). ZUNIT0
defines zunit test-framework semantics, detection boundaries, conservative
scanner strategy, zunit-specific raw kinds, helper/fixture/mock/assertion
policies, redaction, dynamic boundaries, public-safe examples, and the
ZUNIT1-ZUNIT3 roadmap. It does not implement zunit extraction, change
classification behavior, execute zunit or zsh code, or add a parser/runtime
dependency. ZUNIT1 adds static `.zunit` classification and basic
test-structure raw observations for zunit files, suites, test cases, test
names, and bounded dynamic tests. It does not execute zunit or zsh, run
assertions, run commands under test, model hooks/helpers/fixtures/mocks,
canonicalize zunit facts, or add readback. ZUNIT2 adds static zunit hook,
assertion, expectation, command-under-test, helper, fixture, mock, stub, skip,
todo, parameterized-case, redaction, and dynamic-boundary observations. It
treats all test-framework facts as source/test intent, not execution, and does
not run tests, assertions, helpers, fixtures, mocks/stubs, commands under test,
or zsh. ZUNIT3 adds selected zunit canonicalization and bounded count-only
dogfooding for public-safe fixtures. Commands under test, helpers, fixtures,
hooks, assertions, mocks, and stubs remain source/test intent, not runtime
execution or pass/fail proof, and dynamic or unsupported zunit facts remain
raw-only.

## Nix Extractor

The Nix extractor is static only. Nix evaluation is not part of extraction.

Static extraction should identify:

- imports;
- flake outputs;
- packages;
- apps;
- checks;
- dev shells;
- overlays;
- references to scripts or generated files.

Earlier revisions of this document proposed optional "safe evaluation" through
commands such as `nix flake show` or controlled `nix eval`. That direction is
withdrawn. Those commands evaluate Nix expressions and may fetch flake inputs
over the network, so they fall outside the extraction admission boundary in
ADR 0050 D3 at every setting, not merely by default. There is no enabled mode
in which extraction evaluates Nix.

Safety here is a property of the invocation mode rather than of the Nix tooling:
`nix-instantiate --parse` produces a syntax tree without evaluating, which makes
it an admissible candidate direction where the evaluating modes are not. It is a
candidate subject to the ADR 0050 adoption gate, not a selection, and it is not
the only conceivable static-parse direction for Nix.

## Python Extractor

The Python extractor uses the standard-library `ast` module. Its accepted
grammar is therefore whatever the running interpreter accepts, and capability is
bound to that exact interpreter identity rather than to a version range. Whether
a given file parsed is a per-file result to be recorded, not something derivable
from a declared range. It should identify:

- modules;
- imports;
- classes;
- functions and methods;
- calls where statically visible;
- `if __name__ == "__main__"` entry points;
- console-script style wrappers when discoverable from project metadata.

## Ruby Extractor

The Ruby extractor should start with conservative support:

- `require` and `load`;
- classes and modules;
- methods;
- executable scripts;
- obvious shell-outs or file operations.

The implemented Ruby extractor is a conservative dependency-free scanner. Ruby
support may later use `Ripper` or another parser, but no parser has been
selected and any selection must pass the ADR 0050 adoption gate, including its
primary-source licensing review and its packaging and platform requirements. A
parser reachable only through a CRuby extension would make Ruby extraction
depend on an operator-supplied external runtime, which is a distinct ownership
shape with its own evidence obligations.

## Awk and AppleScript Extractors

Awk and AppleScript can begin as lightweight extractors. They should produce
file-level facts, entry-point facts, and coarse references where reliable.

## PowerShell Extractor

PowerShell extraction is a static, non-executing bridge between structured
language extraction and shell-family extraction. PWSH1 classifies `.ps1`,
`.psm1`, and `.psd1` files and emits basic raw structural observations for
scripts, modules, manifests, functions, params, requires directives, module
imports, dot-sourcing, bounded dynamic invocation, secret-like markers, and
simple manifest fields. PWSH2 adds conservative command, argument, alias,
external-command, splat, and pipeline raw observations. PWSH3 adds
conservative static side-effect observations for file, environment, registry,
network, remoting, process, service, scheduled-task, package-management,
security-policy, and credential-handling patterns without executing
PowerShell. PWSH4 adds conservative literal `.psd1` manifest raw observations
for fields, dependencies, file references, exports, private data, bounded
unknown expressions, and secret-like value redaction. PWSH5 adds conservative
static alias-definition observations, literal splat-assignment summaries,
call-site splat links, richer dynamic invocation metadata, and block
comment/here-string false-positive suppression. PWSH6 adds selected canonical
graph mappings and bounded count-only fixture dogfooding summaries while
leaving dynamic, unsupported, and fine-grained argument/pipeline details
raw-only. The broader taxonomy, safety policy, redaction rules, fixture
strategy, and remaining roadmap are documented in
[PowerShell Extraction Design](../extraction/powershell-extraction-design.md).

## Testing

Each extractor should have:

- unit tests for small language fixtures;
- integration tests for a synthetic mixed-language repository;
- golden raw observation fixtures;
- normalization tests for canonical graph output.

Extractor tests should include dynamic or ambiguous cases and assert confidence
labels rather than pretending every edge is fully resolved.
