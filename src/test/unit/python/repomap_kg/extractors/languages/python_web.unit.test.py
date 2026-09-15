import unittest

from repomap_kg.extractors.languages.python import (
    PythonModuleIndex,
    extract_python_file_observations,
)


class PythonWebProfileUnitTests(unittest.TestCase):
    def test_flask_profile_observations_capture_static_routes_and_redactions(self):
        content = (
            "from flask import Flask, Blueprint\n"
            "\n"
            "app = Flask(__name__)\n"
            "bp = Blueprint('admin', __name__)\n"
            "app.config['SECRET_KEY'] = 'fake-flask-secret-value'\n"
            "\n"
            "@app.route('/users/<user_id>', methods=['GET', 'POST'])\n"
            "def user_detail():\n"
            "    return 'ok'\n"
            "\n"
            "@bp.post('/admin/token')\n"
            "def create_token():\n"
            "    return 'ok'\n"
            "\n"
            "def health_handler():\n"
            "    return 'ok'\n"
            "\n"
            "app.add_url_rule('/health', 'health', health_handler, methods=['GET'])\n"
            "\n"
            "@app.route(prefix + '/dynamic')\n"
            "def dynamic_route():\n"
            "    return 'ok'\n"
        )

        observations = extract_python_file_observations(
            "src/main/python/service/flask_app.py",
            content,
            module_index=PythonModuleIndex.empty(),
        )

        kinds = {item.kind for item in observations}
        payload = "\n".join(item.to_json_line() for item in observations)
        routes = [item for item in observations if item.kind == "python.flask_route"]
        route_by_name = {item.name: item for item in routes}
        references = [item for item in observations if item.kind == "python.reference"]
        diagnostics = [
            item
            for item in observations
            if item.kind == "python.parse_error"
            and item.metadata["error_kind"] == "dynamic-python-web-route"
        ]

        self.assertTrue(
            {
                "python.flask_app",
                "python.flask_blueprint",
                "python.flask_route",
                "python.reference",
                "python.redaction",
            }.issubset(kinds)
        )
        self.assertEqual(route_by_name["user_detail"].metadata["route_path"], "/users/<user_id>")
        self.assertEqual(route_by_name["user_detail"].metadata["http_methods"], ["GET", "POST"])
        self.assertEqual(route_by_name["create_token"].metadata["http_methods"], ["POST"])
        self.assertEqual(route_by_name["health_handler"].metadata["route_path"], "/health")
        self.assertEqual(route_by_name["dynamic_route"].metadata["route_path_kind"], "dynamic")
        self.assertTrue(diagnostics)
        self.assertTrue(any(item.metadata["reference_kind"] == "flask_route_handler" for item in references))
        self.assertNotIn("fake-flask-secret-value", payload)

    def test_fastapi_profile_observations_capture_routes_dependencies_and_redactions(self):
        content = (
            "from fastapi import FastAPI, APIRouter, Depends\n"
            "\n"
            "app = FastAPI(title='Fixture')\n"
            "router = APIRouter()\n"
            "\n"
            "def require_user(api_key='fake-fastapi-secret-default'):\n"
            "    return api_key\n"
            "\n"
            "@app.get('/items/{item_id}', response_model=Item, tags=['items'], summary='read an item safely')\n"
            "async def read_item(item_id: str, user=Depends(require_user)):\n"
            "    return {'item_id': item_id}\n"
            "\n"
            "@router.api_route('/bulk', methods=['POST', 'PUT'], description='bulk operation details')\n"
            "def bulk_items():\n"
            "    return []\n"
            "\n"
            "app.include_router(router)\n"
            "\n"
            "@app.get(prefix + '/dynamic')\n"
            "def dynamic_route():\n"
            "    return {}\n"
        )

        observations = extract_python_file_observations(
            "src/main/python/service/fastapi_app.py",
            content,
            module_index=PythonModuleIndex.empty(),
        )

        kinds = {item.kind for item in observations}
        payload = "\n".join(item.to_json_line() for item in observations)
        routes = [item for item in observations if item.kind == "python.fastapi_route"]
        route_by_name = {item.name: item for item in routes}
        dependencies = [
            item for item in observations if item.kind == "python.fastapi_dependency"
        ]
        references = [item for item in observations if item.kind == "python.reference"]
        diagnostics = [
            item
            for item in observations
            if item.kind == "python.parse_error"
            and item.metadata["error_kind"] == "dynamic-python-web-route"
        ]

        self.assertTrue(
            {
                "python.fastapi_app",
                "python.fastapi_router",
                "python.fastapi_route",
                "python.fastapi_dependency",
                "python.reference",
                "python.redaction",
            }.issubset(kinds)
        )
        self.assertEqual(route_by_name["read_item"].metadata["route_path"], "/items/{item_id}")
        self.assertEqual(route_by_name["read_item"].metadata["http_methods"], ["GET"])
        self.assertTrue(route_by_name["read_item"].metadata["summary_present"])
        self.assertIn("summary_sha256", route_by_name["read_item"].metadata)
        self.assertNotIn("read an item safely", payload)
        self.assertEqual(route_by_name["bulk_items"].metadata["http_methods"], ["POST", "PUT"])
        self.assertEqual(route_by_name["dynamic_route"].metadata["route_path_kind"], "dynamic")
        self.assertTrue(dependencies)
        self.assertTrue(any(item.metadata["reference_kind"] == "fastapi_include_router" for item in references))
        self.assertTrue(diagnostics)
        self.assertNotIn("fake-fastapi-secret-default", payload)

    def test_django_profile_observations_capture_urls_models_settings_and_redactions(self):
        url_content = (
            "from django.urls import path, re_path, include\n"
            "from . import views\n"
            "\n"
            "urlpatterns = [\n"
            "    path('users/', views.user_list, name='users'),\n"
            "    re_path(r'^items/(?P<slug>[-\\\\w]+)/$', views.ItemView.as_view()),\n"
            "    path('api/', include('fixture.api.urls')),\n"
            "    path(dynamic_prefix, views.dynamic_view),\n"
            "]\n"
        )
        model_content = (
            "from django.db import models\n"
            "from django.apps import AppConfig\n"
            "\n"
            "class InventoryItem(models.Model):\n"
            "    name = models.CharField(max_length=64)\n"
            "    active = models.BooleanField(default=True)\n"
            "\n"
            "class InventoryConfig(AppConfig):\n"
            "    name = 'inventory'\n"
        )
        settings_content = (
            "SECRET_KEY = 'fake-django-secret-key'\n"
            "DATABASE_URL = 'postgres://user:fake-db-secret@example.invalid/app'\n"
            "INSTALLED_APPS = ['inventory']\n"
        )

        url_observations = extract_python_file_observations(
            "src/main/python/project/urls.py",
            url_content,
            module_index=PythonModuleIndex.empty(),
        )
        model_observations = extract_python_file_observations(
            "src/main/python/project/app/models.py",
            model_content,
            module_index=PythonModuleIndex.empty(),
        )
        settings_observations = extract_python_file_observations(
            "src/main/python/project/settings.py",
            settings_content,
            module_index=PythonModuleIndex.empty(),
        )
        observations = (*url_observations, *model_observations, *settings_observations)

        kinds = {item.kind for item in observations}
        payload = "\n".join(item.to_json_line() for item in observations)
        patterns = [item for item in observations if item.kind == "python.django_urlpattern"]
        models = [item for item in observations if item.kind == "python.django_model"]
        setting_refs = [
            item for item in observations if item.kind == "python.django_setting_reference"
        ]
        users_path = next(
            item
            for item in patterns
            if item.metadata.get("route_path") == "users/"
        )
        regex_path = next(
            item
            for item in patterns
            if item.metadata["urlpattern_kind"] == "re_path"
        )
        include_path = next(
            item
            for item in patterns
            if item.metadata["urlpattern_kind"] == "include"
        )
        diagnostics = [
            item
            for item in observations
            if item.kind == "python.parse_error"
            and item.metadata["error_kind"] == "dynamic-python-web-route"
        ]

        self.assertTrue(
            {
                "python.django_app",
                "python.django_urlpattern",
                "python.django_view",
                "python.django_model",
                "python.django_setting_reference",
                "python.reference",
                "python.redaction",
            }.issubset(kinds)
        )
        self.assertEqual(users_path.metadata["route_path"], "users/")
        self.assertEqual(regex_path.metadata["route_path_kind"], "regex_literal")
        self.assertEqual(include_path.metadata["include_target"], "fixture.api.urls")
        self.assertEqual(models[0].metadata["model_name"], "InventoryItem")
        self.assertEqual(models[0].metadata["model_field_count"], 2)
        self.assertIn("SECRET_KEY", {item.name for item in setting_refs})
        self.assertTrue(diagnostics)
        self.assertNotIn("fake-django-secret-key", payload)
        self.assertNotIn("fake-db-secret", payload)

    def test_python_web_profile_observations_are_bounded_with_safe_diagnostics(self):
        content = "from flask import Flask\napp = Flask(__name__)\n"
        for index in range(80):
            content += (
                f"@app.get('/route-{index}')\n"
                f"def route_{index}():\n"
                "    return 'ok'\n"
            )

        observations = extract_python_file_observations(
            "src/main/python/service/many_routes.py",
            content,
            module_index=PythonModuleIndex.empty(),
        )

        routes = [item for item in observations if item.kind == "python.flask_route"]
        diagnostics = [
            item
            for item in observations
            if item.kind == "python.parse_error"
            and item.metadata["error_kind"] == "python-web-profile-limit"
        ]

        self.assertLessEqual(len(routes), 64)
        self.assertTrue(diagnostics)
        self.assertNotIn("route_79", "\n".join(item.to_json_line() for item in diagnostics))

    def test_python_web_profile_redacts_credentialed_routes_and_secret_assignments(self):
        content = (
            "from flask import Flask\n"
            "from fastapi import FastAPI\n"
            "\n"
            "app = Flask(__name__)\n"
            "api = FastAPI()\n"
            "API_TOKEN = 'fake-web-assignment-secret'\n"
            "\n"
            "@app.route('https://user:fake-route-secret@example.invalid/path')\n"
            "def unsafe_route():\n"
            "    return 'redacted'\n"
            "\n"
            "@api.post('/created', status_code=201)\n"
            "def create_item():\n"
            "    return {}\n"
        )
        settings_content = "DEBUG = True\n"

        observations = extract_python_file_observations(
            "src/main/python/service/mixed_web.py",
            content,
            module_index=PythonModuleIndex.empty(),
        )
        settings_observations = extract_python_file_observations(
            "src/main/python/service/settings.py",
            settings_content,
            module_index=PythonModuleIndex.empty(),
        )
        payload = "\n".join(
            item.to_json_line()
            for item in (*observations, *settings_observations)
        )
        flask_route = next(
            item for item in observations if item.kind == "python.flask_route"
        )
        fastapi_route = next(
            item for item in observations if item.kind == "python.fastapi_route"
        )
        setting = next(
            item
            for item in settings_observations
            if item.kind == "python.django_setting_reference"
        )

        self.assertEqual(flask_route.metadata["route_path_kind"], "redacted")
        self.assertTrue(flask_route.metadata["redacted"])
        self.assertEqual(fastapi_route.metadata["status_code"], 201)
        self.assertEqual(setting.name, "DEBUG")
        self.assertFalse(setting.metadata["redacted"])
        self.assertIn("secret-like-assignment", payload)
        self.assertNotIn("fake-web-assignment-secret", payload)
        self.assertNotIn("fake-route-secret", payload)
