# Awk Extraction Design

Status: AWK3 adds selected awk canonicalization and bounded count-only
dogfooding for public-safe fixtures. Awk IO, pipes, and `system()` remain
source intent, not runtime execution or host-mutation proof, and unsupported or
dynamic facts remain raw-only.

## Purpose

Awk extraction should give RepoMap useful static evidence from awk programs
without treating awk as a shell or executing awk source. Awk is shell-adjacent:
awk programs can read files, write files, open command pipes, and call
`system()`, but their native structure is pattern/action rules over records and
fields rather than shell command lists.

AWK0 defines:

- how awk relates to SH0's shared shell-family taxonomy;
- which awk-specific raw observations should represent language-native facts;
- how future phases should classify awk files and dialect evidence;
- the conservative scanner/parser subset for AWK1 and AWK2;
- redaction, dynamic/unknown, IO, pipe, and `system()` boundaries;
- public-safe fixture strategy;
- the AWK1 through AWK3 roadmap.

## Design Principles

Awk extraction should be static, conservative, awk-language-aware,
shell-adjacent but not shell-flattened, IO and command-pipe aware,
redaction-first, honest about dynamic behavior, and useful for graph evidence
without executing source.

Future extraction should prefer bounded unknown observations over false
precision. A dynamic file name, regex, field reference, pipe command, or
`system()` string should never become a fabricated precise path or command.

## Non-Execution Policy

AWK0 inherits SH0's static boundary and makes it awk-specific. Future awk
extraction must not:

- execute awk programs;
- invoke `awk`, `gawk`, `mawk`, `nawk`, shells, package managers, or external
  commands;
- call subprocess to ask awk or a shell how source parses or runs;
- run `system()` calls or command-pipe strings;
- open files, FIFOs, sockets, pipes, or redirects referenced by awk source;
- inspect the filesystem to decide whether an awk IO target exists;
- expand shell commands embedded in awk strings;
- infer runtime records, fields, variables, regex matches, or input data;
- mutate host filesystem, environment, profiles, services, scheduled jobs,
  package state, process state, container runtime, or network state;
- store raw secret-like values, raw command snippets that are secret-like or
  long, or private source snippets in observations, canonical metadata, or
  bounded readback.

Every future awk observation should include metadata equivalent to:

- `language="awk"`;
- `dialect="awk"`, `dialect="gawk"`, `dialect="mawk"`, or
  `dialect="unknown"`;
- `static_only=true`;
- `awk_executed=false`;
- `shell_executed=false`.

## Relationship To SH0 And Shell-Family Taxonomy

Awk is part of the shell-family roadmap because it often appears in operational
repositories and shell scripts, but awk should not be flattened into ordinary
`shell.*` command extraction.

Use awk-specific raw kinds for language-native facts such as programs,
pattern/action rules, fields, records, variables, builtins, includes,
redirections, pipes, and `system()` calls.

Shared `shell.*` kinds may be reused only where they honestly represent
shell-facing evidence:

- `shell.command`;
- `shell.command_argument`;
- `shell.external_command`;
- `shell.redirect`;
- `shell.dynamic_invocation`;
- `shell.file_read`;
- `shell.file_write`;
- `shell.network_call`;
- `shell.host_mutation`;
- `shell.secret_like`.

Early awk phases should primarily emit `awk.*` kinds. Any shell-facing
observation derived from awk `system()` or command-pipe source must preserve
non-execution metadata such as `command_executed=false`,
`awk_executed=false`, and `shell_executed=false`.

## Awk-Specific Raw Kind Policy

Use awk-specific observations where shared shell facts would be misleading or
too lossy.

