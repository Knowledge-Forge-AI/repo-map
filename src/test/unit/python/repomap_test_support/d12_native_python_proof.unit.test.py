"""ADR 0102 pure component validators: exact envelope, hierarchy, image, capture and payload facts; every refusal."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from typing import Any, Callable

import pytest

from repomap_kg.runtime import python_payload as payload
from repomap_test_support import d12_native_python_proof as proof
from repomap_test_support import d12_python31216 as older
from src.test.unit.python.tools.d12_native_python_fixture_helpers import (
    AMD, ARM, ARM_TK, ROOT, capture, image_attrs, raw_and_inner,
)

Mutation = Callable[[dict[str, Any], dict[str, Any]], object]
ENVELOPE = (ROOT / proof.ENVELOPE_PATH).read_bytes()


def _meta() -> dict[str, bytes]:
    return proof.read_envelope(ROOT)


def test_exact_envelope_hash_schema_and_older_arm_manifest_bytes() -> None:
    assert hashlib.sha256(ENVELOPE).hexdigest() == proof.ENVELOPE_SHA256
    meta = _meta()
    assert tuple(sorted(meta)) == proof.METADATA_KEYS
    assert meta["arm64-manifest"] == older.RETAINED_ARM64_MANIFEST_BYTES  # A5: duplicated ARM bytes are identical
    assert proof.CONFIGS == {"arm64": payload.PYTHON_31216_ARM64_CONFIG, "amd64": payload.PYTHON_31216_AMD64_CONFIG}
    with pytest.raises(proof.NativeComponentError, match="altered or stale"):
        proof.load_envelope(ENVELOPE.replace(b"3.12.16", b"3.12.17", 1))
    with pytest.raises(proof.NativeComponentError, match="oversized"):
        proof.load_envelope(ENVELOPE + b" " * proof.ENVELOPE_LIMIT)


@pytest.mark.parametrize("text, message", [
    ('{"schema": "repomap-python31216-native-inputs-v1", "schema": "x", "metadata_utf8": {}}', "duplicate JSON keys"),
    ('{"schema": NaN, "metadata_utf8": {}}', "non-finite"),
    ('{"schema": "repomap-python31216-native-inputs-v1"', "malformed"),
    ('{"schema": "other", "metadata_utf8": {}}', "schema is not exact"),
    ('{"schema": "repomap-python31216-native-inputs-v1", "metadata_utf8": {}, "x": 1}', "schema is not exact"),
    ('{"schema": "repomap-python31216-native-inputs-v1", "metadata_utf8": {"index": "{}"}}', "missing, foreign"),
])
def test_envelope_schema_is_strict_even_when_the_hash_matches(text: str, message: str) -> None:
    data = text.encode()
    with pytest.raises(proof.NativeComponentError, match=message):
        proof.load_envelope(data, expected_sha256=hashlib.sha256(data).hexdigest())


@pytest.mark.parametrize("platform", [ARM, AMD])
def test_hierarchy_binds_index_one_platform_manifest_config_and_rootfs(platform: str) -> None:
    found = proof.verify_hierarchy(_meta(), platform)
    arch = platform.split("/")[1]
    assert (found["index"], found["manifest"], found["config"]) == (
        payload.PYTHON_31216_INDEX, proof.MANIFESTS[arch], proof.CONFIGS[arch])
    assert len(found["diff_ids"]) == 4 and found["layers"] == 4
    if platform == ARM:
        assert tuple(found["diff_ids"]) == older.EXPECTED_ARM64_DIFF_IDS
    with pytest.raises(proof.NativeComponentError, match="do not hash"):
        proof.verify_hierarchy({**_meta(), "index": _meta()["index"] + b" "}, platform)


def _crafted(change: Callable[[Any, Any, Any], object]) -> tuple[dict[str, bytes], dict[str, str]]:
    """Re-serialize an edited ARM hierarchy with self-consistent hashes, so only the edited relation can refuse."""
    meta = _meta()
    index, manifest, config = (json.loads(meta[k]) for k in ("index", "arm64-manifest", "arm64-config"))
    change(index, manifest, config)
    config_bytes = json.dumps(config).encode()
    if manifest["config"].get("digest") == proof.CONFIGS["arm64"]:
        manifest["config"].update(digest=proof.digest(config_bytes), size=len(config_bytes))
    manifest_bytes = json.dumps(manifest).encode()
    for item in index["manifests"]:
        if isinstance(item, dict) and item.get("digest") == proof.MANIFESTS["arm64"]:
            item.update(digest=proof.digest(manifest_bytes), size=len(manifest_bytes))
    index_bytes = json.dumps(index).encode()
    pins = {"index": proof.digest(index_bytes), "manifest": proof.digest(manifest_bytes),
            "config": proof.digest(config_bytes)}
    return {**meta, "index": index_bytes, "arm64-manifest": manifest_bytes, "arm64-config": config_bytes}, pins


@pytest.mark.parametrize("change, message", [
    (lambda i, m, c: None, None),
    (lambda i, m, c: i["manifests"].append(copy.deepcopy(next(
        d for d in i["manifests"] if d["platform"].get("architecture") == "arm64"))), "descriptors or a duplicate"),
    (lambda i, m, c: [d["platform"].update(architecture="arm") for d in i["manifests"]
                      if d["platform"].get("architecture") == "arm64"], "0 linux/arm64 descriptors"),
    (lambda i, m, c: i.update(mediaType="application/json"), "index is malformed"),
    (lambda i, m, c: i["manifests"].append("x"), "index is malformed"),
    (lambda i, m, c: m["config"].update(digest=proof.CONFIGS["amd64"]), "does not bind the exact config"),
    (lambda i, m, c: m.update(layers=[]), "does not bind the exact config"),
    (lambda i, m, c: c.update(architecture="amd64"), "rootfs diff IDs are not exact"),
    (lambda i, m, c: c["rootfs"].update(diff_ids=["sha256:short"]), "rootfs diff IDs are not exact"),
])
def test_hierarchy_refuses_ambiguous_foreign_or_unbound_descriptors(change: Any, message: str | None) -> None:
    meta, pins = _crafted(change)
    if message is None:
        assert proof.verify_hierarchy(meta, ARM, expected=pins)["config"] == pins["config"]
        return
    with pytest.raises(proof.NativeComponentError, match=message):
        proof.verify_hierarchy(meta, ARM, expected=pins)


def test_native_daemon_is_confirmed_never_inferred() -> None:
    assert proof.require_native("aarch64", ARM) == "arm64" and proof.require_native("x86_64", AMD) == "amd64"
    for daemon, platform, message in (("x86_64", ARM, "refuses the amd64 daemon"), ("arm64", AMD, "refuses the arm64"),
                                      ("riscv64", ARM, "unknown daemon"), ("aarch64", "linux/arm/v7", "unsupported")):
        with pytest.raises(proof.NativeComponentError, match=message):
            proof.require_native(daemon, platform)


@pytest.mark.parametrize("change, message", [
    (lambda a: a.update(Id=proof.MANIFESTS["arm64"]), "not the selected config"),
    (lambda a: a.update(Id=payload.PYTHON_31216_INDEX), "not the selected config"),
    (lambda a: a.update(RepoDigests=[]), "RepoDigests"),
    (lambda a: a["RepoDigests"].append("python@sha256:" + "0" * 64), "RepoDigests"),
    (lambda a: a.update(Architecture="amd64"), "observed image is linux/amd64"),
    (lambda a: a["RootFS"]["Layers"].pop(), "rootfs diff IDs differ"),
    (lambda a: a.update(RootFS=None), "rootfs diff IDs differ"),
])
def test_observed_image_attributes_are_independently_verified(change: Any, message: str) -> None:
    hierarchy = proof.verify_hierarchy(_meta(), ARM)
    assert proof.verify_image(image_attrs(), hierarchy)["image_config_verified"] is True
    attrs = image_attrs()
    change(attrs)
    with pytest.raises(proof.NativeComponentError, match=message):
        proof.verify_image(attrs, hierarchy)


def test_override_is_exact_when_required_and_only_recorded_otherwise() -> None:
    hierarchy = proof.verify_hierarchy(_meta(), AMD)
    assert proof.verify_override(proof.CONFIGS["amd64"], hierarchy, required=True)["selected"] is True
    for value in (None, "", proof.CONFIGS["arm64"], proof.CONFIGS["amd64"].upper()):
        with pytest.raises(proof.NativeComponentError, match="missing or foreign"):
            proof.verify_override(value, hierarchy, required=True)
        assert proof.verify_override(value, hierarchy, required=False)["selected"] is False


FOREIGN_31215_AMD = payload.build_31216_exclusion("amd64", payload.AMD64_31216_NATIVE_BASELINE_IMPORTS)._replace(
    python_config="sha256:a33c10a97f11005523814c6eee013986119fe41f3122f444518117536675c8e1")


def test_amd_default_stays_held_and_unenrolled(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR 0103 superseded the held default: both actual defaults are configured; held maps are isolated doubles."""
    assert proof.default_states() == {"amd64_default_enrolled": True, "arm64_default_enrolled": True,
                                      "bound_by": "raw native observation"}
    for arch, names in (("amd64", payload.AMD64_31216_NATIVE_BASELINE_IMPORTS),
                        ("arm64", payload.ARM64_31216_NATIVE_BASELINE_IMPORTS)):
        assert proof.configured_default(arch) == payload.build_31216_exclusion(arch, names)
    arm = payload.PYTHON_PAYLOAD_EXCLUSIONS["arm64"]
    doubles: list[tuple[dict[str, Any], str]] = [
        ({"arm64": arm}, "amd64 3.12.16 default is missing"),
        ({"arm64": arm, "amd64": None}, "amd64 3.12.16 default is None"),
        ({"arm64": arm, "amd64": ("_ssl",)}, "amd64 3.12.16 default is malformed"),
        ({"arm64": arm, "amd64": arm}, "amd64 3.12.16 default is malformed"),
        ({"arm64": arm, "amd64": FOREIGN_31215_AMD}, "amd64 3.12.16 default is foreign")]
    for held, message in doubles:
        with pytest.raises(proof.NativeComponentError, match=message):
            proof.default_states(held)
    monkeypatch.setattr(payload, "PYTHON_PAYLOAD_EXCLUSIONS", {"arm64": arm, "amd64": None})
    with pytest.raises(proof.NativeComponentError, match="default is None"):
        proof.default_states()  # the module default map is read at call time, never cached


