# ADR 0030: Python Ecosystem And Web Framework Graph Model

## Status

Accepted

## Date

2026-07-01

## Authoritative References

- ADR 0001: Graph Identity Model
- ADR 0002: Canonical Key Grammar And Relationship Vocabulary
- ADR 0003: Canonicalization Pipeline, Storage Transition, And Replay Strategy
- ADR 0010: Structured Configuration Graph Model
- ADR 0021: Static JavaScript Graph Model
- ADR 0027: JS/TS Framework Source Extraction
- ADR 0028: OpenAPI And Swagger Graph Model
- ADR 0029: Terraform HCL Static Extraction
- `docs/adr/2026/06/0010-structured-configuration-graph-model.md`
- `docs/adr/2026/07/0021-static-javascript-graph-model.md`
- `docs/adr/2026/07/0027-js-ts-framework-source-extraction.md`
- `docs/adr/2026/07/0028-openapi-swagger-graph-model.md`
- `docs/status/2026/07/01/00056-js6-framework-readback-polish-exit.md`
- `docs/status/2026/07/01/00058-openapi2-readback-polish-exit.md`
- `docs/status/2026/07/01/00060-tfhcl2-terraform-readback-polish-exit.md`

## Context

RepoMap already extracts basic static Python source facts, structured
configuration, static JavaScript and TypeScript framework facts, OpenAPI and
Swagger contract evidence, Terraform JSON, and Terraform HCL. Those slices
establish the current posture: local files are parsed or scanned statically,
raw/profile observations preserve evidence, canonical graph facts are added
only when identity is stable, and readback summaries make stored evidence
inspectable without re-running extraction.

The next Python increment should improve RepoMap's usefulness on itself and on
common Python services. Useful local evidence includes:

- Python package and dependency declarations;
- Python project configuration;
- static unittest and pytest test structure; and
- Flask, FastAPI, and Django route/view/model source facts.

Python ecosystem extraction is especially sensitive because normal Python
tooling often imports modules, executes setup code, evaluates decorators,
inspects environments, starts servers, or reaches package indexes. RepoMap must
not do that. PY0 defines an architecture boundary for static local Python
ecosystem, test, and web-framework extraction before implementation.

PY0 is architecture only. It does not implement extraction changes, add parser
dependencies, add commands, add fixtures or tests, add storage migrations, add
MCP tools, run Python code, import application modules, run tests, install
packages, contact package indexes, fetch OpenAPI documents, or change public
readback defaults.

## Decision

RepoMap will model Python ecosystem, test, and web-framework evidence as
static local source and configuration facts.

Future Python extraction may combine:

- local packaging and configuration files;
- local Python source files parsed with Python AST where practical;
- existing generic Python source observations;
- existing ADR 0010 structured configuration observations; and
- existing OpenAPI contract observations as separate evidence when present.

The future Python pipeline is:

```text
local Python package/config/test/source file
-> safe static parse, AST inspection, or conservative diagnostic
-> generic config/file/Python observations where already accepted
-> optional Python ecosystem/test/framework raw observations
-> existing canonical Python facts where already accepted
-> storage through existing raw/canonical pipeline
-> future read-only summary/readback
```

Python extraction is not application execution. Future implementation must not
import modules, execute decorators, run tests, start ASGI or WSGI servers,
install dependencies, inspect virtualenv or site-packages as dependency truth,
contact PyPI or other package indexes, fetch generated OpenAPI docs, call
endpoints, or treat declared routes as runtime truth.

The initial posture remains raw/profile-first. Existing Python canonical
namespaces from ADR 0002 remain available for basic modules, classes,
functions, and methods where current extraction already supports them. PY0
defers broad Python ecosystem, test, and framework canonical namespaces until
implementation and readback evidence justify a separate identity review.

## Scope

In scope:

- Python packaging and configuration extraction architecture;
- `requirements.txt` style dependency declaration model;
- `pyproject.toml` project metadata model;
- static unittest extraction model;
- static pytest extraction model;
- Flask source extraction model;
- FastAPI source extraction model;
- Django source extraction model;
- relationship to existing Python source extraction;
- relationship to ADR 0010 structured configuration extraction;
- relationship to OpenAPI contract extraction;
- relationship to RepoMap dogfooding;
- raw observation names;
- possible future canonical namespace policy;
- reference handling;
- redaction and privacy requirements;
- limits and diagnostics;
- future implementation phases; and
- future test requirements.

Out of scope:

- implementing Python extraction changes;
- adding parser dependencies;
- adding CLI commands;
- adding fixtures or tests;
- adding storage migrations;
- adding MCP tools;
- running Python application code;
- importing project modules;
- running tests;
- running pytest;
- running unittest;
- running Flask, FastAPI, or Django servers;
- calling ASGI or WSGI apps;
- calling HTTP endpoints;
- starting databases;
- reading environment variable values;
- installing packages;
- resolving dependencies online;
- contacting PyPI or package indexes;
- calling OpenAPI endpoints;
- fetching generated OpenAPI docs;
- performing route-contract matching as truth;
- provider/API acquisition;
- public readback default changes; and
- Phase F migration.

## Product Posture

PY0 is not "run the Python app." PY0 is "statically map declared Python
ecosystem, test, and web-framework intent from local files."

Requirements for future implementation:

- local repository files only;
- deterministic parsing and bounded metadata;
- no Python source execution;
- no application module imports;
- no pytest or unittest execution;
- no Flask, FastAPI, or Django startup;
- no ASGI or WSGI calls;
- no HTTP endpoint calls;
- no database startup or inspection;
- no environment variable value reads;
- no dependency installation;
- no package-manager invocation;
- no virtualenv or site-packages inspection as dependency truth;
- no PyPI or package-index access;
- no generated OpenAPI fetching;
- no route-contract truth claims from source decorators or contracts alone;
- no provider/API acquisition; and
- no broad Python framework canonical namespaces without implementation
  evidence.

Python facts should be provenance-preserving, redaction-aware, bounded,
deterministic, and explainable from local files.

## Supported Future File Families

Future Python phases may inspect packaging and configuration files:

- `requirements.txt`;
- `requirements-*.txt`;
- `dev-requirements.txt`;
- `test-requirements.txt`; and
- `pyproject.toml`.

Future phases may inspect Python source and test files:

- `.py`;
- Python package directories with `__init__.py`;
- `test_*.py`;
- `*_test.py`; and
- files under `tests/`.

The following are explicitly deferred unless a later ADR accepts them:

- lockfile deep dependency graphs;
- `setup.cfg`;
- `setup.py`;
- `Pipfile`;
- `poetry.lock`;
- `pdm.lock`;
- `uv.lock`;
- tox or nox execution;
- virtualenv or site-packages inspection;
- generated OpenAPI fetching;
- Celery, RQ, or background-job framework modeling;
- SQLAlchemy or ORM relationship modeling;
- Jupyter notebooks;
- type checker execution; and
- coverage report ingestion.

`setup.py` is deferred because safe metadata extraction is difficult without
execution. A later phase may accept shallow lexical hints, but it must not run
`setup.py`.

## Relationship To Existing Python Source Extraction

RepoMap already has basic static Python source extraction and canonical Python
key guidance in ADR 0002. PY0 does not replace that model.

Future Python ecosystem extraction should reuse existing generic Python facts
where they are stable, such as modules, classes, functions, methods, imports,
and references. New package, test, Flask, FastAPI, and Django facts should
initially be raw/profile observations beside those generic facts.

Existing canonical Python namespaces remain the main public graph where already
implemented:

- `python.module`;
- `python.class`;
- `python.function`; and
- `python.method`.

PY0 does not accept broad canonical namespaces for Python package declarations,
tests, Flask routes, FastAPI routes, Django URL patterns, Django views, Django
models, or framework-specific profile facts.

## Relationship To ADR 0010 Configuration

Python packaging and configuration files should layer on ADR 0010 where the
format is already structured:

- `pyproject.toml` remains a TOML configuration document;
- generic `config.document`, `config.path`, and `config.reference` facts remain
  the base structured configuration model;
- Python-specific observations are profile/raw observations layered beside
  generic config facts;
- TOML parse diagnostics remain generic config diagnostics where applicable;
  and
- Python profile facts must not weaken generic config extraction.

`requirements.txt` files are line-oriented dependency declarations rather than
TOML/JSON/YAML documents. They may emit Python profile observations and
references directly, plus generic file facts where applicable.

## Packaging And Dependency Model

Future extraction should statically parse `requirements.txt` style files and
record safe dependency declaration facts:

- package requirement names;
- version specifiers;
- extras;
- environment markers;
- editable installs as local or external references;
- direct URL requirements as redacted, not-fetched references;
- include directives such as `-r other.txt` when local and repo-contained;
- constraint directives such as `-c constraints.txt` when local and
  repo-contained;
