# Zsh Extraction Design

Status: ZSH4 closes the static zsh phaseset with selected canonical graph
mappings, bounded count-only zsh evidence summaries, and public fixture
dogfooding through extraction, canonicalization, summary generation, and
storage-row preparation. ZSH4 remains static-only and treats startup, plugin,
completion, command, glob, parameter expansion, and side-effect evidence as
source/configuration intent, not runtime execution or host-mutation proof.
Dynamic, unsupported, runtime-sensitive, and overly precise zsh facts remain
raw-only.

## Purpose

Zsh extraction should give RepoMap useful static evidence from zsh scripts,
startup files, completion functions, plugin/theme declarations, options, and
dialect syntax without treating zsh as Bash or generic POSIX shell. Zsh is
shell-family, but its startup semantics, option model, autoload/fpath behavior,
glob qualifiers, parameter expansion flags, completion conventions, and plugin
ecosystem need dialect-aware boundaries.

ZSH0 defines:

- how zsh relates to SH0's shared `shell.*` taxonomy;
- which zsh-specific raw observations are justified;
- future zsh detection and classification strategy;
- conservative non-executing parser/scanner strategy;
- startup/profile, option, autoload/fpath, zstyle, zmodload, completion,
  plugin, glob, parameter expansion, redaction, dynamic, and side-effect
  policies;
- public-safe fixture and example strategy;
- the ZSH1 through ZSH4 roadmap.

ZSH1 adds:

- `.zsh`, zsh-shebang, known zsh startup filename, and explicit completion
  candidate classification;
- `zsh.script` and `zsh.startup_file` file-level observations;
- `zsh.option` observations for `setopt`, `unsetopt`, and `emulate -L zsh`;
- `shell.function` with `dialect="zsh"` for ordinary and hook-like functions;
- bounded `shell.assignment`, `shell.export`, and `shell.source`
  observations with zsh metadata;
- `shell.command_substitution`, `shell.dynamic_invocation`, and
  `shell.secret_like` markers for supported static patterns.

ZSH1 does not execute zsh, source files, load plugins, inspect runtime shell
state, model commands or side effects, canonicalize zsh facts, or add readback.

ZSH2 adds:

- `shell.command`, `shell.command_argument`, and `shell.external_command`
  observations for fixture-backed simple zsh commands and wrappers;
- `shell.pipeline` and `shell.command_chain` for simple `|`, `&&`, and `||`
  syntax without modeling byte flow or branch execution;
- `shell.redirect` and `shell.heredoc` observations without reading or writing
  files and without storing heredoc bodies;
- `zsh.autoload`, `zsh.fpath`, `zsh.zstyle`, `zsh.zmodload`, `zsh.bindkey`,
  `zsh.compinit`, and `zsh.completion_function` configuration-intent
  observations;
- `zsh.plugin`, `zsh.plugin_manager`, `zsh.theme`, and `zsh.prompt`
  observations for fixture-backed plugin/theme/prompt declarations;
- stronger redaction for zstyle, prompt, plugin/source, and command-argument
  contexts.

ZSH2 does not execute zsh or shell code, load plugins, initialize
completions, apply styles or bindings, load zmodules, inspect fpath or runtime
state, classify plugin managers as network/package/host mutations, canonicalize
zsh facts, or add readback.

ZSH3 adds:

- `zsh.array_assignment` and `zsh.associative_array_assignment` observations
  with bounded counts and no runtime array expansion;
- `zsh.parameter_expansion` observations for fixture-backed expansion flags
  such as `${(q)path}`, `${(@f)...}`, `${(j: :)array}`, `${(U)...}`,
  `${(L)...}`, and `${(u)...}` without evaluating values;
- `zsh.glob_qualifier`, `zsh.extended_glob`, and `zsh.path_reference`
  observations for fixture-backed glob syntax without expanding globs,
  inspecting files, or inferring match counts;
