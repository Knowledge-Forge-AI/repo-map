# ADR 0181: Exact installed experience and evidence

Status: bounded installed-experience milestone accepted for staging source
`c31fdfbc6bd7c65df75b1e473be2a3f0134233be` after CI139 attempt 1 and the
exact-source five-owner host bundle check. This accepts the diagnostic installed
Local and provisioned-Server workflows in the hosted Linux AMD64 sandbox only.
Full W8, package-manager release, a fresh Server dependency install, release
images, host-native qualification and attended macOS remain open. The original
design and source-parent record below are preserved.
Date: 2026-11-09. Phase: `REPOMAP-CLOE-INSTALLED-EXPERIENCE1` (W8 prerequisite).
Source parent: `5997d06b7bf08b774e479968b518c6d167f556c6`. Public base: `5ad00d162ad8a04430874275246a53227578c533`.

## Context

CI137 attempt 1 accepted the bounded first-use workload, including the host
check of the exported bundles (see the roadmap record). W8 still has no proof
that the exact candidate wheel, installed on its own, gives a useful
experience. Current source covers only part of this:

- `runtime/cloe_installed_cutover.int.test.py` builds the incumbent and
  candidate wheels offline. It checks catalogs, the three commands, the finite
  `repomap_kg` facade and both unsupported overlap/uninstall orders. Its
  interpreters use `system_site_packages=True`, so the SDK's packages are
  visible to them.
- `runtime/arch7f_release_wheel.int.test.py` checks wheel metadata and installed
  catalog discovery through a `--target` directory placed on `PYTHONPATH`.
- `cli/sqlite_local_*` and `ops/first_use_*` exercise the real Local, MCP,
  backup/restore and context flows, but only from the source checkout.
- `tools/runner_coverage_execution.py` treats `arch7f_pip` and `arch7f_probe`
  as unmeasured. `prepare_child_coverage_environment` removes `COVERAGE_*`
  keys and runner bootstrap entries. It never applies `extra_env["PYTHONPATH"]`
  (its loop skips that key), so other inherited `PYTHONPATH` entries survive.
  Scrubbing alone therefore cannot prove that nothing falls back to the source tree.

No current test shows a wheel-only interpreter that has nothing besides the
declared dependency closure, then configures, refreshes, asks, navigates,
backs up, restores, migrates and serves MCP with the original source gone.
The only base requirement is `typing-extensions==4.16.0`. The SDK installs it
with `--no-cache-dir`, so no wheel file for it can be assumed to exist.

## Decision

Implement one milestone of three connected epics under the
[installed-experience contract](../../../specs/cloe-installed-experience-v1.md).

1. **Exact offline installed environments.** One shared builder assembles the
   current source wheel once per pytest process, using the existing route
   (`pip wheel --no-index --no-deps --no-build-isolation` under `arch7f_pip`).
   It checks the wheel's inventory against the current owners. A *pure-Local*
   environment is a fresh `system_site_packages=False` venv holding the wheel
   and a verified projection of the SDK's installed `typing-extensions` 4.16.0
   distribution, and nothing else. Children run outside the checkout with an
   explicitly closed environment. Independent witnesses then prove the
   interpreter class, `sys.path` closure, module and resource origin, the
   distribution set and the absence of the driver.
2. **Real installed workflows.** Installed wrappers and modules run the
   supported workflows: Local configure, initialize, check, refresh, a
   predeclared useful question, navigation and context, backup, restore and
   source-blind readback; canonical and finite legacy stdio MCP; and
   configuration migration apply, rollback and finalize over owned homes whose
   paths contain spaces, with the incumbent wheel's command where supported. A
   separately labelled *dependency-provisioned Server* environment proves the
   installed code paths against the SDK's existing dynamic Psycopg and a
   temporary PostgreSQL.
3. **Inspectable exact-candidate evidence.** A code-owned recipe is frozen before execution; workflow intent is frozen
   after shared wheel preparation and before scenario execution. The intent binds the wheel bytes, candidate
   inputs, environment and dependency provenance, and the expected semantic
   facts. Bounded observations come from child outputs and filesystem witnesses.
   A checkout-only reconciler and `tools/installed_experience.py check`
   compare them, keeping failures, expected refusals, unknown outcomes and
   cleanup states distinct.

### Selected boundaries

- **No product, packaging or runner change is planned.** If an installed
  workflow fails because of a product defect inside this boundary, the parent
  decides on the fix after design acceptance. If a fix would need package
  metadata, a lock, a dependency or the license, the work stops at a named gate
  (contract §13).
- **The dependency projection is test-owned preprovisioning.** It copies only
  rows of the SDK distribution's installed `RECORD` whose hashes verify, from
  the sandbox interpreter's purelib into the venv's purelib. It refuses
  symlinks, unknown members, path escapes, hash or size mismatches, missing
  license files and drift from frozen digests. It is not vendoring, network
  resolution or evidence of public package resolution, and no wheel is ever
  fabricated.
- **Environment classes are explicit.** A `pure-local` label requires
  `include-system-site-packages = false` and a closed origin witness. The
  `provisioned-server` class is never reported as pure. A shared-site venv
  presented as pure fails the classifier.
- **Launch and measurement are unchanged.** Children use the existing
  `arch7f_pip` and `arch7f_probe` families through
  `launch_observed_process`/`popen_observed_process`. The proof is diagnostic
  installed evidence. It is not M coverage, does not change measured or abrupt
  roles, and mints no runner class, flag, environment key or admission.
