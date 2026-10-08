import math

import pytest

from repomap_kg.artifacts._canonical import (
    CanonicalEncodingError, canonical_json, decode_canonical_json,
)
from repomap_kg.extractors.config.generic import extract_config_file_observations
from repomap_kg.extractors.config.generic_values import (
    _safe_value_summary, _stable_array_members, _value_type,
)


@pytest.mark.parametrize("value", [1.25, 0.1, -1.25, -0.0, 0.0, 1.0, 1.7976931348623157e308, 5e-324])
def test_binary64_summary_is_exact_and_canonical(value):
    summary = _safe_value_summary(value)
    assert summary == {"numeric_type": "binary64", "hex": value.hex()}
    recovered = float.fromhex(summary["hex"])
    assert recovered == value
    assert math.copysign(1, recovered) == math.copysign(1, value)
    encoded = canonical_json(summary)
    assert canonical_json(decode_canonical_json(encoded)) == encoded
    assert _value_type(value) == "number"


@pytest.mark.parametrize("suffix,content", [
    ("json", '{"ratio":1.25,"values":[0.1,1.25],"password":1.25}'),
    ("jsonc", '{"ratio":1.25, // comment\n"password":1.25}'),
    ("jsonl", '{"ratio":1.25,"password":1.25}\n'),
    ("toml", 'ratio = 1.25\nvalues = [0.1,1.25]\npassword = 1.25\n'),
    ("yaml", 'ratio: 1.25\npassword: 1.25\n'),
    ("plist", '<plist><dict><key>ratio</key><real>1.25</real><key>password</key><real>1.25</real></dict></plist>'),
])
def test_sibling_config_numbers_share_summary_and_redaction(suffix, content):
    observations = extract_config_file_observations("settings." + suffix, content)
    summaries = [item.metadata.get("value_summary") for item in observations]
    assert {"numeric_type": "binary64", "hex": "0x1.4000000000000p+0"} in summaries
    for item in observations:
        canonical_json(item.to_dict())
        if "password" in str(item.metadata.get("pointer", "")):
            assert item.metadata.get("value_summary") is None


def test_numeric_stable_members_never_use_dictionary_repr():
    members = _stable_array_members([{"id": 1.25}, {"id": -0.0}])
    assert [member.segment for member in members] == [
        "binary64:0x1.4000000000000p+0", "binary64:-0x0.0p+0",
    ]
    assert not _stable_array_members([{"id": float("inf")}])
    assert _safe_value_summary({"numeric_type": "binary64", "hex": "invalid"}) is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_values_are_marked_refusals_not_numbers(value):
    assert _safe_value_summary(value) == {"numeric_type": "binary64", "refusal": "non-finite"}
    with pytest.raises(CanonicalEncodingError):
        canonical_json({"value": value})


def test_integer_only_canonical_vector_is_unchanged_and_unsupported_values_refuse():
    vector = b'{"a":[1,-2,true,null],"z":"hello"}\n'
    assert canonical_json({"z": "hello", "a": [1, -2, True, None]}) == vector
    assert canonical_json(decode_canonical_json(vector)) == vector
    for invalid in (b'{"value":NaN}\n', b'{"value":1.25}\n', b'{"x":1,"x":2}\n'):
        with pytest.raises(CanonicalEncodingError):
            decode_canonical_json(invalid)
    with pytest.raises(CanonicalEncodingError):
        canonical_json({"value": object()})
