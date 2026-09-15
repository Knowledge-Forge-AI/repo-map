"""Deterministic public-safe workloads for SCALE11 pipeline profiling."""

from __future__ import annotations

from dataclasses import dataclass

from repomap_kg.observations.raw import RawObservation


FAMILIES = (
    "files",
    "raw_observations",
    "canonical_nodes",
    "canonical_edges",
    "canonical_evidence",
    "canonical_node_evidence",
    "canonical_edge_evidence",
)
PROFILES = (
    "file_raw_heavy",
    "canonical_node_evidence_heavy",
    "canonical_edge_evidence_heavy",
    "duplicate_proposal_heavy",
    "payload_heavy",
    "mixed",
)
WARMUP_SIZE = 32
MEASURED_SIZE_BANDS = (128, 512, 2_048, 8_192)
_MAX_SIZE = MEASURED_SIZE_BANDS[-1]


class Scale11WorkloadError(ValueError):
    """Raised when a requested SCALE11 workload is outside the contract."""


@dataclass(frozen=True)
class Scale11Workload:
    """One deterministic normalized-observation workload."""

    profile: str
    work_items: int
    observations: tuple[RawObservation, ...]
    normalized_bytes: int


def build_workload(profile: str, size: int) -> Scale11Workload:
    """Build one closed synthetic workload without executing target code."""

    if profile not in PROFILES:
        raise Scale11WorkloadError("SCALE11 workload profile is invalid")
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= _MAX_SIZE:
        raise Scale11WorkloadError("SCALE11 workload size is invalid")
    observations: list[RawObservation] = []
    for index in range(size):
        observations.append(_file_observation(index, payload_heavy=profile == "payload_heavy"))
        for proposal in range(_import_count(profile, index)):
            observations.append(_import_observation(profile, index, proposal))
    result = tuple(observations)
    return Scale11Workload(
        profile=profile,
        work_items=size,
        observations=result,
        normalized_bytes=sum(
            len(observation.to_json_line().encode("utf-8"))
            for observation in result
        ),
    )


def _file_observation(index: int, *, payload_heavy: bool) -> RawObservation:
    path = f"fixture/module_{index:05d}.py"
    metadata: dict[str, object] = {
        "content_hash": f"{index:064x}",
        "executable": False,
        "generated": False,
        "language": "python",
        "role": "source",
    }
    if payload_heavy:
        metadata["profile_payload"] = "x" * 512
    return RawObservation(
        kind="file",
        source_id=path,
        path=path,
        confidence="extracted",
        extractor="scale11-public-fixture",
        extractor_version="1",
        metadata=metadata,
    )


def _import_count(profile: str, index: int) -> int:
    if profile == "file_raw_heavy":
        return 1 if index % 16 == 0 else 0
    if profile == "canonical_node_evidence_heavy":
        return 3
    if profile in {"canonical_edge_evidence_heavy", "duplicate_proposal_heavy"}:
        return 4
    if profile == "mixed":
        return 1 + (index % 2)
    return 1


def _import_observation(profile: str, index: int, proposal: int) -> RawObservation:
    path = f"fixture/module_{index:05d}.py"
    source_module = f"fixture.module_{index:05d}"
    if profile == "duplicate_proposal_heavy":
        target_module = "fixture.shared_dependency"
    elif profile == "canonical_node_evidence_heavy":
        target_module = f"fixture.node_{index:05d}_{proposal}"
    elif profile == "canonical_edge_evidence_heavy":
        target_module = f"fixture.edge_{index:05d}_{proposal}"
    else:
        target_module = f"fixture.dependency_{(index + proposal) % 64:02d}"
    metadata: dict[str, object] = {
        "module": source_module,
        "imported_module": target_module,
        "imported_names": [target_module.rsplit(".", 1)[-1]],
        "level": 0,
        "resolution": "local",
    }
    if profile == "payload_heavy":
        metadata["profile_payload"] = "y" * 512
    return RawObservation(
        kind="python.import",
        source_id=f"{path}#scale11-import:{proposal}",
        path=path,
        start_line=proposal + 1,
        end_line=proposal + 1,
        name=target_module,
        target=f"python.module:{target_module}",
        confidence="extracted",
        extractor="scale11-public-fixture",
        extractor_version="1",
        metadata=metadata,
    )