@pytest.mark.parametrize("architecture", ["arm64", "amd64"])
def test_inner_script_prints_raw_first_and_passes_only_an_explicit_derived_mapping(architecture: str) -> None:
    source = (ROOT / "src/main/python/repomap_kg/runtime/python_payload.py").read_bytes()
    script = proof.build_inner_script(source, architecture)
    assign = ast.parse(script).body[1]  # syntax only: the inner script is never executed on the host
    assert isinstance(assign, ast.Assign)
    assert ast.literal_eval(assign.value) == (source, architecture, proof.MACHINES[architecture])
    raw_print, trim = script.index(proof.RAW_PREFIX), script.index("mod.main([ARCH], exclusions={ARCH: entry})")
    assert script.index("mod.main([ARCH, '--no-exclusion'])") < raw_print < trim
    driver = "\n".join(ast.unparse(node) for index, node in enumerate(ast.parse(script).body) if index != 1)
    assert "PYTHON_PAYLOAD_EXCLUSIONS =" not in driver and "BASELINE_IMPORTS" not in driver
    assert "sys.flags.optimize == 0" in script and "'-I', '-B'" in script
    assert script.index("sys.excepthook = _hook") < script.index("exec(compile(") and proof.ERROR_PREFIX in script
    with pytest.raises(proof.NativeComponentError, match="unsupported"):
        proof.build_inner_script(source, "riscv64")


