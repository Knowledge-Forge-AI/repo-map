"""Closed, inert component-dossier shape; structural validation has no IO."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from retrieval_semantic_experiment_contracts import canonical_json_bytes
from retrieval_semantic_pair_artifacts import MEMBER_NAMES, refuse
from retrieval_semantic_raw_component_anchors import (
    COMPONENT_ROLES, COUNT_FIELDS, DIGEST_PATTERN, digest_map, object_map,
)


DOSSIER_SCHEMA = "cloe-w5-component-dossier-v1"
MAX_DOSSIER_BYTES = 64 * 1024
ACCEPTANCE = {
    "origin_authenticated": False, "inference_correctness": False,
    "scientific_comparability": False, "held_out_evaluated": False,
    "production_admitted": False, "execution_authority": False,
}
DISCLOSURES = {
    "builder": "explicit_source_bytes_and_original_component_anchors_joined",
    "reader": "structural_only_no_source_or_live_store_reauthentication",
    "correspondence": "artifact_agreement_does_not_establish_origin_or_inference_correctness",
    "drift": "before_after_input_checks_not_atomic_snapshot_or_hostile_writer_confinement",
    "legacy": "original_v1_v2_bytes_and_unknown_fields_unchanged",
}


def closed(value: object, fields: set[str], code: str) -> Mapping[str, object]:
    result = object_map(value, code)
    if set(result) != fields:
        raise refuse(code)
    return result


def validate_binding(value: object) -> None:
    binding = closed(value, {"sha256", "length"}, "dossier_binding")
    digest = binding["sha256"]
    length = binding["length"]
    if type(digest) is not str or DIGEST_PATTERN.fullmatch(digest) is None:
        raise refuse("dossier_binding_digest")
    if type(length) is not int or not 0 <= length <= 32 * 1024 * 1024:
        raise refuse("dossier_binding_length")


def validate_counts(value: object) -> Mapping[str, object]:
    counts = closed(value, set(COUNT_FIELDS), "dossier_counts")
    if any(type(item) is not int or item < 0 for item in counts.values()):
        raise refuse("dossier_counts")
    if cast(int, counts["document_count"]) + cast(int, counts["query_count"]) != counts["record_count"] or (
        counts["embedding_count"] != counts["record_count"]
    ):
        raise refuse("dossier_count_algebra")
    return counts


def validate_component(value: object) -> None:
    component = closed(value, {
        "recorded", "recorded_counts", "recorded_component_digests", "supplied",
        "correspondence", "artifact_correspondence_verified", "verified_counts",
        "verified_component_digests",
    }, "dossier_component")
    recorded = component["recorded"]
    if recorded == "recorded":
        validate_counts(component["recorded_counts"])
        if component["recorded_component_digests"] is None:
            raise refuse("dossier_recorded_identity")
    elif recorded != "not_recorded" or component["recorded_counts"] is not None:
        raise refuse("dossier_recorded_state")
    original = component["recorded_component_digests"]
    if original is not None:
        digest_map(original, COMPONENT_ROLES)
    if component["supplied"] == "not_supplied":
        if component["correspondence"] != "unknown" or any(component[name] is not None for name in (
            "artifact_correspondence_verified", "verified_counts", "verified_component_digests",
        )):
            raise refuse("dossier_unknown_state")
    elif component["supplied"] == "supplied":
        if component["correspondence"] != "verified" or component["artifact_correspondence_verified"] is not True:
            raise refuse("dossier_verified_state")
        verified = validate_counts(component["verified_counts"])
        digest_map(component["verified_component_digests"], COMPONENT_ROLES)
        if component["verified_component_digests"] != original:
            raise refuse("dossier_component_digest_join")
        if recorded == "recorded" and verified != component["recorded_counts"]:
            raise refuse("dossier_component_count_join")
    else:
        raise refuse("dossier_supplied_state")


def validate_component_dossier(value: object) -> None:
    """Validate closed types and joins, without reopening any source path."""
    dossier = closed(value, {"schema", "paired_report", "generations", "acceptance", "disclosures"}, "dossier_fields")
    if dossier["schema"] != DOSSIER_SCHEMA:
        raise refuse("dossier_schema")
    acceptance = closed(dossier["acceptance"], set(ACCEPTANCE), "dossier_acceptance")
    if any(flag is not False for flag in acceptance.values()):
        raise refuse("dossier_acceptance")
    if dossier["disclosures"] != DISCLOSURES:
        raise refuse("dossier_disclosures")
    validate_binding(dossier["paired_report"])
    generations = dossier["generations"]
    if type(generations) is not list or len(generations) != 2:
        raise refuse("dossier_generations")
    for generation, value in enumerate(generations, 1):
        row = closed(value, {"generation", "attempt_id", "journal_members", "result_v2", "component"}, "dossier_generation_fields")
        if type(row["generation"]) is not int or row["generation"] != generation or (
            row["attempt_id"] != f"w5-semantic-g{generation}"
        ):
            raise refuse("dossier_generation_identity")
        members = closed(row["journal_members"], set(MEMBER_NAMES), "dossier_journal_members")
        for binding in members.values():
            validate_binding(binding)
        validate_binding(row["result_v2"])
        validate_component(row["component"])
    try:
        raw = canonical_json_bytes(dossier) + b"\n"
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise refuse("dossier_json") from None
    if len(raw) > MAX_DOSSIER_BYTES:
        raise refuse("dossier_size")


__all__ = [
    "ACCEPTANCE", "DISCLOSURES", "DOSSIER_SCHEMA", "MAX_DOSSIER_BYTES",
    "closed", "validate_binding", "validate_component_dossier", "validate_counts",
]
