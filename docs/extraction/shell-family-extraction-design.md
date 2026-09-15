# Shell-Family Extraction Design

Status: SH0 defines the shared shell-family extraction substrate, taxonomy,
safety policy, fixture strategy, and roadmap before Bash-specific implementation
begins.

## Purpose

Shell-family extraction should give RepoMap useful graph evidence from
operational scripts while staying static, conservative, and honest about
uncertainty. Bash, Bats, awk, zsh, and zunit share enough syntax and operational
surface area that their extractors should use a common model for commands,
arguments, pipelines, redirects, dynamic execution, redaction, side effects,
canonicalization, and bounded readback.

SH0 is a design phase only. It does not implement a new extractor, alter the
existing conservative shell extractor, add classification, change storage, or
add parser/runtime dependencies.

The current shell extractor already emits a small conservative set of
`shell.command`, `shell.source`, `shell.env`, and `shell.host_mutation`
observations. SH0 defines the larger shared model that later Bash, Bats, awk,
zsh, and zunit phases should grow toward without breaking that existing
boundary.

## Design Principles

Future shell-family extraction should be:

- static;
- conservative;
- dialect-aware;
- side-effect-aware;
- redaction-first;
- honest about dynamic behavior;
- useful for canonical graph evidence without executing source.

When the extractor cannot statically understand a construct, it should emit a
bounded unknown or dynamic observation rather than inventing a precise fact.

## Non-Execution Policy

Shell-family extraction must be static.

Future extraction must not:

- execute shell scripts or test files;
- invoke `sh`, `bash`, `zsh`, `awk`, `bats`, `zunit`, package managers, or
  external commands to inspect behavior;
- call subprocess to ask a shell how it would parse or expand code;
- resolve aliases, functions, arrays, globs, command substitutions, traps,
  process substitutions, or dynamic commands by running code;
- run package managers or network commands;
- mutate the host filesystem, environment, shell profiles, services, scheduled
  jobs, process table, package state, or container runtime;
- read real private shell scripts into public fixtures or docs;
- store raw secret values in observations, canonical metadata, fixtures, or
  bounded readback.

Static source text may contain command-looking syntax. Extractors should record
evidence about that syntax without executing it and should mark metadata with
`static_only=true` and `shell_executed=false`.

## Dialect Strategy

The default shared raw observation prefix should be `shell.*`.

Use metadata to identify dialect and dialect features:

- `dialect`: `sh`, `bash`, `bats`, `awk`, `zsh`, or `zunit`;
- `dialect_feature`: a short feature name such as `array-assignment`,
  `bats-test-case`, `awk-pattern-action`, or `zsh-glob-qualifier`;
- `static_only=true`;
- `shell_executed=false`.

Use dialect-specific raw kinds only when the shared taxonomy cannot honestly
represent the fact.

Potential dialect-specific observations include:

- `bash.array_assignment`;
- `bash.shell_option`;
- `bash.trap`;
- `bash.builtin`;
- `bash.arithmetic`;
- `zsh.autoload`;
- `zsh.zstyle`;
- `zsh.glob_qualifier`;
- `bats.test_case`;
- `bats.setup`;
- `bats.teardown`;
- `awk.pattern_action`;
- `awk.function`;
- `zunit.test_case`.

This keeps common command, argument, redirect, source, environment, dynamic,
redaction, and side-effect handling in one substrate while allowing each
dialect to add facts that would be misleading under a generic `shell.*` kind.

## Shared Observation Taxonomy

Future shared raw observations should include these kinds:

| Kind | Meaning |
| --- | --- |
| `shell.script` | A shell-family source file or script-like entry point. |
| `shell.function` | A statically named function definition. |
| `shell.assignment` | A variable assignment or declaration. |
| `shell.export` | An exported variable or export statement. |
| `shell.source` | A static or bounded dynamic source/dot include. |
| `shell.command` | A shell builtin, function, or command invocation. |
| `shell.command_argument` | A named, positional, switch-like, or redacted command argument. |
| `shell.external_command` | An obvious external executable/tool invocation. |
| `shell.pipeline` | A pipeline with segment ordering. |
| `shell.command_chain` | A command list connected by sequencing or boolean operators. |
| `shell.redirect` | A file descriptor redirect, here-string, or static redirect target. |
| `shell.heredoc` | A heredoc boundary and redaction summary. |
| `shell.process_substitution` | Process substitution such as `<(...)` or `>(...)`. |
| `shell.command_substitution` | Command substitution such as `$(...)` or backticks. |
| `shell.dynamic_invocation` | Dynamic command execution such as `eval`, `$cmd`, or `"${cmd[@]}"`. |
| `shell.env_read` | A read from an environment variable. |
| `shell.env_write` | A write to an environment variable. |
| `shell.file_read` | A likely static file read reference. |
| `shell.file_write` | A likely static file write or directory mutation reference. |
| `shell.host_mutation` | A likely host mutation category. |
| `shell.network_call` | A likely network request or download command. |
| `shell.package_manager` | A package manager operation. |
| `shell.secret_like` | A redacted secret-like variable, argument, heredoc, or assignment. |

Optional shared kinds can be added when fixtures prove they are useful:

- `shell.alias`;
- `shell.trap`;
- `shell.shell_option`;
- `shell.subshell`;
- `shell.test_expression`;
- `shell.glob`;
- `shell.path_reference`.

## Confidence And Dynamic Metadata

RepoMap raw observations should continue to use the existing confidence values:

- `extracted`;
- `heuristic`;
- `unknown`.

If the design needs a conceptual dynamic state, record it in metadata rather
than adding a new schema confidence value:

- `resolution="dynamic"`;
- `dynamic_reason="command-substitution"`;
- `dynamic_reason="process-substitution"`;
- `dynamic_reason="eval"`;
- `dynamic_reason="variable-command"`;
- `dynamic_reason="computed-source"`;
- `dynamic_reason="computed-redirect"`;
- `dynamic_reason="indirect-expansion"`;
- `dynamic_reason="glob-expansion"`;
- `dynamic_reason="trap-handler"`;
- `dynamic_reason="unresolved-alias"`.

Dynamic and unknown observations should be first-class evidence. They are better
than false precision.

## Core Constructs

Future shell-family implementation phases should model these constructs
conservatively.

### Shebangs And Dialect Markers

Recognize:

- shebangs such as `#!/bin/sh`, `#!/usr/bin/env bash`, and
  `#!/usr/bin/env zsh`;
- file extensions and test framework markers;
- dialect-specific feature use that may upgrade a generic shell hint to a more
  specific dialect.

Shebang extraction should not invoke the interpreter or check whether the path
exists.

### Shell Options

Recognize:

- `set -e`;
- `set -euo pipefail`;
- `set -o nounset`;
- `shopt -s nullglob`;
- zsh options when later zsh phases define their subset.

Options can be represented as `shell.shell_option` or dialect-specific kinds
when needed. They should include dialect metadata and line evidence.

### Functions

Recognize:

- `name() { ... }`;
- `function name { ... }`;
- dialect-specific forms such as zsh autoloaded functions when a zsh phase adds
  support.

Function extraction should record function name, line range when available,
dialect, and source file. It should not execute function bodies.

### Assignments And Exports

Recognize:

- `NAME=value`;
- `local NAME=value`;
- `declare NAME=value`;
- `typeset NAME=value`;
- `readonly NAME=value`;
- `export NAME=value`;
- `export NAME`;
- assignments before a command, such as `FOO=bar command`.

Assignments should record variable names, declaration keyword, export status,
scope if known, value presence, redaction status, and whether the value is
static or dynamic. Secret-like values must not be stored.

### Sourcing

Recognize:

- `. ./file.sh`;
- `source ./file.bash`;
- zsh and Bash helper-loading conventions when static.

Static same-repository source targets may become file references in future
phases. Computed, absolute, repository-escaping, or command-substituted targets
should remain bounded dynamic/unknown observations unless a later phase
explicitly scopes safe same-repo resolution.

