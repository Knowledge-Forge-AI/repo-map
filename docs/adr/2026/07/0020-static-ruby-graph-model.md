# ADR 0020: Static Ruby Graph Model

## Status

Accepted

## Date

2026-07-01

## Context

RepoMap already extracts several local source, configuration, document, and
artifact families. Python, Nix, Markdown, structured configuration, XML, HTML,
CSS, feeds, archives, documents, and YAML have established the current pattern:
local bytes become raw observations, evidence, canonical nodes, and canonical
edges without guessing runtime behavior.

Ruby is the next useful language-family target because many important project
files are Ruby code or Ruby DSLs:

- ordinary Ruby source files;
- tests using Minitest;
- `Vagrantfile`;
- Sinatra applications;
- Hanami applications, configuration, routes, and actions;
- Rake tasks;
- Gemfiles; and
- gemspecs.

Ruby is executable and highly dynamic. The useful graph facts live in syntax
and static DSL cues, but discovering them must not run Ruby, load gems, boot
applications, invoke Bundler, start Vagrant, execute tests, or evaluate
framework DSLs.

RUBY0 defines the static graph model before implementation. It extends the
existing source-language graph identity approach from ADR 0001, ADR 0002, and
ADR 0003 while keeping ecosystem-specific Ruby frameworks as profile hints
until generic Ruby facts prove insufficient.

## Decision

RepoMap will model Ruby as static local source analysis.

The future Ruby pipeline is:

```text
local Ruby file
-> safe static parse or lexical scan
-> raw Ruby observations
-> canonicalize observations
-> load through existing storage path
-> expose through existing readback and future read-only MCP
```

Ruby extraction is source analysis, not Ruby execution. RUBY1 must not run
Ruby, invoke Bundler, load gems, boot applications, run tests, evaluate DSL
blocks, execute Vagrantfiles, start virtual machines, contact providers, fetch
references, install dependencies, or run shell commands.

RUBY0 accepts generic Ruby graph identity for files, modules, classes, methods,
singleton methods, constants, tests, routes, and conservative references. It
defers framework-specific canonical namespaces such as `minitest.*`,
`vagrant.*`, `sinatra.*`, and `hanami.*`.

## Scope

In scope:

- static Ruby graph model design;
- supported file and profile policy for RUBY1;
- safe parser or scanner policy;
- raw Ruby observation vocabulary;
- canonical Ruby namespace policy;
- canonical edge policy using existing edge kinds only;
- conservative reference detection;
- generic Ruby structure extraction;
- static Minitest, Vagrantfile, Sinatra, Hanami, Rake, Gemfile, and gemspec
  profile hints;
- dynamic Ruby policy;
- redaction policy; and
- fixture and test requirements for RUBY1.

Out of scope:

- implementing Ruby parsing;
- adding discovery routing;
- adding canonicalization code;
- adding fixtures or tests;
- adding MCP tools;
- adding storage migrations;
- changing existing Python, Nix, shell, Markdown, configuration, DOCS, YAML, or
  public readback behavior; and
- Phase F migration.

## Product Posture

Ruby graphing must remain static, local, deterministic, and non-executing.

Requirements:

- local files only;
- no Ruby execution;
- no Bundler execution;
- no `bundle exec`;
- no gem loading;
- no application boot;
- no Rails, Hanami, Sinatra, Rack, or framework boot;
- no Vagrant execution;
- no VM or provider calls;
- no shell command execution;
- no test execution;
- no network;
- no dependency installation;
- no code generation;
- no evaluation of arbitrary constants or method calls;
- no expansion of metaprogramming; and
- no MCP write, import, run, or source-creation tools.

## Supported Files

Future RUBY1 should route:

- `.rb`
- `.rake`
- `Rakefile`
- `Gemfile`
- `.gemspec`
- `Vagrantfile`

Future discovery may route common Ruby executable scripts with a Ruby shebang
if existing discovery conventions support shebang-based language routing.

Profile hints for RUBY1:

- `generic_ruby`
- `minitest`
- `vagrantfile`
- `sinatra`
- `hanami`
- `rake`
- `gemfile`
- `gemspec`

Profile hints are metadata only. They do not create framework-specific
canonical namespaces and must not trigger execution, application boot, tool
invocation, dependency resolution, or network calls.

## Parser Policy

