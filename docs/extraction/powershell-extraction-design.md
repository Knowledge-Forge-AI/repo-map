# PowerShell Extraction Design

Status: PWSH6 implements selected conservative canonicalization and bounded
count-only dogfooding summaries for public-safe PowerShell fixtures. The
remaining sections still define the broader future design.

## Purpose

PowerShell should become RepoMap's bridge between structured source-code
extractors and less-structured shell extraction. The future extractor should
produce useful graph evidence from PowerShell files while staying static,
bounded, and honest about uncertainty.

PWSH0 defines the taxonomy, safety policy, fixture plan, and phase roadmap
before implementation. Later phases may implement extraction, canonicalization,
and readback, but those phases should preserve the non-execution boundary
defined here.

PWSH1 implements classification and basic static raw observations for `.ps1`,
`.psm1`, and `.psd1` files. It recognizes script, module, manifest, function,
param, `#requires`, `using module`, `Import-Module`, static dot-source,
bounded dynamic invocation, secret-like, and simple manifest-field observations.
It does not execute PowerShell, invoke `pwsh`, evaluate manifests, add
canonicalization, or change storage schema.

PWSH2 adds conservative raw observations for recognized cmdlets, a small static
alias table, obvious external command tokens, named and positional command
arguments, splats, and simple pipelines with segment order. It still does not
execute PowerShell, infer object-flow semantics, classify host mutation, add
canonicalization, or change storage schema.

PWSH3 adds conservative raw observations for likely side effects visible in
static command shapes: file reads/writes, environment reads/writes, registry
reads/writes, network calls, remoting, process execution, service control,
scheduled-task changes, package-management operations, security-policy changes,
and credential-handling commands. It still does not execute PowerShell, invoke
external tools, model full runtime semantics, add canonicalization, or change
storage schema.

PWSH4 adds conservative literal `.psd1` manifest extraction for common scalar,
array, export, dependency, file-reference, and `PrivateData.PSData` fields. It
parses only a small data-literal subset, emits bounded unknowns for expressions
such as variables or `(Get-Date)`, redacts secret-like manifest values, and
still does not evaluate manifests, import modules, execute PowerShell, add
canonicalization, or change storage schema.

PWSH5 expands the conservative static model for aliases, splats, and dynamic
invocation. It adds tested built-in aliases, static same-file alias-definition
observations, literal splat-assignment summaries, call-site splat links, richer
dynamic invocation metadata, and a small line sanitizer for block comments and
here-strings. It still does not resolve aliases or splats by running
PowerShell, evaluate expressions, import modules, execute command targets, add
canonicalization, or change storage schema.

PWSH6 maps a selected subset of PowerShell raw observations into canonical graph
nodes and edges. It adds PowerShell script/module/manifest/function/export
canonical keys, reuses existing `tool:*`, `file:*`, `env:*`,
`host.category:*`, `external:*`, and `external.url:*` targets, and emits
standard relationship kinds such as `defines`, `imports`, `sources`,
`executes`, `references`, `depends_on`, and `mutates_host`. It also adds a
bounded in-memory summary helper for fixture dogfooding. Dynamic invocation,
alias definitions, splat assignments, command arguments, pipeline details,
secret markers, manifest fields/private data, and detailed file/registry
side-effect observations remain raw-only unless a selected mapping is safe.
PWSH6 still does not execute PowerShell, evaluate aliases or splats, add storage
schema changes, add MCP/readback API changes, or run live/private graph
refreshes.

## Non-Execution Policy

PowerShell extraction must be static.

Future extraction must not:

- execute scripts;
- invoke `pwsh`, Windows PowerShell, package managers, remoting, services, or
  external commands;
- evaluate `.psd1` expressions;
- resolve dynamic invocation by running code;
- call network APIs;
- mutate the host filesystem, registry, environment, services, scheduled
  tasks, user profiles, or process table;