### Commands And Arguments

Recognize simple command invocations, builtins, external tools, and arguments.
Avoid treating comments, strings, heredoc bodies, assignments, hashtable-like
data, or manifest-like docs as command calls.

Command observations should include:

- original token;
- normalized command when safe;
- command family: `builtin`, `external`, `function`, `wrapper`, `unknown`;
- wrapper commands such as `sudo`, `env`, `command`, `builtin`, `time`,
  `nohup`, and `xargs`;
- argument count;
- static/dynamic/redaction markers;
- `static_only=true`;
- `shell_executed=false`.

Argument observations should distinguish:

- named flags such as `--output`;
- short flags such as `-o`;
- switch-like flags without values;
- positional arguments;
- redacted secret-like values;
- values supplied by variables, arrays, command substitutions, or globs.

### Command Chains

Recognize command-chain separators and control operators:

- `;`;
- `&&`;
- `||`;
- Bats and shell test command lists where safe.

The first implementation should preserve order and operator metadata without
claiming full control-flow semantics.

### Pipelines

Recognize:

- `|`;
- `|&`.

Pipelines should record segment count, segment order, operator, line range, and
the command observations for each segment. They should not model object or byte
flow beyond static ordering.

### Redirects

Recognize:

- `>`;
- `>>`;
- `<`;
- `2>`;
- `2>&1`;
- `&>`;
- `<<<`.

Redirect observations should record file descriptor, mode, target kind, and
redaction state. Static relative targets may become file references. Computed
targets should remain dynamic.

### Heredocs

Recognize:

- `<<EOF`;
- `<<-EOF`;
- quoted delimiters such as `<<'EOF'`;
- heredoc bodies only as bounded summaries.

Heredoc observations should include delimiter style, quoted/unquoted marker,
body line count, and whether secret-like assignments or values were redacted.
Do not store raw heredoc bodies in ordinary observations or readback.

### Substitutions And Subshells

Recognize:

- command substitution: `$(...)` and backticks;
- process substitution: `<(...)` and `>(...)`;
- subshells: `( ... )`.

These constructs should record bounded dynamic or structural observations. They
should not execute, expand, or infer exact runtime command targets unless the
inner syntax is explicitly modeled as static source text by a future phase.

### Dynamic Execution

Recognize:

- `eval "$cmd"`;
- `$cmd`;
- `"${cmd[@]}"`;
- `bash -c "$text"`;
- dynamically computed source paths;
- alias or function names that cannot be resolved statically.

Emit `shell.dynamic_invocation` with `dynamic_reason` and avoid precise command
targets unless the command token is statically visible without execution.

### Traps And Aliases

Recognize:

- `trap 'cleanup' EXIT`;
- `alias ll='ls -la'`.

Trap handlers and aliases should be bounded observations. Later dialect phases
may decide whether same-file alias definitions can influence later static
normalization. Cross-file alias resolution should remain out of scope until it
has a dedicated phase and tests.

## Command Normalization

Future normalization should start small and fixture-backed.

Builtins to recognize:

- `cd`;
- `pwd`;
- `test`;
- `[`;
- `echo`;
- `printf`;
- `read`;
- `export`;
- `source`;
- `.`;
- `alias`;
- `trap`;
- `set`;
- `shift`;
- `return`;
- `exit`.

Wrapper prefixes should be modeled explicitly:

- `command`;
- `builtin`;
- `env`;
- `sudo`;
- `time`;
- `nohup`;
- `xargs`.

Examples:

- `sudo apt install x` may later record both wrapper evidence and underlying
  package-manager intent when the argument pattern is static.
- `env FOO=bar command` may later record an environment overlay and the wrapped
  command.
- `find ... -exec ...` and `xargs ...` should be conservative and may emit
  dynamic or unknown command evidence rather than pretending to model runtime
  expansion.

Assignments and redirects before or after commands should not hide the command
token, but they should not be evaluated.

