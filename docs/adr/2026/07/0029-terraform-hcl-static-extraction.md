# ADR 0029: Terraform HCL Static Extraction

## Status

Accepted

## Date

2026-07-01

## Authoritative References

- ADR 0001: Graph Identity Model
- ADR 0002: Canonical Key Grammar And Relationship Vocabulary
- ADR 0003: Canonicalization Pipeline, Storage Transition, And Replay Strategy
- ADR 0010: Structured Configuration Graph Model
- ADR 0026: Terraform, JSON, And Ecosystem Configuration Graph Model
- `docs/adr/2026/07/0026-terraform-json-ecosystem-config-graph-model.md`
- `docs/status/2026/07/01/00054-tfjson1-terraform-json-ecosystem-config-exit.md`

## Context

ADR 0026 defined RepoMap's Terraform, JSON, and ecosystem configuration graph
model. TFJSON1 implemented the first slice of that model for Terraform JSON
variants, including `.tf.json`, `.tfvars.json`, and `terraform.tfvars.json`,
while keeping Terraform facts raw/profile-first and preserving the generic ADR
0010 `config.document`, `config.path`, and `config.reference` behavior.

The commonly used Terraform configuration format is HCL, not JSON. RepoMap now
needs a separate architecture boundary for safe parsing and extraction of
Terraform HCL files before implementation. That boundary must be narrower than
"understand Terraform": HCL extraction should statically map declared
configuration intent from local files, not run Terraform, compute a plan, infer
cloud resources, or resolve runtime values.

Terraform HCL files may contain sensitive values, provider and backend
topology, private module sources, credentials in URLs, data source lookup
arguments, and expressions whose meaning depends on variables, locals,
provider schemas, module contents, workspaces, and remote state. RepoMap must
preserve local evidence without treating those declarations as runtime truth.

TFHCL0 defines architecture only. It does not implement HCL parsing, add parser
dependencies, add CLI commands, add fixtures or tests, change storage, add MCP
tools, run tools, fetch providers or modules, inspect state, or change public
readback defaults.

## Decision

RepoMap will model Terraform HCL as static local configuration evidence aligned
with ADR 0026 and TFJSON1. Future HCL extraction should feed the same raw
Terraform profile model wherever practical:

```text
local Terraform HCL file
-> safe static parse or conservative parse diagnostic
-> optional generic file/config-compatible evidence
-> Terraform profile raw observations
-> existing canonical graph only where already supported
-> storage through existing raw/canonical pipeline
-> future read-only summary/readback
```

Terraform HCL extraction is not Terraform execution. Future implementation must
not call Terraform, OpenTofu, Terragrunt, provider CLIs, shell commands, cloud
APIs, provider registries, module registries, remote state backends, data
sources, secret managers, or network URLs. It must not evaluate expressions as
runtime truth, download modules or providers, inspect `.terraform/`, load
provider schemas, infer plan/apply behavior, or expose `.tfvars` values.

The initial TFHCL implementation should remain raw/profile-first. Existing
generic file/config facts remain the stable public graph. Broad Terraform
canonical namespaces are deferred until implementation and readback evidence
justify a separate identity review.

## Scope

In scope:

- Terraform HCL file-family policy;
- parser or scanner strategy requirements;
- static extraction targets for common Terraform blocks;
- raw observation model for Terraform HCL facts;
- relationship to TFJSON1 raw observations;
- future canonical namespace policy;
- reference handling;
- `.tfvars` redaction policy;
- expression classification policy;
- limits and diagnostics;
- future implementation phases; and
- future test requirements.

Out of scope:

- implementing HCL extraction;
- adding parser dependencies without review;
- adding CLI commands;
- adding fixtures or tests;
- adding storage migrations;
- adding MCP tools;
- running Terraform, OpenTofu, Terragrunt, provider CLIs, shell commands, or
  cloud APIs;
- `terraform init`, `terraform validate`, `terraform plan`, or
  `terraform apply`;
- provider download;
- module download;
- remote state access;
- data source lookup;
- expression evaluation as runtime truth;
- provider schema loading;
- secret resolution or decryption;
- public readback default changes; and
- Phase F migration.

## Product Posture

TFHCL0 is not "understand the Terraform plan." TFHCL0 is "statically map
declared Terraform configuration intent from local HCL syntax."

Requirements for future implementation:

- local repository files only;
- deterministic parser or scanner behavior;
- no Terraform, OpenTofu, or Terragrunt execution;
- no Terraform CLI validation, formatting, planning, applying, or console use;
- no provider or module download;
- no `.terraform/` inspection;
- no remote state inspection;
- no data source lookup;
- no provider schema loading;
- no cloud-provider, registry, backend, secret-manager, or shell access;
- no expression evaluation beyond syntactic classification;
- no plan/apply multiplicity inference from `count` or `for_each`;
- no `.tfvars` literal value exposure;
- no broad Terraform canonical namespaces in TFHCL0 or TFHCL1; and
- no MCP import, write, or run tools.

## Supported Future File Families

Future TFHCL phases may support these Terraform HCL file families:

- `.tf`;
- `.tfvars`;
- `terraform.tfvars`; and
- `*.auto.tfvars`.

The following are explicitly deferred unless a later ADR accepts them:

- `.tofu`;
- `.tofuvars`;
- `*.auto.tofuvars`;
- Terragrunt files such as `terragrunt.hcl`;
- arbitrary `.hcl`; and
- Nomad, Consul, Packer, Vault, or other non-Terraform HCL dialects.

This ADR names Terraform HCL only. OpenTofu compatibility may be assessed later
if local syntax compatibility and product naming boundaries are clear.
Terragrunt and other HCL dialects require separate scope because their semantics,
file conventions, includes, dependency behavior, and remote interactions differ.

## Parser Strategy

TFHCL0 defines implementation strategy requirements but does not choose or add
a parser dependency.

Preferred future parser options:

1. Use a safe Python HCL parser if already available or lightweight enough,
   pinned, reviewed, and tested.
2. If no parser is acceptable, implement a conservative shallow scanner for
   Terraform block headers and simple attributes.
3. For TFHCL1, choose the smallest parser/scanner strategy that can reliably
   handle common Terraform blocks without executing expressions.

The parser or scanner must:

- read local bytes only;
- impose file-size limits;
- impose block, attribute, reference, diagnostic, and nesting limits;
- produce diagnostics on malformed or unsupported syntax;
- preserve source spans and line numbers as evidence metadata when available;
- identify block headers and labels deterministically;
- classify expressions instead of evaluating them; and
- keep parser/scanner failures local to the affected file.

The parser or scanner must not:

- call Terraform;
- invoke `terraform fmt` or `terraform validate`;
- load provider schemas;
- resolve module sources;
- evaluate interpolation or functions;
- execute external programs;
- expand variables;
- read environment variables;
- inspect `.terraform/`; or
- perform plan-time interpretation.

Source spans and line numbers are evidence metadata only. They must never be
used as canonical identity.

## Terraform Block Model

Future extraction should statically recognize declared Terraform blocks where
syntax is clear:

- `terraform`;
- `provider`;
- `resource`;
- `data`;
- `module`;
- `variable`;
- `output`;
- `locals`;
- `moved`;
- `import`;
- `check`; and
- `removed`.

For each block, future extraction may capture:

- block type;
- labels;
- safe local name;
- file path;
- source span or line evidence when available;
- simple literal attributes where safe;
- expression or dynamic markers where not safe;
- redaction status;
- block nesting or parent context when relevant; and
- references detected syntactically.

The extractor must not claim that a block will create, update, delete, or read
anything at runtime. Terraform runtime behavior depends on evaluation, provider
plugins, state, module expansion, backend configuration, workspaces, and
provider responses.

## Raw Observation Model

Future HCL extraction should reuse and extend the TFJSON1 Terraform raw model
where possible:

- `terraform.file`;
- `terraform.block`;
- `terraform.provider`;
- `terraform.resource`;
- `terraform.data_source`;
- `terraform.module`;
- `terraform.variable`;
- `terraform.output`;
- `terraform.local`;
- `terraform.backend`;
- `terraform.required_provider`;
- `terraform.required_version`;
- `terraform.reference`;
- `terraform.moved`;
- `terraform.import`;
- `terraform.check`;
- `terraform.removed`;
- `terraform.parse_error`; and
- `terraform.redaction`.

These observations are raw/profile facts first. They should use standard raw
observation fields such as `kind`, `source_id`, `path`, optional line range,
optional `name`, optional `target`, `confidence`, `extractor`,
`extractor_version`, and `metadata`.

Recommended common metadata:

- `format = "terraform-hcl"` or a bounded format label;
- `profile = "terraform"`;
- `file_family`;
- `block_type`;
- `labels`;
- `source_span` or line metadata when available;
- `expression_kind` where applicable;
- `redacted`;
- `redaction_reason`;
- `dynamic`;
- `not_fetched` for external references; and
- safe parser/scanner diagnostics.

## Relationship To TFJSON1

TFHCL extraction should align with TFJSON1 metadata and observation meanings.

Examples:

- `resource "aws_s3_bucket" "main"` in HCL and the equivalent `.tf.json`
  resource should produce analogous `terraform.resource` metadata for resource
  type and local name.
- HCL `terraform.required_providers` and Terraform JSON required providers
  should produce compatible `terraform.required_provider` metadata when
  practical.
- `.tfvars`, `terraform.tfvars`, `*.auto.tfvars`, `.tfvars.json`, and
  `terraform.tfvars.json` should follow the same strict value-sensitive
  posture.
- Provider, module, resource, data source, variable, output, backend, local,
  and reference observations should use compatible names for shared metadata
  fields when practical.

TFHCL may emit `terraform.block` where HCL has a useful syntactic block concept
that Terraform JSON does not expose in the same shape. TFJSON1 compatibility
does not require pretending HCL and JSON syntax are identical; it requires
shared semantics where the underlying Terraform declaration is analogous.

## Canonical Graph Policy

TFHCL0 does not accept broad Terraform canonical namespaces.

Existing generic file/config facts remain the stable public graph. Terraform
HCL facts should remain raw/profile evidence in TFHCL1 unless an existing
canonical namespace and edge already applies safely.

Possible future canonical namespaces only after implementation evidence:

- `terraform.file`;
- `terraform.provider`;
- `terraform.resource`;
- `terraform.data_source`;
- `terraform.module`;
- `terraform.variable`;
- `terraform.output`; and
- `terraform.backend`.

Potential future identity guidance:

- resource identity should be scoped by repository file or Terraform module
  context plus resource type and local name, not by provider runtime ID;
- data source identity should be scoped by local declaration context, not query
  results;
- module identity should use local block identity and source summary, not
  fetched module content;
- variable and output identity should use declared names scoped to a file or
  module context;
- backend identity should use backend type and config file context, not remote
  state contents; and
- canonical keys must never include secret values, tfvars values, runtime state
  values, line numbers, provider IDs, absolute machine paths, current time, or
  fetched data.

A later TFHCL3 or TFCANON0 phase may review canonical Terraform identity after
TFHCL1 and TFHCL2 provide raw evidence and readback experience.

## Edge Vocabulary

TFHCL0 adds no new edge kinds.

Future extraction should use existing edge kinds where canonicalization already
supports them:

- `defines`; and
- `references`.

If Terraform relationships later require richer vocabulary, that change
requires a separate ADR or explicit implementation review. TFHCL1 should not
invent canonical edge kinds for Terraform-specific relationships.

## Reference Policy

Future HCL extraction may record references without fetching:

- provider source names;
- provider version constraints;
- backend type;
- module source strings as redacted or summarized metadata;
- local file references where obvious and repo-contained;
- variable references when statically visible;
- resource and data references when statically visible;
- provider alias references when static and safe;
- `depends_on` entries when static and safe; and
- required Terraform version constraints.

Never fetch:

- registry modules;
- Git modules;
- providers;
- backend state;
- HTTP data sources;
- cloud APIs;
- secrets managers; or
- remote files.

Target policy:

- local file references may become file references only when they normalize
  inside the repository root;
- repo-escaping paths become unknown or external placeholders with safe
  diagnostics;
- provider and module sources remain raw metadata or external references unless
  a later package/module namespace is accepted;
- remote source URLs may become safe summaries with `not_fetched = true`;
- credentialed URLs are redacted; and
- expression-bearing references become dynamic markers or raw-only
  diagnostics.

## Module Source Handling

Module sources can contain local paths, registry addresses, Git URLs, SSH URLs,
private repository names, credentials, or internal topology.

Policy:

- local module paths may be recorded as file references only if repo-contained;
- registry, Git, HTTP, HTTPS, and SSH sources are references only;
- all remote module sources must be marked `not_fetched = true`;
- credentialed sources are redacted;
- source strings should be summarized or hashed when useful; and
- module source strings must not become canonical identity in TFHCL1.

The extractor must not download modules, inspect module content, follow Git
URLs, read registry metadata, or infer child module declarations.

## Backend Handling

