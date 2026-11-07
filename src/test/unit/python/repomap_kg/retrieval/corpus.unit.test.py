"""Unit tests for the controlled mixed-v1 retrieval evaluation fixture and canary registry (S2)."""

from __future__ import annotations

from pathlib import Path

from repomap_test_support.retrieval_evaluation_canaries import (
    CANARY_REGISTRY,
    assert_canary_free,
    scan_for_canaries,
)
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_BINDINGS,
    MIXED_V1_FIXTURE_ROOT,
    compute_working_copy_digests,
    materialize_mixed_v1_working_copy,
)


def test_mixed_v1_fixture_bindings_and_two_generations_materialize_deterministically(
    tmp_path: Path,
) -> None:
    """mixed-v1 materializes four bindings across two generations with deterministic digests."""
    assert MIXED_V1_FIXTURE_ROOT.is_dir()
    assert tuple(MIXED_V1_BINDINGS) == ("core", "companion", "feeds", "mailbox")

    gen1_a = materialize_mixed_v1_working_copy(tmp_path / "g1a", generation=1)
    gen1_b = materialize_mixed_v1_working_copy(tmp_path / "g1b", generation=1)
    gen2 = materialize_mixed_v1_working_copy(tmp_path / "g2", generation=2)

    digests_1a = compute_working_copy_digests(gen1_a)
    digests_1b = compute_working_copy_digests(gen1_b)
    digests_2 = compute_working_copy_digests(gen2)

    assert digests_1a == digests_1b
    assert digests_1a != digests_2

    # Duplicate relative path exists across core and companion
    assert ("core", "shared/status_codes.py") in digests_1a
    assert ("companion", "shared/status_codes.py") in digests_1a
    assert digests_1a[("core", "shared/status_codes.py")] != digests_1a[("companion", "shared/status_codes.py")]

    # Generated edge-case files (>262 KiB truncatable, >1 MiB oversized, long line, CRLF, NUL, invalid UTF-8)
    assert digests_1a[("companion", "generated/truncatable_prose.md")]["size_bytes"] > 262144
    assert digests_1a[("companion", "generated/oversized_dump.txt")]["size_bytes"] > 1048576
    assert ("companion", "generated/long_line_notes.md") in digests_1a
    assert ("companion", "generated/crlf_notes.txt") in digests_1a
    assert ("companion", "generated/binary_nul.txt") in digests_1a
    assert ("companion", "generated/invalid_utf8.txt") in digests_1a

    # Generation 2 includes modified, deleted, and newly added files
    assert ("core", "pkg/legacy_deprecated.py") in digests_1a
    assert ("core", "pkg/legacy_deprecated.py") not in digests_2
    assert ("core", "pkg/gen2_extension.py") not in digests_1a
    assert ("core", "pkg/gen2_extension.py") in digests_2


def test_canary_registry_detects_private_body_leaks_and_passes_clean_payloads() -> None:
    """Canary scanner catches synthetic private email/unselected tokens and passes public outputs."""
    assert len(CANARY_REGISTRY) >= 3
    clean_payload = {
        "status": "ok",
        "hits": [{"binding_id": "bind1:core", "source_relative_path": "pkg/pipeline.py"}],
    }
    assert scan_for_canaries(clean_payload) == ()
    assert_canary_free(clean_payload)

    sample_canary = next(iter(CANARY_REGISTRY.values()))
    leaked_payload = {"snippet": f" accidental disclosure of {sample_canary} in output "}
    findings = scan_for_canaries(leaked_payload)
    assert len(findings) == 1
