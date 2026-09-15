from __future__ import annotations


def test_pkg5_discovery_routes_to_shell_package_functions() -> None:
    import repomap_kg.graph.discovery as discovery

    import repomap_kg.extractors.shell.awk as owner_0
    import repomap_kg.extractors.shell.bash as owner_1
    import repomap_kg.extractors.shell.bats as owner_2
    import repomap_kg.extractors.shell.powershell as owner_3
    import repomap_kg.extractors.shell.zsh as owner_4
    import repomap_kg.extractors.shell.zunit as owner_5

    for package_module, function_name in (
        (owner_0, 'extract_awk_file_observations'),
        (owner_1, 'extract_bash_file_observations'),
        (owner_2, 'extract_bats_file_observations'),
        (owner_3, 'extract_powershell_file_observations'),
        (owner_4, 'extract_zsh_file_observations'),
        (owner_5, 'extract_zunit_file_observations'),
    ):

        assert getattr(discovery, function_name) is getattr(package_module, function_name)