- read private source snippets into ordinary public docs or readback output.

When the extractor cannot statically understand a construct, it should emit a
bounded unknown or dynamic observation rather than inventing a precise fact.

## File Types

PowerShell support should cover these file roles:

- `.ps1`: scripts, maintenance commands, operational runbooks, and entry-point
  files.
- `.psm1`: modules that define reusable functions, aliases, and exports.
- `.psd1`: module manifests and data files. These can include expressions, so
  extraction must parse conservatively and must not evaluate the file.

The first implementation phase should route these files only after tests prove
classification and extraction are non-executing.

## Observation Taxonomy

Future raw observations should use `powershell.*` kinds. The first stable set
should include:

| Kind | Meaning |
| --- | --- |
| `powershell.script` | A `.ps1` script file. |
| `powershell.module` | A `.psm1` module file. |
| `powershell.manifest` | A `.psd1` manifest or data file. |
| `powershell.manifest_field` | A statically visible `.psd1` field or bounded unknown field. |
| `powershell.manifest_dependency` | A module, assembly, or nested-module dependency from a manifest. |
| `powershell.manifest_file_reference` | A static manifest file reference such as `RootModule` or `ScriptsToProcess`. |
| `powershell.manifest_export` | A manifest export list entry or wildcard. |
| `powershell.manifest_private_data` | A safe `PrivateData` or `PrivateData.PSData` metadata value. |
| `powershell.function` | A statically named function definition. |
| `powershell.param` | A parameter block or function parameter. |
| `powershell.requires` | A `#requires` directive. |
| `powershell.using_module` | A `using module` statement. |
| `powershell.import_module` | An `Import-Module` command. |
| `powershell.dot_source` | A static dot-source include. |
| `powershell.command` | A cmdlet or function command invocation. |
| `powershell.command_argument` | A named or positional command argument when useful. |
| `powershell.pipeline` | A pipeline segment or command chain relation. |
| `powershell.external_command` | A non-PowerShell executable invocation. |
| `powershell.alias_command` | A recognized alias invocation and its normalized target. |
| `powershell.splat` | A splatted parameter source such as `@params`. |
| `powershell.alias_definition` | A simple same-file `Set-Alias` or `New-Alias` definition. |
| `powershell.splat_assignment` | A simple literal splat hashtable assignment summary. |
| `powershell.dynamic_invocation` | A dynamic command invocation such as `& $Command`. |
| `powershell.env_read` | A read from `$env:NAME`. |
| `powershell.env_write` | A write to `$env:NAME`. |
| `powershell.file_read` | A likely file read target. |
| `powershell.file_write` | A likely file write or directory mutation target. |
| `powershell.registry_read` | A likely registry read target. |
| `powershell.registry_write` | A likely registry write target. |
| `powershell.host_mutation` | A likely operational side effect on the host. |
| `powershell.network_call` | A likely network request or download. |
| `powershell.remoting` | A likely remoting or session operation. |
| `powershell.secret_like` | A secret-like variable, parameter, literal, or argument. |

Observation kinds may be split later if implementation finds a durable reason,
but the first extractor should avoid overly specific kinds until fixtures prove
the distinction is useful.

## Confidence Levels

PowerShell observations should include one of these confidence values:

- `static`: directly recognized syntax or a command pattern with a static
  target.
- `heuristic`: a command and argument pattern that strongly suggests a fact, but
  does not fully resolve runtime behavior.
- `dynamic`: a value, command target, or include target depends on runtime
  state.
- `unknown`: the extractor deliberately records a bounded unknown rather than
  guessing.

Dynamic and unknown observations are first-class evidence. They are preferable
to false precision.

RepoMap raw observation schema currently accepts `extracted`, `heuristic`,
`manual`, and `unknown` as stored confidence values. PWSH1 maps dynamic
PowerShell constructs to `confidence="unknown"` with `metadata.resolution =
"dynamic"` rather than adding a new schema confidence.