def test_capture_requires_one_strict_raw_and_one_component_line() -> None:
    raw, inner = raw_and_inner()
    lines = proof.capture_lines(capture(raw, inner, extra="noise\n"))
    assert proof.parse_raw(lines) == raw and proof.parse_inner(lines) == inner
    for data, message in ((capture(raw, None), "one component observation line, found 0"),
                          (capture(raw, inner) + capture(raw, None), "one raw observation line, found 2"),
                          (b"\xff" + capture(raw, inner), "not UTF-8"),
                          (b"x" * (proof.CAPTURE_LIMIT + 1), "exceeds"),
                          ((proof.RAW_PREFIX + '{"rc": 1, "rc": 1, "report": {}}\n').encode(), "duplicate JSON"),
                          ((proof.RAW_PREFIX + '{"rc": 1}\n').encode(), "raw observation record is not exact")):
        with pytest.raises(proof.NativeComponentError, match=message):
            found = proof.capture_lines(data)
            proof.parse_raw(found)
            proof.parse_inner(found)
    with pytest.raises(proof.NativeComponentError, match="component observation record is not exact"):
        proof.parse_inner(proof.capture_lines(capture(raw, {**inner, "extra": 1})))


def test_inner_error_is_optional_single_strict_and_redacted() -> None:
    raw, inner = raw_and_inner()
    assert proof.parse_error(proof.capture_lines(capture(raw, inner))) is None
    line = proof.ERROR_PREFIX + json.dumps({"type": "AssertionError", "message": f"/root/x {'b' * 64}"})
    assert proof.parse_error([line]) == {"type": "AssertionError", "message": "<path> <id>"}
    for lines, message in (([line, line], "one inner error line, found 2"),
                           ([proof.ERROR_PREFIX + '{"type": "X"}'], "inner error record is not exact"),
                           ([proof.ERROR_PREFIX + '{"type": "X", "message": 1}'], "inner error record is not exact")):
        with pytest.raises(proof.NativeComponentError, match=message):
            proof.parse_error(lines)


