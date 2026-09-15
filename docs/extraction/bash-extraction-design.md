# Bash Extraction Design

Status: BASH0 defined Bash-specific extraction boundaries before
implementation. BASH1 implements evidence-based Bash classification and basic
structural raw observations. BASH2 adds conservative static command, argument,
redirect, heredoc, pipeline, chain, and process-substitution raw observations.
BASH3 adds conservative static side-effect and host-mutation raw observations.
BASH4 adds conservative advanced-safety raw observations for aliases, arrays,
traps, arithmetic, tests, case labels, and deeper dynamic boundaries. Later
BASH5 adds selected canonicalization, bounded count-only summary readback, and
public fixture dogfooding.

## Purpose

Bash extraction should make RepoMap's shell-family graph evidence more useful
for Bash scripts while preserving the static, conservative safety boundary
defined in SH0.

BASH0 decides:

- how Bash reuses the shared `shell.*` taxonomy;
- which Bash-specific raw kinds are justified;
- how future phases should detect Bash files and dialect features;
- what parser/scanner strategy the first implementation should use;
- how Bash redaction, dynamic/unknown handling, side-effect detection, and
  false-positive prevention should work;
- what public-safe fixtures and follow-up phases should look like.

BASH0 was design-only. BASH1 adds implementation for the basic structural
slice, but it still does not execute shell code, invoke Bash, add parser/runtime
dependencies, change storage, or add canonical/readback behavior.

## BASH1 Implementation Note

BASH1 classifies Bash files only when there is explicit evidence:

- `.bash`;
- `.bashrc`;
- `.bash_profile`;
- `.bash_login`;
- `.sh` with a Bash shebang;
- `.profile` with a Bash shebang.

Generic `.sh` files without Bash evidence remain under the existing conservative
shell extractor. `.profile` files without Bash evidence and `.bats` files are
not classified as Bash.

BASH1 uses a stdlib-only static scanner for:

- `shell.script` with Bash dialect metadata, shebang metadata, and
  classification evidence;
- `bash.shell_option` for `set` options;
- `bash.shopt` for `shopt` options;
- `shell.function` for `name() { ... }` and `function name { ... }`;
- `shell.assignment` for simple scalar assignments and declaration forms;
- `shell.export` for simple export forms;
- `shell.source` for static and dynamic source/dot includes;
- `shell.command_substitution` for `$()` and backtick markers;
- `shell.dynamic_invocation` for `eval`, variable commands, array commands,
  `bash -c`, and `sh -c`;
- `shell.secret_like` for redacted secret-like assignments and exports.

BASH1 intentionally leaves arrays, aliases, traps, arithmetic, test
expressions, case modeling, command/argument extraction, pipelines, redirects,
heredoc observations, side-effect classification, canonicalization, and bounded
readback to BASH2 through BASH5.

## BASH2 Implementation Note

BASH2 extends the same static scanner with conservative raw observations for:

- `shell.command`;
- `shell.command_argument`;
- `shell.external_command`;
- `shell.pipeline`;
- `shell.command_chain`;
- `shell.redirect`;
- `shell.heredoc`;
- `shell.process_substitution`.

BASH2 recognizes fixture-backed command evidence for simple builtins,
external tools, leading assignment overlays, and wrapper commands. It records
arguments, long and short flags, switch flags, positional values, dynamic
values, and redacted secret-like values. Pipelines and command chains preserve
operator and segment order without modeling byte streams, object flow, or
control flow.

Redirect observations cover common read, truncate, append, fd-duplication,
combined-output, and here-string operators. Heredoc observations summarize
delimiter metadata and body counts while keeping `raw_body_stored=false`.
Process substitution is represented as bounded dynamic evidence with
`inner_modeled=false`.

BASH2 still does not classify host mutations or operational side effects.
Tokens such as `curl`, `sudo`, `apt-get`, `rm`, redirects, and heredocs are
static evidence only in this phase. `shell.file_read`, `shell.file_write`,
`shell.env_read`, `shell.env_write`, `shell.host_mutation`,
`shell.network_call`, and `shell.package_manager` remain deferred to BASH3+.
No shell code is executed, and no shell/parser/runtime dependency is added.

