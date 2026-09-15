"""Process-wide canonical mediation for every Docker image build and pull.

The canonical runner executes pytest and the smoke driver in one process, so
every independently constructed ``docker.from_env()`` client shares the Docker
SDK classes patched here. Mediation is therefore installed on the stable class
API rather than on any one client or collection instance, which is what makes
an additional client incapable of bypassing it.

Three mechanisms are closed:

``docker-sdk-high``
    ``ImageCollection.build`` / ``ImageCollection.pull``.

``docker-sdk-low``
    ``BuildApiMixin.build`` plus every low-level image-acquisition route
    (``ImageApiMixin.pull`` / ``import_image`` / ``load_image``), reached by
    low-level ``client.api`` callers and by the high-level methods themselves.
    Re-entrancy is tracked so one logical operation yields one event.

``container-cli``
    ``subprocess.Popen`` argv carrying ``docker build``, ``docker pull``,
    ``docker buildx build``, ``docker compose build``, or ``compose --build``.

A refusal is journalled and raised before the real callable is invoked, so the
daemon is never asked to mutate.
"""

from __future__ import annotations

import os
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Sequence

from repomap_test_support.resource_docker_operations import (
    DockerAuthorityClass,
    DockerOperationJournal,
    DockerOperationKind,
    DockerOperationResult,
)


def install_canonical_authority(ledger: Any) -> "CanonicalDockerAuthority":
    """Install mediation before any Docker client exists in this process."""
    authority = CanonicalDockerAuthority(DockerOperationJournal.for_ledger(ledger))
    authority.install()
    return authority


# Discovery only. Authorization never consults this list; a ticket is matched
# solely against the authority instance that owns it.
_INSTALLED: list["CanonicalDockerAuthority"] = []


def installed_authorities() -> tuple["CanonicalDockerAuthority", ...]:
    """Authorities currently intercepting in this process, install order first."""
    return tuple(_INSTALLED)


CONTAINER_RUNTIMES = frozenset({"docker", "podman", "nerdctl"})
# The ``import_image_from_*`` helpers all delegate to ``import_image``.
LOW_LEVEL_PULL_ROUTES = ("pull", "import_image", "load_image")
_BUILD_VERBS = frozenset({"build"})
_PULL_VERBS = frozenset({"pull"})
# Command groups that precede the operation verb; ``builder build`` is a real
# build route, so omitting it here would classify a build as unrelated.
_COMMAND_GROUPS = frozenset({"buildx", "builder", "compose", "image"})
# Global options whose value is a separate argv token. Without this the value
# is read as the operation verb and ``docker -H host build`` escapes mediation.
_VALUE_OPTIONS = frozenset(
    {
        "-H",
        "--host",
        "-c",
        "--context",
        "-l",
        "--log-level",
        "--config",
        "--tlscacert",
        "--tlscert",
        "--tlskey",
    }
)