| Kind | Planned Phase | Purpose |
| --- | --- | --- |
| `awk.program` | AWK1 | File-level awk program evidence, including shebang and dialect hints. |
| `awk.pattern_action` | AWK1 | A pattern/action rule with bounded pattern metadata and action presence. |
| `awk.begin` | AWK1 | Dedicated BEGIN block evidence. |
| `awk.end` | AWK1 | Dedicated END block evidence. |
| `awk.function` | AWK1 | A user-defined awk function. |
| `awk.rule_pattern` | AWK1 | Optional detailed pattern evidence when useful. |
| `awk.action` | AWK1 | Optional bounded action summary when useful. |
| `awk.variable_assignment` | AWK1 | Assignment to an awk variable or special variable. |
| `awk.field_reference` | AWK1 | Field reference such as `$0`, `$1`, `$NF`, or dynamic `$(i)`. |
| `awk.record_reference` | AWK1 | Record-level references such as `$0`, `NR`, `FNR`, or `FILENAME`. |
| `awk.dynamic_expression` | AWK1 | Bounded evidence for unsupported or dynamic expressions. |
| `awk.builtin_call` | AWK2 | Calls to awk builtins such as `print`, `getline`, `gsub`, or `system`. |
| `awk.user_function_call` | AWK2 | Static calls to user-defined functions. |
| `awk.file_read` | AWK2 | Runtime file-read intent such as `getline x < "input.txt"`. |
| `awk.file_write` | AWK2 | Runtime file-write intent such as `print x > "out.txt"`. |
| `awk.pipe_read` | AWK2 | Runtime command-pipe read intent such as `"date" | getline now`. |
| `awk.pipe_write` | AWK2 | Runtime command-pipe write intent such as `print x | "sort"`. |
| `awk.system_call` | AWK2 | Static source evidence for `system(...)`, never execution proof. |
| `awk.redirect` | AWK2 | Awk redirection operator evidence independent of side-effect claims. |
| `awk.include` | AWK2 | Static gawk `@include` evidence. |
| `awk.extension` | AWK2 | Static gawk `@load` or extension evidence. |
| `awk.secret_like` | AWK2 | Awk-owned redacted secret-like evidence when `shell.secret_like` is too broad. |

AWK3 adds selected canonicalization, bounded count-only readback, and fixture
dogfooding. It does not try to canonicalize every raw kind.

## Detection And Classification Strategy

Future awk classification should be evidence-based.

Classify as awk when:

- the extension is `.awk`;
- an executable or extensionless file has an awk shebang such as
  `#!/usr/bin/awk -f`;
- the shebang is `#!/usr/bin/env awk -f`;
- the shebang is `#!/usr/bin/env gawk -f`;
- the shebang is `#!/bin/awk -f`.

Do not classify shell scripts, Makefiles, task runners, Bash, Bats, zsh,
generic shell files, or docs as awk merely because they contain the token
`awk`. Inline awk one-liners should remain shell command arguments unless a
later embedded-language phase explicitly scopes safe static extraction of
embedded awk source.

`.awk` files should not be routed through Bash or generic shell extraction.

### Dialect Evidence

Use `dialect="gawk"` only when evidence is explicit:

- a `gawk` shebang;
- gawk-specific syntax such as `@include` or `@load`;
- gawk-specific variables or features such as `BEGINFILE`, `ENDFILE`, `FPAT`,
  `PROCINFO`, `SYMTAB`, namespaces, or `gensub`.

Use `dialect="awk"` for ordinary `.awk` files or awk shebangs when no
gawk-specific feature is visible. Use `dialect="unknown"` only if the future
classifier cannot distinguish a source as generic awk versus a dialect-specific
variant while still having awk evidence.

Do not assume gawk behavior for all awk programs.

## Parser And Scanner Strategy

AWK1 should start with a stdlib-only static scanner/tokenizer:

- no awk invocation;
- no shell invocation;
- no parser/runtime dependency;
- brace-aware scanning for `BEGIN`, `END`, pattern/action rules, and
  `function` definitions;
- string-aware and comment-aware scanning;
- bounded unknown observations for unsupported syntax;
- fixture-backed recognition only;
- false-positive avoidance over high recall.