## BASH3 Implementation Note

BASH3 extends the same stdlib-only static scanner with conservative
operational side-effect raw observations:

- `shell.env_read`;
- `shell.env_write`;
- `shell.file_read`;
- `shell.file_write`;
- `shell.network_call`;
- `shell.package_manager`;
- `shell.host_mutation`.

The extractor derives side-effect observations only from statically visible
commands, wrapper arguments, environment overlays, and redirect metadata.
Read-only commands such as `cat`, `grep`, `test`, `docker ps`, `kubectl get`,
`terraform plan`, and package-manager version/list-style examples are not
labeled as host mutations. Mutating examples such as redirects to files,
`touch`, `mkdir`, `cp`, `mv`, `ln`, `chmod`, `chown`, archive extraction,
service control, scheduled jobs, package installs, selected container/runtime
operations, infrastructure apply/destroy operations, and security/credential
commands produce bounded `shell.host_mutation` metadata.

Dynamic targets are recorded as `target_kind="dynamic"` with
`target_display="[dynamic]"`; the extractor does not fabricate paths, URLs,
packages, services, or hosts. Secret-like environment, argument, heredoc, and
credential values remain redacted, and raw fake secret values are absent from
serialized observations. BASH3 still does not execute shell code, invoke any
shell/interpreter, add parser/runtime dependencies, change storage schema,
canonicalize Bash facts, or add bounded readback behavior.

## BASH4 Implementation Note

BASH4 extends the same stdlib-only static scanner with bounded advanced-safety
raw observations:

- `bash.alias`;
- `bash.array_assignment`;
- `bash.associative_array_assignment`;
- `bash.trap`;
- `bash.arithmetic`;
- `bash.test_expression`;
- `bash.case_pattern`.

Alias definitions are represented as file-scoped evidence with
`expansion_modeled=false`; alias targets are not executed, expanded across
files, or used to infer host mutations. Dynamic alias definitions become
bounded dynamic alias observations.

Indexed and associative arrays are summarized with counts, safe key/value
summaries, dynamic counts, and redaction metadata. BASH4 does not expand arrays
into commands, arguments, or host-mutation targets.

Trap handlers are represented as non-executing event evidence with
`executes_at_parse_time=false`. Handler bodies are summarized or redacted and
do not produce command or host-mutation observations.

Arithmetic, test expressions, and case patterns are extracted as bounded
structure. Arithmetic is not evaluated, test expressions do not prove runtime
branch execution, and case labels do not become command or chain observations.

Dynamic invocation metadata now covers `command eval`, quoted variable command
targets, indirect expansion, and selected parameter-replacement expansion
markers. Dynamic facts remain `shell.dynamic_invocation` or bounded
Bash-specific evidence; the extractor does not infer precise runtime commands.

BASH4 still does not execute shell code, invoke any shell/interpreter, add
parser/runtime dependencies, change storage schema, canonicalize Bash facts, or
add bounded readback behavior.

## BASH5 Implementation Note

BASH5 converts a selected, conservative subset of Bash raw observations into
canonical graph evidence:

- `shell.script` produces `bash.script` canonical nodes linked from file nodes;
- `shell.function` produces `bash.function` nodes defined by Bash script nodes;
- static `shell.source` observations produce `sources` file-reference edges;
- `shell.command` and `shell.external_command` produce `tool:*` nodes with
  `executes` edges;
- `shell.env_read` and `shell.env_write` produce `env:*` nodes with
  `reads_env` and `writes_env` edges;
- `shell.host_mutation` produces `host.category:*` nodes with `mutates_host`
  edges;
- static-safe `shell.file_read` and `shell.file_write` targets produce bounded
  file reference edges;
- static-safe `shell.network_call` targets produce external URL or external
  network references;
- `shell.package_manager` produces package-manager tool evidence.

