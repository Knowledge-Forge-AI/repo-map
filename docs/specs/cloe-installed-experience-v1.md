# CLOE installed experience and evidence contract v1

Status: accepted design under [ADR 0181](../adr/2026/11/0181-exact-installed-experience-and-evidence.md).
An implementation candidate and scoped diagnostic evidence exist. Corrective
source proof and final review govern publication; exact-source hosted acceptance
remains pending. Phase `REPOMAP-CLOE-INSTALLED-EXPERIENCE1`.
Source parent `5997d06b7bf08b774e479968b518c6d167f556c6`.
Paths are repository-relative. The line facts below describe the source parent
and must be re-read before editing. Corrections below resolve design1 findings B1–B4 and M1–M4;
they are design expectations, not observed installed results. Design2 F1–F9
are disposed below; no new dependency, runner, image or native authority.

## 1. Verified source facts

| Owner | Fact relied on |
|---|---|
| `pyproject.toml` | Distribution `common-lore-index` 0.0.3, `requires-python >=3.12`, license `AGPL-3.0-or-later`. Its only unconditional dependency is `typing-extensions==4.16.0`, with extra `postgres = psycopg[c]==3.3.6`. Scripts: `cloe`, `common-lore-index` and `repomap-kg` → `common_lore_index.entrypoints:{cloe,long,legacy}_main`. Packages: `common_lore_index*` plus `repomap_kg`, `repomap_kg.ops` and `repomap_kg.server`. Package data is `third_party_licenses/*.{json,txt}`. Data files go under `share/common-lore-index/{rdbms,coordinator-rdbms}/…` |
| `tools/test_sandbox/Dockerfile` | Base `python:3.13.12-slim`. `typing-extensions==4.16.0` is installed by `pip install --no-cache-dir` (version-pinned, not hash-pinned). Pinned setuptools 83.0.0, wheel 0.48.0 and packaging 26.3 are present. `psycopg-c` 3.3.6 is built offline and attested to link `libpq.so.5`. PostgreSQL 17 binaries are on `PATH` |
| `runtime/cloe_installed_cutover.int.test.py` | Module fixture `wheels` builds the incumbent (`git archive` of `6d818ad…`) and candidate wheels with `pip wheel --no-index --no-deps --no-build-isolation` (`arch7f_pip`). `interpreter()` uses `venv.EnvBuilder(with_pip=False, system_site_packages=True)`. `install()` runs `pip --python <venv> install --no-index --no-deps`. Children get `extra_env={"PYTHONPATH": "", "PYTHONNOUSERSITE": "1", "PIP_NO_INDEX": "1", …}`. The overlap matrix covers both install orders and removing either owner |
| `tools/runner_coverage_execution.py` | `arch7f_probe` and `arch7f_pip` are in `UNMEASURED_FAMILIES`. In the unmeasured branch, `scrub_coverage_environment` drops `COVERAGE_*` keys and runner bootstrap entries. `extra_env["PYTHONPATH"]` is only filtered and appended, never applied as empty, and the loop skips `PYTHONPATH`. Any other inherited entries therefore survive |
| `runtime/arch7f_release_wheel.int.test.py` | Checks that unconditional Requires-Dist is exactly `typing-extensions==4.16.0` and that the data-share members equal the source catalogs. Its probe puts a `--target` directory on `PYTHONPATH`, so it is not a wheel-only interpreter |
| `common_lore_index/storage/_schema_migrations.py` | `default_rdbms_root()` uses `<package>/../../resources/rdbms` when that directory exists, and otherwise `sysconfig.get_path("data")/share/common-lore-index/rdbms` |
| `common_lore_index/entrypoints.py`, `repomap_kg/server/mcp.py` | `LEGACY_COMMAND_NOTICE` and `LEGACY_MCP_NOTICE` are printed to stderr. Every command delegates to `common_lore_index.cli.main(argv, prog=…)` |
| `common_lore_index/server/mcp.py`, `server/_ops_records.py` | `main()` serves stdio with no arguments. The home comes from `REPOMAP_OPS_CONFIG`, otherwise `load_graph_registry_config_home()`. `tool_definitions()` comes from `server/mcp_schemas.py`, and `MCP_PROTOCOL_VERSION` from `server/_mcp_dispatch` |
| `server/_mcp_navigation.py` | `repomap_navigation_search` requires `graph_id` and `query`. `scope` is `all\|code\|docs`, `limit` is 1–50, and the server field is `"repomap-kg"`. Members resolve through `repomap_node_locations` |
| `common_lore_index/ops/config_migration.py` | `apply_`, `rollback_` and `finalize_cloe_config_migration(home, *, confirmed=False, dry_run=False)` return `cloe-config-migration-result-v1`. Refusals include `repo-map-home-required`, `confirmation-required`, `confirmation-conflict`, `config-entry-unsafe` and `config-home-mixed-format`. `repomap_kg.ops.config_migration` re-exports the identical function objects |
| `runtime/installation_ownership.py` | `inspect_installation_ownership()` returns `single-owner`, `conflicting`, `owner-mismatch` or `unverified`, and reads metadata only |
| `docs/ops/sqlite-local.md` | Argument shapes for `ops config-check`, `graphs [--check-db]`, `sqlite-init`, `refresh-preflight`, `refresh-graph`, `sqlite-backup` and `sqlite-restore`, and `mcp serve --repo-map-home`. Backup output holds exactly `graph.sqlite3` and `manifest.json`. Restore refuses with `sqlite-restore-target-exists`. A PostgreSQL home without the driver fails with `postgresql-driver-unavailable` |
| `repomap_test_support/sqlite_local_guard.py` | A stdlib-only launcher, executed by path, that imports `common_lore_index.cli.main` after installing socket, spawn and psycopg guards. `REPOMAP_TEST_SQLITE_BLOCK_PSYCOPG=1` blocks the driver family |
| `repomap_test_support/sqlite_local_fixtures.py` | Defines `graph_toml`, `multi_graph_toml` and `write_sqlite_home(home, graphs, name=…)` |
| `docs/specs/cloe-first-use-workload-v1.md` §1, §3 | Facts about `ops/first_use_local` (`context-select --pin-publication` and `context-pack` shapes) and `ops/first_use_server` (`temporary_postgres()`, `apply_migrations`, `refresh_graph`). `INNER_REPORT_ROOT` is `/sandbox-report/report`. The repository mount is read-only. Owners include `tools/first_use_workload_bundle.py` (exclusive writer and bounded reader) and the census |

