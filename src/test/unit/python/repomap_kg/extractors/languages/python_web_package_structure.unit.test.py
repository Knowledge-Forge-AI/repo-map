from __future__ import annotations



PYTHON_WEB_OBSERVATION_EXPORTS = (
    "python_web_parse_error_observation",
    "python_web_profile_observation",
    "python_web_redaction_observation",
    "python_web_reference_observation",
)
PYTHON_WEB_ROUTE_EXPORTS = (
    "_fastapi_include_router_reference",
    "_fastapi_route_from_decorator",
    "_flask_add_url_rule_observation",
    "_flask_route_from_decorator",
)
PYTHON_WEB_DJANGO_EXPORTS = (
    "_django_app_observation",
    "_django_model_observation",
    "_django_setting_observations",
    "_django_urlpattern_observations",
    "_function_default_redactions",
    "add_config_redaction_if_needed",
)


def test_rootpkg29_python_web_reexports_observation_and_framework_builders() -> None:
    import repomap_kg.extractors.languages.python_web as web
    import repomap_kg.extractors.languages.python_web_observations as observations
    import repomap_kg.extractors.languages.python_web_route_frameworks as routes
    import repomap_kg.extractors.languages.python_web_django as django
    for name in PYTHON_WEB_OBSERVATION_EXPORTS:
        assert getattr(web, name) is getattr(observations, name)
    for name in PYTHON_WEB_ROUTE_EXPORTS:
        assert getattr(web, name) is getattr(routes, name)
    for name in PYTHON_WEB_DJANGO_EXPORTS:
        assert getattr(web, name) is getattr(django, name)