## Metadata Fields

PowerShell observations should include the common raw observation fields plus
PowerShell-specific metadata where available:

- command name;
- normalized command name;
- original command token;
- alias expansion, if any;
- argument names;
- argument value redaction status;
- source path;
- line range if available;
- pipeline index;
- target path, registry key, URI, module name, or environment variable when
  statically visible;
- mutation category;
- confidence;
- extractor version;
- redaction marker;
- `path_examples_included=false` for private graph readback unless an explicit
  safe mode is added later.

Do not store raw secret values, long source snippets, private absolute paths, or
unbounded path lists in ordinary observations or readback.

## Command Normalization

PowerShell command normalization should preserve both the original token and a
normalized target.

Planned handling:

- Verb-noun cmdlets such as `Get-ChildItem`, `Set-ItemProperty`, and
  `Invoke-WebRequest` normalize to their canonical command name.
- Common aliases such as `gci`, `ls`, `cat`, `iwr`, `irm`, `ni`, and `rm`
  should emit `powershell.alias_command` with a normalized target when the alias
  table is static and local to RepoMap.
- PWSH5 also recognizes tested aliases such as `echo`, `curl`, `wget`,
  `mkdir`, and `rmdir`. These are treated as PowerShell source alias semantics,
  not as evidence that any native tool was executed.
- Simple same-file `Set-Alias` and `New-Alias` definitions emit
  `powershell.alias_definition`; static definitions encountered earlier in the
  same file may be used for later command normalization in that file only.
- External commands such as `git`, `winget`, `choco`, `scoop`, `kubectl`,
  `terraform`, and `docker` should emit `powershell.external_command` with
  `tool:<command>` style targets where consistent with existing shell evidence.
- Dynamic invocation such as `& $Command`, `Invoke-Expression`, and command
  strings should emit `powershell.dynamic_invocation`. The extractor should not
  execute or expand them.
- Splatting such as `@params` should emit `powershell.splat` and attach the
  visible splat variable name. PWSH5 summarizes simple literal splat hashtable
  assignments with key counts, safe key names, redacted key names, and dynamic
  value markers. It links call-site splats to same-file assignments when
  statically available, but it does not expand splats into runtime behavior.
- Pipelines should preserve command order with pipeline indexes and should avoid
  pretending to know object flow unless a future model explicitly supports it.
- Command chains should be represented as bounded command observations, not as
  a full runtime control-flow graph.

## Side-Effect Taxonomy

The future extractor should distinguish ordinary readback from host mutation.
The following side-effect categories are proposed:

- file read;
- file write;
- directory mutation;
- environment read;
- environment write;
- registry read;
- registry write;
- process execution;
- service control;
- scheduled task mutation;
- package install, update, or remove;
- network call or download;
- remoting or session;
- credential or secret handling;
- policy or security change;
- unknown host mutation.

Host mutation examples include:

- `Set-ItemProperty`;
- `New-ItemProperty`;
- `New-Item`;
- `Remove-Item`;
- `Set-Content`;
- `Copy-Item`;
- `Move-Item`;
- `Start-Process`;
- `Start-Service`;
- `Set-Service`;
- `New-Service`;
- `Register-ScheduledTask`;
- `Install-Module`;
- `Install-Package`;
- `winget install`;
- `choco install`;
- `scoop install`.

Network and remoting examples include:

- `Invoke-WebRequest`;
- `Invoke-RestMethod`;
- `Start-BitsTransfer`;
- `Invoke-Command`;
- `Enter-PSSession`;
- `New-PSSession`.

These examples are taxonomy inputs, not permission for the extractor to execute
anything.

## Secret Redaction

PowerShell extraction should mark and redact secret-like values.

Secret-like signals include:

- variable, parameter, property, or environment names containing `password`,
  `secret`, `token`, `key`, `credential`, `apikey`, or `pat`;
