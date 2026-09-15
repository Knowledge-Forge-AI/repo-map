"""Set-based SCALE3 validation and merge SQL for source-index and raw rows."""

from __future__ import annotations

from dataclasses import dataclass
import re

from repomap_kg.storage.sql_core import sql_literal
from repomap_kg.storage.staging_duplicate_guard import identity_conflict_guard
from repomap_kg.storage.staging_family_catalog import (
    descriptors_for_merge_scope,
    merge_operations_for_scope,
)
from repomap_kg.storage.staging_family_contracts import (
    DuplicatePolicy,
    ValidationRule,
)
from repomap_kg.storage.staging_merge_operations import MergeOperation, MergeScope
from repomap_kg.storage.staging_ownership import StageOwner, StageOwnershipError


__all__ = (
    "MergeContext",
    "MergeContractError",
    "build_source_index_merge_statements",
)

_STAGE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class MergeContractError(ValueError):
    """A set-based merge context is invalid."""


@dataclass(frozen=True)
class MergeContext:
    """Validated stage owner and run identity for one merge attempt."""

    stage_id: str
    owner: StageOwner
    run_id: int

    @property
    def repository_id(self) -> int:
        """Return the graph repository carried by the stage owner."""

        return self.owner.repository_id

    def validate(self) -> "MergeContext":
        if not isinstance(self.owner, StageOwner):
            raise MergeContractError("invalid set-based merge owner")
        try:
            self.owner.validate()
        except StageOwnershipError as error:
            raise MergeContractError("invalid set-based merge owner") from error
        if (
            not isinstance(self.stage_id, str)
            or _STAGE_ID_PATTERN.fullmatch(self.stage_id) is None
            or not isinstance(self.run_id, int)
            or isinstance(self.run_id, bool)
            or self.run_id < 1
        ):
            raise MergeContractError("invalid set-based merge context")
        return self


def build_source_index_merge_statements(
    context: MergeContext,
) -> tuple[str, ...]:
    """Build validation and merge statements for file and raw source rows."""

    context.validate()
    owner = context.owner
    stage = sql_literal(context.stage_id)
    run = str(context.run_id)
    builders = {
        MergeOperation.FILES: lambda: _files_merge(stage, run),
        MergeOperation.RAW_OBSERVATIONS: lambda: _raw_merge(stage, run),
    }
    try:
        operations = tuple(
            builders[binding.operation]()
            for binding in merge_operations_for_scope(MergeScope.SOURCE_INDEX)
        )
    except KeyError as error:
        raise MergeContractError("invalid source-index merge operation") from error
    return (
        _stage_guard(stage, owner, run),
        _proposal_guard(stage, run),
        *operations,
    )


def _stage_guard(stage: str, owner: StageOwner, run: str) -> str:
    repository = str(owner.repository_id)
    owner_values = {
        "operation_id": sql_literal(owner.operation_id),
        "execution_mode": sql_literal(owner.execution_mode),
        "job_id": _nullable_literal(owner.job_id),
        "coordinator_instance_id": _nullable_literal(
            owner.coordinator_instance_id
        ),
        "source_generation": sql_literal(owner.source_generation),
        "config_generation": sql_literal(owner.config_generation),
        "extractor_generation": sql_literal(owner.extractor_generation),
        "canonicalizer_generation": sql_literal(owner.canonicalizer_generation),
    }
    return f"""DO $scale3$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM ingestion_stages
        WHERE stage_id = {stage}
          AND repository_id = {repository}
          AND operation_id = {owner_values['operation_id']}
          AND attempt = {owner.attempt}
          AND execution_mode = {owner_values['execution_mode']}
          AND job_id IS NOT DISTINCT FROM {owner_values['job_id']}
          AND coordinator_instance_id IS NOT DISTINCT FROM
              {owner_values['coordinator_instance_id']}
          AND singleton_fencing_epoch = {owner.singleton_fencing_epoch}
          AND graph_lease_fencing_epoch = {owner.graph_lease_fencing_epoch}
          AND source_generation = {owner_values['source_generation']}
          AND config_generation = {owner_values['config_generation']}
          AND extractor_generation = {owner_values['extractor_generation']}
          AND canonicalizer_generation = {owner_values['canonicalizer_generation']}
          AND state IN ('validated', 'merging')
          AND validation_status = 'passed'
    ) THEN
        RAISE EXCEPTION 'SCALE3 stage is not validated';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM runs
        WHERE id = {run}
          AND repository_id = {repository}
    ) THEN
        RAISE EXCEPTION 'SCALE3 run is not owned by repository';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM stage_raw_observations
        WHERE stage_id = {stage}
          AND source_ordinal > 2147483647
    ) THEN
        RAISE EXCEPTION 'SCALE3 raw ordinal exceeds final schema';
    END IF;
END
$scale3$;"""