def test_retained_arm_observation_validates_from_its_own_raw_imports() -> None:
    raw, inner = raw_and_inner()
    summary = proof.validate_observation(raw, inner, "arm64")
    assert summary["baseline_imports"] == raw["report"]["baseline"]["imports"]  # observed, never a historical tuple
    assert tuple(summary["baseline_imports"]) == payload.ARM64_31216_NATIVE_BASELINE_IMPORTS
    assert (summary["before_entries"], summary["after_entries"], summary["excluded_path"]) == (1721, 1720, ARM_TK)
    assert summary["excluded_missing"] == ["libtcl8.6.so", "libtk8.6.so"] and summary["unresolved"] == []
    assert summary["retained_owner_count"] == 21 and summary["default_enrolled"] is True
    with pytest.raises(proof.NativeComponentError, match="raw --no-exclusion report"):
        proof.validate_observation(raw, inner, "amd64")  # the ARM fixture never stands in for AMD


@pytest.mark.parametrize("arm, message", [
    (None, "arm64 3.12.16 default is None"),
    (FOREIGN_31215_AMD, "arm64 3.12.16 default is malformed"),
    (payload.build_31216_exclusion("arm64", ("_ssl", "math")), "foreign to the raw native observation"),
    (payload.build_31216_exclusion("arm64", payload.ARM64_31216_NATIVE_BASELINE_IMPORTS)._replace(
        python_config=payload.PYTHON_31216_AMD64_CONFIG), "default is foreign to the frozen native Tk spec"),
])
def test_host_binds_the_configured_default_to_the_raw_observation(arm: Any, message: str) -> None:
    raw, inner = raw_and_inner()
    assert proof.validate_observation(raw, inner, "arm64", exclusions=dict(payload.PYTHON_PAYLOAD_EXCLUSIONS))
    with pytest.raises(proof.NativeComponentError, match="arm64 3.12.16 default is missing"):
        proof.validate_observation(raw, inner, "arm64", exclusions={})
    with pytest.raises(proof.NativeComponentError, match=message):
        proof.validate_observation(raw, inner, "arm64", exclusions={**payload.PYTHON_PAYLOAD_EXCLUSIONS, "arm64": arm})


def _tk(r: dict[str, Any]) -> dict[str, Any]:
    return dict(r["report"]["baseline"]["elves"][ARM_TK])