These were **not read** in the design pass, and the implementer must read
them before relying on them: `tools/run_tests.py` argument parsing; the
`timeout` parameter of `launch_observed_process`; the portable-worker launch
owner; the `temporary_postgres` connection surface; the home-selector
resolution behind `CLOE_HOME`; the `context-select`/`context-pack` argument
parser; the `mixed-v1` message-file census rows; and the first-use driver's
bundle-location helper. If one of them contradicts this contract, follow §13.

## 2. Environment classes

| Class | Construction | Must hold |
|---|---|---|
| `pure-local` | `venv.EnvBuilder(with_pip=False, system_site_packages=False, symlinks=True)` under an owned root containing a space. The candidate is installed with `--no-index --no-deps`, then the §5 projection runs | `pyvenv.cfg` has `include-system-site-packages = false`. The distribution set is exactly {`common-lore-index` 0.0.3, `typing-extensions` 4.16.0}. `pip --python <env> check` exits 0. The origin closure of §6 holds |
| `incumbent-local` | Same construction, with the incumbent wheel (`repomap-kg` 0.0.3, built from `6d818ad…`). It is a separate root and never overlaps the candidate | Same, with distribution {`repomap-kg`, `typing-extensions`} |
| `provisioned-server` | `system_site_packages=True`; candidate installed with `--no-deps` | `common_lore_index` and its resources come from the environment. Psycopg 3.3.6 has `pq.__impl__ == "c"` and comes from the SDK system site. Its label always reads `provisioned-server` and never `pure-local` |

The environment of every installed child is built as follows:

1. Call `prepare_child_coverage_environment(os.environ, family="arch7f_probe",
   capability=cap)`, or `"arch7f_pip"` for pip itself.
2. Delete `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`, `PYTHONUSERBASE`,
   `PYTHONEXECUTABLE`, `PYTHONSAFEPATH`, `VIRTUAL_ENV`, every remaining
   `COVERAGE_*` key and every key that `LocalHarness` scrubs (PostgreSQL,
   credential and home selectors).
3. Set `PYTHONNOUSERSITE=1`, `PYTHONDONTWRITEBYTECODE=1`, `PIP_NO_INDEX=1`,
   `PIP_DISABLE_PIP_VERSION_CHECK=1`, `LANG=C.UTF-8`, `HOME=<owned user-home>`
   and `PATH=<env>/bin:/usr/bin:/bin`. Add `/usr/lib/postgresql/17/bin` only
   for `provisioned-server`.
4. Use an owned `unrelated-cwd` outside the checkout as the working directory.

Pass this closed mapping as `env=`, never `extra_env` or `source_root`.
Step 2 is required because of the §1 runner fact. The witness of §6 checks
the result of this construction instead of trusting it.

## 3. Owned source and test layout

New owners target 350 lines and stay at or under 400. They enroll through the
same ownership and quality records that admitted the first-use owners. Ruff,
mypy, length and suppression roots and ceilings do not change.

| Path | Responsibility |
|---|---|
| `src/test/support/python/repomap_test_support/installed_candidate.py` | `candidate_wheel(factory)` and `incumbent_wheel(factory)`: one build per pytest process, memoized under `factory.getbasetemp()` and keyed by input digest. `wheel_inventory(wheel)` and `expected_inventory(root)` (§4) |
| `.../installed_environment.py` | `InstalledEnvironment` (root, class, python, bin, purelib, data), `create_environment(root, cls)`, `install_wheel(env, wheel)`, `child_environment(env, extra)`, `run_installed(env, argv, *, cwd, input_text=None)` and `pip_check(env)` |
| `.../installed_projection.py` | `project_sdk_distribution(name, version, target_purelib) -> ProjectionRecord` and its refusals (§5) |
| `.../installed_origin.py` | `ORIGIN_PROBE`, `observe_origin(env, *, isolated) -> OriginRecord` and `classify(path, env, checkout)` (§6) |
| `.../installed_mcp_session.py` | `McpSession`: bounded stdio JSON-RPC over `popen_observed_process`. `request`, `notify`, `close() -> McpTranscript` (§8.3) |
| `.../installed_experience_fixture.py` | `write_tiny_material(root)`, `tiny_home(home, material, *, config_name)` and the reviewed public message fixture (§7) |
| `.../installed_experience_driver.py` | Ordered step recording, outcome classification, cleanup registry and bundle location. Imports the first-use bundle writer and the location rule rather than copying them |
| `src/test/fixtures/installed_experience/tiny-v1/` | `code/tinypkg/{__init__,ledger}.py`, `docs/guide.md` and `messages/ledger.eml`, about 4 KiB in total, public-safe |
| `tools/installed_experience_recipe.py` | Frozen scenario catalog (§9), expected facts, `recipe_digest()`, and the projection's frozen digests |
| `tools/installed_experience_records.py` | Closed vocabularies and strict codecs for intent, observation, index and verdict (§10) |
| `tools/installed_experience_reconcile.py` | Pure reconciliation and verdict (§10.4) |
| `tools/installed_experience.py` | CLI `plan`, `check` and `show`. Exit 0 accepted; 1 rejected or incomplete; 2 usage or unreadable |
| `src/test/int/python/repomap_kg/runtime/cloe_installed_{environment,local,mcp,migration,server}.int.test.py` | The §9 rows, one bundle per owner |
| `src/test/unit/python/tools/installed_experience_{recipe,records,reconcile,cli}.unit.test.py` | Pure tool coverage (§14) |
| `src/test/unit/python/repomap_kg/runtime/installed_{candidate,environment,projection,origin,mcp_session,driver}.unit.test.py` | Support logic with fakes and temporary trees |
| `docs/ops/cloe-installed-upgrade-compatibility.md` | New section "Installed experience proof" (§12) |
| `tools/ci/cloe-installed-experience1-exit.md` | Exit record |

