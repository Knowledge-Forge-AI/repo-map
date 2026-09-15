"""TEST-HYGIENE3A quota and closed-configuration contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support.resource_hygiene_policy import (
    GIB,
    HygieneConfig,
    HygieneConfigError,
    HygieneProfile,
    QuotaEvent,
    QuotaExceeded,
    QuotaTracker,
    load_hygiene_config,
)


def test_profile_quotas_match_adr_0048():
    assert HygieneProfile.ORDINARY.quota == (2 * GIB, 50_000)
    assert HygieneProfile.INTEGRATION.quota == (8 * GIB, 200_000)
    assert HygieneProfile.BUILD.quota == (16 * GIB, 300_000)
    assert HygieneProfile.HEAVY.quota == (32 * GIB, 750_000)
    assert HygieneProfile.QUALIFICATION.quota == (64 * GIB, 1_500_000)


def test_quota_warning_once_and_refusal_preserves_registered_evidence():
    events: list[QuotaEvent] = []
    tracker = QuotaTracker(HygieneProfile.ORDINARY, events.append)
    tracker.checkpoint("entry", allocated_bytes=0, inode_count=0)
    tracker.checkpoint("warning", allocated_bytes=2 * GIB * 8 // 10, inode_count=1)
    tracker.checkpoint("still-warning", allocated_bytes=2 * GIB * 9 // 10, inode_count=1)
    with pytest.raises(QuotaExceeded, match="quota_exceeded"):
        tracker.checkpoint("refusal", allocated_bytes=2 * GIB, inode_count=1)
    assert [event.category for event in events] == ["quota_warning", "quota_exceeded"]


def test_configuration_precedence_and_clamps(tmp_path: Path):
    local = tmp_path / "test-hygiene.local.toml"
    local.write_text("[hygiene]\nHARD_WATERMARK_BYTES = 96636764160\n")
    config = load_hygiene_config(
        cli_overrides={"HARD_WATERMARK_BYTES": 100 * GIB},
        environ={"REPOMAP_TEST_HYGIENE_HARD_WATERMARK_BYTES": str(96 * GIB)},
        local_path=local,
    )
    assert config.hard_watermark_bytes == 100 * GIB
    assert config.soft_watermark_bytes == 40 * GIB
    assert config.soft_watermark_inodes == 1_500_000
    with pytest.raises(HygieneConfigError, match="architectural"):
        load_hygiene_config(
            cli_overrides={"HARD_WATERMARK_BYTES": 257 * GIB},
            environ={},
            local_path=tmp_path / "missing.toml",
        )


def test_configuration_rejects_unknown_credential_and_cleanup_keys(tmp_path: Path):
    local = tmp_path / "test-hygiene.local.toml"
    local.write_text("[hygiene]\nPASSWORD = 'secret'\nCLEANUP_PATH = '/tmp'\n")
    with pytest.raises(HygieneConfigError, match="credential|unknown"):
        load_hygiene_config(cli_overrides={}, environ={}, local_path=local)


@pytest.mark.parametrize("value", [True, 1.5, -1])
def test_configuration_dataclass_rejects_non_exact_numeric_values(value):
    with pytest.raises(HygieneConfigError, match="nonnegative integer"):
        HygieneConfig(hard_watermark_bytes=value)


def test_environment_outranks_local_and_rederives_same_digest(tmp_path: Path):
    local = tmp_path / "test-hygiene.local.toml"
    local.write_text("[hygiene]\nHARD_WATERMARK_BYTES = 85899345920\n")
    environ = {"REPOMAP_TEST_HYGIENE_HARD_WATERMARK_BYTES": str(96 * GIB)}
    first = load_hygiene_config(cli_overrides={}, environ=environ, local_path=local)
    second = load_hygiene_config(cli_overrides={}, environ=environ, local_path=local)
    assert first.hard_watermark_bytes == 96 * GIB
    assert first.digest == second.digest


def test_unknown_environment_key_fails_closed(tmp_path: Path):
    with pytest.raises(HygieneConfigError, match="unknown"):
        load_hygiene_config(
            cli_overrides={},
            environ={"REPOMAP_TEST_HYGIENE_CLEANUP_PATH": "/tmp"},
            local_path=tmp_path / "missing.toml",
        )


@pytest.mark.parametrize("layer", ["cli", "local"])
def test_non_environment_numeric_strings_are_rejected(tmp_path: Path, layer):
    local = tmp_path / "test-hygiene.local.toml"
    cli = {}
    if layer == "cli":
        cli["HARD_WATERMARK_BYTES"] = "85899345920"
    else:
        local.write_text("[hygiene]\nHARD_WATERMARK_BYTES = '85899345920'\n")
    with pytest.raises(HygieneConfigError, match="nonnegative integer"):
        load_hygiene_config(cli_overrides=cli, environ={}, local_path=local)


def test_soft_watermarks_cannot_exceed_hard_watermarks():
    with pytest.raises(HygieneConfigError, match="soft byte"):
        HygieneConfig(soft_watermark_bytes=81 * GIB)
