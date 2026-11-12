# ADR 0183: Host-only sandbox ownership attestation

## Status

Operator-approved bounded runner policy, 2026-11-12.
Implementation, scoped proof, independent review and native acceptance remain
separate. Phase: `REPOMAP-CLOE-PUBLIC-TEXT1`.

## Context

An external native calibration controller previously identified its canonical
sandbox through agreeing Docker log/wait descendants. On macOS, a verified
live descendant's command-line read can raise `AccessDenied`. Ignoring that
error, supplying invented command lines or inferring ownership from global
Docker changes would not establish affirmative ownership.

The canonical host runner already receives the exact container ID returned by
its own creation operation and installs its owner marker. It can report those
facts without a command-line inspection of an unrelated descendant.

## Decision

Add an optional, explicit host-runner attestation channel. The parent supplies
two dedicated anonymous-pipe endpoints: one control reader and one receipt
writer. The control frame binds a fresh challenge, the parent's known child
PID/birth identity, source identity, source root, expected exact SDK and canonical arguments.
The host checks its actual PID, source root and arguments. The parent's fresh
process observation independently verifies birth identity; the host does not
claim that echoing the supplied birth value is an independent birth observation.

Each frame is at most 4 KiB and has a closed versioned schema. Reject partial
configuration, standard descriptors, non-pipes, wrong access modes, shared
pipe identity, malformed values, duplicate JSON keys, trailing frames and
unexpected fields. The parent completes and closes the control frame before
releasing the runner; an open peer refuses without blocking. Endpoints become
non-inheritable before any Docker child, including on configuration refusal.
The control reader closes after consuming its frame. The receipt writer closes
after one write, including failure. Neither endpoint nor challenge is forwarded
to the inner sandbox or model. Ordinary runs do not create a channel.

Only after actual creation returns an exact ID and owner-marker installation
succeeds may the host emit one receipt. Bind the challenge, actual PID, supplied
birth identity, source identity, actual ID/image, source root, canonical
arguments and SHA-256 commitment of the actual installed marker. Do not log the
challenge, marker or private receipt.

Before model reservation, the parent verifies its launched PID and fresh birth
identity, exact source snapshot/arguments, challenge and receipt. Independently
inspect the exact container's image, labels, running state, command, selector,
pgvector profile and sole read-only source mount. Read the actual owner marker
from that container and check its commitment. No proposed/pre-existing CID or
global-container lookup is an ownership witness.

The opt-in host path reads only the existing SDK cache, verifies its recipe and
expected image identity, and refuses a miss or mismatch without entering the
build/pull/prune path. Default canonical SDK management stays unchanged.

The private controller selects this proof type explicitly. Its lifetime
observer records identities and ancestry without reading descendant argv; it
does not manufacture `ProcessObservation` objects or silently omit a live
process. The command-tree proof remains a separate unchanged alternative, with
no automatic fallback after denial.

Admission requires the original root to be live. Completion after verified
components and canonical exit zero permits an absent/reaped root, but requires
all observed process identities closed, exact owned-container removal, actual
raw reports, inner cleanup and conserved host resources. Unexpected early root
loss, reused admission identity, inaccessible lifetime metadata, nonzero exit,
missing reports or uncertain cleanup remain fatal. Reaped-root permission
requires the actual parent-owned process exit to be integer zero; arming a
completion prerequisite alone never permits early root loss.

Process sampling proves closure only for identities actually observed. It does
not establish exhaustive coverage of descendants born and reparented between
samples. Retain this limitation; exact container removal and Docker resource
conservation are separate evidence, not a claim of exhaustive process closure.

## Scope and limits

No dependency, package metadata, lockfile, Dockerfile, APT helper, SDK recipe,
production CLI/MCP, graph, coverage floor or debt ceiling changes. The opt-in
host hook must preserve the existing cached SDK recipe; otherwise stop without
replacement build or acquisition.

The private operator allocation permits one exact pgvector attribution
diagnostic after source/review PASS. Only after that PASS and final-controller
review may one successor study run. Historical failed/held studies and source
receipts remain immutable. The conditional hosted campaign remains contingent
on actual native and cleanup proof; this ADR itself grants no execution budget.

## Required evidence and rollback

Scoped unit owners prove real pipe framing, descriptor custody, challenge and
identity mismatch refusals, one-write behavior and no publication before marker
installation. The selected containerized integration owner checks that host
channel configuration is absent inside the authenticated sandbox. The external
diagnostic proves actual PID/CID/source/SDK/profile/selector attribution and
cleanup. Independent review precedes that diagnostic and the native study.

Rollback removes the opt-in hook and private proof selection; existing canonical
runs retain their prior behavior. A failed diagnostic is retained and stops the
phase. Host permissions, elevated execution, ignored inspection errors and
automatic retries are rejected alternatives.
