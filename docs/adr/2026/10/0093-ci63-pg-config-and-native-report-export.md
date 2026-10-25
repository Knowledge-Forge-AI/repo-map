# ADR 0093: CI pg_config custody and native preflight report transport

## Status

Accepted bounded correction design on 2026-10-24 and amended on 2026-10-25
after [CI64](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/40154773099)
(`staging` `0284aa36075c9c74cda1b179ed3240659c7b3164`, test merge `38bb`) under
the maintainer's CI63/CI64 remediation request, ADR0089 D6 and the approved
D12-A admission plumbing. Implementation evidence belongs to the phase commit;
hosted and runtime qualification remain separate.

This decision grants no system-package installation, SDK change, general runner-policy
exception, AMD exclusion, P3 acceptance or application build.

## Context

[CI63](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/40123844449)
stopped unit/static setup because PATH pg_config was diverted. Native AMD
exploration reached an unfrozen Python payload refusal, but its raw reports
were not exported before sandbox teardown. The system prerequisite hold stayed
active. Integration passed its hard gate; its branch cushion remains unresolved.

The first unpublished repair added HTML `--report` to an invocation that
requires `--no-coverage`. The real runner and D12 admission forbid that
combination before sandbox dispatch. An adapter-only unit test missed the CLI
boundary. The local integration attempt refused before running tests; its
receipt and rejected draft remain retained privately. No publication resulted.

