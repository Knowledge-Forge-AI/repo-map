# RepoMap Container Lifecycle Requirements

## Purpose And Scope

This document records the read-only SKILL-REVAMP2 audit and the requirements
for distinguishable RepoMap clusters and safe image retention. It describes
current behavior and future source/test work; it does not claim that lifecycle
labels, stable image identity, or cleanup commands are implemented.

No pre-existing image, container, network, volume, builder, or cache was
deleted or modified during the audit.

## Current Ownership Map

The current local-runtime path is:

```text
repomap-kg local up
  -> CLI local dispatch
  -> runtime.local.up_local_runtime
  -> runtime.plan.build_local_runtime_plan
  -> LocalRuntimeIdentity.from_home
  -> runtime.commands.render_local_runtime_files
     -> runtime.compose.render_compose_yaml
     -> runtime.commands.render_server_dockerfile
  -> docker compose --project-name repomap-<home-hash> up -d --build
```

Closeout and readback are:

```text
repomap-kg local down
  -> docker compose --project-name repomap-<home-hash> down

repomap-kg local status --check-containers
  -> inspect the expected container names and RepoMap runtime labels
```

`local down` does not pass `--rmi` or `--volumes`. It removes the Compose
containers and networks selected by the project, but retains the application
image and named volumes.

## Current Identity And Build Behavior

- Compose has no top-level `name`; the command supplies
  `--project-name repomap-<home-hash>`.
- `<home-hash>` is the first twelve hexadecimal characters of a digest of the
  resolved `REPOMAP_HOME` path.
- The generated Compose file explicitly names the built deployment image
  `repomap-runtime:<home-hash>`. It does not use `latest`, the legacy
  `repomap-runtime-<home-hash>:latest` shape, or Compose's default
  `<project>-<service>` tag.
- The same home-derived token identifies both the Compose instance and the
  deployment tag. Existing images in the old hyphen-plus-`latest` shape remain
  legacy-unclassified until an operator explicitly migrates them.
- Compose build records project/service metadata on the image. Because the
  project identity changes, observed runtime tags represent distinct image
  IDs rather than multiple tags for one shared ID.
- The Dockerfile records `io.repomap.release.*` component-version labels.
  Generated service, network, and volume labels record
  `org.repomap.runtime=true`, `org.repomap.home_hash`, and
  `org.repomap.component`.
- Images do not currently carry `org.repomap.managed`, cluster role,
  retention, or source-revision labels. Containers, networks, and volumes do
  not carry cluster role or retention labels.
- `local status` exposes bounded runtime identity and expected container
  status, but it does not classify a cluster as deployment, development, or
  test.

The generated cluster uses a bind-mounted `postgres-data` directory plus
Compose-managed `coordinator-state` and `admin-state` named volumes. Changing
the Compose project name selects a different named-volume and network resource
set even when the configured home is otherwise unchanged.

## Test And Smoke Closeout Behavior

- The standard integration Postgres harness uses a fixed upstream image,
  starts an exactly named `--rm` container with positive test labels, and
  removes that exact container and its anonymous volumes during teardown. It
  does not build a RepoMap application image.
- Runtime integration/campaign paths that call `local up` with disposable
  homes inherit the home-derived project and image identities. Their
  `local down` closeout does not remove the exact application image or the
  named `coordinator-state` and `admin-state` volumes.
- The container smoke suite asks the repository-owned test-image manager to
  ensure or reuse a dependency-only `repomap-test-runtime:*` cache, then runs
  current source from a read-only mount. The manager retains at most two
  eligible caches and removes only exact positively labelled stale IDs.
- Ephemeral build-test images use `repomap-test-ephemeral:<run-id>-<ordinal>`
  and are removed only by their current-run ledgered exact IDs. Test-image GC
  never selects deployment or legacy-unclassified images and never prunes.