def _nullable_literal(value: str | None) -> str:
    return "NULL" if value is None else sql_literal(value)


def _proposal_guard(stage: str, run: str) -> str:
    descriptors = descriptors_for_merge_scope(MergeScope.SOURCE_INDEX)
    conflicts = "".join(
        identity_conflict_guard(descriptor, stage, "SCALE3")
        for descriptor in descriptors
        if descriptor.duplicate_policy is DuplicatePolicy.IDENTICAL_ONLY
        and ValidationRule.IDENTITY_CONFLICT in descriptor.validation_rules
    )
    raw = next(
        descriptor
        for descriptor in descriptors
        if descriptor.duplicate_policy is DuplicatePolicy.SOURCE_ORDINAL_IDEMPOTENT
    )
    return f"""DO $scale3$
BEGIN
{conflicts}    IF EXISTS (
        SELECT 1
        FROM {raw.stage_table} staged
        JOIN raw_observations existing
          ON existing.run_id = {run}
         AND existing.ordinal = staged.{raw.technical_ordinal}
        WHERE staged.stage_id = {stage}
          AND existing.payload_hash <> staged.payload_hash
    ) THEN
        RAISE EXCEPTION 'SCALE3 raw payload conflict';
    END IF;
END
$scale3$;"""


def _files_merge(stage: str, run: str) -> str:
    return f"""WITH proposals AS (
    SELECT DISTINCT ON (s.path)
        header.repository_id,
        s.path,
        s.language,
        s.role,
        s.content_hash,
        s.executable,
        s.generated,
        s.metadata_json
    FROM stage_files s
    JOIN ingestion_stages header ON header.stage_id = s.stage_id
    WHERE s.stage_id = {stage}
    ORDER BY s.path, s.family_ordinal DESC
)
INSERT INTO files(
    repository_id, last_seen_run_id, path, language, role, content_hash,
    executable, generated, metadata_json
)
SELECT repository_id, {run}, path, language, role, content_hash,
       executable, generated, metadata_json
FROM proposals
ON CONFLICT (repository_id, path) DO UPDATE SET
    last_seen_run_id = EXCLUDED.last_seen_run_id,
    language = EXCLUDED.language,
    role = EXCLUDED.role,
    content_hash = EXCLUDED.content_hash,
    executable = EXCLUDED.executable,
    generated = EXCLUDED.generated,
    metadata_json = EXCLUDED.metadata_json;"""


def _raw_merge(stage: str, run: str) -> str:
    return f"""WITH proposals AS (
    SELECT s.source_ordinal, s.schema_version, s.kind,
           s.source_id, s.path, s.payload_json,
           s.payload_hash
    FROM stage_raw_observations s
    WHERE s.stage_id = {stage}
    ORDER BY s.source_ordinal
)
INSERT INTO raw_observations(
    repository_id, run_id, ordinal, schema_version, kind, source_id,
    path, payload_json, payload_hash
)
SELECT (SELECT repository_id FROM ingestion_stages WHERE stage_id = {stage}),
       {run}, source_ordinal, schema_version, kind, source_id,
       path, payload_json, payload_hash
FROM proposals
ON CONFLICT (run_id, ordinal) DO UPDATE SET
    schema_version = EXCLUDED.schema_version,
    kind = EXCLUDED.kind,
    source_id = EXCLUDED.source_id,
    path = EXCLUDED.path,
    payload_json = EXCLUDED.payload_json,
    payload_hash = EXCLUDED.payload_hash;"""