`runtime/cloe_installed_cutover.int.test.py` changes only so that its
`wheels` fixture calls `incumbent_wheel` and `candidate_wheel`. Every
assertion, the catalog checks, the overlap matrix and both proof prints stay
unchanged. Tools never import `repomap_test_support`. A unit guard asserts
that no `common_lore_index` or `repomap_kg` module imports `installed_*`,
`repomap_test_support` or `tools`.

## 4. Candidate assembly and inventory

`candidate_wheel` copies the exact regular-file package-input census into an owned
source tree, then runs `sys.executable -m pip wheel --no-index --no-deps
--no-build-isolation --wheel-dir <owned> <owned-source>` once per process,
under `arch7f_pip`. It requires exactly one `common_lore_index-0.0.3-*.whl`.
The input digest extends the cutover owner's rule to include NOTICE: the SHA-256 of canonical
`{path: sha256}` over `README.md`, `LICENSE`, `NOTICE`, `pyproject.toml`,
`src/main/python/**` and `src/main/resources/**`, taken from the tracked and
untracked non-ignored census. A digest change discards the memo. The canonical scoped invocation uses jobs=1. Under an existing parallel hosted
invocation the process boundary is explicit: at most one current wheel per
worker, identified by its input digest; this is not a once-per-campaign claim.
Nothing outside the owned build root is touched.

`expected_inventory(checkout)` is derived from the current owners alone:

- every file under `src/main/python/common_lore_index/` except `__pycache__/`
  and `*.pyc`, mapped to `common_lore_index/…`;
- exactly the six `repomap_kg` facade files;
- every `[tool.setuptools.data-files]` glob, parsed with `tomllib` and mapped
  to `common_lore_index-0.0.3.data/data/share/common-lore-index/…`;
- dist-info members `METADATA`, `WHEEL`, `RECORD`, `entry_points.txt`, optional
  `top_level.txt`, and exactly the license members selected by the pinned
  setuptools default patterns from the current root (`LICENSE` and `NOTICE`).
  Inspect the installed pinned builder source before freezing this set; verify
  both root files byte-for-byte in the wheel. Do not infer a packaging defect
  from the first draft's incomplete license whitelist.

The wheel must equal the expected set. `entry_points.txt` must hold exactly
one group, `console_scripts`, with exactly the three `[project.scripts]`
rows. `METADATA` Requires-Dist must equal the release-wheel assertion. Every
`RECORD` row must carry a SHA-256 that matches its member, except `RECORD`
itself. There may be no `.pth` member and nothing from `src/test`, `tools`
or `src/main/resources` outside the data share. A missing source member, missing declared/default-selected license or unexpected
member is a packaging finding. First distinguish a mistaken test expectation
from an actual packaging defect using the pinned builder and source. Never
retune an oracle to unexplained output; a dependency or metadata change needs §13.

## 5. SDK distribution projection

`project_sdk_distribution("typing-extensions", "4.16.0", target)` copies the
SDK's installed pure-Python distribution into a pure environment:

1. **Requirement.** The version and name come from the candidate wheel's
   single unconditional Requires-Dist, parsed from the wheel and not from the
   recipe. Anything other than one exact `==` pin refuses with
   `projection-requirement-unsupported`.
2. **Source.** The source root is `sysconfig.get_path("purelib")` of the
   sandbox interpreter, opened without following symlinks.
   `importlib.metadata.distributions(name=…, path=[purelib])` must yield
   exactly one distribution whose normalized `Name` and `Version` match.
   Otherwise it refuses with `projection-source-missing` or
   `projection-source-ambiguous`.
3. **RECORD.** `RECORD` is read with a 64 KiB bound and parsed as CSV with
   at most 64 rows. Each path must be relative and normalized, with no `..`
   component, and fall within the closed set: `typing_extensions.py`,
   `typing_extensions-4.16.0.dist-info/<file>`,
   `typing_extensions-4.16.0.dist-info/licenses/<file>` and
   `__pycache__/typing_extensions.*.pyc`. Any other path refuses with
   `projection-unknown-entry` or `projection-path-escape`.
4. **Hashes.** Every hashed row is checked with `lstat` (no follow): it must
   be a regular file with one link, owned by root or the current uid, with a
   size equal to the recorded size and a matching SHA-256. Otherwise it
   refuses with `projection-entry-unsafe` or `projection-hash-mismatch`. Only
   `RECORD` and `__pycache__` rows may lack a hash. Bytecode is never copied.
5. **Licence.** Each `License-File` named in `METADATA` must be a hashed
   member. Otherwise it refuses with `projection-license-missing`.
6. **Drift.** The SHA-256 values of `typing_extensions.py` and `RECORD` must
   equal the recipe constants `TE_MODULE_SHA256` and `TE_RECORD_SHA256`.
   Otherwise it refuses with `projection-drift`. The implementer captures
   these once, in a scoped sandbox run, and commits them as reviewed
   constants. The witness is a later byte-for-byte comparison against them,
   never a copy at run time.