- `ConvertTo-SecureString`;
- `PSCredential`;
- `Get-Credential`;
- `Authorization` headers;
- `SecureString`;
- credential-shaped environment variables;
- literal values passed to secret-like parameters.

The extractor should preserve the existence and shape of a secret-like fact
without storing the raw value. Example metadata:

```json
{
  "name": "ApiToken",
  "redacted": true,
  "redaction_reason": "secret-like parameter name"
}
```

Fake fixture values should still be redacted by tests to prove the policy.

## Module Manifest Extraction

PWSH4 statically inspects common literal module manifest fields:

- `RootModule`;
- `ModuleVersion`;
- `GUID`;
- `Author`;
- `CompanyName`;
- `Copyright`;
- `Description`;
- `PowerShellVersion`;
- `CompatiblePSEditions`;
- `RequiredModules`;
- `RequiredAssemblies`;
- `ScriptsToProcess`;
- `TypesToProcess`;
- `FormatsToProcess`;
- `NestedModules`;
- `FunctionsToExport`;
- `CmdletsToExport`;
- `VariablesToExport`;
- `AliasesToExport`;
- `DscResourcesToExport`;
- `ModuleList`;
- `FileList`;
- `PrivateData`;
- `PrivateData.PSData.Tags`;
- `PrivateData.PSData.ProjectUri`;
- `PrivateData.PSData.LicenseUri`;
- `PrivateData.PSData.IconUri`;
- `PrivateData.PSData.ReleaseNotes`;
- `PrivateData.PSData.Prerelease`.

The PWSH4 literal subset covers root hashtables, simple key/value assignments,
single- and double-quoted strings without interpolation, string arrays,
hashtables, nested hashtables, booleans, integers, and `$null`. It records:

- `powershell.manifest_field` for scalar, array, nested, and unknown fields;
- `powershell.manifest_dependency` for `RequiredModules`,
  `RequiredAssemblies`, and `NestedModules`;
- `powershell.manifest_file_reference` for static module, script, type, format,
  nested-module, module-list, and file-list references;
- `powershell.manifest_export` for function, cmdlet, alias, variable, and DSC
  resource exports, including wildcard exports without expansion;
- `powershell.manifest_private_data` for safe `PrivateData` values and known
  `PrivateData.PSData` package metadata.

`.psd1` files can contain expressions. RepoMap should parse literal hashtable
data conservatively and should emit bounded unknown observations for values it
cannot safely parse. It must not evaluate expressions, import modules, resolve
paths by running code, or call PowerShell.

## Fixture Strategy

PWSH0 keeps examples under `docs/examples/powershell/` instead of `src/test`.
Future implementation phases should promote or copy relevant examples into
explicit test fixtures with assertions.

Fixture examples should cover:

- a basic script with a `param` block and functions;
- a module file with exported functions;
- a module manifest;
- imports and dot-source examples;
- pipelines;
- environment reads and writes;
- filesystem mutation examples;
- registry mutation examples;
- package manager examples;
- network call examples;
- remoting examples;
- secret-like fake values;
- dynamic invocation;
- splatting;
- aliases;
- external commands.

Fixture rules:

- keep fixtures fake and public-safe;
- do not include real secrets;
- do not include real private paths;
- do not require execution;
- do not execute anything during tests or docs checks;
- clearly label examples as static extraction fixtures;
- keep mutating or network-looking command syntax inside uncalled functions
  where practical, so the files do not perform work merely by being opened or
  sourced.

## Phase Roadmap

Proposed follow-up sequence:

1. PWSH0: taxonomy, fixtures, and safety design.
2. PWSH1: file classification and basic structural extraction.
3. PWSH2: command normalization and pipeline modeling.
4. PWSH3: host mutation and operational side-effect taxonomy.
5. PWSH4: `.psd1` module manifest extraction.
6. PWSH5: aliases, splatting, and dynamic invocation safety.
7. PWSH6: canonicalization, bounded readback, and dogfooding.