- `zsh.dynamic_invocation` observations for zsh-specific dynamic/plugin-loader
  boundaries such as plugin-manager eval, computed fpath, and plugin-loader
  forms;
- source-intent `shell.env_read`, `shell.env_write`, `shell.file_read`,
  `shell.file_write`, `shell.network_call`, `shell.package_manager`, and
  `shell.host_mutation` observations for fixture-backed static forms.

ZSH3 does not execute zsh or shell code, source startup/plugin/completion files,
load plugins or modules, run plugin managers, expand globs, evaluate parameter
expansions, inspect runtime shell state, open/check/mutate files, run network or
package-manager commands, classify plugin managers as package/network mutation,
canonicalize zsh facts, or add readback.

ZSH4 adds:

- `zsh.script` and `zsh.function` canonical graph keys;
- selected mappings for `zsh.script`, `zsh.startup_file`, zsh
  `shell.function`, static `shell.source`, static zsh `shell.command` and
  `shell.external_command`, `zsh.autoload`, `zsh.zmodload`,
  `zsh.completion_function`, `zsh.plugin_manager`, `zsh.plugin`,
  source-intent environment/file/network/package/host-mutation observations;
- zsh-specific intent edge kinds such as `command_intent`, `network_intent`,
  `package_intent`, `host_mutation_intent`, `uses_plugin`,
  `uses_plugin_manager`, `uses_zsh_module`, and `completion_for`;
- `repomap_kg.zsh_readback.summarize_zsh_evidence`, a count-only internal
  helper for bounded fixture dogfooding;
- storage-row preparation tests for the selected zsh canonical graph.

ZSH4 does not execute zsh or shell code, source startup/plugin/completion files,
load plugins or modules, run plugin managers, expand globs or parameter
expansions, inspect runtime shell state, open/check/mutate files, run network or
package-manager commands, prove host mutation, add parser/runtime dependencies,
change storage schema, or add CLI/MCP readback.

## Design Principles

Zsh extraction should be static, conservative, dialect-aware,
shell-family-compatible, zsh-profile/plugin/completion aware, redaction-first,
honest about dynamic behavior, and useful for graph evidence without running
zsh or loading plugins.

Future extraction should prefer bounded unknown observations over false
precision. Dynamic paths, plugin names, autoloaded functions, glob patterns,
parameter expansions, prompt strings, and command constructions must not become
fabricated precise files, commands, plugin repositories, or runtime shell
state.

## Non-Execution Policy

ZSH0 inherits SH0's static boundary and makes it zsh-specific. Future zsh
extraction must not:

- execute zsh scripts, profiles, startup files, completion functions, prompt
  files, plugin files, or theme files;
- invoke `zsh`, Bash, POSIX shell, awk, Bats, zunit, plugin managers, package
  managers, network tools, or external commands;
- call subprocess to inspect zsh parsing, expansion, completion, globbing,
  plugin loading, startup behavior, or runtime option state;
- source startup files or plugin files;
- run `autoload`, `compinit`, `promptinit`, `zstyle`, `zmodload`, `bindkey`,
  plugin managers, command substitutions, eval strings, or dynamic commands;
- inspect runtime `$ZDOTDIR`, `$ZSH`, `$fpath`, `$FPATH`, `$path`, `$plugins`,
  shell options, completion caches, or plugin directories by running zsh;
- infer current user shell state from source;
- mutate host filesystem, shell profiles, environment, services, scheduled
  jobs, plugin directories, package state, process state, container runtime, or
  network state;
- store raw secret-like values, private source snippets, prompt strings that may
  leak private context, or raw command strings that are secret-like or long.

Every future zsh observation should include metadata equivalent to:

- `language="zsh"`;
- `dialect="zsh"`;
- `static_only=true`;
- `shell_executed=false`;
- `zsh_executed=false`;
- `startup_executed=false`;
- `plugins_loaded=false`.

## Relationship To SH0, Bash, Bats, And Awk

Zsh belongs in the shell-family roadmap and should reuse shared `shell.*` kinds
when they honestly represent shell-family facts:

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