7. **Copy.** Copying is staged. Each verified member is copied with `O_EXCL`,
   mode 0644, into a private sibling of `target`, and the parent directories
   are created as needed. Every copied file is rehashed. The staged members
   are then renamed into `target`. The target must not already contain
   either root, or the copy refuses with `projection-target-occupied`. Record
   each published inode. On any later failure, remove only those exact owned
   published members and the staging directory, proving the original target
   census restored; never remove an unrelated replacement. A cleanup failure
   remains an explicit failure and never claims unchanged target.
8. **Record.** `ProjectionRecord` holds: name, version, member count, hashed
   count, bytecode rows omitted, license count, module and RECORD SHA-256, and
   `source_class = "sdk-installed-record"`. It holds no paths.

Afterwards, `pip --python <env> check` (`arch7f_pip`) must exit 0. This is
an independent check of requirement closure. If the SDK lacks a `RECORD`-
bearing `typing_extensions` distribution, the work stops at gate G1.

## 6. Origin and closure witnesses

`ORIGIN_PROBE` is fixed source text. It runs twice under the child
environment of §2: once as `<env>/bin/python -c PROBE` and once with `-I`. These witness interpreter
resolution, not an instrumented console-wrapper trace. Separately verify every
wrapper's direct shebang or exact quoted distlib sh-exec trampoline selects this interpreter and its entrypoint imports
the expected installed function, then execute its real workflows. Reuse the
existing console-entrypoint form/interpreter parser, separately matching each
wrapper's own entrypoint (its cloe-only target predicate is not universal). It prints JSON containing `sys.prefix`,
`sys.base_prefix`, `sys.path`, `sys.flags.no_user_site`, the `__file__` of
`common_lore_index`, `repomap_kg` and `typing_extensions`, `default_rdbms_root()`,
the default graph and control migration counts,
`find_spec(…) is None` for `psycopg`, `psycopg_c`, `psycopg_binary`,
`psycopg2`, `psycopg_pool`, `onnxruntime`, `numpy`, `tree_sitter` and
`tree_sitter_rust`, the origin of `sitecustomize` and
`usercustomize` (or null), and the sorted normalized names and versions from
`importlib.metadata.distributions()`.

The test process classifies every path, never the probe. The classes are:
`env-purelib`, `env-data`, `env-bin`, `base-stdlib`, `base-dynload`, `system-site`,
`checkout` (under the checkout root), `owned-cwd` and `other`. Empty sys.path
is classified as the exact owned unrelated cwd, never as a wildcard temporary
path. `env-bin` is admitted only for the inspected console script location. Only class
names and counts reach the evidence, never paths.

For `pure-local`, every `sys.path` entry must be `base-stdlib`, `base-dynload`
or `env-purelib`, plus the exact `owned-cwd` for a normal `-c` probe. The three modules must be `env-purelib`. The resource root
must be `env-data`. `sitecustomize` and `usercustomize` must be absent or
`base-stdlib`. The driver family must be absent. The distributions must equal
§2. Both probe runs must agree, apart from the normal probe's working-directory entry, which `-I` removes. Separately, `sys.executable -I -c
"find_spec('common_lore_index')"` must print null under the same environment
(witness `base-interpreter-has-no-product`). Then any child that uses an
interpreter other than the environment's fails visibly instead of falling
back to the source.

Rows A03, L00, M00, R00 and S01 use one owner-bound environment and a real
normal plus `-I` probe before that owner's workflow rows. Local, MCP and
migration create their own fresh pure-local environment, register its owned
root, write intent, and then record the initial witness before any workflow
child. The witness also reads `pyvenv.cfg`, checks the owner's wrappers and
checks that the optional driver is absent. It records only the isolated path
counts; the closure predicate independently checks both probes and permits the
normal probe's single owned-cwd entry.

## 7. Fixtures, homes and the useful question

The tiny material has three bindings, each `privacy = "public-dev"` with
retention `inherit`:

- `code`: `tinypkg/ledger.py` defines `def reconcile_ledger_totals(entries)`
  and a class `LedgerWindow`;
- `docs`: `guide.md` with heading `## Ledger reconciliation`;
- `messages`: one new, short, manually reviewed synthetic public `.eml`
  fixture with reserved example.org identities and an explicit public subject.
  Freeze its relative path and SHA-256 before workflow execution. Do not read,
  copy or relabel mixed-v1 mailbox bodies: that existing binding is
  private-memory/metadata-only. Preserve the extractor's existing message
  privacy/retention semantics and assert the declared published metadata kind.

Homes live under `<tmp>/owned homes/<name>` and backups under
`<tmp>/owned backups/<name>`; the space is intentional. Files are written
with `write_sqlite_home(home, graphs, name=…)`. Current-format homes use the
base name that `plan_cloe_config_filenames(["repomap.rp.toml"], …)` returns,
computed in the test process before any child runs. Legacy homes use
`repomap.rp.toml` plus `zz-local.rpl.toml`.

The useful question, predeclared by hand from the fixture text: "Where is
ledger reconciliation implemented and documented?" It is answered through
`repomap_navigation_search {graph_id: "tiny", query: "reconcile_ledger_totals",
scope: "code"}`. The expected member is kind `python.function`, and
`repomap_node_locations` (compact) must give `source_relative_path =
"tinypkg/ledger.py"` and the line of the `def`. A `scope: "docs"` query for
`Ledger reconciliation` must return a docs member whose location is `guide.md`.
These expectations never come from the output of a run.

## 8. Interfaces exercised

### 8.1 Commands