Parser candidates for later evaluation include Tree-sitter awk, a small custom
awk tokenizer/parser, and other static awk parsers after license, packaging,
determinism, error recovery, line-range, and cross-platform review. Parser
adoption should be a dedicated later phase. AWK1 should not add Tree-sitter,
external parser binaries, or interpreter-backed parsing.

Awk syntax has ambiguous corners: regex literals can resemble division,
patterns and expressions can be compact, and action braces can appear in
strings. Early extraction should miss uncertain constructs rather than produce
dangerous false positives.

## Core Awk Constructs

Future phases should model awk source conservatively.

### Program And Shebang

Recognize awk programs and preserve shebang metadata when present:

```awk
#!/usr/bin/env awk -f
```

Shebang extraction must not invoke the interpreter or test the path.

### BEGIN And END Blocks

Recognize:

```awk
BEGIN { FS = ","; OFS = "\t" }
END { print count }
```

AWK0 chooses dedicated `awk.begin` and `awk.end` observations for BEGIN and END
blocks because they have special lifecycle semantics in awk. They may also
carry `pattern_kind="begin"` or `pattern_kind="end"` metadata for consumers
that prefer uniform pattern/action summaries.

### Pattern/Action Rules

Recognize:

```awk
/ERROR/ { print $0 }
$3 > 10 { count++ }
NR == 1 { next }
```

`awk.pattern_action` metadata should include:

- `pattern_kind`: `begin`, `end`, `regex`, `expression`, `range`, `empty`, or
  `unknown`;
- `action_present=true` or `false`;
- line range when available;
- `action_modeled=false` initially, or a bounded summary when a later phase
  proves the need;
- `static_only=true`;
- `awk_executed=false`.

Pattern/action observations do not prove any input records matched.

### Functions

Recognize:

```awk
function normalize(value,    trimmed) {
  return value
}
```

`awk.function` metadata should include function name, parameters, local
parameters if identifiable through awk's convention of extra spacing in the
parameter list, line range when available, `body_modeled=false` or a bounded
summary, `static_only=true`, and `awk_executed=false`.

Function bodies are source evidence, not runtime execution.

### Variables, Fields, And Records

Recognize simple assignments and references:

```awk
count += 1
name = $1
record = $0
```

Future observations should cover assignments to variables and special
variables, field references such as `$0`, `$1`, `$NF`, and dynamic `$(i)`,
record references, and special variables such as `FS`, `OFS`, `RS`, `ORS`,
`NR`, `FNR`, `NF`, `FILENAME`, `ARGC`, `ARGV`, `ENVIRON`, `RSTART`, and
`RLENGTH`.

Field and record observations do not imply input data was read or inspected by
RepoMap.

### Builtins

AWK2 should model bounded calls to common builtins:

- `print`;
- `printf`;
- `getline`;
- `system`;
- `close`;
- `length`;
- `substr`;
- `split`;
- `sub`;
- `gsub`;
- `match`;
- `tolower`;
- `toupper`;
- `sprintf`;
- `index`;
- `int`;
- `rand`;
- `srand`.

AWK1 may defer builtin extraction except where a structural marker is necessary
for false-positive avoidance.

### Redirections, Pipes, And System Calls

Recognize source patterns such as:

```awk
print value > "out.txt"
print value >> "out.txt"
getline line < "input.txt"
"date" | getline now
print value | "sort"
system("echo static-example")
```

These are runtime IO or command-intent source facts. They are not execution
proof. Future observations should include `command_executed=false`,
`shell_executed=false`, `awk_executed=false`, and `static_only=true`.

### Includes And Extensions

Recognize gawk-specific forms:

```awk
@include "lib.awk"
@load "ordchr"
```

Static include targets may become dependency or file-reference evidence in
AWK2/AWK3. Dynamic or unsupported extension syntax should remain bounded
unknown evidence.

## IO, Pipe, And System-Call Strategy

Awk IO and command execution constructs need their own source-intent model.

Policy:

- emit `awk.file_read`, `awk.file_write`, `awk.pipe_read`, `awk.pipe_write`,
  `awk.system_call`, and `awk.redirect` in AWK2 when statically recognized;
