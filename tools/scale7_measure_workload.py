"""Generated SCALE7 workload and active staging-payload helpers."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src" / "main" / "python"
for import_root in (SOURCE_ROOT,):
    import_root_text = str(import_root)
    if import_root_text not in sys.path:
        sys.path.insert(0, import_root_text)

from psycopg.types.json import Jsonb  # noqa: E402
from repomap_kg.observations.raw import RawObservation  # noqa: E402
from repomap_kg.storage.staged_rows import build_staged_rows  # noqa: E402
from repomap_kg.storage.staging import STAGING_FAMILIES  # noqa: E402


FAMILIES = STAGING_FAMILIES
FIXTURE_LABEL = "scale7-synthetic-family-workload"


class MeasurementContractError(ValueError):
    """Raised when a public-safe measurement value cannot be encoded."""


@dataclass(frozen=True)
class Workload:
    size: int
    observations: tuple[RawObservation, ...]
    normalized_bytes: int

    @property
    def family_rows(self) -> dict[str, int]:
        rows = stage_rows(self, _stage_id(self.size))
        return {family: len(rows[family]) for family in FAMILIES}


def copy_text_row_bytes(values: tuple[object, ...]) -> bytes:
    """Return deterministic PostgreSQL text-COPY payload bytes for one row."""

    fields: list[str] = []
    for value in values:
        if isinstance(value, Jsonb):
            value = value.obj
        if value is None:
            fields.append(r"\N")
            continue
        if isinstance(value, bool):
            field = "t" if value else "f"
        elif isinstance(value, int):
            field = str(value)
        elif isinstance(value, (dict, list, tuple)):
            field = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        elif isinstance(value, bytes):
            field = value.decode("utf-8", "strict")
        elif isinstance(value, str):
            field = value
        else:
            raise MeasurementContractError("unsupported COPY value")
        if "\x00" in field:
            raise MeasurementContractError("COPY value contains nul")
        fields.append(
            field.replace("\\", "\\\\")
            .replace("\t", "\\t")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )
    return ("\t".join(fields) + "\n").encode("utf-8")


def synthetic_observations(size: int) -> tuple[RawObservation, ...]:
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 512:
        raise MeasurementContractError("synthetic size must be between 1 and 512")
    observations: list[RawObservation] = []
    for index in range(size):
        path = f"fixture/module-{index}.py"
        observations.extend(
            (
                RawObservation(
                    kind="file",
                    source_id=path,
                    path=path,
                    confidence="extracted",
                    extractor="scale7-fixture",
                    extractor_version="1",
                    metadata={
                        "content_hash": f"{index:064x}",
                        "executable": False,
                        "generated": False,
                        "language": "python",
                        "role": "source",
                    },
                ),
                RawObservation(
                    kind="python.import",
                    source_id=f"{path}#import:json",
                    path=path,
                    start_line=2,
                    end_line=2,
                    name=f"json_{index}",
                    target=f"module:json-{index}",
                    confidence="heuristic",
                    extractor="scale7-fixture",
                    extractor_version="1",
                    metadata={"module": f"json_{index}"},
                ),
            )
        )
    return tuple(observations)


def prepare_workload(size: int) -> Workload:
    observations = synthetic_observations(size)
    return Workload(
        size=size,
        observations=observations,
        normalized_bytes=sum(
            len(observation.to_json_line().encode("utf-8"))
            for observation in observations
        ),
    )


def stage_rows(
    workload: Workload, stage_id: str
) -> dict[str, tuple[dict[str, object], ...]]:
    prepared = build_staged_rows(
        workload.observations,
        repository_name="scale7-fixture",
        stage_id=stage_id,
    )
    try:
        return {
            family: tuple(rows)
            for family, rows in prepared.family_rows.items()
        }
    finally:
        prepared.close()


def _stage_id(size: int) -> str:
    return f"stage-scale7-{size}"