- index URL presence as redacted summaries only;
- hash and pip option presence as bounded metadata; and
- comments ignored or counted only.

Future extraction must never:

- install packages;
- resolve transitive dependencies;
- contact PyPI;
- query package indexes;
- fetch direct URLs;
- execute `setup.py`;
- call pip, poetry, pdm, uv, or pipenv; or
- treat the installed environment as declared dependency truth.

Dependency declaration identity should be scoped to the local file and declared
package or reference text after safe normalization. Direct URLs and credentialed
sources must be references only and must not become canonical identity in PY1.

## pyproject.toml Model

Future extraction should statically parse `pyproject.toml` using the existing
TOML/config path where possible and record Python-specific project metadata:

- `[project]` name and version when safe;
- project dependencies;
- optional dependencies;
- dependency groups where present;
- scripts and entry points as declared metadata only;
- build-system requirements;
- build backend name as a bounded reference;
- tool section presence for pytest, coverage, mypy, ruff, black, isort,
  poetry, pdm, uv, and setuptools;
- package manager hints;
- local path dependencies when repo-contained; and
- direct URL dependencies as redacted, not-fetched references.

Future extraction must never:

- invoke the build backend;
- run package managers;
- build wheels or source distributions;
- import the package;
- resolve dynamic metadata;
- execute tool configuration; or
- install dependencies.

Dynamic project metadata should become diagnostics or bounded "dynamic" markers
rather than fabricated package facts.

## Python Source Parsing Strategy

Future source extraction should use Python AST where practical.

The extractor may:

- parse `.py` files with `ast.parse`;
- inspect imports;
- inspect module, class, function, and method definitions;
- inspect decorators as syntax;
- inspect simple call shapes;
- inspect simple assignments and constants;
- classify unsupported or dynamic constructs conservatively;
- use line numbers and source spans as evidence only; and
- preserve bounded metadata.

The extractor must not:

- import modules;
- execute decorators;
- evaluate Python expressions;
- resolve dynamic imports;
- execute settings;
- execute factories;
- instantiate apps;
- call functions;
- start servers; or
- run tests.

Line numbers and source spans are evidence metadata only. They must never be
used as durable canonical identity.

## unittest Model

Future extraction may statically recognize:

- module-level `unittest` imports;
- classes subclassing `unittest.TestCase` when statically visible;
- methods named `test_*`;
- skipped tests by decorator presence when statically visible;
- common assertion method calls as counts or bounded summaries, including
  `assertEqual`, `assertTrue`, `assertFalse`, `assertIsNone`, `assertIn`,
  `assertRaises`, and similar methods; and
- setup/teardown method names as safe metadata.

Future extraction must not run tests, import test modules, evaluate decorators,
execute setup/teardown, or infer test outcomes.

## pytest Model

Future extraction may statically recognize:

- functions named `test_*`;
- classes named `Test*`;
- methods named `test_*`;
- `@pytest.fixture` decorators;
- `@pytest.mark.*` decorators;
- `@pytest.mark.parametrize` decorators;
- `assert` statements as counts;
- common pytest imports; and
- pytest configuration presence in `pyproject.toml`.

Future extraction must not run pytest, evaluate fixtures, evaluate marks,
resolve parameter values as runtime data, import test modules, or infer test
outcomes.

## Flask Model

Future extraction may statically recognize:

- `Flask(...)` app construction when visible;
- `Blueprint(...)` construction when visible;
- decorators such as `@app.route`, `@blueprint.route`, `@bp.route`,
  `@bp.get`, `@bp.post`, `@bp.put`, `@bp.patch`, and `@bp.delete`;
- `add_url_rule(...)` calls when arguments are simple and static;
- route path literals;
- HTTP method lists when literal;
- handler function names;
- blueprint names when statically visible; and
- dynamic route markers when path or method declarations are not simple.

Future extraction must not import the app, execute app factories, evaluate
configuration, resolve runtime blueprints, run Flask, call endpoints, or claim
a complete runtime route table.

## FastAPI Model

Future extraction may statically recognize:

- `FastAPI(...)` app construction;
- `APIRouter(...)` construction;
- decorators such as `@app.get`, `@app.post`, `@app.put`, `@app.patch`,
  `@app.delete`, `@router.get`, `@router.post`, and similar router methods;
- route path literals;
- HTTP methods implied by decorators;
- response model presence or safe name references;
- tags, status code, summary, and description presence;
- dependency marker presence via `Depends(...)` without evaluating it; and
- router include calls as raw evidence when statically visible.