RUBY1 should prefer a safe stdlib or lightweight parser if one is already
available to the project. If no parser is available, RUBY1 may begin with a
conservative lexical and shallow structural scanner. If adding a Ruby parser
dependency becomes necessary, RUBY1 must justify the dependency and document
the safe parser configuration in its exit audit.

Parser or scanner requirements:

- parse local bytes only;
- do not execute Ruby;
- do not run `ruby -c`;
- do not use Bundler;
- do not load files through `require`;
- do not resolve gems;
- do not evaluate constants;
- do not expand metaprogramming;
- do not execute DSL blocks;
- enforce maximum file bytes;
- enforce maximum nesting depth where practical;
- preserve parse diagnostics; and
- gracefully degrade to lexical observations when syntax is too dynamic.

Syntax that cannot be parsed safely should emit `ruby.parse_error` or a
diagnostic observation and may still allow conservative lexical facts such as
literal `require` statements when those facts are unambiguous.

## Raw Observations

Future Ruby raw observations may include:

- `ruby.file`
- `ruby.module`
- `ruby.class`
- `ruby.method`
- `ruby.singleton_method`
- `ruby.constant`
- `ruby.require`
- `ruby.include`
- `ruby.extend`
- `ruby.call`
- `ruby.block`
- `ruby.dsl`
- `ruby.route`
- `ruby.test_case`
- `ruby.test_method`
- `ruby.gem_dependency`
- `ruby.vagrant_config`
- `ruby.reference`
- `ruby.parse_error`

RUBY1 should keep the implementation small:

- generic structural observations first;
- profile-specific observations only when cheap, static, and deterministic;
- route, framework, and DSL observations raw/evidence-first before new
  canonical namespaces are accepted; and
- dynamic or ambiguous constructs as diagnostics or safe metadata, not guessed
  graph edges.

Suggested safe metadata fields:

- `format`: `ruby`;
- `profile`;
- `parser`;
- `qualified_name`;
- `owner`;
- `method_name`;
- `visibility`;
- `superclass`;
- `constant_name`;
- `require_path`;
- `require_form`;
- `dsl_name`;
- `route_method`;
- `route_pattern`;
- `test_framework`;
- `redacted`;
- `redaction_reason`;
- `dynamic`;
- `dynamic_reason`; and
- `identity_strength`.

## Canonical Namespaces

ADR 0002 already accepts a small Ruby key family:

- `ruby.module:<encoded-qualified-module-name>`
- `ruby.class:<encoded-qualified-class-name>`
- `ruby.method:<encoded-owner-qualified-name>:<encoded-method-name>`

RUBY0 preserves those durable symbol keys and accepts compatible generic Ruby
additions for future RUBY1 if tests prove them useful:

- `ruby.file:<encoded-file-key>`
- `ruby.singleton_method:<encoded-owner-qualified-name>:<encoded-method-name>`
- `ruby.constant:<encoded-owner-qualified-name>:<encoded-constant-name>`
- `ruby.test_case:<encoded-file-key>:<encoded-qualified-name-or-test-pointer>`
- `ruby.test_method:<encoded-test-case-key>:<encoded-method-name-or-test-pointer>`
- `ruby.route:<encoded-file-key>:<encoded-route-pointer>`

`ruby.file:*` represents the Ruby interpretation of a source file. It is useful
when a file contains top-level DSL facts that do not naturally belong to a
module or class. It does not replace `file:*` identity.

`ruby.test_case:*`, `ruby.test_method:*`, and `ruby.route:*` remain generic Ruby
namespaces. They are not Minitest, Sinatra, or Hanami namespaces. Their
metadata may record the profile that made the fact recognizable.

`ruby.gem:<encoded-gem-name>` is deferred unless RUBY1 determines that Ruby gem
dependencies need first-class Ruby package nodes. Until then, literal gem names
should be metadata or conservative external placeholders.

Framework-specific namespaces are deferred:

- `minitest.*`
- `vagrant.*`
- `sinatra.*`
- `hanami.*`
- `rake.*`
- `gemfile.*`
- `gemspec.*`

Canonical keys must not include:

- method bodies;
- string literal secret values;
- runtime-evaluated values;
- current time;
- absolute machine paths;
- parser object IDs;
- extractor versions;
- line numbers;
- model-generated labels; or
- values produced by executing Ruby.

Ruby's source-level `::` separator is conceptually part of a qualified name and
must be percent-encoded inside key segments according to ADR 0002.

