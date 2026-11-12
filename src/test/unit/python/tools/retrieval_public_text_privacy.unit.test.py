"""Credential-shaped text is refused without changing the maintained v1 redactor."""

# Assemble inert negative-test strings; these contain no usable credential or key.
import pytest

from retrieval_public_text_contracts import (
    EXCERPT_CREDENTIAL_SHAPE_EXCLUDED, EXCERPT_PRIVACY_REFUSED, METADATA_PRIVACY_REFUSED, PublicTextRefusal,
)
from retrieval_public_text_excerpt import encode_model_text, map_excerpt, validate_metadata_fields
from retrieval_public_text_privacy import (
    credential_assignment, credential_shaped_text, credential_uri, is_safe_public_excerpt, is_safe_public_metadata,
    pem_private_key,
)

MARKERS = ("PUBLIC_TEST_PRIVATE_CANARY",)
CREDENTIAL_SHAPES = [
    'password = ' + "".join(("PUBLIC_TEST_", "VALUE")) + '', 'passwd: ' + "".join(("PUBLIC_TEST_", "VALUE")) + '', 'secret=' + "".join(("PUBLIC_TEST_", "VALUE")) + '',
    'token: ' + "".join(("PUBLIC_TEST_", "VALUE")) + '', 'api_key = ' + "".join(("PUBLIC_TEST_", "VALUE")) + '', 'api-key: ' + "".join(("PUBLIC_TEST_", "VALUE")) + '',
    'Authorization: Bearer ' + "".join(("PUBLIC_TEST_", "VALUE")) + '', '{"password": "' + "".join(("PUBLIC_TEST_", "VALUE")) + '"}',
    "{'token': '" + "".join(("PUBLIC_TEST_", "VALUE")) + "'}", "://".join(('https', 'user:PUBLIC_TEST_VALUE@host.invalid/path')),
    "://".join(('HTTP', 'user:PUBLIC_TEST_VALUE@host.invalid/path')),
    # Section 14 item 2: any scheme, key compounds and PEM private-key headers.
    "://".join(('postgres', 'user:PUBLIC_TEST_VALUE@db.invalid:5432/app')), "://".join(('ftp', 'u:PUBLIC_TEST_VALUE@ftp.invalid')),
    "://".join(('redis+tls', 'u:PUBLIC_TEST_VALUE@cache.invalid')), 'aws_secret_access_key=' + "".join(("PUBLIC_TEST_", "VALUE")) + '',
    'access_key: ' + "".join(("PUBLIC_TEST_", "VALUE")) + '', 'access-key=' + "".join(("PUBLIC_TEST_", "VALUE")) + '', 'private_key = ' + "".join(("PUBLIC_TEST_", "VALUE")) + '',
    'credentials = ' + "".join(("PUBLIC_TEST_", "VALUE")) + '', 'credential: ' + "".join(("PUBLIC_TEST_", "VALUE")) + '', 'TOKEN_VALUE=' + "".join(("PUBLIC_TEST_", "VALUE")) + '',
    " ".join(('-----BEGIN', 'RSA', 'PRIVATE', 'KEY-----')), " ".join(('-----BEGIN', 'PRIVATE', 'KEY-----')), " ".join(('-----BEGIN', 'OPENSSH', 'PRIVATE', 'KEY-----')),
    " ".join(('-----BEGIN', 'ENCRYPTED', 'PRIVATE', 'KEY-----')),
    # Item 3: annotation, default and comparison text are conservatively excluded too.
    'password: str = ' + "".join(("PUBLIC_TEST_", "VALUE")) + '', "def f(token='" + "".join(("PUBLIC_TEST_", "VALUE")) + "'):", 'if secret == ' + "".join(("PUBLIC_TEST_", "VALUE")) + ':',
]


@pytest.mark.parametrize("text", CREDENTIAL_SHAPES)
def test_credential_shapes_get_the_distinct_conservative_body_reason(text: str) -> None:
    assert credential_shaped_text(text)
    assert not is_safe_public_excerpt(text, private_markers=MARKERS)
    raw = (text + "\n").encode("utf-8")
    excerpt, reason = map_excerpt(raw, 1, 1, projected_raw_line_count=1, private_markers=MARKERS)
    assert excerpt is None and reason == EXCERPT_CREDENTIAL_SHAPE_EXCLUDED
    with pytest.raises(PublicTextRefusal) as error:
        encode_model_text("py:mod.f", "function", "f", "src/m.py", text, private_markers=MARKERS)
    assert error.value.code == EXCERPT_CREDENTIAL_SHAPE_EXCLUDED
    assert '' + "".join(("PUBLIC_TEST_", "VALUE")) + '' not in str(error.value)


def test_each_rule_is_independent_and_small() -> None:
    assert credential_uri("://".join(('ssh', 'git:PUBLIC_TEST_VALUE@host.invalid'))) and not credential_assignment("ssh://git@x")
    assert credential_assignment('aws_secret_access_key=' + "".join(("PUBLIC_TEST_", "VALUE")) + '')
    assert not credential_uri('aws_secret_access_key=' + "".join(("PUBLIC_TEST_", "VALUE")) + '')
    assert pem_private_key('x\n' + " ".join(('-----BEGIN', 'EC', 'PRIVATE', 'KEY-----')) + '\ny') and not pem_private_key("-----BEGIN PUBLIC KEY-----")
    assert credential_uri("://".join(('http', 'u:p@h'))) and not credential_uri("http://u@h:80/p")


