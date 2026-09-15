import json
from collections import Counter
from pathlib import Path

from repomap_kg.extractors.config.nix import extract_nix_file_observations


NIX_EXTRACT1_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "discovery"
    / "nix_real_flake_shapes"
)
NIX_OUTPUT_KINDS = {"nix.app", "nix.package", "nix.devShell", "nix.check"}
NIX_EXTRACT3_DEFERRED_KINDS = {
    "nix.module",
    "nix.overlay",
}
NIX_EXTRACT3_DIAGNOSTIC_KINDS = {
    "nix.dynamic_output_shape",
    "nix.unsupported_flake_shape",
}
NIX_EXTRACT1_FIXTURES = (
    "nested_output_sections",
    "helper_frameworks",
    "inputs_modules_overlays",
    "unsupported_shapes",
)
NIX_EXTRACT5_GAP_FIXTURES = (
    "wrapped_multiline_outputs_sections",
    "inline_open_brace_output_sections",
    "wrapper_generated_output_sections",
)
NIX_EXTRACT7_TARGETED_FIXTURES = (
    "let_bound_output_attrsets",
)


def read_nix_extract1_fixture(name: str) -> str:
    return (NIX_EXTRACT1_FIXTURE_ROOT / name / "flake.nix").read_text(
        encoding="utf-8"
    )


def extract_nix_extract1_fixture(name: str):
    return extract_nix_file_observations(
        "flake.nix",
        read_nix_extract1_fixture(name),
        flake_ref=f"extract1-{name}",
    )


def kind_counts(observations) -> Counter[str]:
    return Counter(item.kind for item in observations)


def serialized_observations(observations) -> str:
    return json.dumps(
        [item.to_dict() for item in observations],
        sort_keys=True,
    )


def flake_input_observations(observations):
    return [item for item in observations if item.kind == "nix.flake_input"]


def output_section_observations(observations):
    return [item for item in observations if item.kind == "nix.output_section"]


def sections_by_name(observations):
    return {
        item.metadata["section"]: item
        for item in output_section_observations(observations)
    }


def dynamic_shape_observations(observations):
    return [
        item for item in observations if item.kind == "nix.dynamic_output_shape"
    ]


def unsupported_shape_observations(observations):
    return [
        item for item in observations if item.kind == "nix.unsupported_flake_shape"
    ]


def diagnostic_observations(observations):
    return [
        item for item in observations if item.kind in NIX_EXTRACT3_DIAGNOSTIC_KINDS
    ]


def assert_no_concrete_or_deferred_outputs(test_case, observations) -> None:
    counts = kind_counts(observations)

    test_case.assertFalse([
        item for item in observations if item.kind in NIX_OUTPUT_KINDS
    ])
    test_case.assertFalse(NIX_EXTRACT3_DEFERRED_KINDS & set(counts))