- Test-image inventory, build, and GC serialize under one owner-only lock at
  `.scratch/locks/repomap-test-images-<uid>.lock` beneath the project root —
  repository-owned ignored scratch, not `/tmp`. The lock deliberately does not
  follow the runner's per-run `TMPDIR`.
- That serialization is checkout-scoped, not host-wide. Runner processes
  launched against the same checkout serialize with each other; two checkouts
  sharing one Docker daemon hold separate locks and do not. Operators
  scheduling concurrent runs across checkouts must not assume daemon-wide
  serialization. A host-stable coordinator is deferred, not decided.
- Image builds and acquisitions inside a runner process are mediated by one
  canonical authority; see `docs/testing/managed-docker-mediation-boundary.md`
  for the enforced surfaces and the honest limits of that closure.

## Bounded Engine Observation

The positive RepoMap-only inventory observed on 2026-07-29 found:

- 42 `repomap-runtime-<home-hash>:latest` tags and 42 distinct image IDs;
- 40 unreferenced runtime images and 2 images referenced by running
  containers;
- one stopped container also referencing one of those active images, but no
  old image referenced only by a stopped container;
- 42 distinct Compose project labels across the 42 runtime images;
- 1,578 labeled runtime volume project identities, with 3,152 of 3,156
  labeled named volumes belonging to projects with no current labeled
  container;
- no role or retention labels on the selected runtime images, volumes, or
  networks.

The selected images' virtual sizes sum to about 6.84 GiB. That sum is not
unique disk consumption because images can share layers. Engine-wide aggregate
BuildKit cache was about 63.74 GiB, about 60.82 GiB reclaimable. This proves
that build cache is a separately material engine category, but the current
labels do not support positive RepoMap-only cache attribution; no RepoMap
cache-deletion claim is therefore made.

## Accumulation Classification

| Question | Decision |
|---|---|
| Does Compose build without an explicit image name? | No. The generated Compose file sets `image: repomap-runtime:<home-hash>` and a `build` section. |
| Are images tagged by default project-service identity? | No. The explicit tag is home-derived, although Compose adds project/service labels to the image. |
| Do unique test/home project identities create unique tags? | Yes. Project and image tag reuse the same home-derived token. |
| Do multiple runtime tags alias one image ID? | No in the observed inventory: 42 tags mapped to 42 IDs. |
| Are old images held by stopped containers? | No in the observed old-image set. Forty were unreferenced; the stopped reference shared an active image. |
| Is reliable ownership/retention labeling present? | Partial ownership only. Release and Compose labels identify image provenance, but role, retention, managed-owner, and source-revision labels are absent. |
| Does a closeout path remove its built image? | The smoke suite does; `local down` and runtime integration/campaign closeout do not. |
| Is BuildKit cache separately material? | Yes engine-wide, but RepoMap-only attribution is open because cache ownership labels are unavailable. |

## Current Safe Interim Procedure

Until reliable image lifecycle labels and a repository-owned cleanup command
exist:

1. An agent may remove only an exact image reference or ID created by the
   current authorized task.
2. Before removal, prove that no container references that exact image.
3. Do not use global prune, negative-label selection, name heuristics, or
   deletion of pre-existing RepoMap-like images.
4. Treat the long-lived deployment cluster, its images, and its persistent
   data resources as protected unless the operator explicitly authorizes
   lifecycle work.

The same exact-ownership rule applies to disposable containers, networks, and
volumes created by the current task. It does not authorize cleanup of the
pre-existing inventory above.

## Target Cluster Identity Contract

Every RepoMap-managed container, network, and volume should carry:

```text
org.repomap.managed=true
org.repomap.cluster.role=deployment|development|test
org.repomap.cluster.id=<public-safe-id>
org.repomap.retention=retain|ephemeral
org.repomap.source.revision=<commit-or-build-id>
```

Retain `org.repomap.runtime=true`, `org.repomap.home_hash`, and
`org.repomap.component` through a compatibility interval. Do not use the
reserved `com.docker.compose.*` namespace for RepoMap labels.