If duplicate definitions, reopenings, or monkey patches make a global Ruby
symbol key ambiguous, RUBY1 should preserve evidence and conflict metadata
rather than changing key grammar or appending line numbers to identity.

## Edge Vocabulary

RUBY0 adds no edge kind.

Use existing edge kinds:

- `defines`
- `references`

Do not overload Python-specific `imports` for Ruby `require` unless a later ADR
explicitly broadens that relationship for source-language imports. Ruby
`require`, `require_relative`, and `load` should use `references` in RUBY1.

Expected canonical edges:

- `file:* --defines--> ruby.file:*`
- `ruby.file:* --defines--> ruby.module:*`
- `ruby.file:* --defines--> ruby.class:*`
- `ruby.module:* --defines--> ruby.method:*`
- `ruby.class:* --defines--> ruby.method:*`
- `ruby.module:* --defines--> ruby.singleton_method:*`
- `ruby.class:* --defines--> ruby.singleton_method:*`
- `ruby.module:* --defines--> ruby.constant:*`
- `ruby.class:* --defines--> ruby.constant:*`
- `ruby.file:* --defines--> ruby.test_case:*`
- `ruby.test_case:* --defines--> ruby.test_method:*`
- `ruby.file:* --defines--> ruby.route:*`
- `ruby.file|ruby.module|ruby.class|ruby.method|ruby.route --references--> file:* | external.url:* | external:* | unknown:* | dynamic:*`

If implementation proves that `ruby.file:*` is unnecessary for simple files,
RUBY1 may emit direct `file:* --defines--> ruby.module:*` and
`file:* --defines--> ruby.class:*` edges while documenting that choice.

Markdown `links_to` remains Markdown-specific. Ruby syntactic links use
`references`.

## Reference Model

RUBY1 should emit references only for conservative syntactic references.

Candidate references:

- `require "x"`;
- `require_relative "x"`;
- `load "x"`;
- Gemfile `gem "name"`;
- gemspec dependencies;
- Rake task file references where static;
- Vagrant box, provider, network, and synced-folder references where static;
- Sinatra template or static path references where literal;
- Hanami app, action, view, provider, or route references where literal;
- test helper requires;
- fixture paths; and
- URLs in string literals only when associated with obvious configuration calls
  or known reference fields.

Target policy:

- `require_relative` -> repo-local `file:*` when resolvable conservatively;
- relative local paths -> `file:*` when inside the repository root;
- repo-escaping paths -> `unknown:file:repo-escaping-ruby-reference`;
- absolute paths -> `external:file:absolute-ruby-reference`;
- gem names -> `external:ruby-gem:<gem-name>` or raw metadata unless a later
  package target vocabulary is accepted;
- URLs -> `external.url:*`;
- dynamic or interpolated strings -> `dynamic:*` or raw-only diagnostics; and
- constants or method calls whose target cannot be statically resolved -> raw
  metadata or `unknown:*`.

References are never loaded, followed, fetched, installed, or executed.

## Generic Ruby Extraction

RUBY1 should detect these facts statically and conservatively:

- module declarations;
- class declarations;
- literal superclass names;
- instance method definitions;
- singleton or class method definitions;
- constant assignments;
- `require`;
- `require_relative`;
- `load`;
- `include`;
- `extend`;
- top-level obvious DSL calls; and
- basic block structure sufficient to attach observations to a containing
  file, module, class, or method when deterministic.

RUBY1 must not attempt:

- full type inference;
- runtime constant resolution;
- method dispatch resolution;
- metaprogramming expansion;
- DSL execution;
- monkey-patch semantics;
- Rails autoloading; or
- Bundler resolution.

## Minitest Profile

Minitest profile detection should recognize:

- `require "minitest/autorun"`;
- classes inheriting from `Minitest::Test`;
- obvious `describe` and `it` style blocks;
- methods named `test_*`;
- common assertions such as `assert`, `refute`, and `assert_equal` as metadata;
  and
- test helper references.

Future RUBY1 or RUBY2 behavior may emit:

- `ruby.test_case` for classes inheriting from `Minitest::Test` or obvious spec
  blocks; and
- `ruby.test_method` for `test_*` methods and obvious literal `it` blocks.

Minitest extraction must not run tests, load fixtures, connect to databases,
start services, or contact the network.

## Vagrantfile Profile

Vagrantfiles are executable Ruby DSLs. RUBY1 must treat them as static DSL text
only.

Vagrantfile profile detection should recognize:

- file name `Vagrantfile`;
- `Vagrant.configure`;
- `config.vm.box`;
- `config.vm.provider`;
- `config.vm.network`;
- `config.vm.synced_folder`;
- `config.vm.provision`;
- provider names as metadata or conservative references;
- box names as external artifact or package references when safe; and
- synced-folder local paths as file references when conservative.

RUBY1 must never:

- run `vagrant`;
- evaluate the Vagrantfile;
- start VMs;
- contact providers;
- execute provisioners; or
- run shell commands from provisioners.

Provisioner command bodies should be redacted and treated as DSL metadata or
dynamic diagnostics unless a later ADR accepts a specific non-executing command
model for Ruby DSL configuration.

## Sinatra Profile

Sinatra profile detection should recognize:

- `require "sinatra"`;
- `require "sinatra/base"`;
- classes inheriting from `Sinatra::Base`;
- route DSL calls:
  - `get`
  - `post`
  - `put`
  - `patch`
  - `delete`
  - `options`
  - `head`
- `set`, `configure`, `before`, `after`, and `helpers` as metadata; and
- template calls such as `erb`, `haml`, and `slim` as static references only
  when literal.

Future behavior may emit `ruby.route` observations for literal route patterns.
Route method and route path are metadata and may participate in a deterministic
route pointer when static.

Sinatra extraction must not evaluate route blocks, boot Rack or Sinatra, infer
dynamic routes from variables or interpolation, connect to services, or render
templates.

## Hanami Profile

Hanami profile detection should recognize, conservatively:

- `Hanami::App`;
- Hanami action classes;
- `config/routes.rb`;
- app, slice, provider, settings, and routes configuration files;
- route-like DSL calls where literal; and
- action, view, provider, or local file references when static.

Hanami extraction must not boot Hanami, load the app environment, run
dry-system containers, resolve providers dynamically, evaluate routes, connect
to databases, or contact services.

## Rake, Gemfile, And Gemspec Profiles

Rake profile detection should recognize:

- `Rakefile`;
- `.rake` files;
- literal `task` calls;
- literal `namespace` blocks; and
- `desc` metadata.

Rake tasks must not be executed.

Gemfile profile detection should recognize literal:

- `source`;
- `gem`;
- `group`;
- `platforms`; and
- `ruby`.

Gemfile extraction must not run Bundler, resolve dependency versions, install
gems, or fetch gem metadata.

Gemspec profile detection should recognize literal metadata and dependency
declarations where static. Gemspec extraction must not build gems, evaluate
computed metadata, or load files to resolve values.

## Dynamic Ruby Policy

Ruby dynamic constructs are evidence and diagnostics, not instructions to
execute code.

If an expression is dynamic:

- record a diagnostic or safe metadata;
- do not fabricate a precise edge;
- use `dynamic:*` only when a canonical placeholder is useful;
- preserve evidence location when available; and
- do not execute Ruby to resolve it.

Examples of dynamic constructs:

- string interpolation;
- computed constants;
- `send`;
- `define_method`;
- `class_eval`;
- `instance_eval`;
- `eval`;
- `method_missing`;
- runtime conditionals;
- environment-variable-driven configuration; and
- loops building routes, tasks, providers, or test cases.

Environment variable references such as `ENV["NAME"]` may be metadata or
references to `env:NAME` only if the existing target vocabulary supports that
use in context. RUBY1 must never read the current process environment. Secret
prone environment variable names trigger redaction.

## Redaction

Ruby files and DSLs may contain secrets in literals, environment variable names,
configuration calls, framework settings, provisioners, and dependency
credentials.

RUBY1 should reuse ADR 0010 and YAML secret markers:

- `token`
- `secret`
- `password`
- `passwd`
- `api_key`
- `apikey`
- `credential`
- `private_key`
- `access_key`
- `refresh_token`
- `bearer`
- `auth`
- `client_secret`
- `secret_key`
- `access_token`
- `id_token`
- `session`
- `cookie`
- `connection_string`
- `jdbc_url`
- `datasource_password`

Ruby and framework markers:

- `rack_secret`
- `session_secret`
- `sinatra_secret`
- `hanami_secret`
- `vagrant_cloud_token`
- `vagrant_token`
- `gem_credentials`
- `rubygems_api_key`

Requirements:

- secret literal values must not appear in canonical keys;
- secret literal values must not appear in raw observation metadata;
- secret literal values must not appear in canonical node metadata;
- secret literal values must not appear in edge metadata;
- secret literal values must not appear in golden fixtures;
- secret literal values must not appear in CLI readback or explain output.

Redacted observations may preserve safe metadata:

- literal type;
- `redacted=true`;
- redaction reason;
- key, call, or argument name;
- profile; and
- structural pointer.

## Fixtures For RUBY1

RUBY1 should add fixtures under:

```text
src/test/fixtures/discovery/ruby_basic/
src/test/fixtures/canonicalization/ruby_basic/
```

Fixture files should include:

- `lib/example.rb`
- `lib/example/service.rb`
- `test/example_test.rb`
- `test/test_helper.rb`
- `app.rb` or `sinatra_app.rb`
- `Vagrantfile`
- `Rakefile`
- `Gemfile`
- `example.gemspec`
- optional Hanami-like files:
  - `config/routes.rb`
  - `app/actions/home/index.rb`
  - `config/app.rb`
- redaction fixture with fake secrets; and
- dynamic fixture with `define_method`, interpolation, `send`, and similar
  dynamic constructs.

Fixtures must use fake values only. They must not include real tokens, private
endpoints, internal service names, or secret literals.

## Required RUBY1 Tests

RUBY1 should add tests for:

- generic Ruby file extraction;
- module, class, method, singleton method, and constant detection;
- superclass metadata;
- `require`, `require_relative`, and `load` reference extraction;
- `include` and `extend` metadata;
- Gemfile gem dependency extraction;
- gemspec dependency extraction;
- Rake task detection;
- Minitest test case and test method detection;
- Vagrantfile static configuration detection without execution;
- Sinatra route detection without app boot;
- Hanami profile, route, and action detection without app boot;
- dynamic construct diagnostics;
- redaction;
- no Ruby execution;
- no Bundler execution;
- no Vagrant execution;
- no test execution;
- storage load and readback;
- explaining one Ruby reference edge; and
- proving secret values are absent from readback and explain output.

## Rejected Alternatives

### Execute Ruby To Discover Structure

Rejected. Ruby execution would turn extraction into application behavior and
would load user code, gems, constants, hooks, and side effects.

### Run `ruby -c` In RUBY1

Rejected for RUBY1. Syntax checking still invokes the Ruby toolchain and is not
needed for a first static extractor. A later ADR may revisit local tool
invocation if there is a precise, non-executing need.

### Use Bundler Or Load Gems

Rejected. Dependency resolution and gem loading are runtime behavior and may
execute code or contact external services.

### Run Tests

Rejected. Minitest extraction observes test structure only. It must not execute
test suites, fixtures, setup hooks, or service initialization.

### Boot Sinatra Or Hanami

Rejected. Framework boot executes application initialization and may connect to
databases, services, secret stores, or other runtime dependencies.

### Execute Vagrantfile Or Invoke Vagrant

Rejected. Vagrantfiles are executable Ruby DSLs. RepoMap must not evaluate them,
start VMs, contact providers, or execute provisioners.

### Evaluate DSL Blocks

Rejected. DSL blocks are source text. RUBY1 may observe literal calls inside
them, but it must not execute them or resolve runtime state.

### Resolve Routes, Tasks, Or Providers Dynamically

Rejected. Dynamic route, task, or provider construction should become
diagnostics or dynamic placeholders, not precise graph facts.

### Add Framework-Specific Namespaces In RUBY0

Rejected. Minitest, Vagrantfile, Sinatra, and Hanami start as profiles and
metadata on generic Ruby observations. First-class framework namespaces require
a later ADR and implementation evidence.

### Store Method Bodies Or Secret Literals In Canonical Metadata

Rejected. Method bodies and literal values are evidence at most. Secret values
must be redacted before raw or canonical serialization.

### Use Runtime Values As Canonical Identity

Rejected. Canonical Ruby identity must come from static source facts, not
values produced by evaluating Ruby.

## Proposed Phases

RUBY1:
Generic static Ruby extraction for `.rb`, `.rake`, `Rakefile`, `Gemfile`,
`.gemspec`, `Vagrantfile`, and Ruby shebang scripts when discovery safely
supports them.

RUBY2:
Profile-specific static readback polish for Minitest, Vagrantfile, Hanami, and
Sinatra if RUBY1 facts are useful but too generic.

Future framework ADRs:
Optional first-class framework namespaces only if a profile needs them and the
generic Ruby model proves insufficient.