Every command runs through the environment's own wrapper (`<env>/bin/cloe`,
`common-lore-index` or `repomap-kg`) or `<env>/bin/python -m …`. The only
exception is the guarded refresh, `<env>/bin/python -I <guard path>
ops refresh-graph …`, with `REPOMAP_TEST_SQLITE_BLOCK_PSYCOPG=1`. The guard
is stdlib-only, and `-I` keeps its directory off `sys.path`. Argument shapes
follow §1. Context commands use the shapes from `first_use_local` and are
re-read before use.

### 8.2 Migration API

Installed probes run `<env>/bin/python -c` with the home path supplied as
`argv[1]` and print the result mapping as JSON. Apply and finalize use
`common_lore_index.ops.config_migration`. Rollback uses
`repomap_kg.ops.config_migration`, which shows the finite facade at work.

### 8.3 MCP session

`McpSession` sends `initialize` (protocol version taken from source),
`notifications/initialized`, `tools/list` and then the declared
`tools/call` requests, one JSON line each. It then closes stdin. The child
must exit within its deadline. Bounds: 2 MiB of stdout, 64 KiB of stderr and
64 replies. Each stdout line must parse as JSON-RPC 2.0 with an id that
matches a request, except the deliberately malformed line's parse-error reply
with null id and code -32700; permit only source-declared notifications.
`McpTranscript` keeps the canonical SHA-256 of each reply's `result`, the
error codes, the line count and a stderr class (`empty`,
`legacy-module-notice`, `legacy-command-notice` or `other`). It keeps no
bodies.

## 9. Scenario matrix

Each row is one recorded step. Outcomes are `passed`, `expected-refusal`,
`failed`, `unknown` or `not-reached`. "Source" means a value computed in the
test process from current source before any child runs.

| ID | Env | Action | Expected facts (witness) |
|---|---|---|---|
| A01 | — | Shared candidate assembly | Source-derived inventory, entry points and Requires-Dist match; wheel SHA-256 is a preparation binding, not an expected fact |
| A02 | pure | Install the wheel, project the dependency, run `pip check` | Install exit 0; projection record; `pip check` exit 0; `pyvenv.cfg` flag false (file read) |
| A03 | pure | Origin probe, with and without `-I`, and the base interpreter | §6 closure holds (class counts); base interpreter has no product |
| A04 | pure | `cloe identity --installation-check --json` | `single-owner`, exit 0 (stdout) |
| A05 | shared | The A03 classifier applied to a `system_site_packages=True` env | Classified `provisioned`; a pure label refuses with `environment-class-mismatch` |
| A06 | pure | A03 probe with the checkout's `src/main/python` injected on `PYTHONPATH` | Witness reports a `checkout` origin; a pure label refuses with `origin-checkout` |
| A07 | pure | Projection from a scratch copy of the SDK distribution with one changed byte, a symlink, or an unknown member | `projection-hash-mismatch`, `-entry-unsafe` or `-unknown-entry`; target unchanged (listing digest) |
| L00 | pure | Before L01, origin and closure witness for this owner's fresh environment | §6 closure holds; false `pyvenv.cfg` system-site flag; driver absent; own wrappers; base interpreter has no product |
| L01 | pure | `--version` for all three wrappers | Exactly `"<name> 0.0.3\n"`; stderr empty except for `repomap-kg`, which prints the legacy notice line |
| L02 | pure | `ops config-check --json`, `ops graphs --json` | `valid` true; graph `tiny`; `storage.backend` is `sqlite`; public-dev paths classify as the owned fixture; only sanitized facts reach evidence |
| L03 | pure | `ops sqlite-init --graph tiny --json`, then `graphs --check-db` | Initialized; state `current`, `published` false |
| L04 | pure | `refresh-preflight`, then the guarded `refresh-graph --json` | Generation 1 accepted; explicit owned guard log has no forbidden socket/spawn/driver event; a separate deliberate import probe proves refusal |
| L05 | pure | MCP useful question (§7) | Expected member kinds and locations |
| L06 | pure | Context select with pinned publication, then pack | Pin equals generation 1; the pack is within its declared bound and contains the §7 code location |
| L07 | pure | `ops sqlite-backup --output "<owned backups>/b1" --json` | `created`; exactly two files; manifest graph id and generation 1 |
| L08 | pure | Rename the material root out of reach, then MCP readback | Reply digests equal the L05 digests; material root absent (stat) |
| L09 | pure | Remove the graph database and sidecars, `sqlite-restore`, then readback | `restored`, `schema_state` `current`; `graphs --check-db` generation 1; reply digests equal L05; material still absent |
| L10 | pure | `sqlite-restore` again onto the existing database | `sqlite-restore-target-exists`, exit 1; database SHA-256 unchanged |
| L11 | pure | `ops config-check --check-db` on a PostgreSQL home | Exit 1 with `postgresql-driver-unavailable`; no psycopg in the environment |
| M00 | pure | Before M01, origin and closure witness for this owner's fresh environment | The same §6 pure-local closure, false system-site flag, absent driver, own wrappers and base-interpreter refusal |
| M01 | pure | `cloe mcp serve --repo-map-home H` | Protocol version equals source; `tools/list` digest equals the source `tool_definitions()` digest; stderr `empty` |
| M02 | pure | `python -m common_lore_index.server.mcp` with `CLOE_HOME=H` | Same `tools/list` digest and call digests as M01 |
| M03 | pure | `python -m repomap_kg.server.mcp` with `CLOE_HOME=H` | stderr is exactly the `LEGACY_MCP_NOTICE` line; stdout digests equal M01 |
| M04 | pure | `repomap-kg mcp serve --repo-map-home H` | stderr is exactly the `LEGACY_COMMAND_NOTICE` line; digests equal M01 |
| M05 | pure | `python -m repomap_kg --version` | Legacy branding and the stderr notice (source constant) |
| M06 | pure | Unknown tool, `limit: 0`, a malformed line, then a valid call | tool results with `isError: true` for the first two; parse error -32700/null id for the malformed line; valid call succeeds |
| M07 | pure | Witness after M01–M06 | Main database SHA-256 and attempt-directory listing unchanged (WAL and SHM sidecars allowed) |
| R00 | pure | Before R01, origin and closure witness for this owner's fresh environment | The same §6 pure-local closure, false system-site flag, absent driver, own wrappers and base-interpreter refusal |
| R01 | pure | Legacy home `owned homes/legacy home`; init and refresh with `cloe` | Generation 1; identity snapshot (database SHA-256 and generation), plus unchanged read-only MCP result digests; no separate bundle-id snapshot is claimed |
| R02 | incumbent | `repomap-kg --version`; `ops config-check --repo-map-home H --json` | `"repomap-kg 0.0.3\n"`; `valid` true |
| R03 | pure | `apply(H, dry_run=True)` | `would-apply`, zero writes; home file bytes unchanged |
| R04 | pure | `apply(H, confirmed=True)`; `cloe ops config-check` | `applied`, `rollback_available` true; valid; identity snapshot unchanged; MCP digest unchanged |
| R05 | pure+incumbent | Legacy-path `rollback(H, confirmed=True)`; incumbent `config-check` | `rolled-back`; names and bytes equal the R01 snapshot; incumbent valid; identity unchanged |
| R06 | pure | `apply` confirmed, `finalize` confirmed, then `rollback` confirmed | `applied`, `finalized` with no operation directory retained, then `nothing-to-recover` and zero writes |
| R07 | pure | `apply(None)`; `apply(H)` unconfirmed; `apply` on a home with a symlinked config | `repo-map-home-required`; `confirmation-required`; `config-entry-unsafe`; zero writes each |
| R08 | pure | `cloe ops graphs --json` with `CLOE_HOME=H` and no flag | Output digest equals the `--repo-map-home H` output |
| S01 | prov | Install and origin probe | Product, resources and data are environment classes; psycopg is `system-site`, 3.3.6, `c` |
| S02 | prov | Installed catalog discovery | Graph and control triples equal source discovery |
| S03 | prov | Installed probe: `apply_migrations`, then `refresh_graph` against parent-owned `temporary_postgres` | Generation 1 accepted; the declared `python.function` key is present |
| S04 | prov | `cloe mcp serve` on the PostgreSQL home | `tools/list` digest equals source; the useful-question member is found |
| X* | each | Owner cleanup | Direct children reaped; safe owned roots removed; any unproved worker/workspace retained-reported, never accepted |