- do not open files;
- do not execute command strings;
- do not infer that runtime input caused the IO or command to run;
- record static safe targets when short and public-safe;
- mark dynamic targets with `target_kind="dynamic"` and
  `target_display="[dynamic]"`;
- redact secret-like targets or command strings;
- do not fabricate file paths, command names, hosts, URLs, or package names.

System calls and command pipes may eventually produce shell-facing evidence, but
that evidence must remain command-intent source evidence. AWK2 should not emit
ordinary host-mutation proof from `system("rm ...")`. Host-mutation
canonicalization, if ever added, should wait for AWK3 or a later explicitly
scoped phase and must preserve `command_executed=false`.

## Redaction Policy

Awk inherits SH0/Bash redaction and adds awk-specific contexts.

Secret-like names include password, passwd, secret, token, key, credential,
apikey, pat, authorization, and auth. Awk-specific sensitive contexts include
variable assignments such as `token = "..."`, `ENVIRON["TOKEN"]`, `system()`
command strings, pipe command strings, printed output strings containing fake
tokens, and file paths with secret-like names.

Rules:

- do not store raw secret-like values;
- preserve the field, key, or variable name and redaction reason;
- set `raw_value_stored=false`;
- emit `awk.secret_like` or `shell.secret_like` only when useful and tested;
- do not over-match ordinary words such as `path` as `pat`;
- fixtures must use fake placeholders only and later tests must prove those
  values are absent from serialized observations, canonical records, summaries,
  and storage rows.

The `-v TOKEN=value` shell invocation form belongs to shell command-argument
extraction unless a future embedded-language phase scopes the boundary between
shell invocations and awk source files.

## Dynamic And Unknown Policy

Future awk extraction should emit bounded dynamic or unknown evidence for:

- dynamic regexes;
- dynamic fields such as `$(i)`;
- dynamic file names such as `print x > out`;
- dynamic command strings such as `system(cmd)`;
- dynamic pipe strings such as `cmd | getline` or `print x | cmd`;
- string concatenation;
- unsupported gawk extensions;
- syntax the conservative scanner cannot confidently classify.

Metadata should record `dynamic_reason`, such as `dynamic_regex`,
`dynamic_field`, `dynamic_file_target`, `dynamic_command_string`,
`string_concatenation`, `unsupported_gawk_extension`,
`ambiguous_regex_or_division`, or `unsupported_expression`.

Do not execute, expand, or deeply parse shell command strings unless a future
phase explicitly scopes safe static command-string extraction.

## False-Positive Boundaries

Future scanner safeguards should suppress extraction from:

- comments beginning with `#`;
- strings containing `{`, `}`, `BEGIN`, `END`, `function`, `system`, or
  `getline`;
- escaped quotes inside strings;
- regex literals that are too ambiguous to distinguish from division;
- action braces inside strings;
- multiline strings or continuations that the scanner cannot safely bound;
- shell heredocs or docs examples containing awk source;
- shell scripts invoking awk one-liners;
- comments or strings containing dangerous command examples.

Prefer missing a construct over extracting a dangerous false positive.

## Canonicalization And Readback Targets

AWK3 follows BASH5 and BATS3: map a selected safe subset and leave dynamic or
runtime-sensitive details raw-only.

Implemented canonical mappings:

- awk files/programs as `awk.program` nodes linked from file nodes with
  `defines` edges;
- functions as `awk.function` nodes linked from awk programs with `defines`
  edges;
- same-file static user-function calls as `calls` edges;
- builtin calls as bounded `awk.builtin` external evidence with
  `uses_builtin` edges;
- static safe `@include` targets as file references with `includes` edges;
- static safe `@load` targets as `awk.extension` dependencies;
- static safe file reads/writes as bounded file references with `reads` or
  `writes` edges;
- static safe command-pipe and `system()` strings as command-intent evidence
  with `pipe_command_intent` or `system_command_intent` edges.

