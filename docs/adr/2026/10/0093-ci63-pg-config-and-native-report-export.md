# ADR 0093: CI pg_config custody and native preflight report transport

## Status

Accepted bounded correction design on 2026-10-24 after independent design
review and parent disposition under the maintainer's CI63 remediation request,
ADR0089 D6 and the approved D12-A admission plumbing. This replaces an
unpublished incorrect draft. Implementation evidence belongs to the phase
commit; hosted and runtime qualification remain separate.

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

## Decision

1. Preserve the shared native APT helper, its generic diversion refusal, SDK
   recipe, locks and product source. A CI-only stdlib helper may prove the
   known libpq-dev original when a canonical PATH wrapper is diverted. Plain
   and relocated matching PATH tools retain the shared attestation route.
2. The known-relocation route requires one coherent installed manager and
   canonical source/destination pair, one installed native libpq-dev/libpq5
   pair with equal package/source versions, original package ownership, and a
   regular executable non-symlink target. Missing, foreign, local, ambiguous
   or inconsistent evidence refuses before execution. Never execute the
   wrapper, fabricate package ownership or suppress diversion evidence.
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
   diagnostics and immutable-data assertions. Package transcript tests remain
   unit/adapter evidence; the hosted bootstrap supplies the real Linux proof.

## Scope and exclusions

Changes belong to CI custody/bootstrap, the existing outer transport adapter,
their scoped tests, additive strict inventory and phase documentation. No
dependency/lock, shared APT helper, SDK recipe, application context, schema,
public CLI/MCP contract, authority record, debt ceiling or coverage threshold
changes. No complete local suite, local SDK build, emulation or live action.

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
