# ADR 0153: System containerd capacity binding and fresh staging attempt

## Status

Accepted under the operator's new instruction, "ci failed try again". This
authorizes one new campaign after CI119, not automatic rearm of ADR 0152.

## Context

CI119 passed unit, static, source/export, native, all system scenarios, SBOM
and CodeQL jobs. Staging stopped before collection with
`sandbox_capacity_refused: unbound_backing_evidence` after SDK setup succeeded.
There is no staging test or coverage result for that attempt.

The failing job used Ubuntu 26.04 image 20261101.186.1 with Docker 29.4.2;
the passing system job used Ubuntu 24.04. The hosted log does not retain the
rejected path, so its exact value is unknown. Separately, source inspection
and a scoped regression reproduce a compatibility defect: the existing
containerd branch requires snapshots beneath DockerRootDir/containerd, but
Docker's documented default system containerd store is independent of that
directory. This supported-layout mismatch is the leading explanation for
CI119; hosted confirmation remains required.

## Decision

For the already corroborated overlayfs snapshotter branch, additionally accept
the exact default Linux system layout
`/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/<positive-decimal-id>/fs`
when DockerRootDir is exactly `/var/lib/docker`. Do not accept arbitrary roots,
rootless/custom layouts, sibling paths, other snapshotters, traversal, malformed
IDs or suffixes. Preserve the existing Docker-managed containerd and overlay2
paths. Engine driver, snapshotter status, null GraphDriver and container Storage
corroboration remain mandatory before binding.

Keep the closed probe schema, real statvfs measurement, 10 GiB/5% floors,
exclusive root-owned binding, owner token, full mount-line digest, timestamp
checks, fresh measurement and mount/token revalidation. No environment or CLI
path/capacity override, daemon reconfiguration, broad cleanup or dependency.

Use scoped unit and authenticated containerized protocol integration proof.
Integration may supply public fixture Engine metadata and mountinfo streams
while executing the real parser, subprocess, statvfs and exclusive writer.
Label that boundary accurately; it is not native qualification of a new daemon
layout. Hosted CI owns full population and native platform acceptance.

After final scoped proof, unchanged-debt static enforcement, privacy/hygiene
checks, independent `dynamic_default` review and an exact-commit report, permit
one ordinary staging synchronization for automatic CI120 attempt 1. Authenticate
CI119's actual application consumption before binding the grant. The new retry
request allocates only application start 31 after 30, with cumulative caps
31/31, fresh approval/nonce/reservation and CI119 replay rejection. Preserve all
historical rows and legacy bounds. No CI121, start 32 or automatic retry.

No complete local suites, candidate coverage, local SDK/application build,
workflow trigger/runner-image change, product CLI/MCP/schema change, new
dependency, main/tag/PR-state mutation or scientific/full-W5/production acceptance.

## References

- [Docker daemon data directories](https://docs.docker.com/engine/daemon/#daemon-data-directory)
- [Containerd snapshot layout](https://github.com/containerd/containerd/blob/main/docs/content-flow.md)
- [Exact Ubuntu 26.04 runner image](https://github.com/actions/runner-images/blob/ubuntu26/20261101.186/images/ubuntu/Ubuntu2604-Readme.md)