Raw-only observations:

- `awk.begin`;
- `awk.end`;
- `awk.pattern_action`;
- `awk.variable_assignment`;
- `awk.field_reference`;
- `awk.record_reference`;
- `awk.dynamic_expression`;
- `awk.redirect`;
- `awk.secret_like`.

Dynamic, redacted, unsafe absolute, repository-escaping, or long command/file
targets remain raw-only bounded evidence.

Bounded readback should be count-only first:

- awk files/programs;
- BEGIN/END blocks;
- pattern/action rules;
- functions;
- assignments;
- field and record references;
- builtin calls;
- `getline` count;
- file read/write count;
- pipe read/write count;
- system-call count;
- include/extension count;
- dynamic/unknown count;
- secret-like redacted count;
- canonical nodes/edges produced.

Readback must not include raw source snippets, raw secret values, unbounded path
lists, private absolute paths, raw heredoc/source blocks, or raw command strings
when secret-like or long.

## Fixture Strategy

AWK0 adds public-safe docs examples under `docs/examples/awk/`. Concrete
implementation fixtures should begin under `src/test/fixtures/shell/awk/` in
AWK1 or a later implementation phase.

Suggested future fixtures:

- `basic.awk`;
- `patterns-and-actions.awk`;
- `functions.awk`;
- `io-and-pipes.awk`;
- `dynamic.awk`;
- `redaction.awk`;
- `gawk-extensions.awk`;
- `false-positives.awk`.

Fixture rules:

- fixtures and examples are static extraction inputs only;
- they must not need execution;
- they must remain non-executable by default;
- they must contain no real private paths;
- they must contain no real credentials, tokens, private keys, or sensitive
  command strings;
- they may use `.invalid` domains and fake placeholders;
- command-looking syntax should be clearly labeled as source examples, not
  commands to run.

## Roadmap

### AWK1: Classification And Structure

AWK1 classifies `.awk` and awk-shebang files, avoids shell-script awk one-liner
extraction, and emits `awk.program`, `awk.begin`, `awk.end`,
`awk.pattern_action`, `awk.function`, `awk.variable_assignment`,
`awk.field_reference`, `awk.record_reference`, and `awk.dynamic_expression`
observations from public-safe fixtures. AWK1 preserves the no-execution and
no-parser-dependency boundary.

### AWK2: IO, Calls, Pipes, System, Variables, And Redirection

AWK2 models builtin calls, static same-file user-function calls, file
read/write intent, command-pipe read/write intent, `system()` command intent,
redirection operators, gawk `@include` and `@load`, secret redaction, and
dynamic command/file target boundaries. These observations are source intent
only: AWK2 records `runtime_intent=true`, `awk_executed=false`,
`shell_executed=false`, `command_executed=false`, `filesystem_checked=false`,
and `host_mutation_proven=false` where applicable.

### AWK3: Canonicalization, Readback, And Dogfooding

AWK3 adds selected raw-to-canonical mappings, a bounded count-only
summary/readback helper, public-safe fixture dogfooding, non-executed
command/system/pipe evidence, dynamic/unsupported raw-only behavior, fake
secret non-leakage, and no broad storage schema redesign.

## AWK1 Implementation Notes

The AWK1 extractor is intentionally conservative:

- classification is evidence-based for `.awk` extensions and first-line awk or
  gawk shebangs;
- ordinary shell scripts, Makefiles, docs, and task runners are not
  reclassified as awk merely because they contain awk command text;
- `dialect="gawk"` is recorded only when a gawk shebang or tested
  gawk-specific feature is visible;
- structural observations carry `language="awk"`, `static_only=true`,
  `awk_executed=false`, and `shell_executed=false`;
- secret-like variable assignments are redacted in assignment metadata without
  storing raw values;
- dynamic regexes, dynamic fields, string concatenation targets, computed
  targets, and unsupported gawk features are bounded as
  `awk.dynamic_expression`;
- comments, strings, and obvious division expressions are guarded against
  structural false positives;