The overlap and uninstall matrix stays in `cloe_installed_cutover` and is
not duplicated here. The owners are: environment (A01–A07), local (L00–L11),
mcp (M00–M07), migration (R00–R08) and server (S01–S04), 45 rows total with
13 local rows under the 16-row owner ceiling. The local, mcp and
migration owners each publish the tiny graph once. A guard command explicitly
sets `REPOMAP_TEST_SQLITE_GUARD_LOG` to its owned file. The deliberate
installed `python -I -c` probe loads the stdlib-only guard with `runpy.run_path`,
calls its blocker, attempts `psycopg` import and observes `import-blocked`.
Allow the source-declared `import-info` events on ordinary guarded commands. Incumbent-local must
first prove its unconditional dependency is the existing exact 4.16.0 pin; a
different pin is a named missing artifact, never an implicit download.

## 10. Evidence

The Server cluster stays in the parent harness. Write an owned private config
home plus private argv/psql handoff for the installed child; never emit its
credentials, database name, command paths or runtime identifiers into evidence.

### 10.1 Formats

There are five derived formats, `cloe-installed-experience-{intent,observation,index,verdict,projection}-v1`.
They are written with `canonical_bytes`, and their bounds are: intent 16 KiB,
at most 48 observations across the recipe and 16 per owner, each 2 KiB;
an 8 KiB index, 2 KiB verdict and 1 KiB projection record embedded in the
2 KiB observation. A bundle holds at most 19 files and 128 KiB. Reuse unmodified
`BundleWriter` and `read_bundle`: call `default_bundle_base(temporary)`, add
owned `installed-experience/<owner>` directories, then use storage scenario
`local` (environment/local/MCP/migration) or `server` and a fresh 32-hex attempt.
The actual layout is `first-use-workload/installed-experience/<owner>/<storage-scenario>-<attempt>/`.
Write `intent.json`, ordered `observation-SS-1.json`, `index.json`, then
`verdict.json`. The installed codecs impose these tighter bounds and schemas
after the existing descriptor-anchored reader. The five bundles add at most640KiB under unchanged export ceilings.
No first-use domain, codec, writer or reader changes; storage scenario is not an installed owner claim.

### 10.2 Intent

Assembly and immutable SDK projection inspection precede workflow intent. Their
source inputs and output hashes are retained as preparation provenance. Each
owner writes intent after shared wheel preparation and before its first
scenario workflow child, never retroactively from scenario results. It contains:
`recipe_digest`; `candidate_input_sha256` and count; `wheel_sha256`,
`wheel_bytes`, `wheel_member_count` and `inventory_sha256`;
`incumbent_wheel_sha256` (migration owner only); the projection constants;
the tiny fixture census digest; `candidate_census_sha256` (`src/main`,
`src/test`, `tools` and `pyproject.toml`, the same coverage as the runner's
`source_sha256`); `python` (`3.13.12`) and `platform` (machine string); the
environment classes; and per scenario the ID, action and expected facts.
Expected facts are recipe constants or source-computed digests.

### 10.3 Observation