Future extraction must not import the app, execute dependencies, evaluate
Pydantic models beyond names or safe references, generate or fetch OpenAPI,
run an ASGI server, call endpoints, or claim a complete runtime route table.

## Django Model

Future extraction may statically recognize Django project and app file hints:

- `manage.py`;
- `settings.py`;
- `urls.py`;
- `views.py`;
- `models.py`; and
- `apps.py`.

Future extraction may statically recognize source facts:

- `urlpatterns` assignments when simple/static;
- `path(...)` calls;
- `re_path(...)` calls;
- `include(...)` calls as references, not recursive runtime resolution;
- view function names when statically visible;
- class-based views and `.as_view()` markers;
- model classes subclassing `models.Model` when statically visible;
- Django app config classes when statically visible; and
- settings references as presence and safe key names only.

Future extraction must not set `DJANGO_SETTINGS_MODULE`, import settings, run
migrations, inspect databases, execute URLConfs, start Django, resolve
middleware/apps dynamically, or infer a complete runtime URL table.

## Relationship To OpenAPI

Python web-framework facts and OpenAPI/Swagger documents are separate evidence
sources.

Future linking may compare:

- Flask, FastAPI, and Django static route facts; and
- OpenAPI operation method/path facts.

Any such link must be confidence-labeled, evidence-backed, and explicit that it
is not runtime truth. PY0 does not implement route-contract matching, generated
OpenAPI fetching, or framework-to-contract canonical links.

FastAPI can generate OpenAPI at runtime, but RepoMap must not import a FastAPI
app or fetch `/openapi.json` in PY1 or PY2. Local committed OpenAPI files remain
the source for OpenAPI extraction under ADR 0028.

## Relationship To RepoMap Dogfooding

Future Python phases should include measured RepoMap dogfooding:

- extract RepoMap's own `pyproject.toml` or requirements/config files if
  present;
- extract RepoMap's own unittest or pytest structure where present;
- extract internal CLI, test, and module patterns safely;
- verify storage/load/readback over small reproducible fixtures or snapshots;
  and
- report counts, bounded examples, known gaps, and no secret leakage in a
  future PY3 status audit.

Dogfooding is a verification exercise, not a reason to broaden scope. Future
implementation must not add product features solely to make RepoMap look good,
mutate tracked files through self-analysis, commit large generated reports
unless explicitly scoped, or replace focused assertions with huge artifacts.

## Raw Observation Model

Future Python phases may emit raw/profile observations such as:

- `python.package_file`;
- `python.requirement`;
- `python.dependency_group`;
- `python.pyproject`;
- `python.build_system`;
- `python.entry_point`;
- `python.tool_config`;
- `python.test_file`;
- `python.test_case`;
- `python.test_method`;
- `python.test_function`;
- `python.test_fixture`;
- `python.test_parametrize`;
- `python.test_assertion`;
- `python.unittest_case`;
- `python.pytest_test`;
- `python.pytest_fixture`;
- `python.flask_app`;
- `python.flask_blueprint`;
- `python.flask_route`;
- `python.fastapi_app`;
- `python.fastapi_router`;
- `python.fastapi_route`;
- `python.fastapi_dependency`;
- `python.django_project`;
- `python.django_app`;
- `python.django_urlpattern`;
- `python.django_view`;
- `python.django_model`;
- `python.django_setting_reference`;
- `python.reference`;
- `python.parse_error`; and
- `python.redaction`.

Future implementation should use existing generic Python observations where
they already exist and avoid renaming stable facts unnecessarily. Profile facts
should be added only where they are clean, static, bounded, and tested.

## Canonical Namespace Policy

PY0 is raw/profile-first. It does not accept broad new canonical namespaces for
Python ecosystem or web-framework facts.

Possible future canonical namespaces only after implementation and readback
evidence:

- `python.package`;
- `python.requirement`;
- `python.test_case`;
- `python.test_function`;
- `python.flask_route`;
- `python.fastapi_route`;
- `python.django_urlpattern`; and
- `python.django_view`.

Recommendation: PY1 and PY2 should keep package, test, and framework facts as
raw/profile evidence. PY3 should make that evidence easy to inspect through a
read-only summary. A later PYCANON0 may review canonical identity once there is
enough implementation evidence that keys are stable and useful.

## Edge Vocabulary

PY0 adds no new edge kinds.