Runtime-sensitive or overly detailed raw observations remain raw-only in BASH5,
including shell options, assignments, exports, command arguments, pipelines,
chains, redirects, heredocs, substitutions, dynamic invocations, secret-like
markers, aliases, arrays, traps, arithmetic, tests, and case patterns.

BASH5 adds `repomap_kg.bash_readback.summarize_bash_evidence`, an internal
count-only helper for public fixture dogfooding. The summary includes Bash raw
kind counts, side-effect category counts, selected canonical node/edge counts,
and safety markers. It does not include raw payloads, source snippets, path
examples, heredoc bodies, trap bodies, or secret values.

The Bash fixture set is dogfooded through extraction, canonicalization, bounded
summary generation, and canonical storage-row preparation. BASH5 still does not
execute shell code, invoke any shell/interpreter, add parser/runtime
dependencies, change storage schema, add CLI/MCP readback behavior, run live
graph refreshes, or expand dynamic Bash constructs.

## Relationship To SH0

Bash should use SH0's shared `shell.*` raw observation kinds by default.

Expected shared kinds for Bash include:

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

Every Bash observation should include:

- `dialect="bash"`;
- `static_only=true`;
- `shell_executed=false`.

Shared `shell.*` kinds should carry Bash-specific context in metadata such as
`dialect_feature`, `shell_option`, `assignment_keyword`, `redirect_operator`,
`heredoc_quoted`, `dynamic_reason`, or `wrapper_command`.

Use Bash-specific raw kinds only where a shared `shell.*` kind would be
misleading or too lossy.

## Bash-Specific Raw Kind Policy

BASH0 reserves these likely Bash-specific kinds:

| Kind | Planned phase | Why shared `shell.*` is not enough |
| --- | --- | --- |
| `bash.array_assignment` | BASH4 | Bash indexed arrays have syntax and expansion behavior that ordinary scalar `shell.assignment` would blur. |
| `bash.associative_array_assignment` | BASH4 | Associative arrays need key/value summary and redaction separate from scalar assignments. |
| `bash.shell_option` | BASH1 or BASH4 | `set -o` options affect later script behavior and deserve structured option metadata. |
| `bash.shopt` | BASH1 or BASH4 | `shopt` is Bash-specific and may indicate dialect features such as `extglob` or `nullglob`. |
| `bash.trap` | BASH4 | Trap handlers are event-bound dynamic execution evidence, not ordinary commands. |
| `bash.alias` | BASH4 | Aliases can affect later static command normalization but should not be treated as commands themselves. |
| `bash.arithmetic` | BASH4 | Arithmetic contexts have distinct expansion and command-like syntax. |
| `bash.test_expression` | BASH4 | `[[ ... ]]`, `[ ... ]`, and `test ...` deserve expression summaries without pretending to execute conditions. |
| `bash.case_pattern` | BASH4 | Case patterns are control-flow labels and should not become command or glob observations. |

`bash.builtin` is not planned as a default raw kind. Builtins should usually be
represented as `shell.command` with `command_family="builtin"` and
`dialect="bash"`. A future phase may add `bash.builtin` only if tests show that
raw command metadata is insufficient.

## Dialect Detection And Classification

Future Bash classification should be evidence-based.

Classify as Bash when:

- extension is `.bash`;
- filename is `.bashrc`, `.bash_profile`, or `.bash_login`;
- shebang is `#!/usr/bin/env bash`;
- shebang is `#!/bin/bash`;
- shebang is `#!/usr/bin/bash`;
- a `.sh` file has a Bash shebang.

Do not classify generic `.sh` files as Bash without evidence.

`.sh` files may be upgraded to Bash only when a future implementation can
statically detect Bash-only syntax safely, such as:

- `[[ ... ]]`;
- `declare -A`;
- `${BASH_SOURCE[0]}`;
- `shopt`;
- `mapfile` or `readarray`;
- process substitution when paired with Bash evidence;
- Bash array assignment syntax in a context that is not ambiguous.