Each observation holds: `scenario`, `seq`, `env_class`, `family`
(`arch7f_pip` or `arch7f_probe`), `exit`, `outcome`, `stderr_class`,
`facts` (closed keys, each `{value, source}`, where `source` is one of
`child-stdout`, `child-exit`, `filesystem`, `pip-check`, `mcp-reply` or
`guard-log`), the `origin_classes` counts, `cleanup` (`removed`,
`retained-reported` or `not-applicable`), and for failures a
`failure_code` from a closed set. It contains no paths, host values,
environment values, raw streams, bodies or subjective words.

### 10.4 Reconciliation

`reconcile(intent, observations)` accepts only when all of these hold:

- the scenarios appear exactly once, in recipe order;
- every expected fact is matched by an observed fact with the same value and
  a non-intent `source`;
- A03, L00, M00, R00 and S01 origin rows carry the isolated path counts that satisfy §6; their witness fact proves the same environment's normal and `-I` probes, including the normal probe's permitted owned-cwd entry;
- every row is `passed`, or `expected-refusal` where the recipe declares one;
- cleanup is recorded for every owner.

Otherwise the verdict is `rejected` with categories `fact-mismatch`,
`witness-missing`, `order-violation`, `duplicate`, `unexpected-outcome`,
`class-mismatch`, `cleanup-missing`, `bound-exceeded` or `binding-mismatch`,
or `incomplete` when a step is `not-reached` or `unknown`. A skip is never
accepted. Fact values copied from the intent have source `intent`, which is
rejected as `witness-missing`.

### 10.5 Host check

`python3 tools/installed_experience.py check <bundle-dir>
--candidate-source-sha256 <hex>` re-decodes every member with the bounded
reader and recomputes the index and verdict. It requires
`candidate_census_sha256` to match the hosted report's
`candidate_identity.source_sha256`. Before invoking this consistency checker,
the host acceptance owner resolves the hosted report candidate commit to its
recorded Git merge tree and independently verifies the complete source snapshot,
tree and census against the downloaded exact candidate. The CLI does not fetch
GitHub or establish that external tree association. Host acceptance requires both
that external receipt and this checker; a source digest argument alone is not
hosted qualification. The checker refuses staleness, cross-owner/storage/attempt
path changes, mixing, tampering and unsafe members.

## 11. Failure handling and cleanup

- A step runs once and is never retried. After a required failure, later
  steps of that owner are recorded as `not-reached`. Cleanup still runs.
- Commands use the existing `popen_observed_process` with an adapter-owned 300-second deadline; `popen_observed_process`
  has no deadline itself. `McpSession` implements its own 300 s deadline and
  bounded incremental stdout/stderr reads before accumulation.
  Expiry is `unknown/child-deadline` with bounded available output retained
  privately. Reap the direct owned child and its declared group. Product workers
  use separate sessions: group cleanup alone cannot prove their absence. Retain
  and report an unproved worker workspace; never delete it or claim acceptance.
- The primary outcome takes precedence over the cleanup outcome.
  `KeyboardInterrupt` and `SystemExit` propagate unchanged after the
  observation and cleanup are recorded.
- Cleanup removes only exact owned roots after children are reaped. Root
  ancestors must be non-symlink directories; unknown worker roots are retained.
  Owned venv symlink leaves are
  unlinked without following them, never traversed or resolved for deletion. The
  `guard_first_use_root` rules apply. A failed removal is recorded as
  `retained-reported` and is never swept.
- Refusals inside the projection leave the target unchanged and are recorded
  as `failed` with their code, unless the recipe declares them (A07).

## 12. Documentation

The new section of `docs/ops/cloe-installed-upgrade-compatibility.md` covers
the following, and nothing more:

- what the proof covers;
- the three environment classes and their labels;
- that the scoped proof runs in the Linux canonical sandbox on the host's
  architecture (currently ARM64) with CPython 3.13.12;
- that hosted AMD64 evidence comes from the next ordinary staging CI;
- the unchanged holds: attended macOS installed-wheel proof, native services,
  Windows Local mutation, release image and package-manager publication;
- that the projection is not public package resolution.

The pending note in `docs/ops/sqlite-local.md` under "Installed-wheel
qualification" gains one link to it.

## 13. Gates and stop conditions

Stop and report, without widening scope, in any of these cases:

- **G1.** The SDK has no `RECORD`-bearing `typing-extensions` 4.16.0, or the
  projection cannot verify it. The only remaining routes, an image wheel cache
  or an acquisition, need a separate image or dependency decision.
- **G2.** `temporary_postgres` cannot be addressed from an installed child
  through a test-written private configuration. Record S03 and S04 as
  `installed-server-harness-unavailable`, and record the remaining
  installed-Server gap; nothing is built.
- **G3.** Exporting `installed-experience/` beside the report needs a runner
  or staging-report change, or `tools/` is outside the quality roots.
- **G4.** The wheel is missing a source member, the license or a declared
  resource (§4). Distinguish a test-oracle error from an actual packaging
  defect; a necessary metadata change is a separate decision.
- Any of the following:
  - The portable worker or another product child does not start through
    `sys.executable` plus the product-built environment without checkout
    `PYTHONPATH`. Retain a provenance probe
    immediately before refresh and inspect the source-backed launch route;
    distinguish this from an instrumented trace of every product worker.
  - A manual §7 expectation fails on the candidate.
  - The incumbent cannot run R02.
  - An owner exceeds 400 lines after a reasonable split.
  - `launch_observed_process` has no deadline control.
  - The context command shapes differ from §8.1.

An ordinary helper/API expectation mismatch goes to the parent for a source-backed
correction, not an invented operator gate. A demonstrated product defect inside
this boundary goes to the parent with a minimal fix and product unit coverage.
Any actual dependency, metadata, runner, image or native-class change remains
a separate decision. Do not silently fold a product fix into test support.

## 14. Verification

Use `--no-coverage` only. Brace groups expand to one path each.