@pytest.mark.parametrize("mutate, message", [
    (lambda r, i: r.update(rc=0), "raw contract must refuse"),
    (lambda r, i: i.update(rc_trimmed=True), "trimmed contract must pass"),
    (lambda r, i: i.update(entry_delta=0), "exactly one Tk removal"),
    (lambda r, i: i.update(entry_delta=-1.0), "exactly one Tk removal"),
    (lambda r, i: i.update(removed=[ARM_TK, "/usr/local/bin/python3"]), "exactly one Tk removal"),
    (lambda r, i: i.update(modified_survivors=["/usr/local/bin/python3.12"]), "exactly one Tk removal"),
    (lambda r, i: i.update(python_version="3.12.15"), "interpreter facts"),
    (lambda r, i: i.update(machine="x86_64"), "interpreter facts"),
    (lambda r, i: i.update(default_matches=False), "enrolled default differs"),
    (lambda r, i: i.update(default_enrolled=1, default_matches=1), "enrolled default differs"),
    (lambda r, i: i.update(default_enrolled=False, default_matches=False), "inner flags must equal the host"),
    (lambda r, i: r["report"].update(result="clean"), "exact refusal"),
    (lambda r, i: r["report"].update(reasons=["PayloadRefusal: other"]), "unexpected raw refusal"),
    (lambda r, i: r["report"]["baseline"].update(machine="x86_64"), "not native"),
    (lambda r, i: r["report"]["baseline"]["imports"].reverse(), "raw imports are malformed"),
    (lambda r, i: r["report"]["baseline"]["failed"].update(_ssl={"exit": 1}), "another module failed"),
    (lambda r, i: r["report"]["baseline"]["elves"][ARM_TK].update(sha256="0" * 64), "frozen native Tk spec"),
    (lambda r, i: r["report"]["baseline"]["elves"][ARM_TK].update(ldd="\tlibtk8.6.so => not found\n"),
     "frozen native Tk spec"),
    (lambda r, i: i["trimmed_report"].update(exclusion={**i["trimmed_report"]["exclusion"], "size": 1}),
     "exact derived Tk exclusion"),
    (lambda r, i: i["trimmed_report"]["baseline"].update(digest="0" * 64), "baseline differs from the raw"),
    (lambda r, i: i["trimmed_report"]["retained"].update(digest=r["report"]["baseline"]["digest"],
                                                         expected_digest=r["report"]["baseline"]["digest"]),
     "not preserved"),
    (lambda r, i: i["trimmed_report"]["retained"]["imports"].pop(), "not preserved"),
    (lambda r, i: i["trimmed_report"]["retained"].update(unresolved=["x"]), "not preserved"),
    (lambda r, i: i["trimmed_report"]["retained"].update(elf_count=True), "not preserved"),
    (lambda r, i: i["trimmed_report"]["retained"]["owners"].popitem(), "ownership is incomplete"),
    (lambda r, i: i["trimmed_report"]["retained"]["owners"].update(
        {k: " " for k in i["trimmed_report"]["retained"]["owners"]}), "ownership is incomplete"),
    (lambda r, i: i["trimmed_report"].pop("retained"), "trimmed report is not"),
    (lambda r, i: i.pop("machine"), "malformed component observation"),
])
def test_observation_refuses_tampered_incomplete_or_conflicting_facts(mutate: Mutation, message: str) -> None:
    raw, inner = raw_and_inner()
    mutate(raw, inner)
    with pytest.raises(proof.NativeComponentError, match=message):
        proof.validate_observation(raw, inner, "arm64")


def test_public_reasons_remove_private_paths_and_container_ids_but_keep_digests() -> None:
    error = RuntimeError(f"409 for {'a' * 64} at /home/runner/work/x and /Users/me/y; {payload.PYTHON_31216_INDEX}")
    reason = proof.public_reason("create", error)
    assert reason.startswith("create: RuntimeError: ") and "a" * 12 not in reason
    assert "/home/" not in reason and "/Users/" not in reason and payload.PYTHON_31216_INDEX in reason
    assert len(proof.public_reason("x", RuntimeError("y" * 5000))) == 600
    assert proof.integrity(b"abc") == {"bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}


def test_ci83_amd_facts_validate_only_with_explicit_prospective_enrollment() -> None:
    """Historical inner flags stay false; a copied prospective unit double is never fresh native evidence."""
    fixture = ROOT / "src/test/unit/python/repomap_test_support/d12_native_amd_ci83_fixture.json"
    record = json.loads(fixture.read_text(encoding="utf-8"))
    raw, historical = record["raw"], record["inner"]
    assert record["source"]["run_id"] == 40612206734 and record["source"]["attempt"] == 1
    assert historical["default_enrolled"] is False and historical["default_matches"] is False
    with pytest.raises(proof.NativeComponentError, match="inner flags must equal the host"):
        proof.validate_observation(raw, historical, "amd64")
    prospective = {**copy.deepcopy(historical), "default_enrolled": True, "default_matches": True}
    summary = proof.validate_observation(raw, prospective, "amd64")
    assert tuple(summary["baseline_imports"]) == payload.AMD64_31216_NATIVE_BASELINE_IMPORTS
    assert (summary["before_entries"], summary["after_entries"], summary["retained_owner_count"]) == (1721, 1720, 21)
    assert summary["default_enrolled"] is True and summary["unresolved"] == []
    with pytest.raises(proof.NativeComponentError, match="amd64 3.12.16 default is missing"):
        proof.validate_observation(raw, prospective, "amd64", exclusions={})
    foreign = payload.build_31216_exclusion("amd64", ("_ssl", "math"))
    with pytest.raises(proof.NativeComponentError, match="foreign to the raw native observation"):
        proof.validate_observation(raw, prospective, "amd64", exclusions={"amd64": foreign})
    assert historical["default_enrolled"] is False  # no retroactive rewrite of the retained CI83 observation
