"""Persisted native units stay inspectable without activating an old module."""
from dataclasses import replace

import pytest

from repomap_kg.service_package import contract, operations as owner
from repomap_kg.service_package.artifacts import ServiceArtifactError
from repomap_kg.service_package.launchd import LaunchdUserAdapter
from repomap_kg.service_package.operations import CoordinatorServiceOperations, ServicePackageError
from repomap_kg.service_package.systemd import SystemdUserAdapter


def test_generation_uses_current_import_owner(tmp_path, service_authority, monkeypatch):
    monkeypatch.setattr(contract, "_IMPORT_PACKAGE", "common_lore_index", raising=False)
    assert contract.build_service_package_spec(tmp_path).foreground_argv[2] == "common_lore_index"


@pytest.fixture(params=[SystemdUserAdapter, LaunchdUserAdapter])
def installed_legacy(request, tmp_path, service_authority, monkeypatch):
    from repomap_kg.runtime.local import setup_local_runtime
    home = tmp_path / "product-home"
    setup_local_runtime(home)
    config = home / "repomap.rpl.toml"
    config.write_text(config.read_text().replace("[runtime]", '[runtime]\ncoordinator_mode = "native"'))
    old_spec = contract.build_service_package_spec(home)
    adapter = request.param(user_home=tmp_path / "user", uid=501)
    calls: list[tuple[str, ...]] = []
    def runner(argv: tuple[str, ...]) -> int:
        calls.append(argv)
        return 0
    ops = CoordinatorServiceOperations(old_spec, adapter, runner=runner,
                                       health_probe=lambda _spec: pytest.fail("legacy health was probed"))
    ops.run("install")
    before = adapter.target_path.read_bytes()
    monkeypatch.setattr(contract, "_IMPORT_PACKAGE", "common_lore_index", raising=False)
    ops.spec = contract.build_service_package_spec(home)
    calls.clear()
    return ops, adapter, calls, before


def test_legacy_status_reports_reinstall_without_probing_or_writing(installed_legacy):
    ops, adapter, calls, before = installed_legacy
    result = ops.run("status")
    assert result.result == "service_legacy_module_reinstall_required"
    assert result.installed and result.ready is False
    assert result.active is None and result.enabled is None and not result.changed
    assert calls == [] and adapter.target_path.read_bytes() == before


@pytest.mark.parametrize("action", ["validate", "start", "stop", "restart", "upgrade"])
def test_legacy_execution_and_upgrade_refuse_before_native_calls(installed_legacy, action):
    ops, adapter, calls, before = installed_legacy
    with pytest.raises(ServicePackageError, match="^service_legacy_module_reinstall_required$"):
        ops.run(action)
    assert not calls and adapter.target_path.read_bytes() == before


def test_legacy_exact_uninstall_never_starts_or_enables(installed_legacy):
    ops, adapter, calls, _before = installed_legacy
    result = ops.run("uninstall")
    assert not result.installed and result.changed and not adapter.target_path.exists()
    assert all(argv not in calls for argv in (*adapter.start_commands(), *adapter.enable_commands(), *adapter.restart_commands()))


def test_legacy_uninstall_restores_file_but_never_reactivates_on_removal_failure(installed_legacy, monkeypatch):
    ops, adapter, calls, before = installed_legacy
    original = owner.remove_owned_artifact
    def remove_then_fail(path, recognize):
        original(path, recognize)
        raise ServiceArtifactError("fixture failure")
    monkeypatch.setattr(owner, "remove_owned_artifact", remove_then_fail)
    with pytest.raises(ServicePackageError, match="^service_uninstall_legacy_recovery_required$"):
        ops.run("uninstall")
    assert adapter.target_path.read_bytes() == before
    assert all(argv not in calls for argv in (*adapter.start_commands(), *adapter.enable_commands()))


def test_legacy_partial_native_failure_never_rolls_back_into_activation(installed_legacy):
    ops, adapter, calls, before = installed_legacy
    def failing_runner(argv):
        calls.append(argv)
        return 1 if argv == adapter.disable_commands()[0] else 0
    ops.runner = failing_runner
    with pytest.raises(ServicePackageError, match="^service_uninstall_legacy_recovery_required$"):
        ops.run("uninstall")
    assert adapter.target_path.read_bytes() == before
    assert all(argv not in calls for argv in (*adapter.start_commands(), *adapter.enable_commands()))


@pytest.mark.parametrize("module", ["repomap_kg.extra", "REPOMAP_KG", "other", "common_lore_index.extra"])
def test_module_spelling_alone_cannot_expand_owned_definition_recognition(installed_legacy, module):
    ops, adapter, _calls, _before = installed_legacy
    argv = list(ops.spec.foreground_argv)
    argv[2] = module
    content = adapter.render(replace(ops.spec, foreground_argv=tuple(argv)))
    assert not adapter.recognizes(content)
    assert adapter.module_classification(content) == "unrecognized"


def test_recognition_requires_complete_definition_not_only_a_legacy_token(installed_legacy):
    _ops, adapter, _calls, before = installed_legacy
    assert adapter.recognizes(before)
    assert adapter.module_classification(before) == "legacy"
    assert not adapter.recognizes(before + b"unexpected content")
    assert adapter.module_classification(before + b"unexpected content") == "unrecognized"


@pytest.mark.parametrize("body", [b"<date>bogus</date>", b"<key>orphan</key>"])
def test_malformed_plist_values_are_controlled_refusals(tmp_path, service_authority, body):
    adapter = LaunchdUserAdapter(user_home=tmp_path / "user", uid=501)
    content = b'<?xml version="1.0"?><plist version="1.0">' + body + b"</plist>"
    assert not adapter.recognizes(content)
    assert adapter.module_classification(content) == "unrecognized"
    with pytest.raises(ValueError, match="^service_definition_invalid$"):
        adapter.validate(content, contract.build_service_package_spec(tmp_path / "product-home"))
