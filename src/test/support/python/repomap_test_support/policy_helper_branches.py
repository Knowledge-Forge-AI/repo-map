"""Shared helpers for policy-helper branch unit tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from types import ModuleType
from pathlib import Path

from repomap_test_support.policy_observations import raw_observation as raw_observation


UNIT_REPOMAP_TEST_ROOT = Path(__file__).parents[3] / "unit" / "python" / "repomap_kg"


def load_unit_contract_class(
    module_filename: str, class_name: str, *,
    load_module: Callable[[str, Path], ModuleType],
) -> object:
    module_path = UNIT_REPOMAP_TEST_ROOT / module_filename
    if not module_path.exists():
        matches = sorted(UNIT_REPOMAP_TEST_ROOT.rglob(module_filename))
        if len(matches) != 1:
            raise RuntimeError(
                f"expected one unit contract module named {module_filename}, found {len(matches)}"
            )
        module_path = matches[0]
    module = load_module(f"repomap_helper_contract_{class_name}", module_path)
    return getattr(module, class_name)


def write_api_fixture(
    root: Path,
    *,
    policy_status: str = "allowed_with_limits",
    include_consent: bool = True,
    credentials_ref: str = "local_secret_ref:fixture-api-token",
    method: str = "GET",
    api_source_class: str = "api.custom_documented_api",
    max_bytes_per_run: int = 1048576,
) -> Path:
    fixture = root / f"api-{len(list(root.glob('api-*')))}"
    fixture.mkdir()
    responses = fixture / "responses"
    responses.mkdir()
    (responses / "items.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "item-1",
                        "name": "Fixture item",
                        "secret": "fixture-secret-value",
                    }
                ]
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    consent_block = (
        "\n[consent]\n"
        'consent_ref = "local_consent_ref:fixture-readonly-api-2026-07"\n'
        'scope_description = "Read-only fixture API metadata export"\n'
        'authorized_operations = ["read"]\n'
        'authorized_data_classes = ["metadata"]\n'
        "revoked = false\n"
        "mutation_allowed = false\n"
        if include_consent
        else ""
    )
    config_path = fixture / "api-source.toml"
    config_path.write_text(
        "[source]\n"
        'source_id = "fixture-readonly-api"\n'
        'source_type = "api.rest"\n'
        f'api_source_class = "{api_source_class}"\n'
        'provider_name = "Fixture Provider"\n'
        'provider_product = "Fixture API"\n'
        f'policy_status = "{policy_status}"\n'
        "read_only = true\n"
        "mutation_allowed = false\n"
        "\n[credentials]\n"
        f'credentials_ref = "{credentials_ref}"\n'
        f"{consent_block}"
        "\n[limits]\n"
        "max_requests_per_run = 10\n"
        "max_requests_per_minute = 10\n"
        "max_concurrent_requests = 1\n"
        f"max_bytes_per_run = {max_bytes_per_run}\n"
        "max_items_per_run = 100\n"
        "max_retries = 0\n"
        "\n[retention]\n"
        'policy = "local_user_controlled"\n'
        'raw_response_retention = "minimized"\n'
        'redacted_response_retention = "retain"\n'
        "\n[redaction]\n"
        'profile = "strict"\n'
        'sensitivity = "private"\n'
        "\n[[endpoints]]\n"
        'name = "items"\n'
        f'method = "{method}"\n'
        'path = "/v1/items"\n'
        'purpose = "Export fixture item metadata"\n'
        'response_type = "application/json"\n'
        "max_page_size = 100\n"
        'pagination = "none"\n'
        'downstream_route = "config"\n'
        'fixture_response_path = "responses/items.json"\n',
        encoding="utf-8",
    )
    return config_path

