from dataclasses import replace
from hashlib import sha256

from repomap_kg.extractors.config.nix import extract_nix_file_observations
from repomap_kg.extractors.config.nix_resolver import (
    NixBindingView,
    ResolutionOutcome,
    resolve_nix_relations,
)
from repomap_kg.observations.raw import RawObservation


def _identity(prefix: str, binding: str) -> str:
    return f"{prefix}:{sha256(binding.encode()).hexdigest()}"


def _reference(
    expression: str,
    *,
    binding: str = "entry",
    provenance: bool = True,
) -> RawObservation:
    metadata = {
        "binding_alias": binding,
        "source_relative_path": "flake.nix",
        "expression": expression,
    }
    if provenance:
        metadata.update(
            {
                "binding_id": _identity("bind1", binding),
                "snapshot_id": _identity("snap1", binding),
            }
        )
    return RawObservation(
        kind="nix.input_ref",
        source_id=f"{_identity('bind1', binding)}:{binding}:flake.nix#1",
        path=f"{binding}/flake.nix",
        start_line=1,
        end_line=1,
        confidence="extracted",
        extractor="nix",
        extractor_version="fixture",
        metadata=metadata,
    )


def _view(
    alias: str,
    input_name: str | None,
    files: set[str],
    *,
    module_exports: dict[str, str | tuple[str, ...]] | None = None,
) -> NixBindingView:
    return NixBindingView(
        alias=alias,
        input_name=input_name,
        files=frozenset(files),
        binding_id=_identity("bind1", alias),
        snapshot_id=_identity("snap1", alias),
        module_exports=module_exports or {},
    )


def _bindings(*views: NixBindingView) -> tuple[NixBindingView, ...]:
    return views


def test_resolves_same_binding_and_exact_cross_binding_targets():
    bindings = _bindings(
        _view("entry", "entry", {"flake.nix", "local.nix"}),
        _view(
            "composition",
            "composition",
            {"flake.nix", "modules/default.nix", "exports/default.nix"},
            module_exports={"default": "exports/default.nix"},
        ),
    )
    observations = (
        RawObservation(
            kind="nix.import",
            source_id="entry:flake.nix#local",
            path="entry/flake.nix",
            target="file:entry/local.nix",
            confidence="extracted",
            extractor="nix",
            extractor_version="fixture",
            metadata={
                "binding_alias": "entry",
                "binding_id": _identity("bind1", "entry"),
                "snapshot_id": _identity("snap1", "entry"),
                "source_relative_path": "flake.nix",
                "resolved_path": "entry/local.nix",
            },
        ),
        _reference("inputs.composition.nixosModules.default"),
    )

    resolutions = resolve_nix_relations(observations, bindings)

    assert [item.outcome for item in resolutions] == [
        ResolutionOutcome.EXACT,
        ResolutionOutcome.EXACT,
    ]
    assert resolutions[0].cross_binding is False
    assert resolutions[0].target_path == "entry/local.nix"
    assert resolutions[1].cross_binding is True
    assert resolutions[1].target_path == "composition/exports/default.nix"


def test_bare_input_reference_is_not_invented_as_flake_file_edge():
    bindings = _bindings(
        _view("entry", "entry", {"flake.nix"}),
        _view("composition", "composition", {"flake.nix"}),
    )

    resolutions = resolve_nix_relations(
        (_reference("inputs.composition", provenance=True),),
        bindings,
    )

    assert resolutions[0].outcome is ResolutionOutcome.UNSUPPORTED
    assert resolutions[0].target_path is None


def test_convention_file_without_explicit_module_export_is_not_exact():
    bindings = _bindings(
        _view("entry", "entry", {"flake.nix"}),
        _view(
            "composition",
            "composition",
            {"flake.nix", "modules/default.nix"},
        ),
    )

    result = resolve_nix_relations(
        (_reference("inputs.composition.nixosModules.default"),),
        bindings,
    )[0]

    assert result.outcome is ResolutionOutcome.UNSUPPORTED
    assert result.target_path is None