Debian's [pg_config tests](https://sources.debian.org/src/postgresql-common/278/t/140_pg_config.t/)
distinguish the libpq-dev tool from the newest installed server-development
tool. The [libpq-dev package](https://packages.debian.org/trixie/amd64/libpq-dev/filelist)
lists the original `/usr/bin/pg_config`; a known package diversion can relocate
it to `pg_config.libpq-dev`. The runner's
[provisioning script](https://raw.githubusercontent.com/actions/runner-images/ubuntu24/20261012.334/images/ubuntu/scripts/build/install-postgresql.sh)
does not establish that another matching versioned provider is installed.
Live metadata, not that assumption, must establish custody.

The D12 owner already writes raw freeze/exploration/cleanup JSON independently
of HTML reporting. The outer sandbox adapter only selected report transport
when HTML `--report` was present. Fixing that transport does not require a
coverage exception.

In [CI64](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/40154773099):

1. `unit-tests` and `pre-review-static` refused during C Psycopg bootstrap with
   `diverted target /usr/bin/pg_config.libpq-dev is itself diverted`. In
   upstream
   [dpkg `src/divert/main.c`](https://github.com/guillemj/dpkg/blob/main/src/divert/main.c),
   a diversion pair attaches `fnn->divert` to both the `camefrom` source and
   the `useinstead` destination: `diversion_listpackage` prints the owning
   package (`postgresql-common` or `LOCAL`) for either endpoint, while
   `diversion_truename` follows `useinstead` only on the source and returns the
   destination path itself on the destination. Rejecting non-empty
   `--listpackage` on the destination rejected the normal `postgresql-common`
   diversion pair, and the unit fixture omitted destination `--listpackage`
   state.
2. `staging-integration-gate` leg `M` passed all 1,793 integration tests (12
   skipped, 24 deselected) before strict shard-directory integrity rejected an
   unregistered `.coverage.<host>.<pid>.<rand>` shard with
   `launch_shape=cpython:-c` (from which no owner can be inferred by PID
   alone), leaving dependent leg `A` blocked with empty records. Source
   inspection indicates `python_payload_contract.int.test.py` passed raw
   `subprocess.run` into `python_payload.observe` and `python_payload.main`,
   which spawn `[sys.executable, "-I", "-B", "-c", "import <stdlib>"]` with
   inherited `os.environ`: `-I` ignores `PYTHONPATH` (skipping the runner's
   `bootstrap/sitecustomize.py` manifest registration) while `site.py` still
   processes `site-packages/*.pth` (`a1_coverage.pth`) and triggers
   `coverage.process_startup(slug="pth")` when `COVERAGE_PROCESS_START` or
   pinned Coverage `7.15.4`'s inherited `COVERAGE_PROCESS_CONFIG` is present
   (see upstream
   [Coverage.py `7.15.4` `coverage/pth_file.py`](https://github.com/coveragepy/coveragepy/blob/7.15.4/coverage/pth_file.py)
   and
   [`coverage/control.py`](https://github.com/coveragepy/coveragepy/blob/7.15.4/coverage/control.py)).
   This causal attribution remains a source-derived inference until a fresh
   hosted measured `M` run completes.
3. `d12-native-amd64` exported a valid sealed negative-evidence bundle with
   zero seal or validation errors, retaining the complete native AMD64 baseline
   and authentic refusal for missing Tcl/Tk (`libtk8.6.so` / `libtcl8.6.so`).

## Decision

1. Preserve the shared native APT helper, its generic diversion refusal, SDK
   recipe, locks and product source. A CI-only stdlib helper may prove the
   known libpq-dev original when a canonical PATH wrapper is diverted. Plain
   and relocated matching PATH tools retain the shared attestation route.
2. The known-relocation route requires one coherent installed manager and
   canonical source/destination pair, exact known manager equality on both
   `dpkg-divert --listpackage <source>` and
   `dpkg-divert --listpackage <destination>`, unchanged destination truename
   (`dpkg-divert --truename <destination> == <destination>`), one installed
   native libpq-dev/libpq5 pair with equal package/source versions, original
   package ownership, and a regular executable non-symlink target. Missing,
   foreign, local, ambiguous, chained or inconsistent evidence refuses before
   execution. Never execute the wrapper, fabricate package ownership or
   suppress diversion evidence.
3. Use documented read-only
   [dpkg-divert](https://manpages.debian.org/trixie/dpkg/dpkg-divert.1.en.html)
   and [dpkg-query](https://manpages.debian.org/trixie/dpkg/dpkg-query.1.en.html)
   metadata. Match the relocated bytes to exactly one installed libpq-dev
   control checksum entry and bind observed bytes with SHA256. The installed
   MD5 record supplies local package integrity, not independent publisher
   authenticity. Existing package/image custody remains the trust basis.
   Do not depend on unverified dpkg-verify diversion semantics.
4. The attested tool's selected header and runtime retain the unchanged shared
   package-owner checks. Bind each build child through a private PATH symlink
   to that executable, compare its three pg_config outputs through the bound
   path, and recheck identity/SHA256 after the build. Preserve the caller
   environment and remove temporary state on success and every failure.
5. Keep the three hash-locked install steps, C Psycopg3.3.6, dynamic system
   linking, header/runtime equality, binary/static/pure exclusions and existing
   BootstrapError/exit2 envelope. No acquisition or build procedure changes.
6. Extend the existing sandbox transport opt-in only for the literal admitted
   `--d12-core-image-preflight` runner token. Preserve its current signature,
   SandboxArgumentsResult, `/sandbox-report/report`, safe exporter, byte/path
   checks and cleanup behavior. Remove the invalid HTML flag from the native
   workflow/fragment/contracts. Generic HTML/coverage and D12 admission rules
   remain unchanged; profile-only/build mode receives no new transport opt-in.
7. Test the real canonical CLI admission before the adapter. Then prove raw
   report export on success and nonzero/refusal, prior to cleanup. Forwarded
   flags must not select transport. Argument abbreviation behavior is unchanged;
   the approved hosted command uses enforced literal flags.
8. Replace synthetic integration branch cases with real filesystem/process and
   temporary PostgreSQL/archive/on-disk artifact boundaries. Use actual APIs,
   diagnostics and immutable-data assertions. In containerized integration,
   invoke real `dpkg-divert` and `dpkg --print-architecture` against a
   test-owned temporary `--admindir` and `--instdir` without host/system
   database mutation to prove source and destination endpoint CLI semantics,
   real CLI nonzero refusal of chained/conflicting `--add` operations,
   malformed `diversions`-database `command_output` refusal, and direct
   `_verify_diversion_records` verification against explicit minimal
   installed-manager and ownership transcript fixtures, while keeping defensive
   owner-level chained-truename and full bootstrap/child-binding contracts in
   unit tests and clearly distinct from hosted distribution qualification.
9. In `python_payload_contract.int.test.py`, wrap real `subprocess.run` across
   both positive and refusal `observe`/`main`/`owners` calls with a
   test-support adapter (`repomap_test_support.python_payload_probes`) that
   intercepts only the exact `[executable, "-I", "-B", "-c", "import <stdlib>"]`
   probe shape for the actual selected SDK stdlib modules and scrubs inherited
   coverage startup state (`COVERAGE_PROCESS_START`, `COVERAGE_PROCESS_CONFIG`
   and related `COVERAGE_*` variables) via
   `prepare_child_coverage_environment(..., family="unmeasured")`. Keep parent
   `python_payload` APIs and branches measured, preserve real ELF, `ldd`,
   `dpkg-query` and import behavior and caller environment, and leave strict
   runner shard integrity and leg `A` reconciliation unchanged.

## Scope and exclusions

Changes belong to CI custody/bootstrap, the existing outer transport adapter,
their scoped tests and test support, additive strict inventory and phase
documentation. No dependency/lock, shared APT helper, SDK recipe, application
context, schema, public CLI/MCP contract, runner coverage policy, authority
record, debt ceiling or coverage threshold changes. No complete local suite,
local SDK build, emulation or live action.

Hard gates remain unit85/85 and integration80/80. Aims remain unit87/87 and
integration82/82, measured only by hosted CI. No synthetic test or local scoped
pass supplies a numeric cushion. The exact AMD exclusion, numeric libpq,
dynamic package map, P3/incumbent comparison and zero application-build
admission remain held.

## Alternatives and rollback

Keeping the held state leaves CI broken. Transport correction alone leaves a
provider assumption. Installing another package, changing SDK inputs or allowing
HTML reporting without coverage needs separate authority and is unnecessary for
this bounded correction. Trusting the wrapper or ignoring diversions would
discard the custody contract.

Rollback is a normal corrective commit restoring the prior CI/transport slice
while retaining failed attempts and existing holds. No history rewrite or
automatic repeated campaign is authorized by this decision.
