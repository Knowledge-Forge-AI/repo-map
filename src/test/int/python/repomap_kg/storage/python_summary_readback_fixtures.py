from __future__ import annotations
from contextlib import contextmanager
import tempfile
from pathlib import Path
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.storage_integration import (
    python_ecosystem_fixture,
    python_web_fixture,
)
from repomap_kg.observations import RawObservation
from repomap_kg.storage.sql_core import sql_literal



def _assert_fixture_anchors() -> None:
    ecosystem = python_ecosystem_fixture("dogfood")
    assert (ecosystem / "requirements.txt").is_file()
    assert (ecosystem / "requirements-dev.txt").is_file()
    assert (ecosystem / "pyproject.toml").is_file()
    web = python_web_fixture()
    assert (web / "flask" / "basic" / "app.py").is_file()
    assert (web / "fastapi" / "basic" / "main.py").is_file()
    assert (web / "django" / "basic" / "manage.py").is_file()
    assert (web / "malformed" / "bad.py").is_file()


@contextmanager
def _fixture_jsonl(observations: tuple[RawObservation, ...]):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        path = Path(handle.name)
        for observation in observations:
            handle.write(observation.to_json_line())
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _python_observations() -> tuple[RawObservation, ...]:
    kinds = (
        "python.package_file",
        "python.pyproject",
        "python.requirement",
        "python.dependency_group",
        "python.build_system",
        "python.entry_point",
        "python.tool_config",
        "python.test_file",
        "python.unittest_case",
        "python.pytest_test",
        "python.test_function",
        "python.test_method",
        "python.test_fixture",
        "python.test_parametrize",
        "python.test_assertion",
        "python.flask_app",
        "python.flask_blueprint",
        "python.flask_route",
        "python.fastapi_app",
        "python.fastapi_router",
        "python.fastapi_route",
        "python.fastapi_dependency",
        "python.django_project",
        "python.django_app",
        "python.django_urlpattern",
        "python.django_view",
        "python.django_model",
        "python.django_setting_reference",
    )
    observations = [
        _observation(kind, index, path="synthetic/repomap_kg/profile.py")
        for index, kind in enumerate(kinds)
    ]
    observations[0] = _observation(
        "python.package_file",
        0,
        path="synthetic/repomap_kg/requirements.txt",
        file_family="requirements.txt",
        source_format="python-requirements",
        project_name="repo-map-synthetic",
        package_name="private-package-name",
        package_version="private-package-version",
        package_extras="private-package-extras",
        version_constraint="private-version-constraint",
        direct_url="https://user:password@private.invalid/package",
        vcs_url="private-vcs-url",
        index_url="private-index-url",
        extra_index_url="private-extra-index-url",
        find_links_url="private-find-links-url",
        local_path="private-local-package-path",
        module_path="private-module-path",
        source_path="private-source-path",
        include_path="private-include-path",
        constraint_path="private-constraint-path",
        configuration_path="private-configuration-path",
        import_target="private-import-target",
        module_name="private-module-name",
        class_name="private-class-name",
        function_name="private-function-name",
        method_name="private-method-name",
        test_name="private-test-name",
        fixture_name="private-fixture-name",
        route_name="private-route-name",
        endpoint_name="private-endpoint-name",
        command="private-package-command",
        script_name="private-script-name",
        plugin_name="private-plugin-name",
        entry_point="private-entry-point-name",
        flask_setting="private-flask-setting",
        fastapi_setting="private-fastapi-setting",
        django_setting="private-django-setting",
        environment_name="private-environment-name",
        environment_value="private-environment-value",
        test_command="private-test-command",
        framework_command="private-framework-command",
        application_command="private-application-command",
        parser_diagnostic="private-parser-diagnostic",
        dynamic_expression="private-dynamic-expression",
        source_snippet="private-python-source-snippet",
        raw_toml="private-raw-toml",
        raw_ini="private-raw-ini",
        raw_requirements="private-raw-requirements",
        raw_python="private-raw-python",
        raw_configuration="private-raw-configuration",
        credential="private-python-credential",
        secret="private-python-secret",
        token="private-python-token",
    )
    observations.extend(
        (
            _observation(
                "python.reference",
                40,
                reference_kind="direct_url",
                source_format="python-requirements",
                not_fetched=True,
            ),
            _observation(
                "python.reference",
                41,
                reference_kind="local_path",
                source_format="pyproject.toml",
                resolution="local",
            ),
            _observation(
                "python.reference",
                42,
                reference_kind="index_url",
                not_fetched=True,
            ),
            _observation("python.reference", 43, framework="flask"),
            _observation(
                "python.redaction", 50, redaction_reason="credentialed-url"
            ),
            _observation("python.redaction", 51, redaction_reason="private-index"),
            _observation("python.redaction", 52, redaction_reason="secret-config"),
            _observation("python.redaction", 53, framework="django"),
            _observation("python.parse_error", 60, error_kind="parser-limit"),
            _observation(
                "python.parse_error", 61, error_kind="dynamic-expression", dynamic=True
            ),
            _observation("python.module", 70, name="synthetic.pkg"),
            _observation("python.class", 71, name="SyntheticClass", module="synthetic.pkg"),
            _observation("python.function", 72, name="synthetic_function", module="synthetic.pkg"),
            _observation(
                "python.method",
                73,
                name="synthetic_method",
                module="synthetic.pkg",
                **{"class": "SyntheticClass"},
            ),
            _observation(
                "python.import",
                74,
                module="synthetic.pkg",
                imported_module="synthetic.dependency",
                resolution="external",
            ),
            *_config_observations(),
        )
    )
    return tuple(observations)