Project-name policy:

- deployment: preserve the existing stable project identity unless an
  explicit migration plan moves its containers, networks, and named volumes;
- development: `repomap-dev[-<bounded-token>]`;
- test: `repomap-test-<short-run-id>`.

`local status` should report the Compose project name, cluster role, public-safe
cluster ID, retention class, image reference/revision, and compatibility
identity. Status must resolve ownership from positive labels and must not infer
role from a private path.

The existing deployment project must not be casually renamed. A rename can
select new isolated networks and named volumes, causing an apparently empty
cluster. Any migration requires an inventory, backup, old-to-new resource map,
validated data attachment, rollback, and explicit operator authorization.

## Target Image Identity Contract

Image identity must be independent from Compose instance identity:

```text
stable image repository
  + source revision or content identity
  + multiple Compose projects referencing the same image
```

For example, a build owner may publish
`repomap/runtime:<source-revision>` locally, and deployment, development, and
test Compose instances may all reference that exact image ID. The per-instance
Compose files should not rebuild the image with project-specific metadata.
Either omit `build` from instance Compose after a repository-owned build step,
or use one stable build owner whose image configuration does not vary by
cluster.

Shared images should carry:

```text
org.repomap.managed=true
org.repomap.source.revision=<commit-or-build-id>
org.repomap.retention=retain|ephemeral
```

Do not put one cluster role or cluster ID on an image shared across roles;
those labels belong to instance resources. A new source revision creates a new
image identity, and cluster rollout must explicitly select it. Rebuilding the
same revision should either reproduce the same content identity or publish a
new explicit build identity rather than silently replacing deployment
evidence.

## Target Cleanup Contract

A future repository-owned cleanup command must:

- be dry-run by default;
- select only `org.repomap.managed=true`;
- filter by explicit role and retention labels;
- require a configurable minimum age;
- list exact candidate image IDs with bounded output;
- keep every image referenced by any running or stopped container;
- keep the active deployment image and every `retention=retain` image;
- keep a configured bounded number of recent development images;
- select only unreferenced, sufficiently old, ephemeral test images by
  default;
- require explicit `--yes` or equivalent confirmation for deletion;
- report exact deleted IDs, failures, and measured reclaimed space;
- never invoke global prune.

Build cache requires a separate positively attributable design. Do not include
unlabeled cache records in normal RepoMap cleanup merely because engine-wide
cache is large.

Named-volume cleanup must be a separate explicit operation with the same
positive ownership, role, retention, age, active-cluster protection, dry-run,
confirmation, and bounded-report requirements. It must never treat an absent
container as sufficient proof that deployment data is disposable.

## Required Source And Test Phases

The target requires a combination of owners:

1. Generated Compose/config source: role-aware project identity, compatible
   labels on containers/networks/volumes, and expanded status readback.
2. Image-build source: stable revision/content image identity decoupled from
   instance Compose identity and image lifecycle labels.
3. Local CLI source: positive-label inventory and dry-run cleanup with exact
   protections and confirmation.
4. Test harness: exact closeout of task-created runtime images and ephemeral
   named volumes, plus failure-path cleanup.
5. Migration phase: protect and, only when authorized, migrate the existing
   deployment project and persistent resources.

Tests must cover label parity, role/name validation, stable image reuse across
multiple project instances, stopped-container protection, deployment
protection, age/retention filtering, dry-run output, confirmation, partial
failure, and exact cleanup ownership.

## Rejected Unsafe Alternatives

- Renaming the existing deployment project without a migration plan.
- Deriving disposable status from a path, name substring, or absent label.
- Keeping image tags coupled to unique test Compose project names.
- Using `docker system prune` or unfiltered image/volume/network prune.
- Force-removing an image referenced by any container.
- Treating UI virtual-size totals as unique reclaimed disk space.
- Deleting all volumes for inactive project names.
- Treating engine-wide BuildKit cache as RepoMap-owned without positive
  attribution.
