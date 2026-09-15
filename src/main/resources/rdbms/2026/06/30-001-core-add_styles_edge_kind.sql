--liquibase formatted sql
--changeset slair:2026_06_30-001-core-add_styles_edge_kind

ALTER TABLE canonical_edges
    DROP CONSTRAINT canonical_edges_edge_kind_check;

ALTER TABLE canonical_edges
    ADD CONSTRAINT canonical_edges_edge_kind_check
    CHECK (
        edge_kind IN (
            'defines',
            'executes',
            'sources',
            'reads_env',
            'writes_env',
            'mutates_host',
            'imports',
            'exposes_script',
            'links_to',
            'references',
            'styles',
            'depends_on',
            'wraps',
            'tests'
        )
    );

--rollback ALTER TABLE canonical_edges DROP CONSTRAINT canonical_edges_edge_kind_check;
--rollback ALTER TABLE canonical_edges ADD CONSTRAINT canonical_edges_edge_kind_check CHECK (edge_kind IN ('defines', 'executes', 'sources', 'reads_env', 'writes_env', 'mutates_host', 'imports', 'exposes_script', 'links_to', 'references', 'depends_on', 'wraps', 'tests'));
