"""Typed fields of the existing canonical test-runtime identity document."""

from typing import TypedDict


class RuntimeIdentityFields(TypedDict):
    architecture: str
    base_image_id: str
    base_reference: str
    base_canonical_reference: str
    base_repo_digests: tuple[str, ...]
    lock_resolution_input: None
    project_runtime_dependencies: tuple[str, ...]
    psycopg_release_version: str
    python_base_family: str
    python_version: str
    recipe_schema: int
    runtime_extras: tuple[str, ...]
