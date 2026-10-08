# Host-Native MCP Console Qualification Runner

This runbook is also the `README.md` of the operator kit. It prepares and
runs the Product step 3 proof: the pinned macOS checkout's own
`.venv/bin/repomap-kg mcp serve --repo-map-home <fresh-home>` serving real
stdio JSON-RPC reads from a disposable PostgreSQL fixture.

A completed run means **evidence is ready for manager review**. It is not
native qualification or Product step 3 acceptance. The receipt attests
delivery only. A Linux run, including the containerized integration exercise
of the same runner, is never native acceptance.

## What the runner does

1. **Prerequisites (`--check`, the default).** These checks create nothing:
   - macOS;
   - integrity of the extracted kit;
   - a clean checkout whose product files and runner sources equal the ones
     the kit was built from;
   - a supported checkout console script whose interpreter is inside
     `<checkout>/.venv/bin`;
   - an import probe that runs that interpreter with the child environment
     from an unrelated folder;
   - parent imports (`repomap_kg` from the checkout; `psycopg`; `pytest`;
     every runner module from the kit);
   - Docker server access and the locally present
     `postgres:16-alpine@sha256:e013…` test image;
   - free disk space and a fresh loopback port.

   Docker is probed only after every local check passed. Any refusal is
   reported as **NOT RUN** (exit 2), not as a failed test. Nothing is ever
   installed or pulled automatically. If the image is absent, the evidence
   names the manual `docker pull` command.
2. **Execution (`--execute`, macOS and extracted kit only).** Each execution
   is a fresh run: a new run id, a new `0700` work root, and a new outbox
   directory. Nothing is resumed or retried. Before the container is created,
   the runner writes `OWNER.json` to disk in the run's outbox folder. The file
   is mode `0600`, fsynced, and secret-free. It holds only:
   - the run id and runner PID;
   - the exact work-root and evidence paths;
   - the backend kind, the exact container name, and the
     `org.repomap.test.run_id` label;
   - the scoped manual cleanup: `docker rm -f repomap-test-postgres-native1…`
     and `rm -rf -- <exact work root>`.

   It contains no password, pgpass contents, environment values or
   `runtime/.env` data. The runner also prints its path and the `docker rm -f`
   command to stderr. The runner then:
   - starts one PostgreSQL container only. It uses `--pull=never`, tmpfs data,
     the `org.repomap.test.run_id` label, and a `127.0.0.1:<fresh port>` bind.
     There is no server container, coordinator, launchd/systemd service, or
     installation;
   - creates two databases and publishes two tiny graphs through the incumbent
     publishers. `host-multi` has two source-qualified shell folders. It is
     published under the tuple that supported refresh writes: name
     `[multi-source]`, root `graph:host-multi`, identity `repo1:host-multi`.
     `host-feed` is one offline RSS acquisition with a fake fetcher. It also
     declares a hidden graph. The setup-owned home comes from
     `repomap-kg`'s local setup and uses the maintained read/status role
     projection;
   - deletes only the fixture source roots, leaving the configuration and the
     credential file;
   - records publication identity, counts, schema digest, home file digests and
     modes, and the route. The route must be `local-native` on the bound port
     with the `repomap_read_status` projection;
   - computes every expected payload from independent maintained query owners
     before the first MCP process starts.
3. **MCP sessions.** Each session launches the console script directly with
   `subprocess.Popen`, from `<work>/child/unrelated cwd`, with a from-scratch
   environment:

   | Key | Value |
   |---|---|
   | `HOME` | a fresh user home |
   | `PATH` | recording shims first, then `/usr/bin:/bin` |
   | `LANG` | |
   | `TMPDIR` | |
   | `PYTHONDONTWRITEBYTECODE` | |
   | `REPOMAP_STORAGE_READBACK_DRIVER` | `psycopg` |

   The child gets no PostgreSQL, Docker, Python import-path, MCP/ops
   configuration, agent or provider variable. Its read/status secret is read
   in memory by the product from the home's `runtime/.env`. The sessions are:
   - **main.** Covers initialize, the unchanged 27-tool catalog
     (`c38abd4f…2dde`), and the config inventory. It then reads each of the
     three read-store families: canonical, investigation and source/feed. Each
     positive read is compared with its oracle and must be nonempty. Graph
     and refresh status for both visible graphs are also compared with
     fixture-admin stored repository facts: existence, latest run, and raw
     and canonical counts. It also checks cross-message chains and nine exact
     refusals. The HOST1-executed PREPARE2 kit predates this status
     comparison. A native run of the current bytes needs a newly built kit;
     see [00976](../status/2026/09/29/00976-product2-multisource-status-fix1-exit.md);
   - **write-denial and connection checks.** After main, the runner runs the
     maintained read-role write-denial probe and waits for read-role
     connections to end;
   - **restart.** A fresh process must reproduce three reads, one per family;
   - **state comparison.** After restart, the runner compares state before
     and after;
   - **outage.** The runner stops the owned container. Then a session checks
     that the config-only inventory still succeeds and that each family's read
     is a bounded refusal (at most 300 characters, with no Docker/container
     topology). The container must still be stopped afterwards, and the shims
     must have recorded no invocation.
