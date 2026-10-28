# ADR 0106: Audit-compatible cleanup of owned temporary directories

## Status

Accepted implementation repair under the current CI85 remediation request.
This preserves ADR0060 authority. It grants no additional application build.

## Date

2026-10-28

## Context

CI85 built the current Trixie application and passed its assembly/runtime
inventory assessment. The coordinator worker then returned
`unsupported_capability`. A scoped native Python 3.12.16 reproduction using
the pinned supplier, copied product package and packaged Go helper reproduced
the refusal. Test-only observation identified `os.remove` from CPython's
descriptor-based `shutil.rmtree` cleanup, including its permission callback.
The equivalent mixed-language source/SDK tests passed under Python 3.13.

ADR0060 explicitly refuses descriptor-relative mutation. The worker already
uses a separate no-follow, identity-checked path cleanup for its materialized
workspace. Semantic scratch directories still used `TemporaryDirectory`,
whose cleanup implementation differs across supported interpreters.

## Decision

Extract the existing materialized-directory identity and path cleanup into
one dependency-free internal owner. Re-export the previous coordinator names.
Use that same cleanup in an internal owned temporary-directory context for
semantic capture, external row sorting and bundle scratch directories.

The owner records the created directory's device, inode and owner, validates
that identity before and after recursive cleanup, and accepts only regular
single-link files and real directories. It refuses symlinks, hard links,
unexpected nodes and root substitution. Its finalizer and explicit/context
cleanup share the same checks. Cleanup errors remain failures.

The audit guard stays byte-for-byte unchanged: no descriptor mutation
exception, new writable/readable root, import, command or network authority.
This changes internal cleanup mechanics, without changing public graph,
storage, CLI/MCP or receipt contracts. No dependency or runner policy changes.

## Required evidence

- Exact fixture repair tests retain the historical approval bytes and native
  observations rather than extending old evidence to refreshed pins.
- Owned temporary-directory unit tests cover normal/exceptional/idempotent
  cleanup, finalization, readonly files, nested directories, foreign root
  substitution, symlinks and hard links.
- The mixed worker on the actual pinned native Python supplier must pass
  with the real audit guard and exact resource cleanup, without an
  application/SDK build or dependency-runtime materialization.
- Scoped callers, guard refusals and canonical static retention enforcement
  remain required. Complete local suites and coverage remain unselected.

## Rejected alternatives

- Widening descriptor permissions contradicts ADR0060 and is unnecessary.
- Ignoring cleanup errors or leaving temporary data would conceal failures.
- Retrying the unchanged image would consume another build without repair.
- Patching Debian or CPython is outside RepoMap's responsibility.

## Hosted boundary

CI85 consumed the fifth native AMD start. ADR0104's five-start ceiling and
no-sixth/no-retry rule remain in force. A new exact hosted build allocation
requires an operator decision after the corrected source and proof are ready.
