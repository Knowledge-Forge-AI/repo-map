# Containerized Smoke Test Design

## Status

TEST-SMOKE0 defined the original smoke boundary and TEST-SMOKE1 first
implemented it. TEST-RUNNER-SAFETY1 first replaced the ordinary smoke build
path with a manually supplied exact image. ADR 0052 and
TEST-IMAGE-LIFECYCLE1 replace that preparation boundary with one
repository-owned dependency-runtime cache manager. REPOMAP-CI2A-R1 replaces
the import/help-only workloads with a bounded end-to-end RepoMap lifecycle.

`tools/run_tests.py --suite smoke` runs only the pass/fail smoke stage.
`--suite staging` runs smoke first and integration second, fail-fast. Both use
the managed runtime cache by default.

## Purpose And Scope

The smoke stage is a small end-to-end runtime tripwire. It proves the current
checkout can start exact run-owned PostgreSQL/runtime resources, initialize and
refresh two tiny fixture graphs, perform product-facing reads, execute a
backup-first destructive operation on one graph database, inspect the resulting
dump, prove the target is gone and the control graph coherent, and clean all
run-owned resources. It is not a performance benchmark, deployment matrix,
private graph refresh, or package-install path.

## Canonical Commands

The canonical path ensures or reuses the host- and architecture-specific
managed cache:

```sh
python3 tools/run_tests.py --suite smoke

python3 tools/run_tests.py \
  --suite staging \
  --hygiene-profile heavy \
  --declared-complete-gates 1 \
  --pg-container-port 55433
```

The manager requires a configured exact Python repository digest, reuses it
locally, or pulls only that digest once on a miss under its checkout-scoped
single-flight lock.
It verifies the Engine RepoDigests, exact image ID, and Docker-server
architecture before extracting normalized runtime dependencies from
`pyproject.toml` and materializing a dependency-only image when its fingerprint
is absent. Materialization uses one label-free, exactly ledgered temporary
container with a private persisted recovery claim and one final commit whose
labels are exactly the five durable cache labels; it does not invoke the Docker image builder or leave
runtime-build intermediate Engine images. It does not resolve mutable tags,
search a registry, choose a fallback, copy RepoMap source, or install the
RepoMap package. Obtain an exact Docker Engine image configuration ID for an
optional diagnostic override with:

```sh
docker image inspect --format '{{.Id}}' <locally-prepared-image>
```

Do not substitute a mutable tag, repository digest, or multi-architecture
manifest digest for an override. An override grants no image cleanup or
deployment ownership.

## Ordinary Smoke Invariants

The smoke stage:

- consumes the manager's exact `sha256:` Engine ID, or validates an override
  with exactly 64 lowercase hexadecimal characters;
- uses local `images.get(reference)` and requires `image.id` equality;
- delegates all image inventory, materialization, reuse, validation, and GC to
  `TestImageManager`;
- permits only the manager's exact configured RepoDigest pull-on-miss and never
  reaches a mutable, alternative, fallback, unmanaged, or broad-prune path;
- never selects or removes deployment, legacy-unclassified, unlabelled,
  wrong-repository, or mixed-tag images;
- uses Docker SDK `containers.create()`, never `containers.run()` because the
  latter may pull after `ImageNotFound`;
- mounts the repository root for the current checkout read-only at
  `/workspace`;
- sets the exact working directory and
  `PYTHONPATH=/workspace/src/main/python` so mounted candidate source wins over
  source installed in the image;
- uses owner-private run-root configuration and backup paths;
- creates one exact current-run network only for runtime-to-Postgres access;
- publishes PostgreSQL only on the selected loopback port;
- uses tmpfs for PostgreSQL data and no Docker volume;
- does not use auto-remove as deletion authority; and
- records one total monotonic budget with a configured ceiling of 540 seconds.

Docker is the only qualified ordinary smoke runtime. Podman compatibility is
deferred until it can provide equivalent identity, ledger, cleanup, and
baseline evidence. The integration Postgres runtime selection is unchanged,
apart from the required `--pull=never` launch guard.