Use zsh-specific raw kinds where shared `shell.*` is misleading or too lossy:

- zsh options are not identical to Bash options;
- `autoload` and `fpath` are not ordinary source includes;
- completion functions have naming and loading conventions;
- `zstyle` is configuration evidence, not a command that ran;
- `zmodload` is module intent, not proof that a module loaded;
- glob qualifiers and parameter expansion flags are source syntax, not runtime
  file targets or expanded values;
- plugin manager declarations are dependency/config intent, not proof that
  plugins were installed, cloned, sourced, or loaded.

Bash, Bats, and awk extraction remain unchanged. Generic `.sh` files should
not become zsh unless future phases add explicit, tested zsh evidence.

## Zsh-Specific Raw Kind Policy

Use zsh-specific observations where shared shell facts would lose dialect
meaning.

| Kind | Planned Phase | Purpose |
| --- | --- | --- |
| `zsh.script` | ZSH1 | File-level zsh script/profile evidence. |
| `zsh.startup_file` | ZSH1 | Startup file role such as `.zshenv`, `.zprofile`, `.zshrc`, `.zlogin`, or `.zlogout`. |
| `zsh.option` | ZSH1 | Bounded option evidence from `setopt`, `unsetopt`, or `emulate`. |
| `zsh.setopt` | ZSH1 | Optional set-option detail if separate kind is useful. |
| `zsh.unsetopt` | ZSH1 | Optional unset-option detail if separate kind is useful. |
| `zsh.function` | ZSH1/ZSH2 | Zsh-specific function evidence for hooks, completions, autoloaded functions, or anonymous forms. |
| `zsh.autoload` | ZSH2 | Autoload declarations and flags. |
| `zsh.fpath` | ZSH2 | Static fpath/path-array configuration evidence. |
| `zsh.zstyle` | ZSH2 | Static zstyle context/style/value evidence. |
| `zsh.zmodload` | ZSH2 | Zsh module load/unload/list intent. |
| `zsh.bindkey` | ZSH2 | Keymap/binding configuration evidence. |
| `zsh.compinit` | ZSH2 | Completion initialization intent without execution. |
| `zsh.completion_function` | ZSH2 | Completion function files or `#compdef` evidence. |
| `zsh.plugin` | ZSH2 | Plugin declarations or plugin repo references. |
| `zsh.plugin_manager` | ZSH2 | Plugin manager command/config evidence. |
| `zsh.theme` | ZSH2 | Theme/prompt framework declarations. |
| `zsh.prompt` | ZSH2 | Prompt configuration evidence, bounded and redacted. |
| `zsh.array_assignment` | ZSH3 | Indexed array assignments with zsh semantics. |
| `zsh.associative_array_assignment` | ZSH3 | Associative array assignments. |
| `zsh.parameter_expansion` | ZSH3 | Parameter expansion flags and bounded dynamic syntax. |
| `zsh.glob_qualifier` | ZSH3 | Glob qualifier evidence without expansion. |
| `zsh.extended_glob` | ZSH3 | Extended glob syntax markers without matching files. |
| `zsh.path_reference` | ZSH3 | Bounded path-like source references when shared file facts would overstate runtime behavior. |
| `zsh.dynamic_invocation` | ZSH3 | Zsh-specific eval/plugin-loader/dynamic command evidence. |
| `zsh.secret_like` | ZSH1+ | Zsh-owned redaction markers when shared shell redaction is too broad. |

Recommended phase allocation:

- ZSH1: classification, `zsh.script`, `zsh.startup_file`, `zsh.option`,
  ordinary function evidence, safe assignment/export/source evidence, command
  substitution markers, dynamic invocation markers, and redaction;
- ZSH2: commands, arguments, pipelines, chains, redirects, heredocs, autoload,
  fpath, zstyle, zmodload, bindkey, compinit, completion functions, plugins,
  themes, and prompts;
