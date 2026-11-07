"""ADR 0154 strict receipt serialization, digest and lifecycle states."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, cast

import pytest

from common_lore_index.extractors.contracts.receipt_codec import (
    MAX_RECEIPT_BYTES,
    decode_receipt,
    encode_receipt,
    receipt_digest,
)
from common_lore_index.extractors.contracts.receipt_schema import (
    MAX_ATTEMPTS,
    Receipt,
    check_transition,
)
from common_lore_index.extractors.contracts.vocabulary import ContractError
from repomap_test_support.extractor_contracts.receipt_fixtures import (
    attempt,
    canonical,
    declaration,
    declared_receipt,
    digest_of,
    observed,
    receipt,
)


def _payload() -> dict[str, Any]:
    return json.loads(encode_receipt(receipt()))


def _code(data: bytes) -> str:
    with pytest.raises(ContractError) as raised:
        decode_receipt(data)
    return raised.value.code


def test_canonical_round_trip_has_external_digest_only() -> None:
    value = receipt()
    data = encode_receipt(value)
    assert decode_receipt(data) == value
    assert encode_receipt(decode_receipt(data)) == data
    digest = receipt_digest(data)
    assert digest == hashlib.sha256(data).hexdigest()
    assert digest.encode() not in data
    assert decode_receipt(data, expected_sha256=digest) == value
    assert set(json.loads(data)) == {
        "schema", "capability_vocabulary", "state", "producer", "consumer_boundary",
        "run_id", "source_sha256", "declared", "observed", "refusal",
    }


def test_declared_and_observed_parts_stay_separate() -> None:
    payload = _payload()
    assert set(payload["declared"]).isdisjoint({"attempts", "achieved", "exercised", "cleanup"})
    assert set(payload["observed"]).isdisjoint({"capabilities", "effects", "provenance"})
    assert payload["observed"]["verification"] == "unverified"


@pytest.mark.parametrize("mutate,code", [
    (lambda p: p.update(extra=1), "unknown_or_missing_field"),
    (lambda p: p.pop("refusal"), "unknown_or_missing_field"),
    (lambda p: p["declared"].update(extra=1), "invalid_declared"),
    (lambda p: p["observed"]["attempts"][0].update(extra=1), "invalid_attempt"),
    (lambda p: p.update(schema="cloe-extractor-run-receipt-v2"), "unsupported_schema"),
    (lambda p: p.update(capability_vocabulary="cap-v2"), "unsupported_vocabulary"),
    (lambda p: p["observed"].update(exit_status=True), "invalid_observed"),
    (lambda p: p["observed"].update(exit_status=256), "invalid_observed"),
    (lambda p: p.update(run_id=7), "invalid_identity"),
    (lambda p: p.update(producer="x" * 65), "invalid_identity"),
    (lambda p: p.update(source_sha256="A" * 64), "invalid_digest"),
    (lambda p: p["declared"].update(profile_sha256="0" * 63), "invalid_digest"),
    (lambda p: p["declared"].update(capabilities=["syntax.tree", "lexical.structure"]),
     "invalid_capability"),
    (lambda p: p["declared"].update(capabilities=["semantic.magic"]), "invalid_capability"),
    (lambda p: p["observed"].update(verification="verified"), "invalid_observed"),
    (lambda p: p["declared"]["effects"].update(network="some"), "invalid_effect"),
])
def test_strict_decoding_refuses_schema_and_type_violations(mutate: Any, code: str) -> None:
    payload = _payload()
    mutate(payload)
    assert _code(canonical(payload)) == code


@pytest.mark.parametrize("data,code", [
    (b'{"a":1,"a":2}', "duplicate_key"),
    (b'{"a":NaN}', "non_finite_number"),
    (b'{"a":Infinity}', "non_finite_number"),
    (b'{"a":1.5}', "float_forbidden"),
    (b'{"a":1' + b"0" * 30 + b"}", "integer_out_of_range"),
    (b"[" * 7 + b"]" * 7, "too_deep"),
    (b"\xff{}", "invalid_encoding"),
    (b'{"a":"\xc3\xa9"}', "invalid_encoding"),
    (b"{", "invalid_json"),
    (b"[]", "unknown_or_missing_field"),
    (b" " * (MAX_RECEIPT_BYTES + 1), "oversized"),
])
def test_malformed_bytes_are_refused_categorically(data: bytes, code: str) -> None:
    assert _code(data) == code


def test_non_canonical_encodings_and_digest_mismatch_are_refused() -> None:
    data = encode_receipt(receipt())
    payload = json.loads(data)
    for variant in (
        data + b"\n",
        json.dumps(payload, sort_keys=True).encode(),
        json.dumps(dict(reversed(list(payload.items()))), separators=(",", ":")).encode(),
        data.replace(b'"state":"complete"', b'"state":"\\u0063omplete"'),
    ):
        assert variant != data
        assert _code(variant) == "non_canonical"
    with pytest.raises(ContractError) as raised:
        decode_receipt(data, expected_sha256=digest_of("other"))
    assert raised.value.code == "digest_mismatch"
    with pytest.raises(ContractError):
        decode_receipt(data, expected_sha256="not-a-digest")
    with pytest.raises(ContractError):
        decode_receipt(cast(bytes, bytearray(data)))


def test_diagnostics_never_echo_payload_text() -> None:
    payload = _payload()
    payload["PRIVATE-SOURCE-TEXT"] = "secret-value"
    with pytest.raises(ContractError) as raised:
        decode_receipt(canonical(payload))
    assert str(raised.value) == "unknown_or_missing_field"
    assert "secret" not in str(raised.value) and "PRIVATE" not in str(raised.value)


@pytest.mark.parametrize("build,code", [
    (lambda: receipt(state="declared"), "invalid_state"),
    (lambda: receipt(state="refused", observed=observed(admitted="refused", attempts=())),
     "invalid_state"),
    (lambda: receipt(observed=observed(cleanup="incomplete")), "incomplete_terminal_facts"),
    (lambda: receipt(observed=observed(exit_status=None)), "incomplete_terminal_facts"),
    (lambda: receipt(observed=observed(admitted="refused")), "attempt_without_admission"),
    (lambda: receipt(observed=observed(installed="unavailable")), "admission_without_installation"),
    (lambda: receipt(observed=observed(attempts=(attempt(achieved=("lexical.structure",),
                                                         exercised=("syntax.tree",)),))),
     "achieved_without_exercise"),
    (lambda: receipt(observed=observed(attempts=(attempt(outcome="parse_rejected"),))),
     "achieved_without_success"),
    (lambda: receipt(observed=observed(attempts=(attempt(completeness="partial"),))),
     "incomplete_tree_claim"),
    (lambda: receipt(observed=observed(attempts=(attempt(
        exercised=("syntax.error_tolerant",), achieved=("syntax.error_tolerant",),
        completeness="none"),))), "undeclared_completeness"),
    (lambda: receipt(declared=declaration(capabilities=("lexical.structure",))),
     "undeclared_capability_exercised"),
    (lambda: receipt(observed=observed(attempts=(attempt(), attempt()))), "duplicate_attempt"),
    (lambda: receipt(state="unavailable", refusal="policy_refused",
                     observed=observed(installed="unavailable", admitted="refused", attempts=())),
     "invalid_state"),
])
def test_lifecycle_facts_are_not_collapsed(build: Any, code: str) -> None:
    with pytest.raises(ContractError) as raised:
        build()
    assert raised.value.code == code


def test_valid_refused_unavailable_and_incomplete_states() -> None:
    refused = receipt(state="refused", refusal="inadmissible_effects",
                      observed=observed(admitted="refused", attempts=()))
    unavailable = receipt(state="unavailable", refusal="dependency_unavailable",
                          observed=observed(installed="unavailable", admitted="undeclared",
                                            attempts=(), artifact_sha256=None))
    partial = attempt(exercised=("syntax.error_tolerant",), achieved=("syntax.error_tolerant",),
                      completeness="partial")
    incomplete = receipt(state="incomplete", observed=observed(
        attempts=(partial,), cleanup="incomplete", exit_status=None))
    for value in (refused, unavailable, incomplete, declared_receipt()):
        assert decode_receipt(encode_receipt(value)) == value
    assert incomplete.observed is not None and incomplete.observed.attempts[0].achieved == (
        "syntax.error_tolerant",
    )


def test_attempt_count_is_bounded() -> None:
    attempts = tuple(attempt(f"input-{index}") for index in range(MAX_ATTEMPTS + 1))
    with pytest.raises(ContractError) as raised:
        observed(attempts=attempts)
    assert raised.value.code == "invalid_attempt"


def test_transitions_extend_but_never_rewrite_earlier_facts() -> None:
    declared = declared_receipt()
    first = receipt(state="incomplete", observed=observed(cleanup="unknown", exit_status=None))
    second = receipt(observed=observed(attempts=(attempt(), attempt("input-2"))))
    check_transition(declared, first)
    check_transition(first, second)
    for previous, following, code in (
        (second, second, "invalid_transition"),
        (declared, declared, "invalid_transition"),
        (first, replace(declared, state="declared"), "invalid_transition"),
        (first, receipt(state="refused", refusal="policy_refused",
                        observed=observed(admitted="refused", attempts=())), "invalid_transition"),
        (declared, replace(first, run_id="run-0002"), "declaration_rewritten"),
        (declared, replace(first, declared=declaration(invocation_mode="other")),
         "declaration_rewritten"),
        (first, receipt(observed=observed(attempts=(attempt("input-3"),))),
         "observation_rewritten"),
    ):
        with pytest.raises(ContractError) as raised:
            check_transition(previous, following)
        assert raised.value.code == code


def test_observed_facts_only_accumulate_across_transitions() -> None:
    def incomplete(**changes: Any) -> Receipt:
        base = {"cleanup": "unknown", "exit_status": None, "resource_events": ("time_bound",),
                "verification": "refused"}
        return receipt(state="incomplete", observed=observed(**{**base, **changes}))

    start = incomplete()
    grown = incomplete(resource_events=("memory_bound", "time_bound"), exit_status=1,
                       cleanup="incomplete", attempts=(attempt(), attempt("input-2")))
    check_transition(start, grown)
    check_transition(incomplete(artifact_sha256=None, invocation_mode=None,
                                verification="unverified"), start)
    for following in (
        incomplete(resource_events=()),
        incomplete(verification="unverified"),
        incomplete(artifact_sha256=digest_of("other-artifact")),
        incomplete(artifact_sha256=None),
        incomplete(invocation_mode="other-mode"),
        incomplete(invocation_mode=None),
    ):
        with pytest.raises(ContractError) as raised:
            check_transition(start, following)
        assert raised.value.code == "observation_rewritten"
    facts = grown.observed
    assert facts is not None
    for following in (
        replace(grown, observed=replace(facts, exit_status=2)),
        replace(grown, observed=replace(facts, exit_status=None)),
        replace(grown, observed=replace(facts, cleanup="unknown")),
        receipt(observed=observed(attempts=facts.attempts, exit_status=1,
                                  resource_events=("memory_bound", "time_bound"),
                                  verification="refused")),
    ):
        with pytest.raises(ContractError) as raised:
            check_transition(grown, following)
        assert raised.value.code == "observation_rewritten"


def test_constructors_refuse_substituted_component_types() -> None:
    with pytest.raises(ContractError):
        replace(receipt(), declared=cast(Any, declaration().to_dict()))
    with pytest.raises(ContractError):
        replace(receipt(), observed=cast(Any, observed().to_dict()))
    with pytest.raises(ContractError):
        Receipt.from_mapping("not-an-object")
    with pytest.raises(ContractError):
        encode_receipt(cast(Any, _payload()))
