"""ADR 0154 closed capability, effect and lifecycle vocabularies."""

from __future__ import annotations

from typing import Any

import pytest

from common_lore_index.extractors.contracts import vocabulary as v
from common_lore_index.extractors.contracts.vocabulary import ContractError, EffectVector

CONTAINED = {
    "target_code_evaluated": "none",
    "execution_boundary": "pure-python",
    "filesystem_read_scope": "selected-input",
    "filesystem_write_scope": "none",
    "network": "none",
}


class _Text(str):
    pass


def test_cap_v1_vocabulary_is_the_exact_adr0050_set() -> None:
    assert v.CAPABILITY_VOCABULARY_VERSION == "cap-v1"
    assert v.CAPABILITIES_V1 == {
        "file.classification", "lexical.structure", "syntax.tree", "syntax.error_tolerant",
        "resolution.include_local", "resolution.symbol_local", "resolution.type",
        "metadata.package", "build.condition",
    }


def test_effect_dimensions_and_provenance_are_closed_and_separate() -> None:
    assert dict(v.EFFECT_DIMENSIONS) == {
        "target_code_evaluated": {"none", "evaluated"},
        "execution_boundary": {"pure-python", "in-process-native", "subprocess"},
        "filesystem_read_scope": {"selected-input", "repository", "beyond-repository"},
        "filesystem_write_scope": {"none", "scratch", "repository", "beyond-repository"},
        "network": {"none", "any"},
    }
    assert all(v.PROVENANCE_VALUES.isdisjoint(values) for values in v.EFFECT_DIMENSIONS.values())


def test_five_lifecycle_facts_are_distinct_with_their_subjects() -> None:
    assert v.LIFECYCLE_STATES == ("installed", "admitted", "attempted", "exercised", "achieved")
    assert dict(v.LIFECYCLE_SUBJECTS) == {
        "installed": "environment", "admitted": "run", "attempted": "attempt",
        "exercised": "attempt", "achieved": "attempt",
    }
    assert v.UNDECLARED in v.INSTALLED_FACTS and v.UNDECLARED in v.ADMISSION_FACTS
    assert "achieved" not in v.INSTALLED_FACTS | v.ADMISSION_FACTS


@pytest.mark.parametrize("dimension", sorted(CONTAINED))
@pytest.mark.parametrize("bad", ["unknown", True, 1, None, _Text("none")])
def test_effect_vector_refuses_values_outside_each_closed_dimension(
    dimension: str, bad: object
) -> None:
    payload: dict[str, Any] = {**CONTAINED, dimension: bad}
    with pytest.raises(ContractError) as raised:
        EffectVector(**payload)
    assert raised.value.code == "invalid_effect"


@pytest.mark.parametrize(
    "payload",
    [{**CONTAINED, "extra": "none"}, {k: CONTAINED[k] for k in list(CONTAINED)[1:]}, [], "x"],
)
def test_effect_vector_mapping_requires_exact_fields(payload: object) -> None:
    with pytest.raises(ContractError):
        EffectVector.from_mapping(payload)


def test_declared_d3_shape_is_a_declaration_not_admission() -> None:
    contained = EffectVector(**CONTAINED)
    assert contained.declares_extraction_admissible_shape()
    assert EffectVector.from_mapping(contained.to_dict()) == contained
    for dimension, value in (
        ("target_code_evaluated", "evaluated"), ("network", "any"),
        ("filesystem_write_scope", "repository"), ("filesystem_read_scope", "beyond-repository"),
    ):
        widened = EffectVector(**{**CONTAINED, dimension: value})
        assert not widened.declares_extraction_admissible_shape()


def test_capability_sets_are_canonical_and_never_expand() -> None:
    assert v.require_capabilities(["syntax.error_tolerant"], code="c") == ("syntax.error_tolerant",)
    assert v.require_capabilities([], code="c") == ()
    for bad in (["syntax.tree", "lexical.structure"], ["syntax.tree", "syntax.tree"],
                ["syntax.complete"], "syntax.tree", [True], {"syntax.tree"}, None):
        with pytest.raises(ContractError):
            v.require_capabilities(bad, code="c")


@pytest.mark.parametrize("value", [True, False, 1.0, "1", None])
def test_integers_refuse_bool_and_other_substitutes(value: object) -> None:
    with pytest.raises(ContractError):
        v.require_int(value, code="c", minimum=0, maximum=10)
    assert v.require_int(3, code="c", minimum=0, maximum=10) == 3
    with pytest.raises(ContractError):
        v.require_int(11, code="c", minimum=0, maximum=10)


def test_tokens_digests_and_strings_are_strict() -> None:
    assert v.require_token("run-1.a", code="c") == "run-1.a"
    for bad in ("", "Run", "-a", "a/b", "a" * 65, _Text("abc"), b"abc"):
        with pytest.raises(ContractError):
            v.require_token(bad, code="c")
    assert v.require_sha256("0" * 64, code="c") == "0" * 64
    for bad in ("0" * 63, "A" * 64, "g" * 64, "0" * 65):
        with pytest.raises(ContractError):
            v.require_sha256(bad, code="c")


def test_reserved_claim_metadata_keys_are_exact_or_receipt_versioned() -> None:
    for key in sorted(v.CAPABILITY_CLAIM_METADATA_KEYS) + [
        v.RECEIPT_REFERENCE_METADATA_KEY, "extractor_receipt_ref_v2", "extractor_receipt",
    ]:
        assert v.is_reserved_claim_metadata_key(key)
    for candidate in ("language", "capabilities", "content_hash", "receipt", 7, None):
        assert not v.is_reserved_claim_metadata_key(candidate)


def test_contract_error_message_is_the_code_only() -> None:
    error = ContractError("invalid_effect")
    assert str(error) == "invalid_effect" and error.code == "invalid_effect"