- AWK2 IO/call/pipe/system/redirection kinds remain deferred in AWK1 fixtures
  only where the source does not contain supported AWK2 forms.

## AWK2 Implementation Notes

AWK2 adds conservative static observations for awk runtime-intent source facts:

- `awk.builtin_call` for fixture-backed builtins such as `print`, `printf`,
  `getline`, `system`, `length`, `substr`, `gsub`, `match`, `sprintf`,
  `tolower`, and gawk `gensub`;
- `awk.user_function_call` for simple same-file function calls, with
  `function_executed=false` and no return-value inference;
- `awk.file_read` and `awk.file_write` for supported `getline < file`,
  `print > file`, and `print >> file` forms;
- `awk.pipe_read` and `awk.pipe_write` for supported command-pipe forms;
- `awk.system_call` for static or dynamic `system(...)` source intent;
- `awk.redirect` for recognized file and pipe redirection operators;
- `awk.include` for gawk `@include` and `awk.extension` for gawk `@load`;
- `awk.secret_like` for awk-owned redacted assignment, command, and path
  contexts.

Static targets are recorded only when short, quoted, non-secret, non-absolute,
and syntactically safe. Dynamic targets use `[dynamic]` and a
`dynamic_reason`; secret-like targets use `[redacted]` and
`raw_value_stored=false`. AWK2 does not inspect the filesystem, load includes,
load extensions, execute command strings, parse shell commands deeply, emit
runtime host-mutation proof, or canonicalize IO/system facts.

## AWK3 Implementation Notes

AWK3 adds selected canonical graph mappings and the
`repomap_kg.awk_readback` bounded summary helper:

- `awk.program` creates an awk program node linked from the source file;
- `awk.function` creates function nodes linked from the awk program;
- `awk.user_function_call` links same-file static calls back to function nodes;
- `awk.builtin_call` creates bounded awk-builtin external evidence;
- static safe `awk.include` and `awk.extension` observations create helper file
  and extension dependency evidence without loading either target;
- static safe `awk.file_read` and `awk.file_write` targets become file
  references with `reads` and `writes` edges;
- static safe `awk.pipe_read`, `awk.pipe_write`, and `awk.system_call`
  observations become command-intent edges, not runtime `executes` edges.

AWK3 leaves BEGIN/END blocks, pattern/action rules, assignments, field and
record references, dynamic expressions, redirects, and secret markers raw-only.
Raw-only observations still become sanitized evidence records, so intentional
raw-only details do not create unsupported-kind diagnostics.

All command-intent and file-intent evidence preserves source-intent metadata
such as `runtime_intent=true`, `awk_executed=false`, `shell_executed=false`,
`command_executed=false`, `filesystem_checked=false`, `file_opened=false`, and
`host_mutation_proven=false` where applicable.

The bounded summary helper reports counts for raw awk observations, selected
canonical node/edge kinds, and safety markers. It omits raw payloads, source
snippets, raw command strings, path examples, and secret values. AWK3 does not
add CLI or MCP readback behavior.

## Known Gaps

After AWK3, RepoMap still deliberately does not implement:

- embedded awk extraction from shell command arguments;
- full awk grammar parsing;
- gawk namespace or extension semantics;
- expression evaluation;
- shell command-string parsing;
- runtime host-mutation classification from `system()` or pipes;
- cross-file include or function resolution;
- canonical readback surfaces beyond the internal bounded helper;
- storage schema changes.

## Acceptance Summary

AWK3 is complete when selected raw observations canonicalize into useful
nodes/edges, raw-only observation kinds remain quiet bounded evidence,
public-safe fixtures dogfood extraction, canonicalization, summary generation,
and storage-row preparation, fake secret values are absent from canonical and
summary output, IO/system facts remain non-executing source intent, no host
mutation is proven, no awk or shell code is executed, no runtime/parser
dependency is added, existing Bash/Bats/PowerShell/generic shell behavior
remains intact, and the combined final gate passes.