## Current-Run Ownership

The allocating `TestResourceRun` selected by `tools/run_tests.py` is passed
explicitly through the suite dispatcher into smoke. An inherited run root has
no allocating owner object, so smoke and `staging` refuse before suite work rather
than opening an unrelated identity.

Before creating a smoke container, the producer captures the exact existing
container baseline. Each creation then:

1. applies centralized project, phase, run, role, and transient-retention
   labels;
2. calls `containers.create()` and takes the returned full container ID;
3. inspects that exact ID and requires identity and label equality;
4. registers it in the allocating run's private `ResourceLedger`; and
5. starts and waits for only that registered container.

Ordinary cleanup uses `DockerResourceOwner`, which requires Engine observation,
central labels, the private ledger, and baseline exclusion to agree. It removes
the exact ID, proves final absence, records the cleanup result, and verifies the
pre-existing container baseline after the workload.

If ledger registration itself fails after a successful create, ordinary
ledger-authorized cleanup is not yet available. The creation transaction has
one bounded rollback authority: remove only the exact ID returned by that
create call, inspect it to prove absence, and fail the run. Rollback failure is
also fatal. Names, prefixes, label searches, broad cleanup, and guessed
identities are never rollback authority.

## Workloads And Environment

The exact runtime image imports the mounted current checkout and connects to
the exact smoke PostgreSQL container on the run-owned network. Product CLI
commands then create two databases from source migrations, initialize the
coordinator control database, refresh two small repository fixtures, and read
their summaries/files. A backup-first database drop destroys only the target;
subsequent product reads prove target absence and control coherence.
`backup-inspect` must verify the checksum, manifest, and PostgreSQL dump
contents, and the dump must be unique and non-empty under the run-owned home.

The current repository mount is read-only. Smoke does not inspect `.git`, test
reports, developer configuration, credentials, private graphs, or live
databases. Cleanup removes the exact run-owned containers, network, home,
fixture copies, and backup staging paths even after failure. Every command gets
only the remaining total budget; cleanup uses a bounded reserved tail.

## Runner And Coverage Semantics

`--suite smoke` is pass/fail only and not coverage-tracked. `--suite staging`
runs smoke first and stops before integration if smoke fails. Integration then
owns its independent 80/80 statement and branch gate. Unit is not rerun and no
combined coverage result exists.

Canonical `staging` permits at most one manager-owned dependency-runtime
materialization and its deterministic cache GC. It has no product/build-profile
or unmanaged image build/removal path. Its integration
Postgres launch uses `--pull=never`, overrides the image-declared data volume
with tmpfs, records the exact returned container ID under centralized run
labels, omits `--rm`, and removes only the ledger-owned ID with volume deletion
disabled. A missing local Postgres image fails instead of authorizing a pull.
The canonical runner also snapshots exact image and volume IDs before
container-capable work and requires zero new unattributed or current-run
residual IDs after pytest and at terminal close.

## Safety Boundaries

Smoke must not read private repositories, operator graph configuration,
developer credentials, home-directory state, or live databases. It must not
acquire source, install packages, contact an external network, expose a
non-loopback port, persist volumes, or publish matched/private payloads.

Failures in exact image admission, Docker connectivity, dependency import,
runtime workload, ownership registration, exact cleanup, final absence, or
baseline restoration are hard failures. Warnings never replace the final
pass/fail result.

Image builds and image acquisitions are mediated run-wide, not only on the
smoke side: the enforced surfaces, the honest scope limits of that closure, and
the fail-closed run-wide boundary are recorded in
`docs/testing/managed-docker-mediation-boundary.md`.

The lifecycle single-flight lock is derived from the project root, so
serialization is checkout-scoped. Concurrent smoke runs from two different
checkouts against one Docker daemon do not serialize with each other.

## Deferred Work

Separate accepted phases may add image-provisioning procedure, per-architecture
prepared-image catalogs, Podman equivalence, runtime matrices, CI integration,
or richer health checks. None is implied by ordinary smoke qualification.