class DockerOperationRefused(RuntimeError):
    """A canonical Docker build or pull was rejected before daemon mutation."""

    def __init__(self, message: str, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class OperationTicket:
    event_id: str
    kind: DockerOperationKind
    authority: DockerAuthorityClass


def classify_container_cli(argv: Sequence[str]) -> DockerOperationKind | None:
    """Classify an argv as a build/pull container-CLI intent, or not one."""
    tokens = [str(item) for item in argv]
    if not tokens or os.path.basename(tokens[0]) not in CONTAINER_RUNTIMES:
        return None
    rest = tokens[1:]
    if any(token == "--build" for token in rest):
        return DockerOperationKind.DOCKER_BUILD
    verbs = []
    index = 0
    while index < len(rest):
        token = rest[index]
        if token in _VALUE_OPTIONS:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        verbs.append(token)
        index += 1
    if not verbs:
        return None
    head = 0
    while head < len(verbs) and verbs[head] in _COMMAND_GROUPS:
        head += 1
    if head >= len(verbs):
        return None
    verb = verbs[head]
    if verb in _BUILD_VERBS:
        return DockerOperationKind.DOCKER_BUILD
    if verb in _PULL_VERBS:
        return DockerOperationKind.DOCKER_PULL
    return None


class CanonicalDockerAuthority:
    """Single run-scoped owner of Docker build/pull authorization and evidence."""

    def __init__(self, journal: DockerOperationJournal) -> None:
        self.journal = journal
        self._state = threading.local()
        self._restore: list[tuple[Any, str, Any]] = []
        self._installed = False

    @property
    def installed(self) -> bool:
        """Whether interception is live, so a zero count has an observer."""
        return self._installed

    @property
    def busy(self) -> bool:
        """Whether this thread holds an open ticket or an in-flight operation."""
        return bool(self._tickets() or self._flight_kinds())

    # --- authorization -------------------------------------------------------

    @contextmanager
    def authorize(
        self,
        *,
        kind: DockerOperationKind,
        authority: DockerAuthorityClass,
        owner: str,
        mechanism: str,
        request: str,
    ) -> Iterator[OperationTicket]:
        """Open one authorized operation; the event exists before the call."""
        if authority is DockerAuthorityClass.UNMANAGED_FORBIDDEN:
            raise ValueError("forbidden authority cannot be pre-authorized")
        event_id = self.journal.begin(
            kind=kind,
            authority=authority,
            owner=owner,
            mechanism=mechanism,
            request=request,
        )
        ticket = OperationTicket(event_id, DockerOperationKind(kind), authority)
        self._tickets().append(ticket)
        try:
            yield ticket
        except BaseException:
            self.journal.complete(
                event_id,
                result=DockerOperationResult.FAILED,
                failure_category="authorized_operation_raised",
            )
            raise
        finally:
            self._tickets().remove(ticket)

    def complete(
        self,
        ticket: OperationTicket,
        *,
        image_ids: Sequence[str] = (),
        cleanup_disposition: str | None = None,
    ) -> None:
        self.journal.complete(
            ticket.event_id,
            result=DockerOperationResult.SUCCEEDED,
            image_ids=image_ids,
            cleanup_disposition=cleanup_disposition,
        )

    # --- interception --------------------------------------------------------

    def install(self) -> None:
        if self._installed:
            raise RuntimeError("canonical Docker authority is already installed")
        self._installed = True
        _INSTALLED.append(self)
        try:
            self._install_sdk()
            self._install_cli()
        except Exception:
            self.uninstall()
            raise

    def uninstall(self) -> None:
        for target, name, original in reversed(self._restore):
            setattr(target, name, original)
        self._restore.clear()
        self._installed = False
        # Tolerant and by identity: uninstall is reachable on a partially
        # installed instance from install()'s own error path.
        for index, entry in enumerate(_INSTALLED):
            if entry is self:
                del _INSTALLED[index]
                break

    def _install_sdk(self) -> None:
        from docker.api.build import BuildApiMixin
        from docker.api.image import ImageApiMixin
        from docker.models.images import ImageCollection

        self._patch(
            ImageCollection, "build", DockerOperationKind.DOCKER_BUILD, "docker-sdk-high"
        )
        self._patch(
            ImageCollection, "pull", DockerOperationKind.DOCKER_PULL, "docker-sdk-high"
        )
        self._patch(
            BuildApiMixin, "build", DockerOperationKind.DOCKER_BUILD, "docker-sdk-low"
        )
        for name in LOW_LEVEL_PULL_ROUTES:
            self._patch(
                ImageApiMixin, name, DockerOperationKind.DOCKER_PULL, "docker-sdk-low"
            )

    def _patch(
        self, target: Any, name: str, kind: DockerOperationKind, mechanism: str
    ) -> None:
        original = getattr(target, name)
        owner = f"{target.__name__}.{name}"

        def guarded(inner: Any, *args: Any, **kwargs: Any) -> Any:
            request = self._request_text(args, kwargs)
            if self._in_flight(kind):
                return original(inner, *args, **kwargs)
            ticket = self._matching_ticket(kind)
            if ticket is None:
                event_id = self.journal.refuse(
                    kind=kind,
                    owner=owner,
                    mechanism=mechanism,
                    request=request,
                    failure_category="unauthorized_canonical_operation",
                )
                raise DockerOperationRefused(
                    f"unmanaged Docker operation refused before daemon mutation: {owner}",
                    event_id,
                )
            with self._flight(kind):
                return original(inner, *args, **kwargs)

        guarded.__name__ = name
        setattr(target, name, guarded)
        self._restore.append((target, name, original))

    def _install_cli(self) -> None:
        original = subprocess.Popen.__init__

        def guarded_init(inner: Any, argv: Any, *args: Any, **kwargs: Any) -> Any:
            kind = classify_container_cli(_argv_tokens(argv))
            if kind is not None and self._matching_ticket(kind) is None:
                event_id = self.journal.refuse(
                    kind=kind,
                    owner="subprocess.Popen",
                    mechanism="container-cli",
                    request=" ".join(_argv_tokens(argv))[:512],
                    failure_category="unauthorized_canonical_operation",
                )
                raise DockerOperationRefused(
                    "unmanaged container-CLI Docker operation refused "
                    "before daemon mutation",
                    event_id,
                )
            return original(inner, argv, *args, **kwargs)

        setattr(subprocess.Popen, "__init__", guarded_init)
        self._restore.append((subprocess.Popen, "__init__", original))

    # --- thread-local bookkeeping -------------------------------------------

    def _tickets(self) -> list[OperationTicket]:
        tickets = getattr(self._state, "tickets", None)
        if tickets is None:
            tickets = []
            self._state.tickets = tickets
        return tickets

    def _matching_ticket(self, kind: DockerOperationKind) -> OperationTicket | None:
        for ticket in reversed(self._tickets()):
            if ticket.kind is kind or (
                kind is DockerOperationKind.DOCKER_BUILD
                and ticket.kind is DockerOperationKind.MANAGED_RUNTIME_LOGICAL_BUILD
            ):
                return ticket
        return None

    def _in_flight(self, kind: DockerOperationKind) -> bool:
        """Re-entrancy is per operation kind, so a nested pull is still seen."""
        return kind in self._flight_kinds()

    def _flight_kinds(self) -> list[DockerOperationKind]:
        kinds = getattr(self._state, "flight", None)
        if kinds is None:
            kinds = []
            self._state.flight = kinds
        return kinds

    @contextmanager
    def _flight(self, kind: DockerOperationKind) -> Iterator[None]:
        kinds = self._flight_kinds()
        kinds.append(kind)
        try:
            yield
        finally:
            kinds.remove(kind)

    @staticmethod
    def _request_text(args: Sequence[Any], kwargs: dict[str, Any]) -> str:
        for key in ("repository", "tag", "path", "fileobj", "dockerfile"):
            if key in kwargs:
                return f"{key}={kwargs[key]!r}"[:512]
        return repr(args[:2])[:512] if args else "<no-arguments>"


def _argv_tokens(argv: Any) -> list[str]:
    if isinstance(argv, (str, bytes, os.PathLike)):
        return [os.fsdecode(os.fspath(argv))]
    try:
        return [os.fsdecode(os.fspath(item)) for item in argv]
    except TypeError:
        return [str(item) for item in argv]


__all__ = [
    "CONTAINER_RUNTIMES",
    "LOW_LEVEL_PULL_ROUTES",
    "CanonicalDockerAuthority",
    "DockerOperationRefused",
    "OperationTicket",
    "classify_container_cli",
    "install_canonical_authority",
    "installed_authorities",
]