4. **Cleanup and evidence.** On every outcome, including an exception, a
   catchable signal or a failed check, cleanup runs in this order:
   1. terminate and reap only the live child's own process group;
   2. remove only the owned container;
   3. verify that no labelled container remains;
   4. delete the work root, which holds the home, pgpass, psql wrapper and
      runtime secrets.

   Each step is attempted independently: a failed step is recorded, and the
   later steps and the evidence still run. A cleanup failure is exit 3 and is
   never reported as success; the manifest keeps the pre-cleanup outcome and
   any original error. The runner then writes `evidence.zip` and
   `receipt.json` beside `OWNER.json` in
   `~/Documents/agent/outbox/repo-map_dev/<phase>/<run-id>/`. Every secret
   value (the fixture admin password and every `runtime/.env` value) is
   redacted by exact value. For each member, the manifest records:
   - the recorded-byte SHA-256;
   - the original-byte SHA-256 and the redaction count, when content changed;
   - for `OWNER.json`, `early_file_sha256`, the hash of the on-disk file.

   `cleanup.json` also lists the backend's already-redacted Docker commands.
5. **Interruption.** SIGINT, SIGTERM and SIGHUP are handled through one
   phase-aware gate:
   - **Before and during setup and the MCP sessions.** The first signal
     cancels the work. Cleanup and evidence then run, and the outcome is
     `interrupted` (exit 130).
   - **During cleanup or evidence finalization.** A signal is recorded with
     its phase and deferred. It cannot abort the remaining cleanup or prevent
     the ZIP and receipt, and repeated signals change nothing. The outcome is
     then the executed result (`completed_pending_manager_review`,
     `checks_failed`, `failed` or `cleanup_incomplete`), with
     `signal_timing: teardown_only_deferred` in the manifest and a stderr note
     that the signal did not cancel the work. It is never described as a
     cancelled test.
   - **Recording.** Every signal is listed in the manifest summary
     (`signals`, `signal_timing`, `signal_handling`).
   - **Docker helpers.** The Docker CLI helpers run in their own session, so a
     terminal Ctrl-C or hangup does not also kill an in-flight `docker rm -f`
     or label check.
   - **Handler restoration.** When the run ends, even by an exception from
     finalization, the handlers it replaced are restored.
   - **SIGHUP.** It is handled like SIGINT and SIGTERM, unless the caller
     already ignores it, as under `nohup`. A signal the caller ignores stays
     ignored.

   This is ordinary catchable-signal handling, not crash-proof
   infrastructure. There is no receipt after SIGKILL, a crash, machine loss,
   or a full disk. In those cases, `OWNER.json` without a `receipt.json`
   beside it names the only container and work root to remove.

| Exit | Outcome |
|---|---|
| 0 | `completed_pending_manager_review` (`--check`: `prerequisites_ok`) |
| 1 | checks failed or setup failed |
| 2 | NOT RUN (a prerequisite was refused) |
| 3 | cleanup incomplete (overrides every other outcome) |
| 130 | interrupted during setup or the MCP sessions (cleanup and evidence still ran) |

`run.sh` refuses before Python starts, with exit 2 and no receipt, when
`--checkout` is missing or `<checkout>/.venv/bin/python` does not exist.

## Parent and child authority

The parent is `<checkout>/.venv/bin/python -I -B` running the kit's
`tools/host_mcp_native_qualify.py`. It alone puts the kit's `tools` and
`src/test/support/python` on `sys.path` for its fixture helpers.

