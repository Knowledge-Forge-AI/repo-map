"""Admission and startup coordination for allocating test runs."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from repomap_test_support.resource_admission import (
    HostSignals,
)
from repomap_test_support.resource_hygiene_policy import (
    HygieneConfig,
    HygieneProfile,
    QuotaExceeded,
)
from repomap_test_support.resource_ledger import ResourceLedger
from repomap_test_support.resource_scratch import ScratchRunOwner
from repomap_test_support.test_scratch import TestScratchLayout

if TYPE_CHECKING:
    from repomap_test_support.resource_run import TestResourceRun


def admit_resource_run(
    run_cls: type[TestResourceRun],
    layout: TestScratchLayout,
    *,
    profile: HygieneProfile = HygieneProfile.ORDINARY,
    config: HygieneConfig | None = None,
    host_signals: HostSignals | None = None,
    now_seconds: int | None = None,
    quota_override: tuple[int, int] | None = None,
    operator_attested_exclusive: bool = False,
    operator_attested_pressure_degradation: bool = False,
    campaign_plan_id: str | None = None,
    declared_complete_gates: int = 0,
) -> TestResourceRun | None:
    """Coordinate admission, index record, and post-admission setup for one run."""
    from repomap_test_support import resource_run

    if not layout.allocated:
        return None
    profile = HygieneProfile(profile)
    effective_config = config or HygieneConfig()
    now = int(time.time()) if now_seconds is None else now_seconds
    index_root = layout.scratch_root / ".index" / layout.project
    summary_path = index_root / "summary.json"
    if summary_path.exists() or summary_path.is_symlink():
        index = resource_run.AdvisoryIndex.open(index_root, scratch_root=layout.scratch_root)
    else:
        index = resource_run.AdvisoryIndex.initialize_empty(
            index_root,
            scratch_root=layout.scratch_root,
            requesting_run_id=layout.run_root.name,
            initialized_at_seconds=now,
        )
    signals = host_signals or resource_run.collect_host_signals(
        layout.scratch_root,
        profile=profile,
        operator_attested_exclusive=operator_attested_exclusive,
        operator_attested_pressure_degradation=(
            operator_attested_pressure_degradation
        ),
        campaign_plan_id=campaign_plan_id,
        declared_complete_gates=declared_complete_gates,
    )
    decision = resource_run.decide_host_admission(profile, effective_config, signals)
    if not decision.admitted:
        raise resource_run.ResourceRunError(f"{decision.outcome}: {decision.reason}")
    max_active = {
        HygieneProfile.ORDINARY: None,
        HygieneProfile.INTEGRATION: 2,
        HygieneProfile.BUILD: 1,
        HygieneProfile.EXHAUSTIVE: 1,
        HygieneProfile.HEAVY: 1,
        HygieneProfile.QUALIFICATION: 1,
    }[profile]
    admission_owner_token = resource_run.secrets.token_hex(16)
    try:
        index.admit(
            run_id=layout.run_root.name,
            phase=layout.phase,
            profile=profile,
            hard_watermark_bytes=effective_config.hard_watermark_bytes,
            hard_watermark_inodes=effective_config.hard_watermark_inodes,
            soft_watermark_bytes=effective_config.soft_watermark_bytes,
            soft_watermark_inodes=effective_config.soft_watermark_inodes,
            admitted_at_seconds=now,
            process_id=os.getpid(),
            process_start_evidence=resource_run.process_start_evidence(),
            owner_token=admission_owner_token,
            configuration_sha256=effective_config.digest,
            max_active_runs=max_active,
        )
    except resource_run.AdmissionRecordedError as error:
        try:
            resource_run.abort_admitted_start(
                layout,
                index,
                now_seconds=now,
                stage="admission_lock_release",
                owner_token=admission_owner_token,
                ledger=None,
                scratch=None,
            )
        except Exception as rollback_error:
            raise resource_run.ResourceRunError(
                "admission lock failure rollback failed"
            ) from rollback_error
        raise resource_run.ResourceRunError(
            "host_admission_refused: admission lock release failed"
        ) from error
    except resource_run.HostAdmissionRefused as error:
        raise resource_run.ResourceRunError(f"host_admission_refused: {error}") from error

    stage = "ledger_creation"
    ledger: ResourceLedger | None = None
    scratch: ScratchRunOwner | None = None
    try:
        identity = resource_run.RunIdentity(layout.project, layout.phase, layout.run_root.name)
        ledger = resource_run.ResourceLedger.create(
            layout.run_root / "resource-ledger.json",
            identity,
            now_seconds=now,
        )
        stage = "scratch_registration"
        scratch = resource_run.ScratchRunOwner(layout, ledger)
        run = run_cls(
            layout,
            ledger,
            scratch,
            index,
            profile,
            effective_config,
            admission_owner_token,
            quota_override,
        )
        entry = scratch.register_layout()
        stage = "configuration_write"
        config_path = layout.run_root / "hygiene-configuration.json"
        resource_run.write_private_json(
            config_path,
            {
                "schema": "repomap-test-hygiene-effective-config-v1",
                "profile": profile.value,
                "configuration_sha256": effective_config.digest,
                "degraded_signals": list(decision.degraded_signals),
            },
        )
        stage = "retained_registration"
        run.retain_evidence(config_path, reason="diagnostic_evidence")
        stage = "entry_quota_checkpoint"
        try:
            run._apply_quota("run_entry", entry)
        except QuotaExceeded:
            pass
    except Exception:
        try:
            resource_run.abort_admitted_start(
                layout,
                index,
                now_seconds=now,
                stage=stage,
                owner_token=admission_owner_token,
                ledger=ledger,
                scratch=scratch,
            )
        except Exception as rollback_error:
            raise resource_run.ResourceRunError(
                "post-admission setup rollback failed"
            ) from rollback_error
        raise

    os.environ[resource_run.ENV_RESOURCE_LEDGER] = str(ledger.path)
    resource_run._ACTIVE_RESOURCE_RUN = run
    return run


__all__ = ["admit_resource_run"]