Terraform backend configuration can expose sensitive infrastructure topology.

Policy:

- record backend type when statically visible;
- record safe key names and presence;
- record redacted value type/shape when useful;
- redact secret-like values;
- never contact the backend;
- never inspect state;
- never use backend address as identity; and
- never treat backend configuration as proof of current state location.

Backends such as S3, GCS, Azure, Terraform Cloud, HTTP, Consul, Kubernetes,
local, and remote should be treated as declared configuration only. Provider or
backend-specific behavior belongs in later phases only if explicitly accepted.

## Required Providers

Future extraction may record:

- provider local name;
- provider source summary;
- version constraint;
- configuration alias if safe;
- `required_version` constraints; and
- safe reference metadata for provider declarations.

It must not:

- query provider registries;
- download providers;
- validate provider versions;
- load provider schemas;
- infer provider resource schema; or
- resolve provider aliases dynamically.

## Variables And Outputs

For `.tf` variable blocks, future extraction may record:

- variable name;
- type expression summary if safe;
- default presence;
- default value type/shape/hash only if later implementation accepts hashes;
- `sensitive` flag when statically visible;
- description presence, length, and hash;
- validation block presence; and
- redaction status.

For `.tfvars`, `terraform.tfvars`, and `*.auto.tfvars`:

- treat all values as sensitive by default;
- record variable names;
- record value type and shape only;
- optionally hash values only if a later implementation explicitly accepts
  non-reversible hashes;
- never expose literal values in raw observations, canonical metadata, edge
  metadata, readback, explain output, fixtures, diagnostics, or status docs.

For output blocks, future extraction may record:

- output name;
- `sensitive` flag when statically visible;
- description presence, length, and hash;
- value expression classification;
- redaction status; and
- safe reference summaries only when syntactically clear.

Output value expression contents should be redacted by default. Terraform
outputs often expose secrets or infrastructure topology even when not marked
`sensitive`.

## Locals

Future extraction may record local names in `locals` blocks as
`terraform.local` raw observations.

Policy:

- record local names;
- treat values as expressions;
- classify value expression kind;
- redact secret-like local names or values;
- never evaluate locals;
- never propagate local values into other observations; and
- never treat locals as proof of runtime values.

## Resource And Data Source Handling

For resources, future extraction may record:

- resource type;
- resource local name;
- provider prefix when obvious from resource type;
- `count` presence, not evaluated value;
- `for_each` presence, not evaluated value;
- `depends_on` references when static and safe;
- `lifecycle` block presence;
- provider alias reference if static and safe;
- connection/provisioner presence as safety metadata; and
- redaction status for secret-like attributes.

For data sources, future extraction may record:

- data source type;
- local name;
- provider prefix when obvious;
- query-like attribute names and value shapes only when safe;
- reference summaries; and
- redaction status.

The extractor must not perform data source lookup, call provider APIs, resolve
remote objects, or treat query-like declarations as facts about actual cloud or
service state.

## Moved, Import, Removed, And Check Blocks

Future extraction may record presence and safe identifiers for:

- moved block `from` and `to` summaries;
- import block target summary;
- import ID type/shape/hash or redacted summary;
- removed block target summary;
- check block name; and
- assertion count.

It must not evaluate conditions, import IDs, assertions, or runtime outcomes.
Import IDs are sensitive by default because they may contain account IDs,
resource identifiers, private topology, or secrets.

## Expression Policy

Terraform expressions are not runtime truth.

Future extraction may classify expression values as:

- literal string, number, bool, or null when safe;
- collection shape;
- traversal/reference expression;
- template or interpolation expression;
- function call;
- conditional expression;
- dynamic block;
- unknown expression; or
- redacted expression.

Do not:

- evaluate functions;
- interpolate strings;
- resolve variables;
- resolve locals;
- resolve provider attributes;
- resolve module outputs;
- interpret `count` or `for_each` as runtime multiplicity;
- evaluate conditions;
- read environment variables; or
- claim planned resources.

Expression summaries must be bounded and redaction-aware. Secret-like values,
credentialed URLs, private keys, tokens, and tfvars values must not be exposed.

## Redaction

Future TFHCL extraction must apply strict Terraform redaction. Redact or avoid
literal values for names, keys, attributes, labels, and paths containing:

- `password`;
- `passwd`;
- `secret`;
- `token`;
- `key`;
- `private_key`;
- `access_key`;
- `secret_key`;
- `client_secret`;
- `credential`;
- `connection_string`;
- `auth`;
- `bearer`;
- `session`;
- `cookie`;
- `kubeconfig`;
- `certificate`;
- `cert`;
- `tls`;
- `ssh`;
- `datasource`;
- `jdbc`;
- `database_url`; and
- `url` when the value appears credentialed.

Redaction requirements:

- no secret values in raw observations;
- no secret values in canonical metadata;
- no secret values in edge metadata;
- no secret values in readback or explain output;
- no secret values in diagnostics;
- no secret values in fixtures;
- no secret values in status docs; and
- no tfvars literal values anywhere in committed outputs.

## Limits And Diagnostics

Future TFHCL implementation should impose deterministic limits:

- max file bytes;
- max blocks per file;
- max attributes per block;
- max references per file;
- max string length in metadata;
- max expression summary length;
- max nesting depth if parser supports it; and
- max diagnostics per file.

Overflow should emit safe diagnostics such as `terraform.parse_error` or a
bounded diagnostic subtype. Diagnostics must not include raw secret values,
tfvars literal values, credentialed URLs, private keys, full expressions,
unbounded source contents, or fetched data.

Malformed HCL should not abort repository discovery. It should produce safe
file-scoped diagnostics and allow unrelated files to continue through the
pipeline.

## Future TFHCL1 Test Requirements

TFHCL1 must include tests for:

- `.tf` file detection;
- `.tfvars`, `terraform.tfvars`, and `*.auto.tfvars` detection;
- provider block extraction;
- `required_providers` extraction;
- `required_version` extraction;
- backend block extraction;
- resource block extraction;
- data source block extraction;
- module block extraction;
- variable block extraction;
- output block extraction;
- locals extraction;
- moved, import, check, and removed block detection if implemented;
- simple attribute metadata;
- dynamic expression classification;
- `depends_on` reference extraction;
- module source reference extraction;
- provider source and version reference extraction;
- local path reference handling;
- remote module source marked `not_fetched = true`;
- credentialed source redaction;
- `.tfvars` strict redaction;
- secret-like key redaction;
- malformed HCL diagnostics;
- parser limits;
- generic file/config layering where applicable;
- no Terraform, OpenTofu, or Terragrunt execution;
- no provider or module downloads;
- no `.terraform/` inspection;
- no state or backend access;
- no cloud or provider API calls; and
- no canonical Terraform namespaces unless explicitly accepted.

## Rejected Alternatives

Rejected:

- running Terraform to parse or validate;
- shelling out to `terraform console`;
- using provider schemas;
- running `terraform init`;
- downloading modules or providers;
- evaluating expressions;
- building a plan graph;
- treating resource `count` or `for_each` as actual multiplicity;
- using remote state;
- inspecting `.terraform/`;
- storing tfvars literal values;
- adding broad Terraform canonical namespaces in this ADR;
- mixing Terragrunt into TFHCL1;
- mixing OpenTofu into TFHCL1 without a compatibility decision; and
- mixing Nomad, Packer, Consul, Vault, or arbitrary HCL dialects into this
  phase.

## Proposed Phases

- TFHCL1: static Terraform HCL implementation for `.tf`, `.tfvars`,
  `terraform.tfvars`, and `*.auto.tfvars`.
- TFHCL2: Terraform HCL readback summary polish.
- TFCANON0: optional Terraform canonical identity ADR after raw/readback
  evidence.
- TOFU0: OpenTofu extension ADR only if needed.
- TERRAGRUNT0: Terragrunt ADR only if needed.

## Acceptance

TFHCL0 is accepted only if it is architecture-only, static-only,
non-executing, no-fetch, redaction-aware, raw/profile-first, aligned with
TFJSON1, and clearly separates:

- Terraform HCL config extraction;
- Terraform JSON extraction;
- OpenTofu and Terragrunt future work;
- provider/API acquisition; and
- runtime plan/apply behavior.

## Consequences

TFHCL0 gives TFHCL1 a narrow implementation target: parse or scan local
Terraform HCL syntax, emit safe Terraform raw/profile observations, align
metadata with TFJSON1, preserve strict `.tfvars` redaction, and avoid runtime
interpretation. It also prevents HCL support from accidentally becoming a
Terraform client, plan engine, cloud inventory tool, Terragrunt parser, or
provider/API acquisition feature.

Source-code tests are intentionally not required for TFHCL0 because the phase
changes only architecture documentation.