def _python_empty_observations() -> tuple[RawObservation, ...]:
    return (
        _observation("file", 0, path="synthetic/empty.txt", language="text"),
        *_config_observations(),
    )


def _config_observations() -> tuple[RawObservation, ...]:
    return (
        _observation("config.document", 80, path="synthetic/config.yaml"),
        _observation(
            "config.path", 81, path="synthetic/config.yaml", pointer="/service"
        ),
        _observation(
            "config.reference",
            82,
            path="synthetic/config.yaml",
            pointer="/service",
            target="file:synthetic/target.yaml",
        ),
    )


def _observation(
    kind: str,
    index: int,
    *,
    path: str = "synthetic/profile.py",
    name: str | None = None,
    target: str | None = None,
    **metadata: object,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=f"{path}#{kind}:{index}",
        path=path,
        confidence="extracted",
        extractor="psycopg80-fixture",
        extractor_version="1",
        name=name or f"synthetic-{index}",
        target=target,
        metadata=metadata,
    )


def _insert_python_empty_canonical_nodes(postgres, *, root_path: str) -> None:
    root = sql_literal(root_path)
    values = ", ".join(
        f"((SELECT id FROM repositories WHERE root_path = {root}), 1, "
        f"{sql_literal(key)}, {sql_literal(kind)}, {sql_literal(display)}, "
        "'{}'::jsonb, 'extracted')"
        for key, kind, display in (
            ("python.module:synthetic.empty", "python.module", "synthetic.empty"),
            (
                "python.class:synthetic.empty.SyntheticClass",
                "python.class",
                "SyntheticClass",
            ),
            (
                "python.function:synthetic.empty.synthetic_function",
                "python.function",
                "synthetic_function",
            ),
            (
                "python.method:synthetic.empty.SyntheticClass.synthetic_method",
                "python.method",
                "SyntheticClass.synthetic_method",
            ),
        )
    )
    postgres.psql_scalar(
        "INSERT INTO canonical_nodes(repository_id, graph_key_version, "
        "canonical_key, kind, display_name, metadata_json, confidence) VALUES "
        f"{values}; SELECT COUNT(*)::text FROM canonical_nodes WHERE "
        f"repository_id = (SELECT id FROM repositories WHERE root_path = {root});"
    )


def _load_fixture(
    fixture_path: Path,
    *,
    root_path: str,
    repository_name: str,
    postgres,
) -> None:
    exit_code, _stdout, stderr = run_repo_map_in_process(
        "storage",
        "load-files",
        str(fixture_path),
        "--repository-name",
        repository_name,
        *_cli_connection_args(postgres, root_path=root_path),
        "--psql-command",
        postgres.psql_command,
        "--json",
    )
    assert exit_code == 0, stderr


def _cli_connection_args(postgres, *, root_path: str) -> tuple[str, ...]:
    return (
        "--root-path",
        root_path,
        "--pg-host",
        str(postgres.socket_dir),
        "--pg-port",
        str(postgres.port),
        "--pg-user",
        postgres.user,
        "--pg-database",
        postgres.database,
    )