Future extraction should use existing edge vocabulary:

- `defines`; and
- `references`.

Examples:

- a packaging/config file defines dependency declarations as raw/profile
  evidence;
- a test file defines test cases, test functions, and fixtures as raw/profile
  evidence;
- Flask, FastAPI, and Django source files define raw route, view, and model
  facts;
- dependencies reference package names or local files;
- route decorators reference handler functions when statically visible;
- Django URL patterns reference views when statically visible; and
- FastAPI routes reference dependencies when statically visible.

If future Python phases need richer relationship vocabulary, that requires a
separate ADR or explicit implementation review.

## Reference Policy

Future Python extraction may record references without fetching:

- package names from requirements and `pyproject.toml`;
- extras and version constraints as bounded metadata;
- local include/constraint files from requirements when repo-contained;
- editable local path dependencies when repo-contained;
- direct URL dependencies as redacted, not-fetched references;
- private or custom indexes as redacted summaries only;
- build backend names;
- local import paths and Python module references where current Python
  extraction supports them;
- Flask, FastAPI, and Django route path literals as local framework evidence;
- Django `include(...)` targets as references only;
- local settings/module string references when safe; and
- OpenAPI contract files only when they are local files already in the repo.

Future extraction must not fetch:

- packages;
- package indexes;
- direct dependency URLs;
- source distributions;
- wheels;
- VCS requirements;
- generated OpenAPI docs;
- HTTP endpoints;
- databases;
- settings modules;
- virtualenv or site-packages contents as dependency truth; or
- remote refs.

Repository-contained local paths may become file references. Repo-escaping
paths must produce safe diagnostics or redacted summaries. Credentialed URLs
must be redacted before observations enter the raw/canonical pipeline.

## Redaction And Privacy

Python projects often contain credentials in dependency URLs, private package
indexes, settings, test fixtures, route examples, and framework configuration.

Future extraction must redact or avoid literal values for:

- dependency URLs with credentials;
- private package indexes;
- tokens in requirement URLs;
- environment variable values;
- settings secrets;
- Django secret-key settings;
- Flask secret-key settings;
- database URLs;
- API keys;
- auth headers;
- cookies;
- credentials;
- `.env`-style values;
- pytest fixture values with secret-like names; and
- Flask, FastAPI, or Django config values with secret-like names.

Redact or avoid literal values for names, keys, attributes, or paths
containing:

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
- `database_url`;
- `django_secret_key`;
- `flask_secret_key`;
- `sqlalchemy_database_uri`; and
- `url` when the value appears credentialed.

Redaction requirements:

- no secret values in raw observations;
- no secret values in canonical keys;
- no secret values in canonical metadata;
- no secret values in edge metadata;
- no secret values in readback;
- no secret values in explain output;
- no secret values in diagnostics; and
- no secret values in fixtures or status docs.

## Limits And Diagnostics

Future implementation should impose deterministic limits:

- max file bytes;
- max dependencies per file;
- max requirements include depth;
- max `pyproject.toml` sections;
- max Python AST nodes;
- max routes per file;
- max tests per file;
- max decorators per function or class;
- max references per file;
- max metadata string length; and
- max diagnostics per file.

Malformed files, unsupported syntax, dynamic constructs, redacted values, and
limit overflows should emit safe diagnostics such as:

- `python.parse_error`;
- `python.redaction`; and
- bounded skip or limit diagnostics.

Diagnostics must not contain source contents, secret values, private URLs,
credentialed URLs, full config values, environment values, dependency payloads,
or unbounded strings.

## Future PY1 Tests

PY1 should cover Python packaging and test profile extraction. Required tests
include:

- `requirements.txt` detection;
- requirements variant detection;
- package name parsing;
- version specifier parsing;
- extras parsing;
- environment marker parsing;
- editable local path requirements;
- direct URL requirements marked `not_fetched = true`;
- credentialed requirement URL redaction;
- local include and constraint file references;
- repo-escaping include and constraint diagnostics;
- index URL redaction;
- `pyproject.toml` project metadata extraction;
- dependencies and optional dependencies;
- dependency groups if implemented;
- build-system extraction;
- script and entry point extraction;
- tool section presence;
- dynamic metadata diagnostics;
- unittest class and method extraction;
- pytest function, class, and method extraction;
- pytest fixture and parametrize extraction;
- assertion counts;
- malformed TOML and Python diagnostics;
- no package installation;
- no PyPI or package-index network calls;
- no test execution;
- no project module imports; and
- no broad canonical namespaces.