def test_missing_or_inconsistent_multi_source_provenance_fails_closed():
    bindings = _bindings(
        _view("entry", "entry", {"flake.nix"}),
        _view(
            "composition",
            "composition",
            {"modules/default.nix"},
            module_exports={"default": "modules/default.nix"},
        ),
    )

    missing = _reference(
        "inputs.composition.nixosModules.default",
        provenance=False,
    )
    with_provenance = _reference("inputs.composition.nixosModules.default")
    inconsistent = replace(
        with_provenance,
        metadata={**with_provenance.metadata, "binding_alias": "composition"},
    )

    resolutions = resolve_nix_relations((missing, inconsistent), bindings)

    assert [item.outcome for item in resolutions] == [
        ResolutionOutcome.UNSUPPORTED,
        ResolutionOutcome.UNSUPPORTED,
    ]
    assert all(item.target_path is None for item in resolutions)


def test_non_exact_outcomes_never_use_first_binding_precedence():
    bindings = _bindings(
        _view("entry", "entry", {"flake.nix"}),
        _view(
            "one",
            "shared",
            {"modules/default.nix"},
            module_exports={"default": "modules/default.nix"},
        ),
        _view(
            "two",
            "shared",
            {"modules/default.nix"},
            module_exports={"default": "modules/default.nix"},
        ),
        _view(
            "conflict",
            "conflict",
            {"modules/default.nix", "default.nix"},
            module_exports={
                "default": ("modules/default.nix", "default.nix")
            },
        ),
    )
    observations = (
        _reference("inputs.shared.nixosModules.default"),
        _reference("inputs.conflict.nixosModules.default"),
        _reference("if pkgs.stdenv.isDarwin then inputs.one else inputs.two"),
        _reference("inputs.missing.nixosModules.default"),
    )

    resolutions = resolve_nix_relations(observations, bindings)

    assert [item.outcome for item in resolutions] == [
        ResolutionOutcome.AMBIGUOUS,
        ResolutionOutcome.CONFLICTING,
        ResolutionOutcome.EVALUATION_DEPENDENT,
        ResolutionOutcome.UNSUPPORTED,
    ]
    assert all(item.target_path is None for item in resolutions)
    assert resolutions[0].candidate_bindings == ("one", "two")


def test_unbound_input_name_is_explicitly_unsupported():
    bindings = _bindings(
        _view("entry", "entry", {"flake.nix"}),
        _view(
            "composition",
            "composition",
            {"modules/default.nix"},
            module_exports={"default": "modules/default.nix"},
        ),
    )

    result = resolve_nix_relations(
        (_reference("inputs.compositon.nixosModules.default"),),
        bindings,
    )[0]

    assert result.outcome is ResolutionOutcome.UNSUPPORTED
    assert result.target_path is None
    assert result.candidate_bindings == ()


def test_real_extractor_metadata_reaches_evaluation_dependent_resolution():
    extracted = extract_nix_file_observations(
        "flake.nix",
        (
            "{ inputs, pkgs, ... }: if pkgs.stdenv.isDarwin then "
            "inputs.composition.nixosModules.default else "
            "inputs.fallback.nixosModules.default\n"
        ),
        flake_ref="entry",
        include_input_references=True,
    )
    references = tuple(item for item in extracted if item.kind == "nix.input_ref")

    assert len(references) == 2
    assert all(
        item.metadata["evaluation_dependency"] == "conditional"
        for item in references
    )

    namespaced = tuple(
        replace(
            item,
            source_id=f"{_identity('bind1', 'entry')}:{item.source_id}",
            path="entry/flake.nix",
            metadata={
                **item.metadata,
                "binding_alias": "entry",
                "binding_id": _identity("bind1", "entry"),
                "snapshot_id": _identity("snap1", "entry"),
                "source_relative_path": "flake.nix",
            },
        )
        for item in references
    )
    bindings = _bindings(
        _view("entry", "entry", {"flake.nix"}),
        _view("composition", "composition", {"modules/default.nix"}),
        _view("fallback", "fallback", {"modules/default.nix"}),
    )

    resolutions = resolve_nix_relations(namespaced, bindings)

    assert [item.outcome for item in resolutions] == [
        ResolutionOutcome.EVALUATION_DEPENDENT,
        ResolutionOutcome.EVALUATION_DEPENDENT,
    ]