Be conservative with `.profile`. It may be POSIX-ish, Bash-ish, zsh-ish, or
environment-specific. Do not classify `.profile` as Bash unless shebang,
Bash-only syntax, or explicit profile metadata gives Bash evidence.

`.bats` belongs to the BATS series. Bash extraction may later share scanner
helpers with Bats extraction, but Bats test-case semantics should remain
separate.

## Parser And Scanner Strategy

BASH1 should start with a stdlib-only static scanner/tokenizer:

- no shell invocation;
- no parser dependency;
- line-aware and heredoc-aware scanning;
- bounded unknown observations for unsupported syntax;
- fixture-backed recognition only;
- false-positive avoidance over high recall.

Bash syntax is more ambiguous than PowerShell. A line-oriented scanner will miss
some constructs, especially nested compound commands and complex quoting. That
is acceptable for the first implementation if the extractor records honest
unknowns and avoids dangerous false positives.

Parser candidates for later evaluation:

- Tree-sitter Bash;
- bashlex;
- `mvdan/sh` through a bridge, if packaging and licensing are appropriate;
- other static parsers with clear Python packaging, license compatibility, and
  deterministic cross-platform behavior.

Parser adoption should be a dedicated phase. Evaluate:

- license compatibility;
- dependency packaging and installation impact;
- behavior on macOS and Linux;
- ability to preserve line/column ranges;
- handling of Bash-specific constructs;
- error recovery for partial scripts;
- performance on large repositories;
- testability without invoking shells.

## Core Bash Constructs

Future Bash phases should model these constructs conservatively.

### Shebangs

Recognize Bash shebangs and preserve the literal interpreter token in metadata.
Do not check whether the interpreter exists.

### Shell Options

Recognize:

- `set -e`;
- `set -u`;
- `set -o pipefail`;
- `set -euo pipefail`;
- `shopt -s nullglob`;
- `shopt -s extglob`;
- `shopt -u <option>`.

Emit either `bash.shell_option` or `bash.shopt` when structured option metadata
is useful. Otherwise use `shell.command` with `command_family="builtin"` and a
`dialect_feature` marker.

### Functions

Recognize:

- `name() { ... }`;
- `function name { ... }`.

Function observations should include function name, source file, line range
when known, dialect, and static execution markers. Do not execute or analyze
function bodies as control flow.

### Assignments And Exports

Recognize:

- `NAME=value`;
- `local NAME=value`;
- `declare NAME=value`;
- `readonly NAME=value`;
- `typeset NAME=value` where Bash compatibility is relevant;
- `export NAME=value`;
- `export NAME`;
- assignments before commands, such as `FOO=bar command`.

Record variable names, declaration keyword, export status, value presence,
static/dynamic value status, and redaction. Secret-like values must not be
stored.

### Arrays

Recognize:

- `arr=(a b c)`;
- `declare -a arr=(...)`;
- `declare -A map=([key]=value)`;
- appends such as `arr+=("value")` when static.

Use `bash.array_assignment` and `bash.associative_array_assignment` for bounded
summaries. Do not expand arrays to runtime command targets.

### Source Includes

Recognize:

- `. ./file.sh`;
- `source ./lib/common.bash`.

Static same-repository targets may become file references in later phases.
Computed, absolute, repository-escaping, or command-substituted targets should
remain dynamic/unknown unless a future phase explicitly scopes static same-repo
resolution.

### Aliases And Traps

Recognize:

- `alias ll='ls -la'`;
- `trap 'cleanup' EXIT`.

Aliases and traps should remain bounded evidence. Same-file alias definitions
may influence later command normalization only if they are order-aware, local,
static, and tested. Trap handlers should not be treated as commands that run at
parse time.

### Commands And Arguments

Recognize simple commands, builtins, external tools, wrappers, and arguments.
Avoid extracting commands from:

- comments;
- quoted strings;
- heredoc bodies;
- arrays;
- assignments;
- case pattern labels;
- README/code-block contexts if future docs scanning exists.

### Chains, Pipelines, Redirects, And Heredocs

Recognize:

- command chains: `;`, `&&`, `||`, and case terminators `;;`;
- pipelines: `|` and `|&`;
- redirects: `>`, `>>`, `<`, `2>`, `2>&1`, `&>`, and `<<<`;
- heredocs: `<<EOF`, `<<-EOF`, and quoted delimiters.

Preserve segment order and operator metadata. Do not model full control flow or
data flow. Heredoc bodies should be summarized, counted, and redacted, never
stored raw in ordinary observations or readback.

### Substitution, Subshells, Arithmetic, Tests, And Case

Recognize as bounded evidence:

- command substitution: `$(...)` and backticks;
- process substitution: `<(...)` and `>(...)`;
- subshells: `( ... )`;
- arithmetic expansion: `$((...))`;
- arithmetic command: `(( ... ))`;
- tests: `[ ... ]`, `[[ ... ]]`, and `test ...`;
- case statements and pattern labels;
- loops and conditionals as structure, not complete control flow.

## Command Normalization

Future Bash normalization should start with a small built-in and wrapper table.

Initial builtins and keywords:

- `cd`;
- `pwd`;
- `test`;
- `[`;
- `[[`;
- `echo`;
- `printf`;
- `read`;
- `export`;
- `source`;
- `.`;
- `alias`;
- `trap`;
- `set`;
- `shopt`;
- `shift`;
- `return`;
- `exit`;
- `local`;
- `declare`;
- `readonly`;
- `type`;
- `command`;
- `builtin`.

Wrapper commands:

- `sudo`;
- `env`;
- `command`;
- `builtin`;
- `time`;
- `nohup`;
- `xargs`;
- `find -exec`;
- `bash -c`;
- `sh -c`.

Policy:

- record wrapper and wrapped command only when statically visible and safe;
- `sudo apt install x` may later record wrapper evidence and package-manager
  intent;
- `env FOO=bar command` may later record environment overlay and wrapped
  command;
- `find -exec` and `xargs` remain conservative unless fixtures prove a safe
  static model;
- `bash -c "$text"` and `sh -c "$text"` are dynamic unless the command string is
  a static literal and a future phase explicitly supports bounded parsing.

Assignments and redirects around a command should not hide a static command
token, but they must not be evaluated.

## Redirect And Heredoc Design

Redirect observations should capture:

- operator;
- file descriptor;
- mode: read, truncate, append, duplicate, here-string, unknown;
- target kind: static, dynamic, unknown;
- target display only when safe;
- redaction status.

Heredoc observations should capture:

- delimiter;
- whether the delimiter is quoted;
- whether tabs are stripped;
- body line count;
- secret-like assignment count;
- redaction markers;
- expansion mode metadata, but no expansion.

Do not store raw heredoc bodies in raw observations, canonical metadata, or
bounded readback.

## Dynamic And Unknown Policy

Bash-specific dynamic cases include:

- `eval "$cmd"`;
- `$cmd`;
- `"${cmd[@]}"`;
- `bash -c "$text"`;
- `source "$computed_path"`;
- command substitution `$(...)`;
- backticks;
- process substitution `<(...)` and `>(...)`;
- indirect expansion `${!name}`;
- arrays and associative arrays;
- glob expansion;
- brace expansion;
- parameter expansion such as `${var:-default}`, `${var#prefix}`, and
  `${var/pat/repl}`;
- arithmetic expansion;
- traps;
- aliases that cannot be resolved statically;
- functions defined conditionally.

Policy:

- emit bounded `shell.dynamic_invocation` or another relevant unknown
  observation;
- record `dynamic_reason`;
- do not infer precise command targets;
- do not execute or expand;
- do not read sourced targets unless a later phase explicitly scopes safe
  same-repository static resolution.

## False-Positive Strategy

Early Bash extraction should prefer missing a construct over extracting a
dangerous false positive.

Future scanner safeguards should cover:

- line comments;
- block-like comments via heredoc idioms where statically visible;
- single-quoted strings;
- double-quoted strings;
- heredoc bodies;
- assignments containing command-looking text;
- arrays containing command-looking text;
- case pattern labels;
- `.env` files vs scripts;
- README/code-block contexts if docs scanning is ever added;
- comments that mention dangerous commands.