## Future PY2 Tests

PY2 should cover Python web-framework static extraction. Required tests include:

- Flask app construction detection;
- Flask blueprint detection;
- Flask route decorator detection;
- Flask `add_url_rule` detection;
- FastAPI app detection;
- FastAPI router detection;
- FastAPI route decorator detection;
- FastAPI dependency marker detection;
- Django project and app hints;
- Django `urlpatterns` extraction;
- Django `path`, `re_path`, and `include` extraction;
- Django view detection;
- Django model class detection;
- route method and path extraction;
- dynamic route diagnostics;
- settings and config secret redaction;
- no imports;
- no server startup;
- no endpoint calls;
- no generated OpenAPI fetching;
- no route-contract matching; and
- no broad canonical namespaces.

## Proposed Phases

- PY1: Python packaging and test profile extraction.
  - `requirements.txt` and variants.
  - `pyproject.toml`.
  - unittest and pytest static tests.
  - RepoMap self-test structure fixture or dogfood check.
- PY2: Python web-framework static extraction.
  - Flask.
  - FastAPI.
  - Django.
  - Route, view, model, dependency, and settings-reference raw evidence.
  - No OpenAPI fetching and no route-contract matching.
- PY3: Python readback summary polish and RepoMap dogfooding.
  - Storage summary for Python ecosystem, test, and framework evidence.
  - Self-repo dogfooding status.
  - Bounded counts and examples.
  - No generated report sprawl.
- PYCANON0: optional Python canonical identity ADR after PY1, PY2, and PY3
  provide enough evidence.

## Rejected Alternatives

### Run pytest Or unittest To Discover Tests

Rejected. Test execution imports project modules, runs arbitrary code, touches
fixtures, may start services, and can mutate local state. RepoMap should map
test structure statically.

### Import Flask, FastAPI, Or Django Apps

Rejected. Imports can execute application code, load settings, connect to
services, register extensions, or evaluate secrets. Framework extraction must
inspect source syntax only.

### Use Django Runtime URL Resolution

Rejected. Runtime URL resolution requires settings and imports. Static
`urlpatterns` evidence should remain raw/profile facts until a later phase
accepts any stronger relationship model.

### Generate Or Fetch FastAPI OpenAPI Documents

Rejected. Runtime OpenAPI generation imports apps and evaluates route metadata.
Local committed OpenAPI files are handled separately by ADR 0028.

### Start ASGI Or WSGI Servers

Rejected. Server startup executes application code and may access databases,
queues, secrets, environment variables, or network services.

### Install Dependencies To Improve Extraction

Rejected. Dependency installation adds network, environment, and supply-chain
risk. RepoMap should operate from local files without package-manager calls.

### Contact PyPI Or Package Indexes

Rejected. Package index lookup is network acquisition, not local static
extraction. Declared dependencies may be recorded as references without
fetching.

### Treat Installed Packages As Declared Dependency Truth

Rejected. Virtualenv and site-packages state may be stale, machine-specific,
or unrelated to the repository. Local declaration files are the evidence source
for dependency facts.

### Treat Route Decorators As Runtime Truth

Rejected. Decorators and URL patterns are source evidence, not proof of the
runtime route table. Factories, imports, conditionals, settings, middleware,
plugins, and deployment configuration can alter runtime behavior.

### Add Broad Python Framework Canonical Namespaces In PY0

Rejected. Python package, test, Flask, FastAPI, and Django identities need
implementation and readback evidence before becoming canonical namespaces.

### Mix Celery, ORM, Jupyter, Or Type-Checker Execution Into PY1/PY2

Rejected. Those areas need separate scope and safety review. PY0 keeps the
initial Python increment focused on package/config, tests, and three common web
frameworks.

## Acceptance

PY0 is accepted only if it is architecture-only, static-only, local-first,
no-execution, no-fetch, redaction-aware, raw/profile-first, and clearly
separates:

- Python packaging and configuration extraction;
- Python test extraction;
- Flask, FastAPI, and Django source extraction;
- OpenAPI contract extraction;
- route-contract comparison;
- RepoMap dogfooding;
- provider/API acquisition; and
- runtime behavior.

## Verification

PY0 verification is docs-only:

- `git diff --check`
- `git diff --cached --check`

Source-code tests are intentionally not run because PY0 only creates an ADR and
does not change executable code, tests, migrations, package metadata, generated
runtime artifacts, or CLI behavior.
