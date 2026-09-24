from __future__ import annotations

import json
import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.extractors.config.generic import extract_config_file_observations
from repomap_kg.extractors.config.nix_resolver import (
    NixBindingView,
    ResolutionOutcome,
    resolve_nix_relations,
)
from repomap_kg.observations.raw import RawObservation


class Slice7ConfigPipelineIntegrationTests(unittest.TestCase):
    """Integration scenarios for Slice 7 Group S7-B configured source routing and configuration pipelines."""

    def test_s7_b01_nix_cross_source_exact_binding_and_input_resolution(self) -> None:
        """Cross-source Nix input references resolve exact target binding and target path with validated provenance."""
        view_primary = NixBindingView(
            alias="primary",
            binding_id="bind_primary",
            snapshot_id="snap_primary",
            files=frozenset(["flake.nix"]),
            input_name="primary",
            module_exports={},
        )
        view_dep = NixBindingView(
            alias="dep",
            binding_id="bind_dep",
            snapshot_id="snap_dep",
            files=frozenset(["flake.nix", "modules/default.nix"]),
            input_name="dep",
            module_exports={"default": "modules/default.nix"},
        )

        obs = RawObservation(
            kind="nix.input_ref",
            source_id="primary/flake.nix#input:dep",
            path="primary/flake.nix",
            target=None,
            confidence="extracted",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "binding_alias": "primary",
                "binding_id": "bind_primary",
                "snapshot_id": "snap_primary",
                "source_relative_path": "flake.nix",
                "expression": "inputs.dep.nixosModules.default",
            },
        )

        resolutions = resolve_nix_relations([obs], [view_primary, view_dep])
        self.assertEqual(len(resolutions), 1)
        res = resolutions[0]
        self.assertEqual(res.outcome, ResolutionOutcome.EXACT)
        self.assertEqual(res.target_binding, "dep")
        self.assertEqual(res.target_path, "dep/modules/default.nix")
        self.assertTrue(res.cross_binding)
        self.assertEqual(res.evidence_class, "static-literal")

    def test_s7_b02_nix_cross_source_evaluation_dependent_and_recovery(self) -> None:
        """Nix cross-source resolution distinguishes evaluation-dependent, unsupported, and ambiguous outcomes."""
        view_primary = NixBindingView(
            alias="primary",
            binding_id="bind_p",
            snapshot_id="snap_p",
            files=frozenset(["flake.nix"]),
            input_name="primary",
        )
        view_dep1 = NixBindingView(
            alias="dep-east",
            binding_id="bind_d1",
            snapshot_id="snap_d1",
            files=frozenset(["flake.nix", "modules/default.nix"]),
            input_name="shared-dep",
            module_exports={"default": "modules/default.nix"},
        )
        view_dep2 = NixBindingView(
            alias="dep-west",
            binding_id="bind_d2",
            snapshot_id="snap_d2",
            files=frozenset(["flake.nix", "modules/default.nix"]),
            input_name="shared-dep",
            module_exports={"default": "modules/default.nix"},
        )

        def make_obs(expr: str, source_id: str) -> RawObservation:
            return RawObservation(
                kind="nix.input_ref",
                source_id=source_id,
                path="primary/flake.nix",
                target=None,
                confidence="extracted",
                extractor="repo-nix",
                extractor_version="0.1.0",
                metadata={
                    "binding_alias": "primary",
                    "binding_id": "bind_p",
                    "snapshot_id": "snap_p",
                    "source_relative_path": "flake.nix",
                    "expression": expr,
                },
            )

        obs_eval = make_obs("inputs.shared-dep.nixosModules.${system}", "primary/flake.nix#eval")
        res_eval = resolve_nix_relations([obs_eval], [view_primary, view_dep1])
        self.assertEqual(res_eval[0].outcome, ResolutionOutcome.EVALUATION_DEPENDENT)

        obs_missing = make_obs("inputs.nonexistent.nixosModules.default", "primary/flake.nix#missing")
        res_missing = resolve_nix_relations([obs_missing], [view_primary, view_dep1])
        self.assertEqual(res_missing[0].outcome, ResolutionOutcome.UNSUPPORTED)

        obs_ambig = make_obs("inputs.shared-dep.nixosModules.default", "primary/flake.nix#ambig")
        res_ambig = resolve_nix_relations([obs_ambig], [view_primary, view_dep1, view_dep2])
        self.assertEqual(res_ambig[0].outcome, ResolutionOutcome.AMBIGUOUS)
        self.assertEqual(res_ambig[0].candidate_bindings, ("dep-east", "dep-west"))

        obs_repaired = make_obs("inputs.shared-dep.nixosModules.default", "primary/flake.nix#repaired")
        res_repaired = resolve_nix_relations([obs_repaired], [view_primary, view_dep1])
        self.assertEqual(res_repaired[0].outcome, ResolutionOutcome.EXACT)
        self.assertEqual(res_repaired[0].target_binding, "dep-east")

        # Conflicting multi-export: module exports multiple paths for same module name
        view_dep_multi = NixBindingView(
            alias="dep-multi",
            binding_id="bind_dm",
            snapshot_id="snap_dm",
            files=frozenset(["flake.nix", "modules/a.nix", "modules/b.nix"]),
            input_name="multi-dep",
            module_exports={"conflict": ("modules/a.nix", "modules/b.nix")},
        )
        obs_conflict = make_obs("inputs.multi-dep.nixosModules.conflict", "primary/flake.nix#conflict")
        res_conflict = resolve_nix_relations([obs_conflict], [view_primary, view_dep_multi])
        self.assertEqual(res_conflict[0].outcome, ResolutionOutcome.CONFLICTING)

        # Bare input reference without module component
        obs_bare = make_obs("inputs.shared-dep", "primary/flake.nix#bare")
        res_bare = resolve_nix_relations([obs_bare], [view_primary, view_dep1])
        self.assertEqual(res_bare[0].outcome, ResolutionOutcome.UNSUPPORTED)
        self.assertEqual(res_bare[0].target_binding, "dep-east")

        # Same-binding nix.import resolution
        obs_import = RawObservation(
            kind="nix.import",
            source_id="primary/flake.nix#import:local",
            path="primary/flake.nix",
            target=None,
            confidence="extracted",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "binding_alias": "primary",
                "binding_id": "bind_p",
                "snapshot_id": "snap_p",
                "source_relative_path": "flake.nix",
                "resolved_path": "primary/modules/local.nix",
            },
        )
        view_with_local = NixBindingView(
            alias="primary",
            binding_id="bind_p",
            snapshot_id="snap_p",
            files=frozenset(["flake.nix", "modules/local.nix"]),
            input_name="primary",
        )
        res_import = resolve_nix_relations([obs_import], [view_with_local])
        self.assertEqual(res_import[0].outcome, ResolutionOutcome.EXACT)
        self.assertEqual(res_import[0].target_binding, "primary")
        self.assertEqual(res_import[0].target_path, "primary/modules/local.nix")
        self.assertFalse(res_import[0].cross_binding)

    def test_s7_b03_terraform_nested_modules_and_local_path_references(self) -> None:
        """Terraform extraction resolves nested module declarations and local path references."""
        tf_content = (
            'module "network" {\n'
            '  source = "./modules/network"\n'
            '  vpc_cidr = "10.0.0.0/16"\n'
            "}\n\n"
            'module "database" {\n'
            '  source = "./modules/database"\n'
            "  network_id = module.network.id\n"
            "}\n"
        )
        obs = extract_config_file_observations("main.tf", tf_content)
        kinds = [o.kind for o in obs]
        self.assertIn("terraform.file", kinds)
        self.assertIn("terraform.module", kinds)

        module_obs = [o for o in obs if o.kind == "terraform.module"]
        self.assertEqual(len(module_obs), 2)
        sources = {m.metadata.get("source_summary") for m in module_obs}
        self.assertEqual(sources, {"./modules/network", "./modules/database"})

        targets = {m.target for m in module_obs}
        self.assertIn("file:modules/network", targets)
        self.assertIn("file:modules/database", targets)

    def test_s7_b04_terraform_credential_safe_external_source_and_malformed_repair(self) -> None:
        """Terraform extraction redacts sensitive URLs and isolates unclosed block parse errors."""
        cred_tf = (
            'module "vault" {\n'
            '  source = "git::https://admin:supersecret@github.com/org/vault.git"\n'
            "}\n"
        )
        obs_cred = extract_config_file_observations("vault.tf", cred_tf)
        mod = next(o for o in obs_cred if o.kind == "terraform.module")
        self.assertNotIn("supersecret", str(mod.target))
        self.assertNotIn("supersecret", str(mod.metadata))

        unclosed_tf = 'module "broken" {\n  source = "./broken"\n'
        obs_err = extract_config_file_observations("broken.tf", unclosed_tf)
        self.assertTrue(any(o.kind == "terraform.parse_error" for o in obs_err))

        fixed_tf = unclosed_tf + "}\n"
        obs_fixed = extract_config_file_observations("broken.tf", fixed_tf)
        self.assertTrue(any(o.kind == "terraform.module" for o in obs_fixed))
        self.assertFalse(any(o.kind == "terraform.parse_error" for o in obs_fixed))

    def test_s7_b05_openapi_nested_components_and_operation_references(self) -> None:
        """OpenAPI extraction captures raw profile observations and generic canonical structure."""
        spec = {
            "openapi": "3.0.3",
            "info": {"title": "Inventory API", "version": "1.0.0"},
            "paths": {
                "/inventory": {
                    "get": {
                        "operationId": "getInventory",
                        "responses": {
                            "200": {
                                "description": "Inventory list",
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/Item"}
                                    }
                                },
                            }
                        },
                    }
                }
            },
            "components": {
                "schemas": {
                    "Item": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}, "count": {"type": "integer"}},
                    }
                }
            },
        }
        content = json.dumps(spec)
        obs = extract_config_file_observations("openapi.json", content)
        kinds = {o.kind for o in obs}

        self.assertIn("openapi.document", kinds)
        self.assertIn("openapi.operation", kinds)
        self.assertIn("openapi.component", kinds)
        self.assertIn("openapi.reference", kinds)
        self.assertIn("config.document", kinds)

        doc_obs = next(o for o in obs if o.kind == "openapi.document")
        self.assertTrue(doc_obs.metadata.get("raw_profile_only"))

        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        raw_warns = [d for d in res.diagnostics if d.category == "unsupported_raw_observation_kind"]
        self.assertGreaterEqual(len(raw_warns), 1)

    def test_s7_b06_openapi_malformed_reference_redaction_and_repair(self) -> None:
        """OpenAPI extraction emits parse errors on malformed JSON and recovers on repaired input."""
        malformed_json = '{"openapi": "3.0.0", "info": {"title": "Broken", "version": 1'
        obs_malformed = extract_config_file_observations("openapi.json", malformed_json)
        self.assertTrue(any(o.kind == "openapi.parse_error" for o in obs_malformed))

        repaired_json = '{"openapi": "3.0.0", "info": {"title": "Fixed", "version": "1.0.0"}}'
        obs_repaired = extract_config_file_observations("openapi.json", repaired_json)
        self.assertTrue(any(o.kind == "openapi.document" for o in obs_repaired))
        self.assertFalse(any(o.kind == "openapi.parse_error" for o in obs_repaired))
