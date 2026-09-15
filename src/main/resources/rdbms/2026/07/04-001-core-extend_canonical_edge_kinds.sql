--liquibase formatted sql
--changeset slair:2026_07_04-001-core-extend_canonical_edge_kinds

ALTER TABLE canonical_edges
    DROP CONSTRAINT canonical_edges_edge_kind_check;

ALTER TABLE canonical_edges
    ADD CONSTRAINT canonical_edges_edge_kind_check
    CHECK (
        edge_kind IN (
            'asserts',
            'calls',
            'command_intent',
            'command_under_test',
            'completion_for',
            'configures',
            'contains',
            'defines',
            'depends_on',
            'executes',
            'expects',
            'exposes_script',
            'has_assertion',
            'has_hook',
            'has_test_case',
            'host_mutation_intent',
            'imports',
            'includes',
            'links_to',
            'loads',
            'mutates_host',
            'network_intent',
            'package_intent',
            'pipe_command_intent',
            'reads',
            'reads_env',
            'references',
            'refutes',
            'sources',
            'styles',
            'system_command_intent',
            'tests',
            'tests_command',
            'uses_builtin',
            'uses_fixture',
            'uses_helper',
            'uses_mock',
            'uses_package_manager',
            'uses_plugin',
            'uses_plugin_manager',
            'uses_stub',
            'uses_zsh_module',
            'wraps',
            'writes',
            'writes_env'
        )
    );

--rollback ALTER TABLE canonical_edges DROP CONSTRAINT canonical_edges_edge_kind_check;
--rollback ALTER TABLE canonical_edges ADD CONSTRAINT canonical_edges_edge_kind_check CHECK (edge_kind IN ('asserts', 'calls', 'command_intent', 'command_under_test', 'completion_for', 'configures', 'contains', 'defines', 'depends_on', 'executes', 'expects', 'exposes_script', 'has_assertion', 'has_hook', 'has_test_case', 'host_mutation_intent', 'imports', 'includes', 'links_to', 'loads', 'mutates_host', 'network_intent', 'package_intent', 'pipe_command_intent', 'reads', 'reads_env', 'references', 'refutes', 'sources', 'styles', 'system_command_intent', 'tests', 'tests_command', 'uses_builtin', 'uses_fixture', 'uses_helper', 'uses_mock', 'uses_package_manager', 'uses_plugin', 'uses_plugin_manager', 'uses_stub', 'uses_zsh_module', 'wraps', 'writes', 'writes_env'));