- **Incumbent results are reused.** The unsupported overlap matrix, catalog
  equality and facade identity stay owned by `cloe_installed_cutover`. That owner
  only switches to the shared wheel builders, and every one of its assertions
  is kept. The W1 namespace and distribution cutover is not reopened.
- **Evidence is checkout-only.** The recipe, codecs, reconciler and CLI live
  under `tools/`, and the execution adapters under `src/test/support/python/`.
  The evidence reuses the unchanged first-use bundle writer and reader through a documented storage adapter and the canonical
  JSON leaf. Product code imports neither root. There is no new installed
  command or diagnostic.
- **Fixtures are small and public.** A tiny committed code and docs fixture
  plus a reviewed synthetic public message file are used; mixed-v1 mailbox bodies are not copied. The 1.4 MB
  first-use recipes are not rerun, and no task, gold or held-out data is read.
- **There are no retries, sweeps or live targets.** Each step runs once.
  Cleanup removes only roots the attempt created. No live home, default home,
  service, client configuration or private target is touched.

## Alternatives considered

- **Relabel the existing `system_site_packages=True` venvs as Local.**
  Rejected. The SDK's site-packages can supply undeclared dependencies or
  shadow missing members, so this proves nothing about wheel-only use.
- **Download or `pip download` the `typing-extensions` wheel.** Rejected. That
  needs the network and its bytes have no custody here.
- **Fabricate a wheel from the installed files, or vendor the module into
  the repository.** Rejected. A synthetic artifact would claim a provenance
  it does not have, and vendoring is a dependency change.
- **Add a wheel cache to the SDK image.** Rejected for this milestone. An
  image build or acquisition needs its own gate. It stays the fallback if the
  projection proves unverifiable (gate G1).
- **Use a clean `python:slim` container per run, like the LOCAL11 kit.** Rejected.
  It needs an image pull and a new container launch class inside the sandbox.
- **Add a public `cloe ops installed-check` diagnostic.** Rejected. It would add
  an installed surface only for evidence. `identity --installation-check`
  already covers metadata ownership.
- **Grow `cloe_installed_cutover` in place.** Rejected. Its ownership and
  overlap question is already settled. New owners keep the questions separate
  and stay under the 400-line ceiling.
- **Add a new launch family for installed children.** Rejected as runner policy.
  The existing unmeasured families already describe these children correctly.

## Authority

The current user asked to continue the roadmap after CI137. This selects an
ordinary W8-prerequisite design within existing authority. ADR0123 already
grants offline wheel assembly and disposable installed checks with the pinned
setuptools, wheel and pip through the arch7f boundary. This ADR adds no
approval: no dependency, lock, version, license, DDL, role, image, network,
native platform, live service, global resource default, runner class or
measurement class. A new test case does not create runner authority. Independent design review and parent disposition are complete. Corrective
scoped proof, final-source review and one staging publication remain governed
by the parent; this design alone authorizes no publication.

Historical design-time pending work in this paragraph is superseded for the
bounded hosted installed checks by the CI139 qualification in Status above.
The remaining full-W8 and release/platform exclusions still apply.

## Consequences

- W8 gains an exact-candidate, wheel-only Local experience proof and a
  separately labelled installed-Server proof, both bound to the wheel's SHA-256.
- The integration population grows by five installed owners. Their children
  stay unmeasured, so whole-product coverage does not change. The hard 85/85
  unit and 80/80 integration gates and the 87/82 desired margins are untouched.
  Only genuine product fixes would need new product coverage.
- Hosted staging with `--report` exports the bundles. Their host `check` is a
  required post-CI gate before bounded installed-experience acceptance.
- The forecast is about 7,500–9,500 meaningful added lines (contract §15),
  below the 10k aim. It is not padded.

## Rollback

Revert the source. Nothing changes in product code, stored formats,
configuration, schemas, dependencies, packaging or runner behaviour. Bundles
are inert derived files. Venvs, homes and wheels live only under pytest-owned
temporary roots.

## Residuals and limits

- R1: The projection is bound to the SDK interpreter's installed `RECORD` and
  to frozen digests. It cannot prove that the SDK's `typing-extensions` came
  from a particular public wheel, nor that public resolution works.
- R2: The local scoped proof runs in the canonical Linux sandbox on the
  developer host's architecture (currently ARM64) with CPython 3.13.12. Hosted
  AMD64 proof comes only from the next ordinary staging CI. Neither run
  qualifies macOS, Windows, native services or a release image.
- R3: The installed-Server environment is provisioned. It borrows the SDK's
  system Psycopg and libpq, so it does not show a fresh Server dependency
  install or a release image.
- R4: The incumbent command is exercised only where the incumbent supports it
  (§9 of the contract). It makes no claim about cross-version database
  compatibility.
- R5: The bundles carry no signature. A host check proves consistency, not
  producer authenticity, as with ADR0180.
- R6: Full W5, W6, W7 and W8, release and image acceptance, held-out
  evaluation, ADR0177's deferred custody scenarios, native AMD and macOS
  attended runs, and main promotion all remain open.

## Acceptance

Completion needs:

- exact scoped unit and containerized integration selectors with
  `--no-coverage` (contract §14);
- meaningful adverse cases;
- clean enrollment of the new owners with ceilings unchanged;
- an exit record;
- independent review of the resulting source and the parent's disposition;
- a fresh final-source binding before one staging publication;
- a host `check` of the hosted exported bundles afterwards.

There is no design-only CI, main promotion, tag, release, retry or automatic successor.
