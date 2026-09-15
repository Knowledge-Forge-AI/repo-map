import json
import unittest

from repomap_kg.extractors.config.generic import extract_config_file_observations
from repomap_kg.extractors.config.openapi_helpers import (
    _is_openapi_document,
    _openapi_bounded_string,
    _openapi_oauth_flow_names,
    _openapi_pointer_is_redacted,
    _openapi_reference_scope,
    _openapi_safe_string,
    _openapi_scope_names,
    _openapi_sensitive_key,
    _openapi_string_list,
)


class ConfigExtractorOpenApiBoundariesUnitTests(unittest.TestCase):
    def test_openapi3_components_webhooks_and_security_schemes(self):
        payload = {
            "openapi": "3.1.0",
            "info": {
                "title": "Webhooks and Components API",
                "version": "2.0.0",
            },
            "servers": [
                {
                    "url": "https://{env}.example.com/v2",
                    "variables": {
                        "env": {"default": "api", "enum": ["api", "staging"]}
                    },
                }
            ],
            "webhooks": {
                "newPet": {
                    "post": {
                        "operationId": "onNewPet",
                        "responses": {
                            "200": {"description": "Event received"}
                        }
                    }
                }
            },
            "components": {
                "schemas": {
                    "Pet": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "name": {"type": "string"},
                        }
                    }
                },
                "parameters": {
                    "limitParam": {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer"}
                    }
                },
                "securitySchemes": {
                    "apiAuth": {
                        "type": "oauth2",
                        "flows": {
                            "implicit": {
                                "authorizationUrl": "https://example.com/oauth/authorize",
                                "scopes": {"read:pets": "read pets"}
                            }
                        }
                    },
                    "bearerAuth": {
                        "type": "http",
                        "scheme": "bearer"
                    }
                }
            }
        }
        obs = extract_config_file_observations(
            "contracts/webhooks.json",
            json.dumps(payload),
        )
        self.assertEqual(obs[0].kind, "config.document")
        kinds = {o.kind for o in obs}
        self.assertIn("openapi.document", kinds)

    def test_openapi_reference_and_slug_helpers(self):
        self.assertTrue(_is_openapi_document({"openapi": "3.0.0"}))
        self.assertFalse(_is_openapi_document({"other": "field"}))
        self.assertEqual(_openapi_bounded_string("short"), "short")
        self.assertEqual(_openapi_bounded_string("a" * 300), "<string:300>")
        self.assertEqual(_openapi_reference_scope("#/components/schemas/Pet"), "internal")
        self.assertEqual(_openapi_reference_scope("./schemas/pet.yaml"), "local_file")
        self.assertEqual(_openapi_reference_scope("https://example.com/pet.yaml"), "remote")
        self.assertEqual(_openapi_safe_string("safe"), "safe")
        self.assertIsNone(_openapi_safe_string(None))
        self.assertEqual(_openapi_string_list(["a", "b"]), ["a", "b"])
        self.assertEqual(_openapi_string_list(None), [])
        self.assertTrue(_openapi_sensitive_key("secret_token"))
        self.assertFalse(_openapi_sensitive_key("normal_field"))
        self.assertEqual(_openapi_oauth_flow_names({"flows": {"implicit": {}, "password": {}}}), ["implicit", "password"])
        self.assertEqual(_openapi_oauth_flow_names({}), [])
        self.assertEqual(_openapi_scope_names({"flows": {"implicit": {"scopes": {"read": "read access", "write": "write access"}}}}), ["read", "write"])
        self.assertEqual(_openapi_scope_names({}), [])
        self.assertTrue(_openapi_pointer_is_redacted("/components/securitySchemes/api_key/secret_token", "secret"))
        self.assertFalse(_openapi_pointer_is_redacted("/components/schemas/Pet", {"type": "object"}))

    def test_swagger2_and_edge_components(self):
        swagger_payload = {
            "swagger": "2.0",
            "info": {"title": "Legacy Swagger API", "version": "1.0"},
            "paths": {
                "/pets": {
                    "get": {
                        "summary": "List pets",
                        "parameters": [
                            {"name": "tag", "in": "query", "type": "string"},
                            "invalid_string_parameter",
                        ],
                        "responses": {
                            "200": {"description": "Pet list"},
                            "default": "invalid_response_string"
                        }
                    },
                    "invalid_verb": {"data": 123},
                    "x-extension": "vendor data",
                },
                "/invalid_path_item": "not a dict",
            },
            "definitions": {
                "Pet": {"type": "object"}
            },
            "securityDefinitions": {
                "petstore_auth": {
                    "type": "oauth2",
                    "authorizationUrl": "https://example.com/oauth",
                    "flow": "implicit",
                    "scopes": {"write:pets": "modify pets"}
                }
            }
        }
        obs = extract_config_file_observations(
            "contracts/swagger.json",
            json.dumps(swagger_payload),
        )
        self.assertEqual(obs[0].kind, "config.document")
        kinds = {o.kind for o in obs}
        self.assertIn("openapi.document", kinds)


if __name__ == "__main__":
    unittest.main()
