"""Test-only suspension of ambient canonical Docker authorities.

The canonical runner installs one run-wide authority before pytest and leaves
it installed for the whole session. ``CanonicalDockerAuthority._patch`` captures
whatever callable currently sits on the SDK class, so an authority installed by
a mediation self-test nests on top of the run-wide guard and delegates its
authorized calls into it. That outer guard holds no ticket of its own and
refuses, which means a nested self-test has no subject: its authorized calls
fail and its refusals may be produced by the outer instance rather than by the
instance under test.

Suspending restores pristine SDK class state for the duration of a self-test
and then reinstalls exactly the same authority objects, which keeps their
journals, tickets and counters intact. This is a test-boundary correction only:
authorization semantics are untouched and tickets stay authority-instance-local.

Suspension mutates global class attributes, so it is sound only while the
process is single-threaded with respect to Docker mediation. The canonical gate
satisfies that: ``tools/run_tests.py`` requires ``--no-coverage`` for
``--jobs``, so the coverage-gated configuration never runs xdist workers.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from repomap_test_support.resource_docker_mediation import (
    CanonicalDockerAuthority,
    installed_authorities,
)


@contextmanager
def ambient_authorities_suspended() -> (
    Iterator[tuple[CanonicalDockerAuthority, ...]]
):
    """Yield with pristine SDK state, then reinstall the same authorities."""
    suspended = installed_authorities()
    if any(authority.busy for authority in suspended):
        raise RuntimeError(
            "cannot suspend a canonical Docker authority with work in flight"
        )
    for authority in reversed(suspended):
        authority.uninstall()
    try:
        yield suspended
    finally:
        for authority in suspended:
            authority.install()


__all__ = ["ambient_authorities_suspended"]