For its own duration it removes libpq `PG*` variables and the RepoMap
connection, registry and home selectors from its environment. It pins the
Psycopg route and prepends `<checkout>/.venv/bin` to its `PATH`. When it
finishes, it restores all of them.

The fixture admin credential exists only in memory and in a `0600` pgpass
file inside the work root, and only its path is exported. None of this is
forwarded to the MCP child.

## Kit contents

**From the reviewed candidate (inside the ZIP):**
- `run.sh` and this `README.md`;
- `KIT-MANIFEST.json`, with per-file SHA-256 and mode, and the product
  manifest of git-listed `src/main/python/repomap_kg`, `src/main/resources`
  and `pyproject.toml` bytes;
- the runner and its AST-computed import closure under `tools/` and
  `src/test/support/python/`;
- the two offline fixture inputs, `discovery/feed_static_basic/rss.xml` and
  `source_ingestion/feed_sources/allowed-rss.toml`.

**Still from the pinned checkout:**
- `.venv/bin/python`;
- the `.venv/bin/repomap-kg` console script, which is the acceptance process;
- the editable `repomap_kg` package with its migrations;
- the installed `psycopg` and `pytest`.

Since LOCAL11 the base package no longer installs Psycopg. Install the checkout
with `.[postgres,test]` (or the full development extras) before running this
kit; without the driver the Psycopg route is unavailable.

An installed wheel or store package is a separate qualification. A working
checkout console does not establish it.

## Operator command

The kit is built into its phase outbox folder, next to `kit-receipt.json` and
the generated `OPERATOR-COMMAND.zsh`. The manager publishes that folder and
the ZIP's SHA-256. The SHA cannot appear in the tracked copy of this file.

The ZIP is used where it was delivered: nothing is copied into an inbox or
Downloads. The command verifies the SHA-256 in place, extracts into a fresh
temporary folder, and runs the extracted sibling `run.sh`. Run it in zsh,
replacing `<KIT_DIR>` and `<KIT_SHA256>` with the published values, or run the
generated `OPERATOR-COMMAND.zsh`, which already contains them:

```zsh
(
  set -eu
  kit_sha=<KIT_SHA256>
  zip="<KIT_DIR>"/repomap-host-mcp-native-kit.zip
  [[ -f "$zip" && "$(shasum -a 256 "$zip" | cut -d' ' -f1)" == "$kit_sha" ]] || {
    print -u2 "NOT RUN: $zip is absent or its SHA-256 is not $kit_sha"; exit 2; }
  dest=$(mktemp -d "${TMPDIR:-/tmp}/repomap-native-kit.XXXXXX")
  ditto -x -k "$zip" "$dest"
  sh "$dest/repomap-host-mcp-native-kit/run.sh" --check --checkout "$HOME/projs/repo-map_dev"
  sh "$dest/repomap-host-mcp-native-kit/run.sh" --execute --checkout "$HOME/projs/repo-map_dev"
)
```

`--check` exits nonzero on NOT RUN, and `set -e` then stops before
`--execute`. The runner generates the `--repo-map-home` itself; never supply
one.

Return both outbox run folders (`check-…` and `native1-…`) for manager review.
Each has its `evidence.zip` and `receipt.json`, and the `native1-…` folder also
has its `OWNER.json`.

`--check` refuses a dirty checkout. It compares the checkout with the kit only
when the checkout is clean, so commit exactly the reviewed candidate bytes
first.

## Limits

- The Linux integration exercise differs from the native run in three ways.
  It uses the runner-provisioned `repomap-kg` wrapper. Its outage is
  `ALLOW_CONNECTIONS false` on the fixture databases, so the error comes at
  login, whereas the native outage stops the container and the error is a TCP
  refusal. And it uses harness-owned PostgreSQL. It proves fixture and
  protocol mechanics only. The native outage error path is first exercised by
  the operator run.
- Deadlines only prevent hangs. No timing or performance threshold is
  asserted.
- Interruption windows:
  - Signal phases change between Python bytecodes.
  - A signal arriving after the work root is created but before the gate is
    installed, a window of microseconds, falls to the default handling. It
    leaves an empty `0700` work root and no receipt.
  - Signal handlers are installed only on the main thread.
  - Signals the caller already ignores, or handles outside Python, are left
    to the caller.
- `run.sh` is POSIX `sh`. The repository has no shell linter.