- ZSH3: arrays, associative arrays, parameter expansion flags, glob
  qualifiers, extended globs, deeper dynamic/plugin-loader boundaries,
  side-effect intent, and false-positive hardening;
- ZSH4: selected canonicalization, bounded count-only readback, and fixture
  dogfooding.

## Detection And Classification Strategy

Future zsh classification should be evidence-based.

Classify as zsh when:

- the extension is `.zsh`;
- the first line has a zsh shebang such as `#!/usr/bin/env zsh`,
  `#!/bin/zsh`, or `#!/usr/bin/zsh`;
- the filename is a known zsh startup file: `.zshenv`, `.zprofile`, `.zshrc`,
  `.zlogin`, or `.zlogout`;
- a file is under zsh-like config paths and has explicit zsh suffix/name
  evidence;
- a completion file has a leading underscore and is under completion-like paths
  or has zsh completion evidence such as `#compdef` or `_arguments`.

Do not classify:

- generic `.sh` files as zsh without explicit zsh shebang or future tested
  zsh-only syntax evidence;
- `.bash`, `.bats`, `.awk`, `.ps1`, `.psm1`, `.psd1`, Makefiles, docs, task
  runners, or plugin manager lockfiles as zsh merely because they mention zsh;
- shell scripts invoking `zsh -c` as zsh source;
- ordinary Bash helper files in test directories as zsh.

Conservative zsh-only syntax evidence that may upgrade a generic shell file in
later phases includes:

- `emulate -L zsh`;
- `autoload -Uz`;
- `zstyle`;
- `zmodload`;
- `setopt` or `unsetopt` with zsh-specific option names;
- fixture-backed glob qualifiers such as `*(.)`, `*(/)`, `*(@)`, `*(N)`, or
  `**/*(.)`;
- fixture-backed parameter expansion flags such as `${(@f)...}`,
  `${(j: :)array}`, or `${(q)var}`.

Do not upgrade on ambiguous syntax alone. For example, `typeset -A` can appear
in more than one shell dialect and should not be enough by itself.

## Parser And Scanner Strategy

ZSH1 should start with a stdlib-only static scanner/tokenizer:

- no zsh invocation;
- no shell invocation;
- no parser/runtime dependency;
- line-aware and heredoc-aware scanning;
- basic brace/function tracking only where reliable;
- bounded unknown observations for unsupported syntax;
- fixture-backed recognition only;
- false-positive avoidance over high recall.

Parser candidates for later evaluation include Tree-sitter Bash/zsh grammars if
a suitable zsh grammar exists, a small custom zsh tokenizer/parser, and other
static parsers after dependency, license, packaging, determinism, line-range,
and cross-platform review. Parser adoption should be a dedicated later phase.

Zsh syntax overlaps with POSIX/Bash but differs in options, arrays, expansion,
globbing, startup semantics, and runtime state. A line-oriented scanner will
miss complex nested constructs, and that is acceptable in early phases.

## Core Zsh Constructs

Future phases should model zsh source conservatively.

### Startup Files

Recognize startup files such as `.zshenv`, `.zprofile`, `.zshrc`, `.zlogin`,
and `.zlogout`.

`zsh.startup_file` metadata should include:

- `startup_file_kind`: `zshenv`, `zprofile`, `zshrc`, `zlogin`, `zlogout`, or
  `unknown`;
- documented startup order when useful;
- `startup_executed=false`;
- `profile_loaded=false`;
- `static_only=true`;
- `zsh_executed=false`.

Observing `.zshrc` does not mean it ran. Do not infer current user shell state
or read/source files referenced by `$ZDOTDIR`, `$ZSH`, `$fpath`, or plugin
managers.

### Options

Recognize source forms such as:

```zsh
setopt extendedglob nullglob prompt_subst
unsetopt beep nomatch
emulate -L zsh
```

Zsh option metadata should include:

- `option_name`;
- `operation`: `set`, `unset`, `emulate`, or `unknown`;
- `option_scope`: `file`, `function_local`, or `unknown`;
- `runtime_option_state_known=false`;
- `static_only=true`;
- `zsh_executed=false`.

Do not infer actual runtime options.

### Functions

Use `shell.function` with `dialect="zsh"` for ordinary static functions unless
zsh-specific function metadata is needed. Use `zsh.function` for autoloaded
functions, completion functions, anonymous functions, hook functions such as
`precmd`, `preexec`, and `chpwd`, or other zsh-specific forms.

Function metadata should include:

- `function_name`;
- `syntax`: `name_parens`, `function_keyword`, `anonymous`, `hook`, or
  `completion`;
- `body_modeled=false` initially;
- `zsh_executed=false`.

Function bodies are source evidence, not runtime execution.

### Autoload And Fpath

Recognize:

```zsh
fpath=("$ZDOTDIR/functions" $fpath)
autoload -Uz compinit promptinit
compinit
```

`zsh.autoload` metadata should include function names, flags such as `-U`,
`-z`, or `-Uz`, target kind, `autoload_executed=false`, and
`function_loaded=false`.

`zsh.fpath` metadata should include operation, path counts, static/dynamic/
redacted path counts, `filesystem_checked=false`, and
`fpath_runtime_state_known=false`.

Do not inspect the filesystem or resolve autoloaded function files.

### Zstyle, Zmodload, Bindkey, And Completion

Recognize bounded configuration source:

```zsh
zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Z}'
zmodload zsh/complist
bindkey -e
bindkey '^R' history-incremental-search-backward
#compdef mytool
_arguments '1:command:->cmds' '*::arg:->args'
```

`zsh.zstyle` should record safe context/style/value summaries while preserving
`zstyle_applied=false`. `zsh.zmodload` should record module intent with
`module_loaded=false`. `zsh.bindkey` should record keymap/binding configuration
without applying it. `zsh.compinit` and `zsh.completion_function` should record
completion intent with `compinit_executed=false` and
`completion_loaded=false`.

Do not run completion scripts, query styles, load modules, or apply bindings.

### Plugins, Themes, And Prompts

Recognize source intent for common plugin ecosystems:

```zsh
plugins=(git docker kubectl)
source "$ZSH/oh-my-zsh.sh"
ZSH_THEME="agnoster"
zinit light zsh-users/zsh-autosuggestions
antigen bundle zsh-users/zsh-completions
zplug "zsh-users/zsh-syntax-highlighting"
antidote load
eval "$(sheldon source)"
```

Plugin/theme observations are dependency or configuration intent only. Do not
install, clone, update, source, load, or execute plugins. Do not infer plugin
availability or call network APIs.

Metadata should include manager, plugin or repo name when static and safe,
declaration kind, `plugin_loaded=false`, `plugin_installed=false`,
`network_called=false`, `shell_executed=false`, and `zsh_executed=false`.

`eval "$(plugin-manager ...)"` should be dynamic invocation evidence, not
execution proof.

### Glob Qualifiers And Parameter Expansion Flags

Recognize source syntax such as:

```zsh
print -- **/*.zsh(.)
rm -- *.tmp(N)
for f in **/*(.om[1,10]); do print -- "$f"; done
print -r -- ${(q)path}
lines=(${(@f)"$(git status --short)"})
joined=${(j: :)array}
```

Policy:

- do not expand globs;
- do not inspect matching files;
- do not infer actual file targets from glob qualifiers;
- do not evaluate parameter expansion flags;
- treat glob and parameter facts as source syntax or bounded dynamic evidence.

`zsh.glob_qualifier` metadata should include a safe qualifier summary,
pattern kind, `filesystem_checked=false`, `glob_expanded=false`, and
`target_count_known=false`.

`zsh.parameter_expansion` metadata should include safe expansion flags,
visible non-secret parameter names when available, `value_expanded=false`, and
dynamic reason metadata.

## Side-Effect Strategy

