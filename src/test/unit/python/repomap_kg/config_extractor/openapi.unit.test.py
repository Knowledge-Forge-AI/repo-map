import json
import unittest


from repomap_kg.extractors.config.generic import (
    extract_config_file_observations,
)


class ConfigExtractorOpenApiUnitTests(unittest.TestCase):
    def test_openapi3_json_emits_profile_observations_refs_and_redaction(self):
        observations = extract_config_file_observations(
            "contracts/openapi.json",
            json.dumps(
                {
                    "openapi": "3.0.3",
                    "info": {
                        "title": "Example Pets API",
                        "version": "1.0.0",
                        "description": "internal description must not be raw",
                    },
                    "servers": [
                        {"url": "https://user:fake-server-secret@api.example.invalid/v1"}
                    ],
                    "externalDocs": {"url": "https://docs.example.invalid/openapi"},
                    "paths": {
                        "/pets": {
                            "get": {
                                "operationId": "listPets",
                                "tags": ["pets"],
                                "summary": "List all pets",
                                "description": "operation prose must not be raw",
                                "parameters": [
                                    {
                                        "name": "limit",
                                        "in": "query",
                                        "schema": {"type": "integer"},
                                    }
                                ],
                                "responses": {
                                    "200": {
                                        "description": "ok",
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "$ref": "#/components/schemas/Pet"
                                                }
                                            }
                                        },
                                    },
                                    "400": {
                                        "description": "bad",
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "$ref": "./schemas/error.yaml#/Error"
                                                }
                                            }
                                        },
                                    },
                                    "422": {
                                        "description": "outside root",
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "$ref": "../../outside.yaml#/Problem"
                                                }
                                            }
                                        },
                                    },
                                },
                            },
                            "post": {
                                "operationId": "createPet",
                                "requestBody": {
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "$ref": "#/components/schemas/PetInput"
                                            },
                                            "example": {
                                                "password": "fake-openapi-password"
                                            },
                                        }
                                    }
                                },
                                "responses": {
                                    "201": {
                                        "description": "created",
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "$ref": (
                                                        "https://api.example.invalid/"
                                                        "schemas/pet.yaml#/Pet"
                                                    )
                                                }
                                            }
                                        },
                                    }
                                },
                            },
                        }
                    },
                    "components": {
                        "schemas": {
                            "Pet": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "token": {
                                        "type": "string",
                                        "example": "fake-openapi-token",
                                    },
                                },
                            },
                            "PetInput": {"type": "object"},
                        },
                        "securitySchemes": {
                            "ApiKeyAuth": {
                                "type": "apiKey",
                                "in": "header",
                                "name": "X-API-Key",
                            }
                        },
                    },
                    "security": [{"ApiKeyAuth": []}],
                }
            ),
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = {observation.kind for observation in observations}
        openapi_document = next(
            item for item in observations if item.kind == "openapi.document"
        )
        operation = next(
            item
            for item in observations
            if item.kind == "openapi.operation"
            and item.metadata["operation_id"] == "listPets"
        )
        references = [
            item for item in observations if item.kind == "openapi.reference"
        ]

        self.assertIn("config.document", kinds)
        self.assertIn("config.path", kinds)
        self.assertIn("config.reference", kinds)
        self.assertTrue(
            {
                "openapi.document",
                "openapi.info",
                "openapi.server",
                "openapi.path",
                "openapi.operation",
                "openapi.parameter",
                "openapi.request_body",
                "openapi.response",
                "openapi.schema",
                "openapi.component",
                "openapi.security_scheme",
                "openapi.tag",
                "openapi.reference",
                "openapi.example",
                "openapi.redaction",
            }.issubset(kinds)
        )
        self.assertEqual(openapi_document.metadata["spec_family"], "openapi3")
        self.assertEqual(openapi_document.metadata["spec_version"], "3.0.3")
        self.assertEqual(operation.metadata["method"], "GET")
        self.assertEqual(operation.metadata["path_template"], "/pets")
        self.assertTrue(operation.metadata["description_present"])
        self.assertIn(
            ("internal", "#/components/schemas/Pet", True),
            {
                (
                    item.metadata["reference_scope"],
                    item.metadata["ref_summary"],
                    item.metadata["not_fetched"],
                )
                for item in references
            },
        )
        self.assertIn(
            ("local_file", "./schemas/error.yaml#/Error", True),
            {
                (
                    item.metadata["reference_scope"],
                    item.metadata["ref_summary"],
                    item.metadata["not_fetched"],
                )
                for item in references
            },
        )
        self.assertTrue(
            any(
                item.metadata["reference_scope"] == "remote"
                and item.metadata["not_fetched"]
                for item in references
            )
        )
        self.assertTrue(
            any(
                item.kind == "openapi.parse_error"
                and item.metadata["error_kind"] == "openapi-local-ref-outside-root"
                for item in observations
            )
        )
        self.assertNotIn("fake-openapi-password", payload)
        self.assertNotIn("fake-openapi-token", payload)
        self.assertNotIn("fake-server-secret", payload)
        self.assertNotIn("../../outside.yaml#/Problem", payload)
        self.assertNotIn("internal description must not be raw", payload)
        self.assertNotIn("operation prose must not be raw", payload)

    def test_openapi_yaml_and_swagger2_emit_profile_observations(self):
        openapi_yaml = extract_config_file_observations(
            "service.openapi.yaml",
            """
openapi: 3.1.0
info:
  title: YAML API
  version: "2026.07"
paths:
  /health:
    get:
      operationId: healthCheck
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Health"
components:
  schemas:
    Health:
      type: object
      properties:
        status:
          type: string
""",
        )
        swagger_json = extract_config_file_observations(
            "swagger.json",
            json.dumps(
                {
                    "swagger": "2.0",
                    "info": {"title": "Swagger API", "version": "2.0"},
                    "host": "api.example.invalid",
                    "basePath": "/v2",
                    "schemes": ["https"],
                    "paths": {
                        "/widgets": {
                            "get": {
                                "operationId": "listWidgets",
                                "responses": {
                                    "200": {
                                        "description": "ok",
                                        "schema": {"$ref": "#/definitions/Widget"},
                                    }
                                },
                            }
                        }
                    },
                    "definitions": {"Widget": {"type": "object"}},
                    "securityDefinitions": {
                        "CookieAuth": {
                            "type": "apiKey",
                            "in": "header",
                            "name": "Cookie",
                        }
                    },
                }
            ),
        )

        yaml_kinds = {item.kind for item in openapi_yaml}
        swagger_kinds = {item.kind for item in swagger_json}
        yaml_document = next(
            item for item in openapi_yaml if item.kind == "openapi.document"
        )
        swagger_document = next(
            item for item in swagger_json if item.kind == "openapi.document"
        )
        swagger_response = next(
            item for item in swagger_json if item.kind == "openapi.response"
        )

        self.assertIn("config.document", yaml_kinds)
        self.assertIn("config.path", yaml_kinds)
        self.assertIn("openapi.document", yaml_kinds)
        self.assertIn("openapi.operation", yaml_kinds)
        self.assertIn("openapi.schema", yaml_kinds)
        self.assertEqual(yaml_document.metadata["format"], "yaml")
        self.assertEqual(yaml_document.metadata["spec_family"], "openapi3")
        self.assertEqual(yaml_document.metadata["spec_version"], "3.1.0")
        self.assertIn("openapi.document", swagger_kinds)
        self.assertIn("openapi.security_scheme", swagger_kinds)
        self.assertEqual(swagger_document.metadata["spec_family"], "swagger2")
        self.assertEqual(swagger_document.metadata["spec_version"], "2.0")
        self.assertEqual(swagger_response.metadata["status_code"], "200")
        self.assertEqual(swagger_response.metadata["media_types"], [])

    def test_openapi_parse_errors_limits_and_unsupported_specs_are_profile_raw(self):
        malformed_json = extract_config_file_observations(
            "openapi.json",
            '{"openapi": "3.0.0", "paths": ',
        )
        unsupported = extract_config_file_observations(
            "openapi.json",
            json.dumps({"openapi": "1.2.3", "info": {}, "paths": {}}),
        )
        too_many_paths = extract_config_file_observations(
            "openapi.json",
            json.dumps(
                {
                    "openapi": "3.0.0",
                    "info": {"title": "Too Many", "version": "1.0"},
                    "paths": {
                        f"/item-{index}": {
                            "get": {"responses": {"200": {"description": "ok"}}}
                        }
                        for index in range(130)
                    },
                }
            ),
        )

        self.assertIn("config.parse_error", {item.kind for item in malformed_json})
        self.assertIn("openapi.parse_error", {item.kind for item in malformed_json})
        self.assertIn("config.document", {item.kind for item in unsupported})
        self.assertIn("openapi.parse_error", {item.kind for item in unsupported})
        self.assertTrue(
            any(
                item.metadata["error_kind"] == "unsupported-openapi-version"
                for item in unsupported
                if item.kind == "openapi.parse_error"
            )
        )
        self.assertTrue(
            any(
                item.kind == "openapi.parse_error"
                and item.metadata["error_kind"] == "openapi-path-limit"
                for item in too_many_paths
            )
        )
