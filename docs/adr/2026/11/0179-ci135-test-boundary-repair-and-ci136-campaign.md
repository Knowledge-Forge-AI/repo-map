# ADR 0179: CI135 test-boundary repair and one CI136 campaign

## Status

Accepted for bounded repair and conditional publication under the operator's
new request to remediate CI135 and try again. Source proof, current identity,
fresh binding and independent final review remain prerequisites. This does
not accept the whole candidate or grant an automatic successor.

## Date

2026-11-09

## Context

CI135 attempt 1 tested staging `2995b75ecfde511014588e7cd5f7f3cfe4006ba2`
over main `5ad00d162ad8a04430874275246a53227578c533`. It is
`EXECUTED_FAIL`: two unit assertions retained pre-ADR0177 sealing costs, and
two integration cases incorrectly expected capture-only sealing to perform
classification. Ordinary discovery still owns classification and its
retention refusal. Unit coverage met hard85/85, with branches21,854/25,152;
desired87 requires29 more branches at that denominator.

Measured integration also rejected a valid but unregistered coverage shard
from the native custody fixture's `refresh_worker`. That fixture copied the
parent's ambient coverage environment while bypassing the registered portable
adapter. Its second-interrupt case allowed the child to exit normally and
flush that shard. M measurement is incomplete; no integration percentage is
accepted. The abrupt leg was blocked. Static, security, CodeQL, native D12,
native Rust and all system scenarios passed for the exact candidate.

Authenticated CI135 consumption adds one application start, one logical
native AMD Rust qualifier invocation and two wheel transfers. Cumulative
consumption is45/15/34. These are spent identities. The native qualifier's
internal command counter is separate from its one invocation allocation.

## Decision

Repair tests and their launch boundary without changing product semantics:

- Assert the accepted two-stream collision comparison and4S+1 sealing lower
  bound. Preserve object integrity, descriptor and cleanup assertions.
- Exercise classification-retention refusal through ordinary discovery, and
  prove that capture-only sealing preserves the accepted store and performs
  no discarded classification reads.
- Use the existing authoritative child-environment helper and admitted
  `unmeasured` family for the direct native refresh-worker fixture. Its parent
  test remains ordinary M. Preserve the canonical launcher, genuine Popen,
  selected reaper, primary exception and custody assertions. Ambient variables
  must not accidentally activate child measurement. Production refresh
  already constructs an explicit worker environment. Registered portable
  children retain strict registration and shard acceptance.
- Add useful observable stream/store boundary contracts within the affected
  maintained modules where existing unit evidence has gaps. No test is added
  solely to execute a line; no coverage improvement is claimed without hosted
  measurement.

After scoped unit and containerized integration proof with `--no-coverage`,
current static/privacy/hygiene checks and independent review, prepare one
normal CI136 attempt1 through one staging push. The minimum inferred cumulative
caps are46 application starts,16 logical native AMD Rust qualifier invocations
and36 wheel transfers. These express this newly requested normal campaign;
they are not an independent numeric operator selection. Reviews must challenge
the inference and binding against actual45/15/34 consumption.

## Binding and qualification

Preserve all inherited ledger roots and list prefixes. Append authenticated
CI135 consumption and one fresh CI136 reservation; never rearm a spent nonce
or reservation. Derive the current application context and exact AST/import
closure from the final source. Use an acyclic digest order, explicitly
disposition the final manifest delta, and refuse predecessor and future tuples.
Generate an exact local report for the source commit before publication.

The existing draft staging-to-main PR supplies automatic public feedback. No
manual duplicate dispatch or rerun is selected. Local checks establish scoped
correctness only. Hard unit85/85 and integration80/80, the full denominator and
desired87/82 margins remain unchanged. Hosted CI must establish valid M
measurement, both legs and the complete candidate result.

## Boundaries and rollback

No runtime dependency, package/lock, image, runner-policy class, M/A role,
coverage denominator/floor/exclusion, suppression, quality debt, schema, CLI
or MCP contract change. No local application/SDK build, image pull, native
parser qualification, complete local suite or whole-population coverage.
There is no CI137, start47, automatic retry, second push, main/tag/release,
history rewrite, installed or live mutation. W6/W7 completion remains separate.

Before publication, retain proof and revert only owned uncommitted changes if
needed. After publication use a separately authorized forward repair. Never
alter consumption evidence to make a spent slot appear available.