@pytest.mark.parametrize("text", [
    "def tokenize(value): return value", "password_policy", "token_count", "https://host.invalid/public",
    "return 'café'", "value = 1", "api_key_reference", "user@host.invalid", "ssh://git@host.invalid/repo",
    "-----BEGIN PUBLIC KEY-----", "-----BEGIN CERTIFICATE-----", "mailto:someone@example.invalid",
])
def test_public_text_and_ordinary_identifiers_remain_usable(text: str) -> None:
    assert not credential_shaped_text(text)
    excerpt, reason = map_excerpt((text + "\n").encode(), 1, 1, projected_raw_line_count=1, private_markers=MARKERS)
    assert reason is None and excerpt is not None and excerpt.excerpt == text + "\n"


def test_marker_and_sanitizer_failures_keep_the_privacy_reason() -> None:
    canary = MARKERS[0]
    # A private marker wins over a credential shape; the unchanged maintained
    # sanitizer (whose escaped patterns need a literal backslash) keeps its own refusals.
    sanitizer_only = "token\\:\\x"
    assert not credential_shaped_text(sanitizer_only)
    for text in (f"value = '{canary}'", f"password = {canary}", sanitizer_only):
        assert not is_safe_public_excerpt(text, private_markers=MARKERS)
        span, reason = map_excerpt((text + "\n").encode(), 1, 1, projected_raw_line_count=1, private_markers=MARKERS)
        assert span is None and reason == EXCERPT_PRIVACY_REFUSED
        with pytest.raises(PublicTextRefusal) as error:
            encode_model_text("py:mod.f", "function", "f", "src/m.py", text, private_markers=MARKERS)
        assert error.value.code == EXCERPT_PRIVACY_REFUSED and canary not in str(error.value)


@pytest.mark.parametrize("value", [
    "python.function:pkg.auth:token:refresh", "ev1:token:42", "python.function:pkg.auth:token:sync",
    "credentials:loader", "access_key:loader", "aws_secret_access_key:reader", 'token: ' + "".join(("PUBLIC_TEST_", "VALUE")) + '',
])
def test_structured_metadata_ids_no_longer_use_the_body_assignment_heuristic(value: str) -> None:
    assert credential_assignment(value)  # the body predicate would refuse it as an excerpt
    assert is_safe_public_metadata(value, private_markers=MARKERS)


@pytest.mark.parametrize("value", ["secret_store.reader", "api_key_reference", "pkg/password_policy.py"])
def test_ordinary_metadata_stays_public(value: str) -> None:
    assert is_safe_public_metadata(value, private_markers=MARKERS)


@pytest.mark.parametrize("value", [
    "name\u0080", "name\u0085", "name\u009f", "x" * 1025, "name\ud800", "", "   ", MARKERS[0],
    "://".join(('https', 'u:PUBLIC_TEST_VALUE@host.invalid')), "://".join(('git+ssh', 'u:PUBLIC_TEST_VALUE@host.invalid')),
    " ".join(('-----BEGIN', 'PRIVATE', 'KEY-----')), 7, None,
])
def test_descriptor_string_bounds_are_enforced_before_body_access(value: object) -> None:
    assert not is_safe_public_metadata(value, private_markers=MARKERS)
    if isinstance(value, str) and value and value.strip():
        assert validate_metadata_fields(
            "py:mod.f", "function", value, "src/m.py", private_markers=MARKERS,
        ) == METADATA_PRIVACY_REFUSED


def test_rule_inputs_are_bounded_by_the_callers() -> None:
    long_metadata = "token:" + "a" * 2000
    assert not is_safe_public_metadata(long_metadata)
    adversarial = "password" + "-" * 4000
    assert not credential_shaped_text(adversarial)


def test_shape_and_sanitizer_overlap_is_the_conservative_shape_but_a_marker_still_wins(monkeypatch) -> None:
    """F7-F8: a sanitizer double proves the precedence marker -> shape -> sanitizer without a database."""
    import retrieval_public_text_excerpt as excerpt_module
    import retrieval_public_text_privacy as privacy_module

    calls: list[str] = []

    def sanitizer_rejects_everything(value: str, *, private_markers: tuple[str, ...]) -> bool:
        calls.append(value)
        return False

    monkeypatch.setattr(privacy_module, "is_sanitized_public_string", sanitizer_rejects_everything)
    overlap = "aws_secret_access_key=abc123"
    assert excerpt_module.excerpt_privacy_reason(overlap, private_markers=("CANARY-X",)) == \
        EXCERPT_CREDENTIAL_SHAPE_EXCLUDED
    assert calls == []
    marked = overlap + " CANARY-X"
    assert excerpt_module.excerpt_privacy_reason(marked, private_markers=("CANARY-X",)) == EXCERPT_PRIVACY_REFUSED
    assert excerpt_module.excerpt_privacy_reason("ordinary words", private_markers=("CANARY-X",)) == \
        EXCERPT_PRIVACY_REFUSED
    assert calls == ["ordinary words"]
