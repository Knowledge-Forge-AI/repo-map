import unittest

from repomap_kg.extractors.languages.javascript import extract_javascript_file_observations


class JavaScriptExtractorUnitTests(unittest.TestCase):
    def test_js5_detects_node_entrypoints_exports_requires_and_env_redaction(self):
        content = (
            'const http = require("node:http");\nconst express = require("express");\n'
            "module.exports = createServer;\nexports.health = health;\n"
            "const secret = process.env.SECRET_TOKEN;\nconst publicPort = import.meta.env.PUBLIC_PORT;\n"
        )

        observations = extract_javascript_file_observations("src/server.ts", content)
        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = {item.kind for item in observations}
        requires = [item for item in observations if item.kind == "node.require"]
        exports = [item for item in observations if item.kind == "node.export"]
        entrypoint = next(item for item in observations if item.kind == "node.entrypoint")
        env_refs = [
            item for item in observations
            if item.kind == "js.framework_reference" and item.metadata.get("reference_kind") == "environment"
        ]

        self.assertEqual(observations[0].metadata["profile"], "node")
        self.assertIn("node.require", kinds)
        self.assertIn("node.export", kinds)
        self.assertEqual(entrypoint.metadata["entrypoint_reason"], "entrypoint-path")
        self.assertIn("express", {item.metadata["specifier"] for item in requires})
        self.assertIn("module.exports", {item.metadata["export_kind"] for item in exports})
        self.assertIn("exports.name", {item.metadata["export_kind"] for item in exports})
        self.assertTrue(any(item.metadata.get("redacted") for item in env_refs))
        self.assertTrue(any(item.metadata.get("env_name") == "PUBLIC_PORT" for item in env_refs))
        self.assertNotIn("SECRET_TOKEN", payload)

    def test_js5_detects_express_routes_middleware_and_error_handlers(self):
        content = (
            'const express = require("express");\nconst app = express();\nconst router = express.Router();\n'
            'app.use("/api", router);\napp.get("/health", authMiddleware, healthHandler);\n'
            'router.post("/users", validateUser, createUser);\napp.get(routeName, dynamicHandler);\n'
            "app.use((err, req, res, next) => next(err));\n"
        )

        observations = extract_javascript_file_observations("src/app.js", content)
        routes = [item for item in observations if item.kind == "express.route"]
        route_keys = {(item.metadata["route_method"], item.metadata.get("route_pattern")) for item in routes}
        dynamic_route = next(item for item in routes if item.metadata["route_method"] == "GET" and item.metadata["dynamic"])
        health_route = next(item for item in routes if item.metadata.get("route_pattern") == "/health")

        self.assertIn("express.app", {item.kind for item in observations})
        self.assertIn("express.router", {item.kind for item in observations})
        self.assertIn("express.middleware", {item.kind for item in observations})
        self.assertIn("express.error_handler", {item.kind for item in observations})
        self.assertIn("js.route", {item.kind for item in observations})
        self.assertIn(("GET", "/health"), route_keys)
        self.assertIn(("POST", "/users"), route_keys)
        self.assertIn(("USE", "/api"), route_keys)
        self.assertEqual(health_route.metadata["middleware_count"], 1)
        self.assertEqual(health_route.metadata["handler_name"], "healthHandler")
        self.assertEqual(dynamic_route.metadata["dynamic_reason"], "dynamic-route-path")

    def test_js5_detects_nest_modules_controllers_providers_and_routes(self):
        content = (
            "@Module({ imports: [UsersModule], controllers: [AppController], providers: [AppService] })\n"
            'export class AppModule {}\n@Controller("users")\n'
            'export class UsersController {\n  @Get(":id")\n  getUser(@Param(\'id\') id: string) {}\n}\n'
            "@Injectable()\nexport class AppService {}\n"
        )

        observations = extract_javascript_file_observations("src/app.controller.ts", content)
        kinds = {item.kind for item in observations}
        module = next(item for item in observations if item.kind == "nest.module")
        controller = next(item for item in observations if item.kind == "nest.controller")
        route = next(item for item in observations if item.kind == "nest.route")

        self.assertEqual(observations[0].metadata["profile"], "nestjs")
        self.assertIn("nest.decorator", kinds)
        self.assertIn("nest.provider", kinds)
        self.assertEqual(module.metadata["module_name"], "AppModule")
        self.assertEqual(module.metadata["controllers"], ["AppController"])
        self.assertEqual(module.metadata["providers"], ["AppService"])
        self.assertEqual(controller.metadata["controller_prefix"], "users")
        self.assertEqual(route.metadata["route_method"], "GET")
        self.assertEqual(route.metadata["route_pattern"], ":id")
        self.assertEqual(route.metadata["controller_name"], "UsersController")

    def test_js5_detects_next_pages_and_app_router_conventions(self):
        page = extract_javascript_file_observations(
            "pages/users/[id].tsx", "import Link from 'next/link';\nexport default function UserPage() { return <Link href=\"/\" />; }\n",
        )
        api = extract_javascript_file_observations(
            "pages/api/users.ts", "export default function handler(req, res) { res.json({ ok: true }); }\n",
        )
        app_route = extract_javascript_file_observations(
            "app/api/health/route.ts",
            "import { NextResponse } from 'next/server';\nexport async function GET() { return NextResponse.json({ ok: true }); }\nexport async function POST() {}\n",
        )
        app_page = extract_javascript_file_observations(
            "app/users/[id]/page.tsx", "import { useRouter } from 'next/navigation';\nexport default function Page() { return null; }\n",
        )

        page_route = next(item for item in page if item.kind == "next.page")
        api_route = next(item for item in api if item.kind == "next.api_route")
        route_file = next(item for item in app_route if item.kind == "next.app_route")
        http_methods = {item.metadata["http_method"] for item in app_route if item.kind == "next.route"}
        framework_refs = [item for item in page + app_page if item.kind == "js.framework_reference"]

        self.assertEqual(page[0].metadata["profile"], "next")
        self.assertEqual(page_route.metadata["route_pattern"], "/users/[id]")
        self.assertEqual(api_route.metadata["route_pattern"], "/api/users")
        self.assertEqual(route_file.metadata["route_file_kind"], "route")
        self.assertEqual(route_file.metadata["route_pattern"], "/api/health")
        self.assertEqual(http_methods, {"GET", "POST"})
        self.assertTrue(any(item.metadata.get("specifier") == "next/link" for item in framework_refs))
        self.assertTrue(any(item.metadata.get("specifier") == "next/navigation" for item in framework_refs))

    def test_js5_improves_jest_raw_observations_for_mocks_spies_and_matchers(self):
        content = (
            "import { describe, expect, jest, test } from '@jest/globals';\n"
            "describe('math helpers', () => {\n  beforeEach(() => jest.fn());\n"
            "  test('adds numbers', () => {\n    jest.mock('./math');\n    jest.spyOn(console, 'log');\n"
            "    expect(1 + 1).toBe(2);\n    expect([1, 2]).toContain(2);\n  });\n});\n"
        )

        observations = extract_javascript_file_observations("src/math.test.ts", content)
        kinds = {item.kind for item in observations}
        matchers = {matcher for item in observations if item.kind == "jest.expectation" for matcher in item.metadata["matchers"]}
        mock_kinds = {item.metadata["mock_kind"] for item in observations if item.kind == "jest.mock"}

        self.assertIn("js.test_suite", kinds)
        self.assertIn("js.test_case", kinds)
        self.assertIn("jest.suite", kinds)
        self.assertIn("jest.test", kinds)
        self.assertIn("jest.expectation", kinds)
        self.assertIn("mock", mock_kinds)
        self.assertIn("spyOn", mock_kinds)
        self.assertIn("toBe", matchers)
        self.assertIn("toContain", matchers)

    def test_js5_detects_jquery_selectors_events_ajax_and_plugins(self):
        content = (
            "$('.save-button').on('click', save);\n$('#signup').submit(handleSubmit);\n$(document).ready(init);\n"
            '$.ajax({ url: "https://example.invalid/api?token=fake-jquery-token", method: "POST" });\n'
            '$.get("/local/data.json");\n$.fn.flashMessage = function () { return this; };\n'
        )

        observations = extract_javascript_file_observations("public/jquery-widget.js", content)
        payload = "\n".join(item.to_json_line() for item in observations)
        selectors = [item for item in observations if item.kind == "jquery.selector"]
        events = [item for item in observations if item.kind == "jquery.event"]
        ajax = [item for item in observations if item.kind == "jquery.ajax"]
        plugins = [item for item in observations if item.kind == "jquery.plugin_reference"]

        self.assertEqual(observations[0].metadata["profile"], "jquery")
        self.assertIn(".save-button", {item.metadata["selector"] for item in selectors})
        self.assertIn("click", {item.metadata["event_name"] for item in events})
        self.assertIn("submit", {item.metadata["event_name"] for item in events})
        self.assertTrue(any(item.metadata["ajax_method"] == "ajax" for item in ajax))
        self.assertTrue(any(item.metadata["ajax_method"] == "get" for item in ajax))
        self.assertEqual(plugins[0].metadata["plugin_name"], "flashMessage")
        self.assertIn("js.dom_selector", {item.kind for item in observations})
        self.assertIn("js.dom_event", {item.kind for item in observations})
        self.assertIn("js.ajax_reference", {item.kind for item in observations})
        self.assertNotIn("fake-jquery-token", payload)

    def test_js5_limits_long_jquery_selectors(self):
        long_selector = "." + ("a" * 200)
        content = f'$("{long_selector}").click(handle);\n'

        observations = extract_javascript_file_observations("public/jquery-widget.js", content)
        payload = "\n".join(item.to_json_line() for item in observations)

        self.assertNotIn(long_selector, payload)
        self.assertFalse(any(item.kind == "jquery.selector" and item.metadata.get("selector") == long_selector for item in observations))
        self.assertTrue(any(item.kind == "js.parse_error" and item.metadata.get("error_kind") == "framework-selector-limit" for item in observations))

    def test_extracts_imports_exports_functions_classes_and_references(self):
        content = (
            'import React, { useEffect } from "react";\n'
            'import { helper } from "./util.mjs";\n'
            'import "./styles.css";\n'
            'export { helper } from "./util.mjs";\n'
            "export function main() {\n"
            '  return fetch("https://example.invalid/api?token=fake-js-token");\n'
            "}\n"
            "class Runner {\n"
            "  start() {\n"
            "  }\n"
            "}\n"
            "const App = () => <main />;\n"
            "const COUNT = 3;\n"
        )

        observations = extract_javascript_file_observations(
            "src/index.js",
            content,
            repository_paths=frozenset(
                {
                    "src/index.js",
                    "src/util.mjs",
                    "src/styles.css",
                }
            ),
        )
        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = {item.kind for item in observations}
        references = {
            (item.metadata.get("reference_kind"), item.target)
            for item in observations
            if item.kind == "js.reference"
        }

        self.assertEqual(observations[0].kind, "js.file")
        self.assertEqual(observations[0].target, "js.file:file%3Asrc%2Findex.js")
        self.assertEqual(observations[0].metadata["profile"], "react")
        self.assertIn("js.module", kinds)
        self.assertIn("js.import", kinds)
        self.assertIn("js.export", kinds)
        self.assertIn("js.function", kinds)
        self.assertIn("js.class", kinds)
        self.assertIn("js.method", kinds)
        self.assertIn("js.variable", kinds)
        self.assertIn("js.component", kinds)
        self.assertIn(("import", "external:js-package:react"), references)
        self.assertIn(("import", "file:src/util.mjs"), references)
        self.assertIn(("side_effect_import", "file:src/styles.css"), references)
        self.assertIn(("fetch", "external.url:https%3A%2F%2Fexample.invalid%2Fapi%3Ftoken%3DREDACTED"), references)
        self.assertNotIn("fake-js-token", payload)

    def test_detects_typescript_interfaces_types_enums_and_dynamic_imports(self):
        content = (
            "import type { Widget } from './types';\n"
            "export interface ServiceConfig { name: string }\n"
            "type Mode = 'fast' | 'safe';\n"
            "enum Status { Ready, Done }\n"
            "const loader = () => import(`./pages/${name}.tsx`);\n"
            "const LazyPanel = React.lazy(() => import('./Panel'));\n"
        )

        observations = extract_javascript_file_observations(
            "src/app.ts",
            content,
            repository_paths=frozenset(
                {
                    "src/app.ts",
                    "src/types.ts",
                    "src/Panel.tsx",
                }
            ),
        )
        kinds = {item.kind for item in observations}
        targets = {item.target for item in observations if item.kind == "js.reference"}
        dynamic = [
            item for item in observations
            if item.kind == "js.parse_error" and item.metadata.get("dynamic")
        ]

        self.assertEqual(observations[0].metadata["format"], "typescript")
        self.assertIn("js.interface", kinds)
        self.assertIn("js.type_alias", kinds)
        self.assertIn("js.enum", kinds)
        self.assertIn("file:src/types.ts", targets)
        self.assertIn("file:src/Panel.tsx", targets)
        self.assertTrue(dynamic)

    def test_detects_jest_suites_and_tests_without_execution(self):
        content = (
            "import { describe, expect, test } from '@jest/globals';\n"
            "describe('math helpers', () => {\n"
            "  test('adds numbers', () => {\n"
            "    expect(1 + 1).toBe(2);\n"
            "  });\n"
            "});\n"
        )

        observations = extract_javascript_file_observations(
            "src/jest/example.test.js",
            content,
        )
        test_suite = next(item for item in observations if item.kind == "js.test_suite")
        test_case = next(item for item in observations if item.kind == "js.test_case")
        expectation = next(
            item for item in observations if item.kind == "js.test_expectation"
        )

        self.assertEqual(test_suite.metadata["profile"], "jest")
        self.assertEqual(test_suite.metadata["test_framework"], "jest")
        self.assertEqual(test_suite.metadata["test_name_summary"], "math helpers")
        self.assertEqual(test_case.metadata["test_name_summary"], "adds numbers")
        self.assertTrue(test_case.target is not None and test_case.target.startswith("js.test_case:"))
        self.assertEqual(expectation.metadata["expectation_count"], 1)

    def test_detects_react_angular_vue_and_report_asset_profiles(self):
        react = extract_javascript_file_observations(
            "src/react/App.jsx",
            (
                "import React, { useState } from 'react';\n"
                "export function App() {\n"
                "  const [count, setCount] = useState(0);\n"
                "  return <Route path=\"/home\" element={<Home />} />;\n"
                "}\n"
            ),
        )
        angular = extract_javascript_file_observations(
            "src/angular/app.component.ts",
            (
                "import { Component } from '@angular/core';\n"
                "@Component({ selector: 'app-root', templateUrl: './app.html', styleUrls: ['./app.css'] })\n"
                "export class AppComponent {}\n"
            ),
            repository_paths=frozenset(
                {
                    "src/angular/app.component.ts",
                    "src/angular/app.html",
                    "src/angular/app.css",
                }
            ),
        )
        vue = extract_javascript_file_observations(
            "src/vue/main.ts",
            "import { createApp, defineComponent } from 'vue';\nconst App = defineComponent({});\n",
        )
        report = extract_javascript_file_observations(
            "public/report.js",
            "export function renderReport() {}\n//# sourceMappingURL=report.js.map\n",
            repository_paths=frozenset({"public/report.js", "public/report.js.map"}),
        )

        self.assertIn("js.component", {item.kind for item in react})
        self.assertIn("js.hook", {item.kind for item in react})
        self.assertIn("js.route", {item.kind for item in react})
        self.assertEqual(angular[0].metadata["profile"], "angular")
        self.assertIn("file:src/angular/app.html", {item.target for item in angular if item.kind == "js.reference"})
        self.assertIn("file:src/angular/app.css", {item.target for item in angular if item.kind == "js.reference"})
        self.assertEqual(vue[0].metadata["profile"], "vue")
        self.assertEqual(report[0].metadata["profile"], "test_report_asset")
        self.assertIn(
            "file:public/report.js.map",
            {item.target for item in report if item.kind == "js.reference"},
        )

    def test_dynamic_constructs_and_secret_literals_are_safe(self):
        content = (
            'const apiToken = "fake-js-secret";\n'
            "const mod = require(name);\n"
            "const target = import(`./${name}.js`);\n"
            "eval('alert(1)');\n"
            "new Function('return secret')();\n"
            "const envValue = process.env.SECRET_TOKEN;\n"
        )

        observations = extract_javascript_file_observations("dynamic.js", content)
        payload = "\n".join(item.to_json_line() for item in observations)
        dynamic = [
            item for item in observations
            if item.metadata.get("dynamic") or item.metadata.get("redacted")
        ]
        variable = next(
            item for item in observations
            if item.kind == "js.variable" and item.name == "apiToken"
        )

        self.assertNotIn("fake-js-secret", payload)
        self.assertGreaterEqual(len(dynamic), 4)
        self.assertTrue(variable.metadata["redacted"])
        self.assertIn("js.parse_error", {item.kind for item in observations})


if __name__ == "__main__":
    unittest.main()
