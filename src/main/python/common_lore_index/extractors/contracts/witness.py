"""Internal observation-batch and parent-witness contract.

The dependency-free foundation has no native runtime observer, so it has no
positive admission path. :class:`ParentWitness` cannot be instantiated,
copied or unpickled, and :func:`refuse_capability_admission` refuses every
input: receipts, digests, nonces, booleans, callbacks, helper self-claims and
forged objects alike. A future reviewed controller must replace this module's
refusal with recomputation of every binding in :data:`REQUIRED_BINDINGS` from
actual observations; nothing here can be extended into that by data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import NoReturn

from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.observations.raw import RawObservation

BATCH_ORIGINS = frozenset({"legacy-discovery", "offline-raw"})
NATIVE_OBSERVER_UNAVAILABLE = "native_observer_unavailable"
REQUIRED_BINDINGS = (
    "admitted_profile",
    "selected_source_bytes",
    "active_run_nonce",
    "clean_exit",
    "strict_protocol",
    "input_matching_ranges",
    "resource_outcome",
    "proven_cleanup",
)
MAX_BATCH_OBSERVATIONS = 1_000_000


class ParentWitness:
    """Live parent verifier state. Not constructible in this foundation."""

    __slots__ = ()

    def __new__(cls, *_args: object, **_kwargs: object) -> ParentWitness:
        raise ContractError(NATIVE_OBSERVER_UNAVAILABLE)

    def __reduce__(self) -> NoReturn:
        raise ContractError(NATIVE_OBSERVER_UNAVAILABLE)

    def __copy__(self) -> NoReturn:
        raise ContractError(NATIVE_OBSERVER_UNAVAILABLE)

    def __deepcopy__(self, _memo: object) -> NoReturn:
        raise ContractError(NATIVE_OBSERVER_UNAVAILABLE)


@dataclass(frozen=True)
class CapabilityRefusal:
    """The only admission outcome this foundation can produce."""

    code: str
    missing_bindings: tuple[str, ...]


def refuse_capability_admission(_evidence: object = None) -> CapabilityRefusal:
    """Refuse any capability claim; the evidence is deliberately not consulted.

    No serialized record, helper self-claim, callback, caller boolean, digest,
    nonce, receipt or constructed token can produce admission, because no
    native observer exists to supply live parent verification state.
    """

    return CapabilityRefusal(NATIVE_OBSERVER_UNAVAILABLE, REQUIRED_BINDINGS)


@dataclass(frozen=True)
class ObservationBatch:
    """Raw schema-1 observations carried with their origin and no witness.

    The batch preserves observations byte-for-byte at the object level: it
    neither adds raw fields nor rewrites metadata. Its origin vocabulary has
    no parent-witnessed member, so a batch cannot represent admission.
    """

    origin: str
    observations: tuple[RawObservation, ...]

    def __post_init__(self) -> None:
        if type(self.origin) is not str or self.origin not in BATCH_ORIGINS:
            raise ContractError("invalid_batch_origin")
        items = self.observations
        if type(items) not in (list, tuple) or len(items) > MAX_BATCH_OBSERVATIONS:
            raise ContractError("invalid_batch")
        if any(type(item) is not RawObservation for item in items):
            raise ContractError("invalid_batch")
        object.__setattr__(self, "observations", tuple(items))

    @classmethod
    def from_observations(
        cls, origin: str, observations: Sequence[RawObservation]
    ) -> ObservationBatch:
        if type(observations) not in (list, tuple) or len(observations) > MAX_BATCH_OBSERVATIONS:
            raise ContractError("invalid_batch")
        return cls(origin=origin, observations=tuple(observations))

    def capability_admission(self) -> CapabilityRefusal:
        """Return the unconditional refusal for any capability claim in the batch."""

        return refuse_capability_admission(self)
