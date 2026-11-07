"""Load the fixed guest source closure as text and bind its identity.

The guest modules are RepoMap package text read through
``importlib.resources``; they are passed to the container as one argument or
injected as one file and never imported here. Nothing about them is selected
from ``PATH``, the environment or serialized data.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib import resources

from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot.component_lock import digest_json

GUEST_PACKAGE = "common_lore_index.extractors.rust_pilot.guest"
GUEST_FILES = ("setup_writer.py", "install_readback.py", "runtime_probe.py", "parse_helper.py",
               "containment_probes.py")
MAX_GUEST_SOURCE = 98_304


@dataclass(frozen=True)
class GuestSources:
    """Exact bytes of the five guest programs."""

    setup_writer: bytes
    install_readback: bytes
    runtime_probe: bytes
    parse_helper: bytes
    containment_probes: bytes

    def text(self, field: str) -> str:
        value = getattr(self, field)
        if field not in {name.removesuffix(".py") for name in GUEST_FILES} or type(value) is not bytes:
            raise ContractError("unknown_guest_source")
        return value.decode("ascii")

    def digests(self) -> dict[str, str]:
        return {name.removesuffix(".py"): hashlib.sha256(getattr(self, name.removesuffix(".py"))).hexdigest()
                for name in GUEST_FILES}


def _validated(data: bytes) -> bytes:
    if len(data) > MAX_GUEST_SOURCE or b"\x00" in data:
        raise ContractError("guest_source_invalid")
    try:
        data.decode("ascii")
    except UnicodeDecodeError:
        raise ContractError("guest_source_invalid") from None
    return data


def load_guest_sources() -> GuestSources:
    """Read every guest program from package data; refuse anything malformed."""

    package = resources.files(GUEST_PACKAGE)
    values = {name.removesuffix(".py"): _validated(package.joinpath(name).read_bytes())
              for name in GUEST_FILES}
    return GuestSources(**values)


def helper_closure_sha256(sources: GuestSources, probe_source_sha256: str) -> str:
    """Identity of the fixed helper closure: five guest programs plus the probe source."""

    return digest_json({**sources.digests(), "probe_source": probe_source_sha256})