## PWSH6 Acceptance Sketch

PWSH6 should be accepted only if:

- selected PowerShell raw observations create useful canonical nodes and edges;
- raw-only observation kinds are documented rather than treated as unsupported
  noise;
- fixture dogfooding proves extraction, canonicalization, storage-row
  preparation, and bounded summary generation over public-safe fixtures;
- dynamic invocation does not become a false precise command target;
- canonical metadata and summaries do not include raw fixture secrets, source
  snippets, or unbounded path lists;
- no PowerShell runtime dependency, storage schema change, MCP API change, or
  live/private graph refresh lands.

## PWSH5 Acceptance Sketch

PWSH5 should be accepted only if:

- extraction remains static and non-executing;
- built-in aliases and simple local alias definitions are represented
  conservatively;
- literal splat assignments are summarized without storing secret-like values;
- splat call sites can link to same-file literal assignments without evaluating
  them;
- dynamic invocation records distinguish static-looking and dynamic targets
  without executing or resolving either;
- comments, block comments, here-strings, assignments, and hashtable entries do
  not create obvious command or side-effect false positives;
- no storage schema, canonicalization, MCP, or readback changes land.

## PWSH4 Acceptance Sketch

PWSH4 should be accepted only if:

- extraction remains static and non-executing;
- common literal `.psd1` fields are represented as raw observations;
- module dependencies, file references, and export lists are modeled without
  filesystem or module resolution;
- `PrivateData.PSData` is parsed only for safe literal values;
- unsupported expressions become bounded unknown manifest-field observations;
- secret-like manifest values are redacted and raw fixture secrets are absent
  from serialized observations;
- no storage schema, canonicalization, MCP, or readback changes land.

## PWSH3 Acceptance Sketch

PWSH3 should be accepted only if:

- extraction remains static and non-executing;
- side-effect observations are emitted only for recognized static command and
  environment-reference shapes;
- `powershell.host_mutation` records are emitted for mutating operations, while
  read-only file, environment, registry, and network observations are not
  mislabeled as host mutations;
- package-manager, process, service, scheduled-task, security-policy, remoting,
  and credential-handling examples are classified conservatively;
- dynamic commands remain bounded dynamic or unknown observations;
- secret-like values are redacted;
- comments and strings do not create side-effect observations.

## PWSH2 Acceptance Sketch

PWSH2 should be accepted only if:

- extraction remains static and non-executing;
- command observations are emitted only for recognized static cmdlets and
  tested alias expansions;
- external command observations remain static evidence and never execute tools;
- command arguments, switch arguments, splats, and pipelines are bounded and
  line-oriented;
- secret-like argument values are redacted;
- dynamic commands remain bounded dynamic or unknown observations;
- host-mutation and operational side-effect classification remains deferred to
  PWSH3.

## PWSH1 Acceptance Sketch

PWSH1 should be accepted only if:

- extraction remains static and non-executing;
- no PowerShell runtime dependency is required;
- `.ps1`, `.psm1`, and `.psd1` classification is tested;
- fixture-based tests cover files, functions, params, imports, and dot-source
  observations;
- private or secret-like values are redacted;
- dynamic or unsupported constructs produce bounded unknowns instead of false
  precise facts;
- no storage schema changes or canonicalization changes land unless explicitly
  scoped for a later phase.

## Known Gaps

- The current extractor uses a conservative stdlib-only scanner. Future
  candidates may include a dedicated PowerShell parser or tree-sitter grammar
  if a later phase needs deeper language coverage.
- Alias coverage should start with a small static table and expand only when
  tests prove value.
- Full PowerShell control flow, object pipeline semantics, type resolution,
  module resolution, and execution policy semantics are out of scope for the
  first implementation.
- POSIX shell extraction should reuse lessons from this work later, but PWSH0
  does not add POSIX shell behavior.