## Side-Effect Taxonomy

Future shell-family extractors should use these operational side-effect
categories:

- file read;
- file write;
- directory mutation;
- env read;
- env write;
- process execution;
- service control;
- scheduled job or cron mutation;
- package management;
- network call or download;
- archive extraction;
- permission or ownership mutation;
- symlink mutation;
- shell profile mutation;
- credential or secret handling;
- policy or security change;
- container or runtime mutation;
- unknown host mutation.

Likely command families for later implementation:

- file and directory reads: `cat`, `grep`, `find`, `test`, `[`;
- file and directory writes: `touch`, `mkdir`, `rm`, `mv`, `cp`, `install`,
  `ln`;
- permissions and ownership: `chmod`, `chown`, `chgrp`;
- network: `curl`, `wget`, `nc`;
- package managers: `apt`, `apt-get`, `dnf`, `yum`, `pacman`, `brew`, `npm`,
  `pip`, `gem`;
- services: `systemctl`, `service`, `launchctl`;
- containers and orchestration: `docker`, `podman`, `kubectl`;
- scheduled jobs: `crontab`, `systemd-run`;
- policy/security: `sudo`, `security`, `spctl`, and carefully scoped
  `defaults write` patterns on macOS policy-sensitive domains.

Read-only commands should not be labeled as host mutations. Host mutation
observations should include category, operation, command name, target kind,
target display when safe, redaction, destructive marker, and execution markers.

## Redaction Policy

Shell-family extraction must redact secret-like values before raw observations,
canonical metadata, fixtures, or readback output store them.

Secret-like variable or key names include:

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

Known sensitive environment names include:

- `AWS_SECRET_ACCESS_KEY`;
- `GITHUB_TOKEN`;
- `NPM_TOKEN`;
- `SSH_AUTH_SOCK` as sensitive path-like context.

Secret-like command arguments include:

- `--password`;
- `--token`;
- `--api-key`;
- `Authorization:` headers;
- `-p` only when command context makes it secret-like.

Other sources that require redaction:

- heredoc bodies containing secret-like assignments;
- `.env`-style assignments;
- SSH/private-key markers if examples ever include multiline strings.

Rules:

- do not store raw secret values;
- preserve the secret-like name or key;
- record a redaction reason;
- record `raw_value_stored=false`;
- avoid over-matching ordinary words such as `path` as `pat`;
- fixtures must use redacted placeholders rather than real or realistic secret
  values.

## Dynamic And Unknown Policy

Future extractors should be conservative for:

- `eval`;
- variable command names;
- command substitution;
- process substitution;
- computed source paths;
- computed redirects;
- arrays;
- indirect expansion such as `${!name}`;
- glob expansion;
- brace expansion;
- shell parameter expansion;
- conditional execution;
- traps;
- aliases that cannot be statically resolved.

Policy:

- emit bounded `shell.dynamic_invocation` or another relevant unknown
  observation;
- record `dynamic_reason`;
- do not infer precise command targets;
- do not execute or expand;
- do not read target files to resolve source or dot commands unless a future
  phase explicitly scopes static same-repository resolution.

## Canonicalization And Readback Targets

Future canonicalization should be selective and conservative, following the
PowerShell PWSH6 pattern.

Good first canonical targets:

- scripts as file or script-like canonical nodes;
- functions as function-like nodes;
- source/dot includes as file reference edges;
- commands and external commands as `tool:*` nodes with `executes` edges;
- package managers as package-management or host mutation targets;
- env reads and writes as `env:*` nodes with `reads_env` and `writes_env`
  edges;
- static redirects as file references;
- host mutations as `host.category:*` nodes;
- network calls as external URL references when static;
- dynamic invocations as raw-only evidence unless a future phase adds bounded
  unknown canonical nodes.

Unsupported or dynamic details should remain raw-only until a safe mapping
exists. Bounded readback should prefer count-only summaries first:

- shell-family files by dialect;
- functions;
- commands and external commands;
- pipelines and command chains;
- redirects and heredocs;
- source includes;
- env reads and writes;
- host mutations by category;
- network and package-manager counts;
- dynamic invocation counts;
- redacted secret-like counts;
- canonical nodes and edges produced for shell-family evidence.

Readback must not include raw source snippets, raw secret values, unbounded path
lists, private absolute paths, or heredoc bodies.

## Fixture Strategy

Public-safe design examples live under `docs/examples/shell-family/` in SH0.
Concrete test fixtures should start in implementation phases, such as:

- `src/test/fixtures/shell/bash/`;
- `src/test/fixtures/shell/bats/`;
- `src/test/fixtures/shell/awk/`;
- `src/test/fixtures/shell/zsh/`;
- `src/test/fixtures/shell/zunit/`.

Fixtures and examples must:

- be clearly labeled static extraction examples only;
- not require execution;
- be non-executable by default;
- use redacted placeholders rather than real or realistic secret values;
- keep mutating-looking commands inside uncalled functions where possible;
- use `.invalid` domains for examples;
- avoid real private paths;
- avoid real credentials, tokens, private keys, or operational policy scripts.

Suggested future fixture themes:

- basic scripts with shebang, options, functions, assignments, exports, and
  source includes;
- side-effect examples for file, directory, permission, package, service,
  network, container, and scheduled-job commands;
- dynamic examples for `eval`, variable commands, command substitutions,
  process substitutions, computed redirects, and computed source paths;
- redaction examples for `.env`-style assignment, command flags, heredocs, and
  authorization headers;
- dialect-specific examples for Bash arrays and traps, Bats test cases and
  hooks, awk pattern/action blocks, zsh autoload/zstyle/glob qualifiers, and
  zunit suites.

## Roadmap

Planned sequence:

1. SH0: shell-family extraction design, shared taxonomy, safety policy, fixture
   strategy.
2. BASH0: Bash-specific design and dialect boundaries.
3. BASH1: Bash file classification and basic structural extraction.
4. BASH2: Bash commands, args, redirects, heredocs, pipelines, and chains.
5. BASH3: Bash host mutation and operational side effects.
6. BASH4: Bash functions, source/export/trap/options/dynamic safety.
7. BASH5: Bash canonicalization, bounded readback, and dogfooding.
8. BATS0: Bats design and fixture strategy.
9. BATS1: Bats test-file classification and test-case extraction.
10. BATS2: Bats assertions, helpers, setup/teardown, load/source modeling.
11. BATS3: Bats canonicalization/readback and dogfooding.
12. AWK0: awk extraction design, grammar subset, fixtures, safety boundaries.
13. AWK1: awk pattern/action and function extraction.
14. AWK2: awk IO, command-pipe, system-call, variable, and redirection
    modeling.
15. AWK3: awk canonicalization/readback and dogfooding.
16. ZSH0: zsh extraction design, Bash reuse boundaries, fixtures.
17. ZSH1: zsh classification and structural extraction.
18. ZSH2: zsh commands, aliases, functions, autoload, arrays, glob qualifiers.
19. ZSH3: zsh side effects and dynamic safety.
20. ZSH4: zsh canonicalization/readback and dogfooding.
21. ZUNIT0: zunit design and fixture strategy.
22. ZUNIT1: zunit test-suite/test-case extraction.
23. ZUNIT2: zunit assertions/hooks/helpers modeling.
24. ZUNIT3: zunit canonicalization/readback and dogfooding.

## SH0 Acceptance

SH0 is accepted only if:

- this design exists;
- shared taxonomy is explicit;
- dialect metadata strategy is explicit;
- non-execution policy is explicit;
- side-effect taxonomy is explicit;
- redaction policy is explicit;
- dynamic and unknown policy is explicit;
- fixture strategy is public-safe;
- Bash, Bats, awk, zsh, and zunit roadmap is documented;
- no shell extractor implementation lands;
- no shell is executed;
- no runtime or parser dependency is added;
- docs-only verification passes.
