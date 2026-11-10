"""Strict installed-experience record codecs and intent assembly."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

import pytest

from installed_experience_domains import (
    MAX_INTENT_BYTES, SCHEMA_OBSERVATION, SCHEMA_PROJECTION, InstalledError,
)
from installed_experience_encoding import decode, encode, is_scalar
from installed_experience_records import (
    check_projection, decode_index, decode_intent, decode_observation, decode_verdict, encode_index,
    encode_intent, encode_observation, encode_verdict, index_payload, verdict_payload,
)
from installed_experience_source_identity import Preparation, fixture_census_sha256, fixture_rows, owner_intent

PREP = Preparation("1" * 64, 3, "2" * 64, 10, 5, "3" * 64)
SOURCE = {"S02": {"graph_catalog_sha256": "a" * 64, "control_catalog_sha256": "b" * 64},
          "S04": {"tools_sha256": "c" * 64}}


def _intent(owner: str = "server", preparation: Preparation = PREP) -> bytes:
    return owner_intent(owner, preparation, SOURCE, fixture_digest="4" * 64, candidate_census="5" * 64,
                        python="3.13.12", platform="aarch64")


def _observation(**changes: Any) -> dict[str, Any]:
    payload = {
        "schema": SCHEMA_OBSERVATION, "owner": "server", "attempt": "a" * 32, "intent": "6" * 64,
        "scenario": "S01", "seq": 1, "env_class": "provisioned-server", "family": "arch7f_probe",
        "exit": 0, "outcome": "passed", "stderr_class": "empty",
        "facts": {"label": {"value": "provisioned-server", "source": "child-stdout"}},
        "origin_classes": {"env-purelib": 1, "system-site": 1}, "projection": None,
        "cleanup": "not-applicable", "failure_code": None,
    }
    payload.update(changes)
    return payload


def _projection(**changes: Any) -> dict[str, Any]:
    payload = {"schema": SCHEMA_PROJECTION, "name": "typing-extensions", "version": "4.16.0",
               "member_count": 6, "hashed_count": 4, "bytecode_omitted": 1, "license_count": 1,
               "module_sha256": "7" * 64, "record_sha256": "8" * 64, "source_class": "sdk-installed-record"}
    payload.update(changes)
    return payload


def test_intent_round_trip_binds_owner_wheel_and_expected_facts() -> None:
    data = _intent()
    decoded = decode_intent(data)
    assert encode_intent(decoded) == data and len(data) <= MAX_INTENT_BYTES
    assert decoded["storage_scenario"] == "server" and decoded["incumbent_wheel_sha256"] is None
    assert [row["id"] for row in decoded["scenarios"]] == ["S01", "S02", "S03", "S04", "X01"]
    assert decoded["scenarios"][1]["expected"]["graph_catalog_sha256"] == "a" * 64
    assert decoded["env_classes"] == ["none", "provisioned-server"]


@pytest.mark.parametrize("env_classes", [["none", 1], [["none"]]])
def test_intent_refuses_untyped_environment_classes(env_classes: object) -> None:
    payload = decode(_intent(), MAX_INTENT_BYTES)
    payload["env_classes"] = env_classes
    with pytest.raises(InstalledError):
        encode_intent(payload)


@pytest.mark.parametrize(("field", "value"), [
    ("message_path", "messages/not-ledger.eml"), ("message_sha256", "0" * 64),
])
def test_intent_refuses_message_binding_drift(field: str, value: str) -> None:
    payload = decode(_intent(), MAX_INTENT_BYTES)
    payload[field] = value
    with pytest.raises(InstalledError):
        encode_intent(payload)


def test_migration_intent_requires_the_incumbent_binding() -> None:
    source: dict[str, dict[str, Any]] = dict(SOURCE, R00={"distributions":"x", "graph_migrations":1, "control_migrations":1}, R02={"incumbent_stdout": "repomap-kg 0.0.3\n", "dependency_pin": "x==1"})
    with pytest.raises(InstalledError) as missing:
        owner_intent("migration", PREP, source, fixture_digest="4" * 64, candidate_census="5" * 64,
                     python="3.13.12", platform="aarch64")
    assert missing.value.category == "witness-missing"
    prepared = replace(PREP, incumbent_wheel_sha256="9" * 64)
    data = owner_intent("migration", prepared, source, fixture_digest="4" * 64, candidate_census="5" * 64,
                        python="3.13.12", platform="aarch64")
    assert decode_intent(data)["incumbent_wheel_sha256"] == "9" * 64


def test_every_intent_fits_the_sixteen_kibibyte_bound() -> None:
    values: dict[str, dict[str, Any]] = {"L00": {"distributions":"x", "graph_migrations":1, "control_migrations":1}, "L01": {"cloe_stdout": "c\n", "long_stdout": "l\n", "legacy_stdout": "r\n"},
              "L05": {"code_line": 15}}
    assert len(owner_intent("local", PREP, values, fixture_digest="4" * 64, candidate_census="5" * 64,
                            python="3.13.12", platform="x86_64")) <= MAX_INTENT_BYTES


@pytest.mark.parametrize("changes", [
    {"outcome": "failed"}, {"outcome": "passed", "failure_code": "child-deadline"},
    {"exit": -9}, {"seq": 0}, {"seq": 17}, {"scenario": "Z01"}, {"family": "cli_module"},
    {"facts": {"label": {"value": 1.5, "source": "child-stdout"}}},
    {"facts": {"label": {"value": "x", "source": "guess"}}}, {"origin_classes": {"tmp": 1}},
    {"cleanup": "swept"}, {"stderr_class": "noisy"}, {"attempt": "short"},
])
def test_observation_refuses_open_or_inconsistent_fields(changes: dict) -> None:
    with pytest.raises(InstalledError):
        encode_observation(_observation(**changes))


def test_observation_round_trip_and_unknown_needs_a_code() -> None:
    data = encode_observation(_observation())
    assert decode_observation(data)["facts"]["label"]["value"] == "provisioned-server"
    unknown = encode_observation(_observation(outcome="unknown", failure_code="child-deadline", facts={}))
    assert decode_observation(unknown)["outcome"] == "unknown"
    reached = encode_observation(_observation(outcome="not-reached", facts={}, origin_classes=None))
    assert decode_observation(reached)["failure_code"] is None


def test_projection_record_is_bounded_and_embedded() -> None:
    assert check_projection(_projection())["source_class"] == "sdk-installed-record"
    for changes in ({"source_class": "fabricated-wheel"}, {"hashed_count": 9}, {"license_count": 0},
                    {"name": "x" * 80}, {"extra": 1}):
        with pytest.raises(InstalledError):
            check_projection(_projection(**changes))
    data = encode_observation(_observation(projection=_projection()))
    assert len(data) <= 2048


def test_index_and_verdict_codecs() -> None:
    rows = [["intent.json", "1" * 64, 10], ["observation-01-1.json", "2" * 64, 20]]
    data = encode_index(index_payload("server", "a" * 32, "3" * 64, rows))
    assert decode_index(data)["members"] == rows
    with pytest.raises(InstalledError):
        encode_index(index_payload("server", "a" * 32, "3" * 64, rows + [["verdict.json", "4" * 64, 1]]))
    with pytest.raises(InstalledError):
        encode_index(index_payload("server", "a" * 32, "3" * 64, [rows[0], rows[0]]))
    verdict = encode_verdict(verdict_payload(owner="server", attempt="a" * 32, intent="3" * 64,
                                             outcome="rejected", counts={"failed": 1},
                                             categories=["fact-mismatch", "fact-mismatch"],
                                             index_sha256=None))
    assert decode_verdict(verdict)["categories"] == ["fact-mismatch"]
    assert decode_verdict(verdict)["counts"]["passed"] == 0


def test_encoding_leaf_is_canonical_and_closed() -> None:
    data = encode({"b": 1, "a": [True, None, "x"]}, 64)
    assert data == b'{"a":[true,null,"x"],"b":1}\n'
    assert decode(data, 64) == {"a": [True, None, "x"], "b": 1}
    for raw in (b'{"a":1}', b'{"a":1.0}\n', b'{"b":1,"a":2}\n', b'{"a":1}\n{"a":1}\n'):
        with pytest.raises(InstalledError):
            decode(raw, 64)
    with pytest.raises(InstalledError) as large:
        encode({"a": "x" * 100}, 32)
    assert large.value.category == "bound-exceeded"
    assert is_scalar("line\n") and not is_scalar("tab\t") and not is_scalar(-1) and not is_scalar("x" * 129)


def test_fixture_census_is_bounded_and_symlink_free(tmp_path) -> None:
    (tmp_path / "code").mkdir()
    (tmp_path / "code" / "a.py").write_text("x = 1\n", encoding="utf-8")
    rows = fixture_rows(tmp_path)
    assert rows == [["code/a.py", hashlib.sha256(b"x = 1\n").hexdigest(), 6]]
    assert len(fixture_census_sha256(tmp_path)) == 64
    (tmp_path / "link").symlink_to(tmp_path / "code" / "a.py")
    with pytest.raises(InstalledError):
        fixture_rows(tmp_path)


def test_committed_tiny_fixture_census_is_small_and_public() -> None:
    from installed_experience_source_identity import FIXTURE_RELATIVE, REPO_ROOT

    rows = fixture_rows(REPO_ROOT / FIXTURE_RELATIVE)
    assert [row[0] for row in rows] == [
        "code/tinypkg/__init__.py", "code/tinypkg/ledger.py", "docs/guide.md", "messages/ledger.eml"]
    assert sum(row[2] for row in rows) <= 4096
