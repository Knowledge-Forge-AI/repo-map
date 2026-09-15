from __future__ import annotations
from typing import NotRequired, TypedDict
import tempfile
from contextlib import contextmanager
from pathlib import Path
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.storage_integration import (
    discovery_fixture,
    terraform_hcl_fixture,
)
from repomap_kg.observations import RawObservation



class _ReferenceMetadata(TypedDict):
    reference_kind: str
    not_fetched: NotRequired[bool]


@contextmanager
def _fixture_jsonl(profile: str):
    if profile == "hcl":
        fixture_root = terraform_hcl_fixture("basic")
        assert {path.name for path in fixture_root.iterdir()} == {
            "main.tf",
            "broken.tf",
            "dev.auto.tfvars",
            "terraform.tfvars",
            "prod.tfvars",
        }
    else:
        fixture_root = discovery_fixture("tfjson1_ecosystem_config")
        assert (fixture_root / "infra" / "main.tf.json").is_file()
        assert (fixture_root / "infra" / "terraform.tfvars.json").is_file()
    observations = _terraform_observations(profile)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False
    ) as handle:
        path = Path(handle.name)
        for observation in observations:
            handle.write(observation.to_json_line())
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


@contextmanager
def _empty_fixture_jsonl():
    observation = _observation(
        "file",
        0,
        path="synthetic/empty.tf",
        language="terraform",
    )
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False
    ) as handle:
        path = Path(handle.name)
        handle.write(observation.to_json_line())
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _terraform_observations(profile: str) -> tuple[RawObservation, ...]:
    paths = (
        (
            ("synthetic/main.tf", "tf"),
            ("synthetic/broken.tf", "tf"),
            ("synthetic/prod.tfvars", "tfvars"),
            ("synthetic/terraform.tfvars", "tfvars"),
            ("synthetic/dev.auto.tfvars", "tfvars"),
        )
        if profile == "hcl"
        else (
            ("synthetic/infra/main.tf.json", "tf"),
            ("synthetic/infra/terraform.tfvars.json", "tfvars"),
        )
    )
    observations = [
        *(
            _observation("terraform.file", index, path=path, file_family=family)
            for index, (path, family) in enumerate(paths)
        ),
        _observation("terraform.block", 10),
        _observation("terraform.provider", 11),
        _observation(
            "terraform.required_provider",
            12,
            version_constraint=">= synthetic-version",
        ),
        _observation("terraform.required_version", 13),
        _observation("terraform.backend", 14),
        _observation("terraform.resource", 15),
        _observation("terraform.data_source", 16),
        _observation("terraform.module", 17),
        _observation("terraform.variable", 18),
        _observation("terraform.output", 19),
        _observation("terraform.local", 20),
        _observation("terraform.moved", 21),
        _observation("terraform.import", 22),
        _observation("terraform.check", 23),
        _observation("terraform.removed", 24),
        _observation("terraform.variable", 25, profile="terraform_tfvars"),
        _observation("file", 26, language="terraform"),
    ]
    reference_metadata: tuple[_ReferenceMetadata, ...] = (
        {"reference_kind": "provider_source", "not_fetched": True},
        {"reference_kind": "required_version"},
        {"reference_kind": "module_source", "not_fetched": True},
        {"reference_kind": "module_source_local"},
        {"reference_kind": "depends_on"},
        {"reference_kind": "provider_alias"},
    )
    observations.extend(
        _observation("terraform.reference", index, **metadata)
        for index, metadata in enumerate(reference_metadata, start=40)
    )
    redactions = (
        ("tfvars-sensitive-by-default", None),
        ("secret-prone-terraform-attribute", "token"),
        ("credentialed-terraform-module-source", None),
        ("terraform-import-id-sensitive-by-default", None),
    )
    observations.extend(
        _observation(
            "terraform.redaction",
            index,
            redaction_reason=reason,
            **({"field_name": field_name} if field_name else {}),
        )
        for index, (reason, field_name) in enumerate(redactions, start=50)
    )
    for index, error_kind in enumerate(
        ("malformed-terraform-hcl", "terraform-block-limit", "terraform-repo-escape"),
        start=60,
    ):
        observations.append(
            _observation("terraform.parse_error", index, error_kind=error_kind)
        )
    observations[0] = _observation(
        "terraform.file",
        0,
        path=paths[0][0],
        file_family=paths[0][1],
        resource_name="private-resource-name",
        module_name="private-module-name",
        provider_source="private/provider-source",
        module_source="https://user:password@private.invalid/module",
        version_constraint="private-version-constraint",
        backend_value="private-backend-value",
        state_path="private-state-path",
        import_id="private-import-id",
        tfvars_literal="private-tfvars-literal",
        expression="private-expression",
        diagnostic="private-parser-diagnostic",
        source_snippet="private-source-snippet",
        raw_hcl="private-raw-hcl",
        raw_json="private-raw-json",
        credential="private-credential",
        secret="private-secret",
        token="private-token",
    )
    return tuple(observations)


def _observation(
    kind: str,
    index: int,
    *,
    path: str = "synthetic/main.tf",
    **metadata: object,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=f"{path}#{kind}:{index}",
        path=path,
        confidence="extracted",
        extractor="psycopg77-fixture",
        extractor_version="1",
        name=f"synthetic-{index}",
        metadata=metadata,
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
