import contextlib
import io
import canonicalization_facade_inventory as inventory_tool


def load_tool_module():
    """Return the statically known pure inventory owner; no loader behavior is tested."""
    return inventory_tool


def test_canon_facade2_inventory_reports_current_static_ledger() -> None:
    tool = load_tool_module()

    inventory = tool.collect_inventory()

    assert inventory.static_ledger_count == 291
    assert inventory.generated_main_count == 291
    assert inventory.public_all_count == 172
    assert inventory.public_package_root_count == 172
    assert inventory.check_passed
    assert inventory.ledger_matches_generated_main
    assert inventory.all_matches_public_surface
    assert inventory.package_root_uses_static_ledger
    assert inventory.missing_from_package_root == ()
    assert inventory.missing_from_main == ()
    assert inventory.extra_main_names == ()
    assert inventory.extra_all_names == ()
    assert inventory.missing_all_names == ()
    assert inventory.family_scaffold_files == ()

    assert "nix_multi_source" not in inventory.all_names
    assert "nix_multi_source" not in inventory.public_names
    assert "_nix_multi_source" not in inventory.all_names
    assert "_nix_multi_source" not in inventory.public_names

    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert not hasattr(canonicalization, "nix_multi_source")
    assert all(hasattr(canonicalization, name) for name in inventory.ledger_names)

    import repomap_kg.canonicalization.nix_family as nix_family
    import repomap_kg.canonicalization._nix_multi_source as private_helper
    assert (
        nix_family.multi_source_opaque_target_key
        is private_helper.multi_source_opaque_target_key
    )
    assert (
        nix_family._nix_import_edge_metadata
        is private_helper.nix_import_edge_metadata
    )


def test_canon_facade2_inventory_detects_drift_from_pure_inputs() -> None:
    tool = load_tool_module()

    inventory = tool.build_inventory(
        ledger_names=("alpha", "stale"),
        generated_main_surface=("alpha", "new"),
        package_root_names=("alpha",),
        public_names=("Public", "Visible"),
        all_names=("Public", "Unexpected"),
        family_scaffold_files=("src/main/python/example_family.py",),
        package_root_uses_static_ledger=False,
    )

    assert not inventory.check_passed
    assert not inventory.ledger_matches_generated_main
    assert not inventory.all_matches_public_surface
    assert inventory.missing_from_package_root == ("stale",)
    assert inventory.missing_from_main == ("stale",)
    assert inventory.extra_main_names == ("new",)
    assert inventory.missing_all_names == ("Visible",)
    assert inventory.extra_all_names == ("Unexpected",)
    assert inventory.family_scaffold_files == ("src/main/python/example_family.py",)

    output = "\n".join(tool.format_inventory(inventory))
    assert "static ledger count: 2" in output
    assert "generated main surface count: 2" in output
    assert "package-root missing ledger names: 1" in output
    assert "ledger names missing from main: 1" in output
    assert "generated main names missing from ledger: 1" in output
    assert "family modules with old scaffold: 1" in output
    assert "status: fail" in output


def test_canon_facade2_inventory_check_cli_returns_success() -> None:
    tool = load_tool_module()
    stdout = io.StringIO()

    with contextlib.redirect_stdout(stdout):
        exit_code = tool.main(["--check"])

    output = stdout.getvalue()
    assert exit_code == 0
    assert "canonicalization facade inventory" in output
    assert "static ledger count: 291" in output
    assert "generated main surface count: 291" in output
    assert "family modules with old scaffold: 0" in output
    assert "status: pass" in output


def test_canon_facade3_inventory_tool_has_no_update_mode() -> None:
    tool = load_tool_module()
    stdout = io.StringIO()
    stderr = io.StringIO()

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            tool.main(["--update"])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("--update unexpectedly returned without exiting")

    assert stdout.getvalue() == ""
    assert "unrecognized arguments: --update" in stderr.getvalue()
