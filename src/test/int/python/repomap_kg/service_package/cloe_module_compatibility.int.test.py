"""Real closed unit definitions and owned files; native commands are recording doubles."""
import os

import pytest

from common_lore_index.runtime.local import setup_local_runtime
from common_lore_index.service_package import contract, operations as owner
from common_lore_index.service_package.artifacts import ServiceArtifactError
from common_lore_index.service_package.launchd import LaunchdUserAdapter
from common_lore_index.service_package.operations import CoordinatorServiceOperations, ServiceActionResult, ServicePackageError
from common_lore_index.service_package.systemd import SystemdUserAdapter
from repomap_test_support.executable_authority import controlled_service_authority


@pytest.mark.parametrize("adapter_type", [LaunchdUserAdapter, SystemdUserAdapter])
@pytest.mark.parametrize("failure", [False, True])
def test_persisted_legacy_definition_is_inspected_and_removed_without_activation(tmp_path, monkeypatch, adapter_type, failure):
    home = tmp_path / "product-home"
    setup_local_runtime(home)
    config = home / "repomap.rpl.toml"
    config.write_text(config.read_text().replace("[runtime]", '[runtime]\ncoordinator_mode = "native"'))
    with controlled_service_authority(tmp_path / "executables"):
        monkeypatch.setattr(contract, "_IMPORT_PACKAGE", "repomap_kg")
        old_spec = contract.build_service_package_spec(home)
        adapter = adapter_type(user_home=tmp_path / "user", uid=os.getuid())
        calls: list[tuple[str, ...]] = []
        def runner(argv: tuple[str, ...]) -> int:
            calls.append(argv)
            return 0
        ops = CoordinatorServiceOperations(old_spec, adapter, runner=runner,
                                           health_probe=lambda _spec: pytest.fail("legacy health probe"))
        ops.run("install")
        before = adapter.target_path.read_bytes()
        monkeypatch.setattr(contract, "_IMPORT_PACKAGE", "common_lore_index", raising=False)
        ops.spec = contract.build_service_package_spec(home)
        assert ops.spec.foreground_argv[2] == "common_lore_index"
        calls.clear()
        status = ops.run("status")
        assert isinstance(status, ServiceActionResult)
        assert status.result == "service_legacy_module_reinstall_required" and status.ready is False
        assert not calls and adapter.target_path.read_bytes() == before
        for action in ("validate", "start", "stop", "restart", "upgrade"):
            with pytest.raises(ServicePackageError, match="service_legacy_module_reinstall_required"):
                ops.run(action)
        assert not calls
        if failure:
            remove = owner.remove_owned_artifact
            def remove_then_fail(path, recognizes):
                remove(path, recognizes)
                raise ServiceArtifactError("fixture failure")
            monkeypatch.setattr(owner, "remove_owned_artifact", remove_then_fail)
            with pytest.raises(ServicePackageError, match="service_uninstall_legacy_recovery_required"):
                ops.run("uninstall")
            assert adapter.target_path.read_bytes() == before
        else:
            removed = ops.run("uninstall")
            assert isinstance(removed, ServiceActionResult)
            assert removed.changed and not adapter.target_path.exists()
        assert all(argv not in calls for argv in (*adapter.start_commands(), *adapter.enable_commands(), *adapter.restart_commands()))


@pytest.mark.parametrize("adapter_type", [LaunchdUserAdapter, SystemdUserAdapter])
def test_malformed_native_definition_is_a_refusal_not_a_parser_exception(tmp_path, adapter_type):
    with controlled_service_authority(tmp_path / "executables"):
        spec = contract.build_service_package_spec(tmp_path / "product-home")
        adapter = adapter_type(user_home=tmp_path / "user", uid=os.getuid())
        malformed = adapter.render(spec) + b"unexpected content"
        assert not adapter.recognizes(malformed)
        assert adapter.module_classification(malformed) == "unrecognized"


@pytest.mark.parametrize("body", [b"<date>bogus</date>", b"<key>orphan</key>"])
def test_malformed_plist_values_refuse_at_the_adapter_boundary(tmp_path, body):
    with controlled_service_authority(tmp_path / "executables"):
        spec = contract.build_service_package_spec(tmp_path / "product-home")
        adapter = LaunchdUserAdapter(user_home=tmp_path / "user", uid=os.getuid())
        content = b'<?xml version="1.0"?><plist version="1.0">' + body + b"</plist>"
        assert not adapter.recognizes(content)
        assert adapter.module_classification(content) == "unrecognized"
        with pytest.raises(ValueError, match="^service_definition_invalid$"):
            adapter.validate(content, spec)
