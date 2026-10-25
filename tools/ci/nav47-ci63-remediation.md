# NAV47 CI63 Remediation Note

## Scope and References

- Phase: `REPOMAP-PRODUCT6-NAVIGATION47-CI63PROOF1` (source-only correction candidate following predecessor
  `REPOMAP-PRODUCT6-NAVIGATION47-CI63REPAIR4` on base `4a25aa25c8e896667f6ce6cbcefcad77970a21fa`)
- ADR: `docs/adr/2026/10/0093-ci63-pg-config-and-native-report-export.md` (ADR 0093)
- Hosted run: [CI63 (`40123844449`)](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/40123844449)
- External references:
  [`dpkg-divert(1)`](https://manpages.debian.org/trixie/dpkg/dpkg-divert.1.en.html),
  [`dpkg-query(1)`](https://manpages.debian.org/trixie/dpkg/dpkg-query.1.en.html),
  [Debian `libpq-dev` file list](https://packages.debian.org/trixie/amd64/libpq-dev/filelist),
  [Debian `140_pg_config.t`](https://sources.debian.org/src/postgresql-common/278/t/140_pg_config.t/),
  [GitHub runner `install-postgresql.sh`](https://raw.githubusercontent.com/actions/runner-images/ubuntu24/20261012.334/images/ubuntu/scripts/build/install-postgresql.sh)

## Exact CI63 Observations

- **Passed jobs**: `source-and-export-policy` (`120960940157`), `codeql-analysis (python)` (`120960986251`),
  `codeql-analysis (go)` (`120960986349`), `sbom-and-vulnerability-scan` (`120960986273`), and
  `staging-integration-gate` (`120960986348`).
- **Failed jobs**:
  - `unit-tests` (`120960986201`) and `pre-review-static` (`120960986210`) — failed in C Psycopg / pre-review bootstrap
    because `PATH` `/usr/bin/pg_config` was diverted.
  - `d12-native-amd64` (`120960986250`) — failed in `Run canonical D12 native preflight` on an unfrozen `_tkinter`
    payload refusal and in `Seal native D12 qualification evidence` because raw preflight reports were not exported
    before sandbox teardown.
  - `main-system-gate` (`120960986272`) — failed as expected while release prerequisites remain held.
- **Staging integration coverage (`M`)**: hard gates unit `85/85`, integration `80/80`; aims unit `87/87`, integration
  `82/82`. `staging-integration-gate` measured `16171 / 19864` branches (`81.4085783326621%`, `118` branches short of
  `82.0%`) and `54604 / 60921` lines (`89.63083337437008%`); `python_payload.py` had `78` uncovered branches.

## Corrected Custody and Transport Mechanism

1. **CI-only `pg_config` custody (`tools/ci/psycopg_pg_config_custody.py`, `tools/ci/psycopg_bootstrap.py`)**:
   Shared `tools/native_apt_prerequisites.py`, SDK recipes, locks, and product source remain unchanged, and
   `psycopg_pg_config_custody.py` uses only public `native_apt_prerequisites` helpers with local package-name and
   architecture regex validators (`_DEB_NAME`, `_DEB_ARCH`). Both routes first verify the installed `libpq-dev`/`libpq5`
   pair against `dpkg --print-architecture` before executing any `pg_config` tool, and `pg_config_version_matches_package`
   accepts only plain upstream or 2-token `Debian`/`Ubuntu` vendor suffix forms matching package and source upstream
   versions. Plain and relocated matching `PATH` tools then use `attest_libpq`. When canonical `/usr/bin/pg_config` or
   `/bin/pg_config` is diverted, `psycopg_pg_config_custody.py` proves one installed manager (`postgresql-common` or
   `postgresql-common-dev`), canonical `pg_config.libpq-dev` target, coherent `dpkg-query -S` diversion and ownership
   records across both the canonical path and physical target (`C.UTF-8`, `LANGUAGE=""`) plus
   `dpkg-query -L libpq-dev`, and single `libpq-dev` `md5sums` control match (local package integrity metadata under
   existing D6 custody, not publisher authentication) plus SHA-256 before executing the relocated original. Both routes
   bind pip's build child via a private `PATH` symlink (`sym`), verify that `realpath(str(sym))` resolves to the
   attested target, recheck target SHA-256/size/filesystem identity immediately before executing the 3 bound
   `pg_config` probes, run the 3 unchanged hash-locked `install_commands` under `BootstrapError`/exit `2`, recheck
   target SHA-256/size/filesystem identity after the build step, preserve `os.environ`, and clean up temporary state.
   A `/bin/pg_config` spelling whose diversion metadata names `/usr/bin/pg_config` refuses safely on usrmerge hosts;
   the known-diversion exception requires coherent literal metadata. Local package tests are unit/adapter evidence;
   hosted `unit-tests` supplies the real Linux proof.
2. **Minimal D12 preflight report transport (`tools/test_sandbox_execution.py`)**:
   An unpublished first draft added HTML `--report` to `--no-coverage`, which real CLI and D12 admission forbid.
   Workflow/fragment/contracts omit `--report`; `sandbox_report_arguments` opts into raw `/sandbox-report/report`
   transport only when literal `--d12-core-image-preflight` is in the runner prefix, exporting raw JSON reports on exit
   `0` and nonzero/refusal before container cleanup.
3. **Real containerized runtime integration tests**:
   `python_payload_contract.int.test.py`, `backup_provenance_boundaries.int.test.py`, and
   `repomap_test_support/backup_provenance_boundaries.py` exercise real SDK ELF/`ldd`/`dpkg-query`/`sys.executable` and
   real `temporary_postgres`/`pg_restore`/on-disk release artifacts. `backup_provenance_boundaries.int.test.py` binds
   `_LiveOp.authority_namespace` from the public `LocalControlAuthority(home)` in
   `repomap_kg.coordinator.local_lifecycle`, preserves the unheld negative upgrade manifest build (`restore_supported=False`,
   `quiescence-not-verified`) and its on-disk refusal outside a maintenance window, refreshes
   `observe_connection_provenance` inside the real `authority.maintenance_window(graph_databases=(graph_db,))`
   advisory-lock window to build the held positive `schema_version=2` artifact (`restore_supported=True`), and separates
   TOC, connection/custody, release-upgrade, and backup-manifest boundary families into four test functions sharing one
   module-scoped container fixture while proving archive bytes, manifest state, table inventory, and representative
   graph/control SQL rows are unchanged.

## Predecessor Evidence, Pending Boundaries, and Holds

- **Historical predecessor (`CI63REPAIR4`) local evidence**: Predecessor `R4` recorded `283 passed, 4 skipped` on the
  scoped unit selector, `7` passed checks on the `pre-review` static selector, and `1 failed, 4 passed` on the scoped
  containerized integration selector (`backup_provenance_boundaries.int.test.py` failed on `restore_supported` when
  `_LiveOp.authority_namespace` was `None` outside a maintenance window).
- **Current scoped-proof requirement**: The approved additional allocation is at most two unit, two containerized
  integration, and two scoped static executions, with one of each first and a correcting source change required
  before any repeat. Canonical Python selectors use `--no-coverage`; the exact selectors and actual results are
  recorded in the phase commit. Publication requires current passing proof for the final candidate, independent
  complete-delta review and parent acceptance. Complete local suites and coverage measurements are unselected.
- **No hosted improvement claim**: Hosted CI, Linux runner custody, native AMD report capture, and successor numeric
  coverage remain unverified until the next hosted campaign runs.
- **Holds**: Native AMD64 D4 exclusion, `d12_hosted_candidate.json` (`libpq` `None`, empty package map,
  `application_builds_maximum: 0`, `application_builds_used: 0`), P3/incumbent comparison, `main-system-gate`, and
  public `main` (`preview003`) remain held. The next reviewed hosted campaign may need one SDK materialization under
  existing authority with the unchanged recipe (`2` total / `1` per-platform / no-retry ceiling); no application build
  follows.