Zsh phases may reuse Bash shell-family side-effect taxonomy, but startup and
plugin semantics matter.

Policy:

- a command in `.zshrc` is source/config intent, not proof of runtime
  execution;
- host mutation observations should be conservative and explicitly static;
- startup-file side-effect metadata should include startup kind,
  `startup_executed=false`, and `zsh_executed=false`;
- plugin manager commands should not become package/network mutation evidence
  unless a later phase explicitly scopes plugin-manager intent;
- dynamic, eval, and plugin-loader commands should remain bounded dynamic
  evidence.

## Redaction Policy

Zsh inherits SH0/Bash redaction and adds zsh-specific contexts.

Secret-like names include password, passwd, secret, token, key, credential,
apikey, pat, authorization, and auth. Sensitive contexts include:

- exports and assignments in startup files;
- plugin manager tokens or private repo URLs;
- `zstyle` values;
- prompt variables that may include tokens or private context;
- command strings inside `eval`;
- completion/cache paths with secret-like names;
- private host/user/path fragments in profiles.

Rules:

- do not store raw secret-like values;
- preserve variable, style, or key name and redaction reason;
- set `raw_value_stored=false`;
- avoid over-matching ordinary words such as `path` as `pat`;
- fixtures must use fake markers that tests prove absent once implementation
  begins.

## Dynamic And Unknown Policy

Future extraction should emit bounded dynamic or unknown evidence for:

- `eval "$cmd"`;
- `source "$computed_path"`;
- `autoload "$fn"`;
- `fpath=($computed $fpath)`;
- plugin arrays with computed names;
- plugin manager `eval "$(tool source)"`;
- command substitution in assignments or prompts;
- parameter expansion flags;
- glob qualifiers;
- anonymous functions and hooks;
- computed `zstyle` contexts or values.

Record `dynamic_reason`, do not infer precise file/plugin/command/function
targets, and do not execute, expand, source, or read referenced files.

## False-Positive Boundaries

Future scanner safeguards should suppress extraction from:

- comments;
- quoted strings;
- heredoc bodies;
- here-string values;
- arrays containing command-looking text;
- `zstyle` values containing command-looking text;
- prompt strings;
- plugin README/code-block examples;
- completion descriptions that look like commands;
- case pattern labels;
- glob qualifiers that look like subshells;
- parameter expansions that look like command substitution.

Prefer missing a construct over extracting a dangerous false positive.

## Canonicalization And Readback Targets

ZSH4 follows BASH5, BATS3, and AWK3: it maps a selected safe subset and leaves
dynamic or runtime-sensitive details raw-only.

Implemented canonical mappings:

- zsh files as `zsh.script` nodes linked from file nodes;
- static zsh functions as `zsh.function` nodes;
- startup-file evidence as bounded zsh startup configuration evidence;
- static source targets as file-reference `includes` edges with
  `source_executed=false` and `file_read=false`;
- static zsh commands as `tool:*` nodes with `command_intent` edges and
  `command_executed=false`;
- autoload declarations as function dependency/config evidence without loading
  functions;
- zmodload declarations as zsh module dependency evidence with
  `module_loaded=false`;
- completion functions as completion evidence with `completion_loaded=false`;
- plugin managers and plugins as dependency/config intent evidence with
  `plugin_loaded=false`, `plugin_installed=false`, and `network_called=false`;
- static environment, file, network, package-manager, and host-mutation source
  intent as bounded graph edges that preserve non-execution metadata.

Raw-only details include zsh options, assignments, exports, command arguments,
pipelines, chains, redirects, heredocs, fpath, zstyle, bindkey, compinit, theme,
prompt, arrays, associative arrays, parameter expansions, glob qualifiers,
extended globs, path references, dynamic invocations, command substitutions,
and secret-like markers.

Bounded readback is count-only:

- zsh files and startup files;
- functions;
- options;
- sources;
- commands;
- pipelines, chains, redirects, and heredocs;
- autoloads;
- fpath entries;
- zstyle entries;
- zmodload entries;
- bindkey entries;
- completion functions;
- plugin and theme declarations;
- arrays;
- glob qualifiers;
- parameter expansions;
- dynamic/unknown count;
- secret-like redacted count;
- canonical nodes/edges produced.

Readback must not include raw source snippets, raw secret values, unbounded path
lists, private absolute paths, prompt strings, or raw command strings when
secret-like or long.

## Fixture Strategy

ZSH0 adds public-safe docs examples under `docs/examples/zsh/`. ZSH1 and ZSH2
add public-safe implementation fixtures under `src/test/fixtures/shell/zsh/`.

Current and planned fixtures include:

- `basic.zsh`;
- `startup/.zshenv`;
- `startup/.zprofile`;
- `startup/.zshrc`;
- `functions.zsh`;
- `commands.zsh`;
- `pipelines-and-redirects.zsh`;
- `autoload-and-fpath.zsh`;
- `zstyle-and-completion.zsh`;
- `plugins-and-themes.zsh`;
- `heredocs.zsh`;
- `globs-and-expansions.zsh`;
- `side-effects.zsh`;
- `dynamic.zsh`;
- `redaction.zsh`;
- `false-positives.zsh`.

Fixture and example rules:

- static extraction inputs only;
- no execution required;
- non-executable by default;
- no real private paths;
- no real credentials, tokens, private keys, or sensitive command strings;
- `.invalid` domains for URI-like strings;
- plugin/network-looking syntax clearly labeled as source examples, not
  commands to run.

## Roadmap

### ZSH1: Classification And Basic Structure

ZSH1 should classify `.zsh`, zsh shebang files, known zsh startup filenames,
and safe completion candidates when evidence is explicit. It should emit
`zsh.script`, `zsh.startup_file`, option observations, function observations,
safe assignments/exports/source includes, command-substitution markers,
dynamic invocation markers, and redaction markers. It should not execute zsh or
add parser/runtime dependencies.

### ZSH2: Commands, Sourcing, Plugins, Completions, And Options

ZSH2 should add command/argument/pipeline/chain/redirect/heredoc observations
with zsh metadata, plus autoload, fpath, zstyle, zmodload, bindkey, compinit,
completion-function, plugin, theme, and prompt evidence. It should not load
plugins, run plugin managers, or call network tools.

### ZSH3: Advanced Dialect Safety

ZSH3 adds arrays, associative arrays, glob qualifiers, extended glob markers,
parameter expansion flags, deeper dynamic/eval/plugin-loader boundaries,
side-effect intent with startup/profile metadata, and false-positive hardening.
All ZSH3 facts remain raw static observations. Glob, parameter-expansion, and
array observations are syntax/configuration evidence only; side-effect
observations are source intent only and preserve `command_executed=false`,
`filesystem_checked=false`, `host_mutation_proven=false`,
`network_called=false`, and `package_manager_executed=false`.

### ZSH4: Canonicalization, Readback, And Dogfooding

ZSH4 adds selected raw-to-canonical mappings, a bounded count-only summary
helper, public-safe fixture dogfooding, startup/plugin/command evidence that
remains non-executed, dynamic/unsupported raw-only behavior, fake secret
non-leakage, and no storage schema redesign.

## Acceptance Summary

ZSH0 is complete when zsh extraction design exists; relationship to SH0 and
completed Bash/Bats/awk phases is explicit; zsh-specific raw-kind policy,
detection/classification strategy, parser/scanner strategy, non-execution
policy, startup/profile policy, plugin/completion policy,
option/autoload/fpath/zstyle policy, glob/parameter expansion safety policy,
redaction policy, dynamic/unknown policy, fixture strategy, and ZSH1-ZSH4
roadmap are documented; no zsh extractor implementation or classification
behavior change lands; no zsh, shell, plugin-manager, or package-manager code
is executed; no runtime/parser dependency is added; and docs-only verification
passes.