```text
python3 tools/run_tests.py --suite unit --no-coverage -- \
  src/test/unit/python/tools/installed_experience_{recipe,records,reconcile,cli}.unit.test.py \
  src/test/unit/python/repomap_kg/runtime/installed_{candidate,environment,projection,origin,mcp_session,driver}.unit.test.py

python3 tools/run_tests.py --suite int --no-coverage --pg-container-port 55433 -- \
  src/test/int/python/repomap_kg/runtime/cloe_installed_{environment,local,mcp,migration,server}.int.test.py \
  src/test/int/python/repomap_kg/runtime/cloe_installed_cutover.int.test.py \
  src/test/int/python/repomap_kg/runtime/arch7f_release_wheel.int.test.py
```

The unit owners cover:

- §5 refusals over temporary trees: symlink, hard link, unknown member, `..`
  escape, size and hash mismatch, a missing license, an oversized `RECORD`,
  duplicate distributions and an occupied target;
- §6 classification, including `checkout` and `system-site`;
- §2 key removal when an inherited `PYTHONPATH` is present;
- §8.3 bounds and malformed replies;
- every §10.4 category, and copied expectations rejected as `witness-missing`;
- CLI exit codes and path-free output;
- the product import guard.

Local `--report` is not used, because the runner refuses it together with
`--no-coverage`. The bundles are validated inside the sandbox.

Further required checks:

- Ruff, mypy, compileall, file length, privacy and topology, suppression and
  both diff checks pass on the changed files, with no debt growth.
- Product, CLI, MCP, runner, packaging and lock bytes are unchanged.
- The complete local suite and local coverage are not selected.

## 15. Acceptance and forecast

Acceptance requires all of the following:

1. Both selector sets pass, and the five bundles are `accepted` in the sandbox.
2. The A05–A07, L10, L11, M06 and R07 negatives refuse as declared.
3. The §14 static checks pass.
4. The exit record claims no W5, W6, W7, W8, release or native result.
5. Independent review of the resulting source passes, followed by the
   parent's disposition.
6. A final-source binding precedes one staging publication.
7. A host `check` accepts the exact-source hosted bundles. This is pending
   at publication, and a missing check blocks acceptance.

This contract is wrong if any of these is true:

- a pure-Local child can import from the checkout or the SDK's site-packages
  while A03 still passes;
- an expected fact can be satisfied by copying it from the intent;
- the projection copies a member that `RECORD` does not verify;
- the overlap matrix weakens.

The forecast is about 7,500–9,500 meaningful added lines: support about
1,900, tools about 1,300, integration owners about 1,800, unit owners about
2,400, plus fixtures, docs and the exit record. This is below the 10k aim and
not padded.

### Implementation refinements before source acceptance

The frozen recipe has 45 rows. Every intent explicitly binds
`message_path = "messages/ledger.eml"` and the reviewed message SHA-256
`3ee85e5ca8ecc4ab2432cf2e2696c0284a4490f5bc227b1e154d6d271ba56da0`.
L05 must observe a published `email.message` node with subject metadata through
installed read-only MCP; merely copying the file or declaring its binding is
insufficient. S03 additionally reads publication generation 1 through installed
`context-select --pin-publication`.

A successful aggregate row permits no child failure to be discarded. Recorded
pass exits are zero or absent for aggregate/filesystem rows, except L06 permits
the existing bounded-partial context-pack exit 3. Declared refusal rows may
record the expected normal refusal exits zero or one; unrelated codes fail.
The producer and host reconciler share this closed exit rule. Deadline or signal
uncertainty preserves owned workspaces as `retained-reported` and cannot pass.

Unexpected child text is never copied into exported facts: the driver omits
undeclared fact keys and string values that do not equal their predeclared public
expectation. The failed row retains its closed failure code and missing witness;
absence does not assert that the child returned null. Safe numeric/boolean
observations remain available for diagnosis. Raw streams remain private.

### Host bundle-set procedure

The host acceptance owner enumerates exactly one installed bundle for each of
`environment`, `local`, `mcp`, `migration` and `server` in the same executed M
report. Extra, duplicate or missing owners refuse set acceptance. Each bundle
must pass the bounded reader and `check` for that report's independently verified
candidate source census. Together the five per-bundle 128-KiB bounds imply the
640-KiB aggregate ceiling. The host records all five individual verdicts and the
actual aggregate byte count. Owner attempt nonces are independent; no equality
of owner nonces or independently built wheel ZIP digests is assumed. Wheel input
identity and the executed candidate census must agree across owners. No single
bundle check by itself claims set acceptance.

The `candidate_input_sha256` field belongs to its containing schema. The unchanged
`cloe-offline-wheel-proof-v1` cutover print retains its historical input census;
installed intents use the NOTICE-inclusive wheel-input census. Do not compare
these differently scoped digests by field name alone.

Shared wheel and environment/material preparation are prerequisites to the
workflow evidence rows. A preparation exception fails the canonical test and
cannot produce an accepted owner bundle. The canonical disposable sandbox owns
its temporary resource cleanup, even if no owner intent could be written. This
phase does not claim an independent per-owner bundle for failed preparation;
that reporting extension remains open for full W8. Workflow rows and unsettled
children retain the explicit owner cleanup/unknown rules above.

R02 separately witnesses the installed incumbent interpreter: all distributions
must be exactly `repomap-kg==0.0.3` and `typing-extensions==4.16.0`; both origins
must be owned purelib, system-site/PYTHONPATH exposure must be absent, and neither
the current product nor the PostgreSQL driver family may be imported. The closed
`incumbent_closure_holds` fact is separate from incumbent configuration validity.
The `probe_*` L04 facts describe the inspected interpreter/module location and
do not attest to an independently traced product-worker launch.