False-positive reduction should be fixture-backed before expanding recall.

## Side-Effect Taxonomy

Bash should reuse SH0's side-effect categories.

Future Bash side-effect command families:

- file and directory reads: `cat`, `grep`, `find`, `test`, `[`;
- file and directory writes: `touch`, `mkdir`, `rm`, `mv`, `cp`, `install`,
  `ln`, `tar`, `unzip`, `rsync`;
- permissions and ownership: `chmod`, `chown`, `chgrp`, `umask`;
- network: `curl`, `wget`, `nc`, `ssh`, `scp`, remote `rsync`;
- package managers: `apt`, `apt-get`, `dnf`, `yum`, `pacman`, `brew`, `npm`,
  `pip`, `pip3`, `gem`, `bundle`, `cargo`, `go install`;
- services: `systemctl`, `service`, `launchctl`, `brew services`;
- containers and orchestration: `docker`, `docker compose`, `podman`,
  `kubectl`, `helm`, `terraform`;
- scheduled jobs: `crontab`, `systemd-run`, `launchctl`;
- security and policy: `sudo`, `su`, `security`, `spctl`, and carefully scoped
  `defaults write` patterns.

Read-only commands should not be host mutations. Mutating commands should emit
`shell.host_mutation` only when command and operation are statically recognized.
Dynamic targets should be bounded dynamic targets, not fabricated paths.

## Redaction Policy

Bash inherits SH0 redaction and adds Bash-specific cases.

Secret-like variable names:

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

Common sensitive environment names:

- `AWS_SECRET_ACCESS_KEY`;
- `AWS_ACCESS_KEY_ID`;
- `GITHUB_TOKEN`;
- `GITLAB_TOKEN`;
- `NPM_TOKEN`;
- `PYPI_TOKEN`;
- `DOCKER_PASSWORD`;
- `SSH_AUTH_SOCK`.

Secret-like command arguments:

- `--password`;
- `--passwd`;
- `--token`;
- `--api-key`;
- `--authorization`;
- `-u user:password` when command context implies credentials;
- `-H 'Authorization: ...'`.

Special cases:

- `.env`-style assignments;
- heredoc bodies with secret-looking assignments;
- SSH private-key markers;
- base64-looking blobs only when tied to secret-like keys.

Do not over-match ordinary words like `path` as `pat`. Preserve the name/key and
redaction reason, and store no raw secret value.

## Canonicalization And Readback Targets

BASH5 follows SH0 and PWSH6: map selected safe facts and leave dynamic or
unsupported details raw-only.

Implemented canonical mappings:

- scripts as `bash.script` canonical nodes linked from file nodes;
- functions as `bash.function` nodes;
- source/dot includes as file reference edges;
- commands and external commands as `tool:*` nodes with `executes` edges;
- package-manager operations as package-manager tool evidence;
- env reads and writes as `env:*` nodes with `reads_env` and `writes_env`
  edges;
- static-safe file read/write observations as file references;
- host mutations as `host.category:*` nodes;
- static network calls as external URL references;
- dynamic invocations as raw-only.

First readback should be count-only:

- Bash files;
- functions;
- shell options;
- aliases;
- commands and external commands;
- pipelines and command chains;
- redirects and heredocs;
- source includes;
- env reads and writes;
- host mutations by category;
- network calls;
- package-manager calls;
- dynamic invocation counts;
- redacted secret-like counts;
- canonical nodes and edges produced.

Readback must not include raw source snippets, heredoc bodies, raw secrets,
unbounded path lists, or private absolute paths.

## Fixture Strategy

Public-safe BASH0 design examples live under `docs/examples/bash/`.

BASH1 through BASH5 implementation fixtures live under
`src/test/fixtures/shell/bash/` and cover basic Bash structure, source
includes, command and argument evidence, redirects, heredocs, dynamic markers,
side effects, advanced safety, canonicalization dogfooding, secret redaction,
and false-positive boundaries.

