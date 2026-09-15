--liquibase formatted sql
--changeset slair:2026_07_12-002-core-add_go_source_instance_edge_kind

ALTER TABLE canonical_edges
    DROP CONSTRAINT canonical_edges_edge_kind_check;

ALTER TABLE canonical_edges
    ADD CONSTRAINT canonical_edges_edge_kind_check
    CHECK (
        edge_kind IN (
            'asserts',
            'benchmarks',
            'calls',
            'command_intent',
            'command_under_test',
            'completion_for',
            'configures',
            'constructs',
            'contains',
            'declares',
            'defers',
            'defines',
            'depends_on',
            'embeds',
            'examples',
            'executes',
            'expects',
            'exposes_script',
            'fuzzes',
            'has_assertion',
            'has_hook',
            'has_test_case',
            'host_mutation_intent',
            'imports',
            'includes',
            'instance_of',
            'instantiates',
            'links_to',
            'loads',
            'method_of',
            'mutates_host',
            'network_intent',
            'package_intent',
            'panics',
            'pipe_command_intent',
            'reads',
            'reads_env',
            'receives',
            'recovers',
            'references',
            'replaces_module',
            'requires_module',
            'refutes',
            'returns',
            'selects',
            'sends',
            'sources',
            'starts_goroutine',
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
            'workspace_uses',
            'wraps',
            'writes',
            'writes_env'
        )
    );

--rollback ALTER TABLE canonical_edges DROP CONSTRAINT canonical_edges_edge_kind_check;
--rollback ALTER TABLE canonical_edges ADD CONSTRAINT canonical_edges_edge_kind_check CHECK (edge_kind IN ('asserts', 'benchmarks', 'calls', 'command_intent', 'command_under_test', 'completion_for', 'configures', 'constructs', 'contains', 'declares', 'defers', 'defines', 'depends_on', 'embeds', 'examples', 'executes', 'expects', 'exposes_script', 'fuzzes', 'has_assertion', 'has_hook', 'has_test_case', 'host_mutation_intent', 'imports', 'includes', 'instantiates', 'links_to', 'loads', 'method_of', 'mutates_host', 'network_intent', 'package_intent', 'panics', 'pipe_command_intent', 'reads', 'reads_env', 'receives', 'recovers', 'references', 'replaces_module', 'requires_module', 'refutes', 'returns', 'selects', 'sends', 'sources', 'starts_goroutine', 'styles', 'system_command_intent', 'tests', 'tests_command', 'uses_builtin', 'uses_fixture', 'uses_helper', 'uses_mock', 'uses_package_manager', 'uses_plugin', 'uses_plugin_manager', 'uses_stub', 'uses_zsh_module', 'workspace_uses', 'wraps', 'writes', 'writes_env'));
