# ADR 0139: CI107 Trixie header refresh and CI108 retry

## Status

Accepted parent-bounded remediation under the maintainer's current instruction
to repair failed CI107 and try again, plus ADR0105's explicit Debian stable-slim
maintenance authority. This records the parent's bounded interpretation, not
a numerical human approval or a new application-build ceiling.

## Date

2026-11-02

## Evidence and cause

CI107 attempt 1, run 41550728803, tested staging commit
`748cc31e221dd8d052b4c11034ffbf3404db32a2` through merge candidate
`7220a6bba9dfcb92713d2bae2a5fe44cec4f1773`. Eight jobs passed, including
complete unit and staging integration qualification. The system gate refused
its same-daemon native preflight before any application build.

The exact normalized candidate-manifest difference is one build prerequisite:
`linux-libc-dev`, architecture `all`, advanced from `6.12.113-1` to
`6.12.115-2`. Its previous SHA-256 was
`b2d475e01aaf0030c72bd3a0300d311f8be64aa9e82d82eae5da1a04f4010071`;
native APT observed
`235ba2cb2ea677f4acaf402b027e76d305342870f6d80d822d7ee9713e2f0ff5`.
An inert download from Debian's official security archive independently matches
that digest, version and architecture. All other normalized manifest fields
match. Strict comparison correctly rejected the stale prerequisite pin.

## Decision

Refresh that exact build-header row and its derived candidate-manifest digest.
Keep exact package, hash, source, trust, dynamic-linkage, payload, cleanup and
native-platform checks. Do not accept arbitrary APT drift or replace comparison
with a subset or version-only check. The runtime closure remains empty.

ADR0105's fresh metadata observation also requires index-only updates:

| Official derivative | Previous index | Current index |
| --- | --- | --- |
| PostgreSQL 16.15 Trixie | `1beaa3084eee2676f20a9cd9928f0bf2c5bf674f8e49f81017912183d377c61c` | `5db6dac2ef5dcff512f4f00a009c3c332b9f2f28f24277175bf3e4a3d02ef83a` |
| Python 3.12 slim Trixie | `aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159` | `b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30` |

The old and current indexes resolve to identical ARM64 and AMD64 child
manifests, configuration digests, creation records and rootfs layer identities.
Refresh the current release, Python-payload and hosted metadata references and
their tests together. Preserve those native child identities and payload
contracts. No image layer pull, image execution or local SDK/application build
is required for this metadata observation. The SDK recipe remains unchanged.

## Dependency and compatibility assessment

This is the existing Debian build-header prerequisite, not a new runtime or
Python dependency. Keeping the old row would repeatedly reject the current
signed Debian security repository; accepting arbitrary changes would discard
the exact-input contract. The selected route instead verifies the single
observed package and retains strict admission.

The package's Debian copyright metadata is retained with the inert inspection;
its Linux-kernel GPL-2 notices remain supplier notices. Headers are build-stage
prerequisites and are not copied into the assembled runtime. This change adds
no static Psycopg linkage, shared library, core package, lockfile, dependency
class, platform, production extension or infrastructure. Existing dynamic
Psycopg/libpq, runtime ABI, payload-license and build-residue checks remain.
Hosted native execution must still prove the assembled result.

## CI108 campaign and custody

Retain CI107's published reservation and nonce, and append its terminal
failed-preflight observation with zero application starts. Cumulative actual
application starts remain 23. The maximum remains 24, with at most one native
AMD64 start for CI108 attempt 1; this does not create start 25.

Create a fresh CI108 source contract, current context, authority digest, ledger
digest, nonce, reservation and grant. Reject CI107's old nonce/reservation and
all earlier denied identities. One reviewed fast-forward staging push may
synchronize existing draft PR23. No automatic retry, duplicate trigger,
manual dispatch, main promotion, tag, release or live activation follows.

Prior phase ledgers remain immutable snapshots. The successor ledger retains
the complete CI107 reservation and its no-start observation before appending
CI108. A successful reservation or scoped check is not hosted qualification.

## Verification and rollback

Run exact scoped unit and containerized integration owners with
`--no-coverage`, including current-header acceptance, stale/tampered-header
refusal before a build intent, current immutable index references, campaign
binding and old-reservation denial. Register any new test owner as clean
retained Python. Run static enforcement, public-export/privacy and diff checks
and obtain independent `dynamic_default` resulting-state review before commit
and publication. Complete local suites, local Python coverage and local
application/SDK builds remain unselected. CI108 owns complete qualification.

Rollback is a reviewed forward change. It preserves published history,
observations, exact package evidence and every spent or unspent reservation;
it cannot reuse CI107's nonce or silently accept a different package.

## Sources

- [Debian Trixie package metadata](https://packages.debian.org/trixie/linux-libc-dev)
- [Exact Debian security archive package](https://security.debian.org/debian-security/pool/updates/main/l/linux/linux-libc-dev_6.12.115-2_all.deb)
- [Debian stable slim responsibility](../10/0105-debian-stable-slim-maintenance-and-ci-responsibility.md)