Future implementation fixtures should use:

- `src/test/fixtures/shell/bash/basic.bash`;
- `src/test/fixtures/shell/bash/strict-mode.bash`;
- `src/test/fixtures/shell/bash/functions-and-source.bash`;
- `src/test/fixtures/shell/bash/commands-pipelines-redirects.bash`;
- `src/test/fixtures/shell/bash/heredocs.bash`;
- `src/test/fixtures/shell/bash/side-effects.bash`;
- `src/test/fixtures/shell/bash/dynamic.bash`;
- `src/test/fixtures/shell/bash/redaction.env.example`;
- `src/test/fixtures/shell/bash/false-positives.bash`;
- `src/test/fixtures/shell/bash/advanced-safety.bash`.

Fixtures and examples must:

- be clearly labeled static extraction examples only;
- remain non-executable by default;
- use redacted placeholders rather than real or realistic secret values;
- use `.invalid` domains;
- put mutating-looking commands in uncalled functions;
- contain no real private paths;
- contain no real secrets, tokens, credentials, or private key material.

## BASH1 Acceptance Sketch

BASH1 should cover classification and basic structure only:

- classify Bash files by extension or shebang evidence;
- avoid generic `.sh` Bash upgrade without evidence;
- emit script, shebang, shell option, function, assignment, export, and source
  observations;
- redact secret-like assignments;
- emit bounded unknowns for dynamic source, eval, and command substitution;
- use public-safe fixtures;
- execute no shell code;
- add no parser/runtime dependency;
- pass the combined final gate.

## BASH2 Acceptance Sketch

BASH2 should cover commands, args, redirects, heredocs, pipelines, and chains:

- static command observations;
- command arguments;
- pipeline and command-chain ordering;
- redirect observations;
- heredoc summaries;
- command and process substitution markers;
- no host mutation classification unless deliberately scoped;
- fake secrets absent from serialized observations;
- execute no shell code.

## BASH3 Acceptance Sketch

BASH3 covers host mutation and side effects:

- file, env, network, package, service, container, permissions, and
  scheduled-job side-effect observations;
- read-only vs mutating distinction;
- dynamic target boundaries;
- redaction;
- execute no shell code.

## BASH4 Acceptance Sketch

BASH4 should cover advanced Bash safety:

- functions, source, export, trap, and option refinements;
- aliases;
- arrays and associative arrays;
- arithmetic, test, and case boundaries;
- eval and dynamic invocation hardening;
- false-positive reduction for heredocs, strings, arrays, and comments.

## BASH5 Acceptance

BASH5 covers canonicalization, bounded readback, and dogfooding:

- selected raw-to-canonical mappings;
- bounded summary helper;
- public-safe fixture dogfooding;
- dynamic and unsupported facts raw-only;
- fake secret non-leakage;
- no storage schema redesign.

## Known Gaps

- Parser choice remains undecided.
- Current conservative shell extraction behavior remains smaller than this Bash
  design.
- `.profile` detection is intentionally conservative.
- Bats semantics remain out of scope for Bash phases.
- Cross-file alias, function, and sourced-file resolution remain future work.
- Full Bash AST parsing, control/data flow, runtime expansion semantics, and
  product CLI/MCP readback remain future work.
- Full control-flow and data-flow modeling remain out of scope.

## BASH0 Acceptance

BASH0 is accepted only if:

- this design exists;
- relationship to SH0's `shell.*` taxonomy is explicit;
- Bash dialect detection strategy is explicit;
- Bash-specific raw-kind policy is explicit;
- parser/scanner strategy is explicit;
- non-execution policy is explicit;
- redaction policy is explicit;
- dynamic/unknown policy is explicit;
- side-effect strategy is explicit;
- fixture strategy is public-safe;
- BASH1 through BASH5 roadmap is documented;
- no Bash extractor implementation lands;
- no classification behavior changes;
- no shell is executed;
- no runtime/parser dependency is added;
- docs-only verification passes.
