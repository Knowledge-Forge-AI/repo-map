"""Integration tests for service package validation refusals."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
from typing import Mapping, Sequence
import unittest

from repomap_kg.artifacts._store_filesystem import FileSystemArtifactStore
from repomap_kg.artifacts._store_common import ArtifactIntegrityError, ArtifactReference
from repomap_kg.artifacts.bundle import PublicationBundle
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.validator import (
    PublicationExpectation,
    PublisherBundleValidator,
)
from repomap_kg.service_package.contract import build_service_package_spec
from repomap_kg.service_package.launchd import LaunchdUserAdapter
from repomap_kg.service_package.operations import (
    CoordinatorServiceOperations,
    ServicePackageError,
    ServiceActionResult,
)
from repomap_kg.service_package.systemd import SystemdUserAdapter
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_test_support.test_scratch import select_scratch_root
from repomap_test_support.service_publication_families import (
    sample_publication_families as _sample_publication_families,
)


class RecordingRunner:
    def __init__(
        self,
        expected: Sequence[tuple[str, ...]],
        failures: Mapping[int, int] | None = None,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.expected = tuple(expected)
        self.failures = dict(failures or {})

    def __call__(self, argv: tuple[str, ...]) -> int:
        index = len(self.calls)
        if index >= len(self.expected) or argv != self.expected[index]:
            raise AssertionError(f"unexpected native command at index {index}: {argv!r}")
        self.calls.append(argv)
        return self.failures.pop(index, 0)

    def assert_complete(self) -> None:
        if len(self.calls) != len(self.expected) or self.failures:
            raise AssertionError("native command script was not fully consumed")


def _systemd_state_prefix(adapter: SystemdUserAdapter) -> list[tuple[str, ...]]:
    enabled_probe = adapter.enabled_probe_argv()
    assert enabled_probe is not None
    return [
        adapter.manager_probe_argv(),
        adapter.active_probe_argv(),
        enabled_probe,
        *adapter.stop_commands(),
        *adapter.disable_commands(),
    ]


def _make_bundle(
    req_id: str, job_id: str, vec: Sequence[tuple[str, int, str]], *,
    candidate_id: str = "cand-1", privacy: PrivacyClassification = PrivacyClassification.PUBLIC,
) -> PublicationBundle:
    return PublicationBundle.create(
        request_id=req_id, job_id=job_id, attempt=1, graph_id="graph-main",
        candidate_id=candidate_id, snapshot_manifest_id="manifest-1", snapshot_vector=vec,
        source_generation="sg1:" + "1" * 64, config_generation="cg1:" + "2" * 64,
        extractor_generation="eg1:" + "3" * 64, canonicalizer_generation="kg1:" + "4" * 64,
        extractor_capability_identity="cap1:service-pipeline-v1",
        resolver_identity="resolver1:standard-v1", canonicalizer_identity="canon1:canonical-v1",
        semantic_contract_identity="semantic1:core-v1", quality_rule_identity="quality1:standard-v1",
        privacy=privacy, families=_sample_publication_families(vec),
        row_stage_contract="legacy-absent-v1",
    )


def _make_receipt(
    req_id: str, job_id: str, vec: Sequence[tuple[str, int, str]], *,
    outcome: str = "completed", bundle_reference: ArtifactReference | None = None,
    bundle_id: str | None = None, family_counts: Mapping[str, int] | None = None,
    diagnostic_category: str | None = None, diagnostic_summary: Sequence[str] = (),
    cancellation: str = "not-requested",
) -> ExtractionReceipt:
    return ExtractionReceipt.create(
        request_id=req_id, job_id=job_id, attempt=1, graph_id="graph-main",
        worker_capability_identity="cap1:portable-worker-v1", contract_version="1.0",
        source_generation="sg1:" + "1" * 64, config_generation="cg1:" + "2" * 64,
        extractor_generation="eg1:" + "3" * 64, canonicalizer_generation="kg1:" + "4" * 64,
        snapshot_manifest_id="manifest-1", snapshot_vector=vec,
        resolver_identity="resolver1:standard-v1", extractor_capability_identity="cap1:service-pipeline-v1",
        canonicalizer_identity="canon1:canonical-v1", semantic_contract_identity="semantic1:core-v1",
        quality_rule_identity="quality1:standard-v1", outcome=outcome, cancellation=cancellation,
        bundle_reference=bundle_reference, bundle_id=bundle_id, family_counts=family_counts or {},
        diagnostic_category=diagnostic_category, diagnostic_summary=diagnostic_summary,
        producer_identity="producer1:test-service-pipeline", attestation_class="untrusted-self-assertion",
    )


class ServicePackageRefusalsIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(
            tempfile.mkdtemp(
                dir=select_scratch_root(),
                prefix="repomap-int-service-refusals-",
            )
        ).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_terminal_receipt_validation_and_conflicting_completed_refusal(self) -> None:
        store = FileSystemArtifactStore(self.tmpdir / "terminal_store")
        vector = (("src:1", 1, "s" * 64),)
        term_receipt = _make_receipt(
            "req-term-1", "job-term-1", vector,
            outcome="failed",
            diagnostic_category="artifact_corrupt",
            diagnostic_summary=("corrupt artifact input",),
        )
        term_ref = store.put(
            term_receipt.canonical_bytes(),
            media_type="application/json",
            record_format="canonical-json-v1",
            privacy=PrivacyClassification.PUBLIC,
        )
        validator = PublisherBundleValidator()
        validated_terminal = validator.validate_terminal_receipt(
            store=store,
            receipt_reference=term_ref,
        )
        self.assertEqual(validated_terminal.outcome, "failed")
        bundle = _make_bundle("req-term-1", "job-term-1", vector)
        b_ref = store.put(
            bundle.canonical_bytes(),
            media_type="application/x-repomap-publication-bundle-v1+jsonl",
            record_format="canonical-jsonl-v1",
            privacy=bundle.privacy,
        )
        comp_receipt = replace(
            term_receipt,
            outcome="completed",
            bundle_id=bundle.bundle_id,
            bundle_reference=b_ref,
            family_counts=bundle.family_counts,
            diagnostic_category=None,
            diagnostic_summary=(),
        ).reidentify()
        r_ref = store.put(
            comp_receipt.canonical_bytes(),
            media_type="application/json",
            record_format="canonical-json-v1",
            privacy=bundle.privacy,
        )
        expectation = PublicationExpectation.from_bundle(bundle, mutating_owner_count=1)
        with self.assertRaises(ValueError) as ctx_term:
            validator.validate_bundle(
                store=store,
                bundle_reference=b_ref,
                receipt_reference=r_ref,
                expectation=expectation,
            )
        self.assertIn("non-completed attempt cannot become completed", str(ctx_term.exception))

    def test_bundle_validator_semantic_mismatch_refusals(self) -> None:
        store = FileSystemArtifactStore(self.tmpdir / "mismatch_store")
        vector = (("src:1", 1, "s" * 64),)
        bundle = _make_bundle("req-mismatch-1", "job-mismatch-1", vector)
        b_ref = store.put(
            bundle.canonical_bytes(),
            media_type="application/x-repomap-publication-bundle-v1+jsonl",
            record_format="canonical-jsonl-v1",
            privacy=bundle.privacy,
        )
        receipt = _make_receipt(
            "req-mismatch-1", "job-mismatch-1", vector,
            outcome="completed",
            bundle_reference=b_ref,
            bundle_id=bundle.bundle_id,
            family_counts=bundle.family_counts,
        )
        r_ref = store.put(
            receipt.canonical_bytes(),
            media_type="application/json",
            record_format="canonical-json-v1",
            privacy=bundle.privacy,
        )
        expectation = PublicationExpectation.from_bundle(bundle, mutating_owner_count=1)
        fresh_validator = PublisherBundleValidator()
        bad_owner_exp = replace(expectation, mutating_owner_count=2)
        with self.assertRaises(ValueError) as ctx_owner:
            fresh_validator.validate_bundle(
                store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=bad_owner_exp,
            )
        self.assertIn("exactly one mutating owner is required", str(ctx_owner.exception))
        bad_priv_exp = replace(expectation, expected_privacy=PrivacyClassification.CANONICAL_GRAPH.value)
        with self.assertRaises(ValueError) as ctx_priv:
            fresh_validator.validate_bundle(
                store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=bad_priv_exp,
            )
        self.assertIn("bundle privacy mismatch", str(ctx_priv.exception))
        self.assertEqual(store.read(b_ref), bundle.canonical_bytes())
        self.assertEqual(store.read(r_ref), receipt.canonical_bytes())
        accepted = fresh_validator.validate_bundle(
            store=store, bundle_reference=b_ref, receipt_reference=r_ref,
            expectation=expectation,
        )
        self.assertFalse(accepted.idempotent_replay)
        for reference in (b_ref, r_ref):
            with self.subTest(unsafe_artifact=reference.content_digest):
                artifact_path = store.object_path(reference)
                artifact_path.chmod(0o644)
                try:
                    with self.assertRaisesRegex(ArtifactIntegrityError, "permissions are unsafe"):
                        fresh_validator.validate_bundle(
                            store=store, bundle_reference=b_ref, receipt_reference=r_ref,
                            expectation=expectation,
                        )
                finally:
                    artifact_path.chmod(0o600)
                expected_bytes = bundle.canonical_bytes() if reference == b_ref else receipt.canonical_bytes()
                self.assertEqual(store.read(reference), expected_bytes)
        replay = fresh_validator.validate_bundle(
            store=store, bundle_reference=b_ref, receipt_reference=r_ref,
            expectation=expectation,
        )
        self.assertTrue(replay.idempotent_replay)
        self.assertEqual(replay.bundle_id, bundle.bundle_id)
        self.assertEqual(store.read(b_ref), bundle.canonical_bytes())
        self.assertEqual(store.read(r_ref), receipt.canonical_bytes())
    def test_platform_adapter_negative_directive_refusals(self) -> None:
        repomap_home = self.tmpdir / "invalid_plat_home"
        repomap_home.mkdir(parents=True, exist_ok=True)
        spec = build_service_package_spec(repomap_home)
        sys_adapter = SystemdUserAdapter(user_home=self.tmpdir / "user_home", uid=1000)
        with self.assertRaises(ValueError) as ctx_sys:
            sys_adapter.validate(b"[Unit]\nDescription=Invalid\n", spec)
        self.assertEqual(str(ctx_sys.exception), "service_definition_invalid")
        launch_adapter = LaunchdUserAdapter(user_home=self.tmpdir / "user_home", uid=501)
        invalid_plist = (
            b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            b'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict></dict></plist>'
        )
        with self.assertRaises(ValueError) as ctx_launch:
            launch_adapter.validate(invalid_plist, spec)
        self.assertEqual(str(ctx_launch.exception), "service_definition_invalid")
    def test_conflicting_completed_attempt_and_inconsistent_terminal_refusals(self) -> None:
        store = FileSystemArtifactStore(self.tmpdir / "conflict_store")
        vector = (("src:1", 1, "s" * 64),)
        bundle = _make_bundle("req-conf-1", "job-conf-1", vector)
        b_ref = store.put(
            bundle.canonical_bytes(), media_type="application/x-repomap-publication-bundle-v1+jsonl",
            record_format="canonical-jsonl-v1", privacy=bundle.privacy,
        )
        receipt = _make_receipt(
            "req-conf-1", "job-conf-1", vector,
            outcome="completed", bundle_reference=b_ref, bundle_id=bundle.bundle_id,
            family_counts=bundle.family_counts,
        )
        r_ref = store.put(
            receipt.canonical_bytes(), media_type="application/json",
            record_format="canonical-json-v1", privacy=bundle.privacy,
        )
        expectation = PublicationExpectation.from_bundle(bundle, mutating_owner_count=1)
        validator = PublisherBundleValidator()
        res = validator.validate_bundle(store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=expectation)
        self.assertTrue(res.byte_integrity_valid)
        bad_receipt = replace(receipt, cancellation="requested").reidentify()
        bad_r_ref = store.put(
            bad_receipt.canonical_bytes(), media_type="application/json",
            record_format="canonical-json-v1", privacy=bundle.privacy,
        )
        with self.assertRaises(ValueError) as ctx_incon:
            validator.validate_bundle(store=store, bundle_reference=b_ref, receipt_reference=bad_r_ref, expectation=expectation)
        self.assertIn("receipt and bundle terminal state is inconsistent", str(ctx_incon.exception))
        alt_bundle = _make_bundle(
            bundle.request_id, bundle.job_id, bundle.snapshot_vector,
            candidate_id="cand-alt",
        )
        alt_b_ref = store.put(
            alt_bundle.canonical_bytes(), media_type="application/x-repomap-publication-bundle-v1+jsonl",
            record_format="canonical-jsonl-v1", privacy=alt_bundle.privacy,
        )
        alt_receipt = replace(receipt, bundle_id=alt_bundle.bundle_id, bundle_reference=alt_b_ref).reidentify()
        alt_r_ref = store.put(
            alt_receipt.canonical_bytes(), media_type="application/json",
            record_format="canonical-json-v1", privacy=alt_bundle.privacy,
        )
        alt_exp = PublicationExpectation.from_bundle(alt_bundle, mutating_owner_count=1)
        with self.assertRaises(ValueError) as ctx_conf:
            validator.validate_bundle(store=store, bundle_reference=alt_b_ref, receipt_reference=alt_r_ref, expectation=alt_exp)
        self.assertIn("conflicting attempt reuse", str(ctx_conf.exception))
        replay = validator.validate_bundle(store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=expectation)
        self.assertTrue(replay.idempotent_replay)
        self.assertEqual(replay.bundle_id, bundle.bundle_id)
        self.assertEqual(store.read(b_ref), bundle.canonical_bytes())
        self.assertEqual(store.read(r_ref), receipt.canonical_bytes())

    def test_coordinator_service_operations_rollbacks_and_refusals(self) -> None:
        repomap_home = self.tmpdir / "service_coord_home"
        user_home = self.tmpdir / "service_user_home"
        for d in (repomap_home, user_home):
            d.mkdir(mode=0o700, parents=True, exist_ok=True)
        adapter = SystemdUserAdapter(user_home=user_home, uid=1000)
        spec = build_service_package_spec(repomap_home)
        fail_reload = ("/usr/bin/systemctl", "--user", "daemon-reload")
        self.assertEqual(adapter.reload_commands(), (fail_reload,))
        runner_fail_install = RecordingRunner((fail_reload, fail_reload), {0: 1})
        ops_fail_install = CoordinatorServiceOperations(
            spec, adapter, runner=runner_fail_install, health_probe=lambda _: True
        )
        with self.assertRaises(ServicePackageError) as ctx_inst:
            ops_fail_install.run("install")
        self.assertEqual(str(ctx_inst.exception), "service_install_rolled_back")
        runner_fail_install.assert_complete()
        self.assertEqual(runner_fail_install.calls, [fail_reload, fail_reload])
        self.assertFalse(adapter.target_path.exists())

        normal_runner = RecordingRunner((fail_reload,))
        ops_normal = CoordinatorServiceOperations(
            spec, adapter, runner=normal_runner, health_probe=lambda _: True
        )
        with self.assertRaises(ServicePackageError) as ctx_miss_start:
            ops_normal.run("start")
        self.assertEqual(str(ctx_miss_start.exception), "service_definition_missing")
        with self.assertRaises(ServicePackageError) as ctx_miss_upg:
            ops_normal.run("upgrade")
        self.assertEqual(str(ctx_miss_upg.exception), "service_definition_missing")
        res_inst = ops_normal.run("install")
        assert isinstance(res_inst, ServiceActionResult)
        self.assertTrue(res_inst.installed)
        self.assertTrue(adapter.target_path.is_file())
        installed_bytes = adapter.target_path.read_bytes()
        normal_runner.assert_complete()

        with self.assertRaises(ServicePackageError) as ctx_exists:
            ops_normal.run("install")
        self.assertEqual(str(ctx_exists.exception), "service_definition_exists")
        home_v2 = self.tmpdir / "service_coord_home_v2"
        home_v2.mkdir(mode=0o700, parents=True, exist_ok=True)
        spec_v2 = build_service_package_spec(home_v2)
        fail_start = ("/usr/bin/systemctl", "--user", "start", "repomap-coordinator.service")
        upgrade_expected = [
            *_systemd_state_prefix(adapter),
            *adapter.reload_commands(),
            *adapter.enable_commands(),
            *adapter.start_commands(),
            *adapter.reload_commands(),
            *adapter.enable_commands(),
            *adapter.start_commands(),
        ]
        self.assertEqual(upgrade_expected[7], fail_start)
        runner_fail_upg = RecordingRunner(upgrade_expected, {7: 1})
        ops_fail_upg = CoordinatorServiceOperations(
            spec_v2, adapter, runner=runner_fail_upg, health_probe=lambda _: True
        )
        with self.assertRaises(ServicePackageError) as ctx_upg:
            ops_fail_upg.run("upgrade")
        self.assertEqual(str(ctx_upg.exception), "service_upgrade_rolled_back")
        runner_fail_upg.assert_complete()
        self.assertEqual(runner_fail_upg.calls, upgrade_expected)
        self.assertEqual(adapter.target_path.read_bytes(), installed_bytes)
        with self.assertRaises(ServicePackageError) as ctx_outdated:
            ops_fail_upg.run("start")
        self.assertEqual(str(ctx_outdated.exception), "service_definition_upgrade_required")
        uninstall_expected = [
            *_systemd_state_prefix(adapter),
            *adapter.reload_commands(),
            *adapter.reload_commands(),
            *adapter.enable_commands(),
            *adapter.start_commands(),
        ]
        self.assertEqual(uninstall_expected[5], fail_reload)
        runner_fail_un = RecordingRunner(uninstall_expected, {5: 1})
        ops_fail_un = CoordinatorServiceOperations(
            spec, adapter, runner=runner_fail_un, health_probe=lambda _: True
        )
        with self.assertRaises(ServicePackageError) as ctx_un:
            ops_fail_un.run("uninstall")
        self.assertEqual(str(ctx_un.exception), "service_uninstall_rolled_back")
        runner_fail_un.assert_complete()
        self.assertEqual(runner_fail_un.calls, uninstall_expected)
        self.assertTrue(adapter.target_path.is_file())
        self.assertEqual(adapter.target_path.read_bytes(), installed_bytes)


if __name__ == "__main__":
    import sys

    sys.exit(
        "Direct execution unsupported: RepoMap integration tests require container sandbox admission via pytest"
    )
