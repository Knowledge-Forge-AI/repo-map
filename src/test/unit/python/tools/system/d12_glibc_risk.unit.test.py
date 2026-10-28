"""ADR 0101 glibc disposition assessor: exact approval, every refusal class, duplicate versus conflicting evidence."""

from __future__ import annotations

import ast
from collections.abc import Callable
import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import pytest

from repomap_kg.runtime import release
from repomap_test_support.d12_image_probes import NOTICES
from tools.system import d12_glibc_risk as risk
from tools.system.d12_glibc_risk import GlibcRiskError

REPO_ROOT = Path(__file__).resolve().parents[6]
RECORD_BYTES = (REPO_ROOT / risk.RECORD_RELPATH).read_bytes()
HISTORICAL = json.loads(RECORD_BYTES)
HISTORICAL_POSTGRES = "postgres:16.15-trixie@" + HISTORICAL["postgres_index"]
HISTORICAL_PYTHON = "python:3.12-slim-trixie@" + HISTORICAL["python_index"]
ARCH = {"linux/amd64": ("amd64", "x86_64", "x86_64-linux-gnu"),
        "linux/arm64": ("arm64", "aarch64", "aarch64-linux-gnu")}
LIBC_SHA, NOTICE_SHA = "e" * 64, "c" * 64
CANDIDATE_ID, SERVER_ID = "sha256:" + "1" * 64, "sha256:" + "5" * 64
NATIVE = {"platform": "linux/amd64", "execution": "native", "builder_platforms": ["linux/amd64"]}
Mutation = Callable[[dict[str, Any]], object]


def _libc_row(triplet: str, invoked: str, **overrides: str) -> dict[str, str]:
    row = {"role": "library", "invoked": invoked, "resolved": f"/usr/lib/{triplet}/libc.so.6", "kind": "elf",
           "sha256": LIBC_SHA, "interpreter": "-", "owner": "libc6", "md5": "match"}
    return {**row, **overrides}


def _inventory(platform: str = "linux/amd64", *, duplicate: bool = False) -> dict[str, Any]:
    """The ``d12_image_probes._inventory`` shape, including the probe's missing-binary and unowned rows."""
    dpkg, machine, triplet = ARCH[platform]
    merged, real = f"/lib/{triplet}/libc.so.6", f"/usr/lib/{triplet}/libc.so.6"
    files = [
        {"role": "invoked", "invoked": "/usr/bin/psql", "resolved": "-", "kind": "missing", "sha256": "-",
         "interpreter": "-", "owner": "-", "md5": "-"},
        {"role": "invoked", "invoked": "/usr/local/bin/python3", "resolved": "/usr/local/bin/python3.12",
         "kind": "elf", "sha256": "f" * 64, "interpreter": "-", "owner": "-", "md5": "-"},
        _libc_row(triplet, merged),
    ]
    links = [["/usr/local/bin/python3", "libpython3.12.so.1.0", "/usr/local/lib/libpython3.12.so.1.0"],
             ["/usr/local/bin/python3", "libc.so.6", merged]]
    if duplicate:  # a second ldd spelling of the SAME real file
        files.append(_libc_row(triplet, real))
        links.append(["/usr/local/lib/libpython3.12.so.1.0", "libc.so.6", real])
    return {
        "files": files, "links": links,
        "packages": [["libc-bin", risk.SOURCE_VERSION, dpkg], ["libc6", risk.SOURCE_VERSION, dpkg],
                     ["libssl3t64", "3.5.7-1~deb13u3", dpkg]],
        "verify_mismatches": [], "verify_count": 0, "unowned_usr_lib": [], "unowned_count": 0,
        "notices": {path: NOTICE_SHA for path in NOTICES}, "os": ["Debian GNU/Linux 13 (trixie)", machine, dpkg],
    }


def _image(label: str = "candidate", image_id: object = CANDIDATE_ID, platform: str = "linux/amd64",
           base: str = HISTORICAL_POSTGRES, **inventory_kw: Any) -> dict[str, Any]:
    return {"label": label, "base_reference": base, "image_id": image_id, "platform": platform,
            "execution": "native", "inventory": _inventory(platform, **inventory_kw)}


def _libc_rows(image: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in image["inventory"]["files"] if row["resolved"].endswith("/libc.so.6")]


def test_assessor_constants_match_retained_approval_and_module_is_stdlib_only() -> None:
    assert hashlib.sha256(RECORD_BYTES).hexdigest() == risk.APPROVED_RECORD_SHA256
    assert risk.RECORD_PATH == (REPO_ROOT / risk.RECORD_RELPATH).resolve()
    assert risk.BASE_REFERENCES == (HISTORICAL_POSTGRES, HISTORICAL_PYTHON)
    assert risk.PYTHON_INDEX == HISTORICAL["python_index"]
    assert set(risk.PLATFORMS) == set(json.loads(RECORD_BYTES)["platforms"]) and risk.PLATFORMS == ARCH
    assert risk.LIBC_NOTICE in NOTICES
    tree = ast.parse(Path(risk.__file__).read_text(encoding="utf-8"))
    modules = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
               for alias in node.names}
    modules |= {str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert modules and modules <= set(sys.stdlib_module_names) | {"__future__"}, modules


def test_exact_record_loads_with_every_original_field() -> None:
    record = risk.load_approved_record()
    assert record == json.loads(RECORD_BYTES) and risk.load_approved_record(RECORD_BYTES) == record
    assert tuple(f["id"] for f in record["advisories"]) == risk.FINDING_IDS and len(risk.FINDING_IDS) == 21
    assert {(f["class"], f["disposition"], f["owner"]) for f in record["advisories"]} == {
        ("affected", "accepted_unresolved", "Samuel Leighton Lair")}
    target = next(f for f in record["advisories"] if f["id"] == "CVE-2026-19499")
    assert (target["highest_reported_score"], target["highest_reported_band"]) == (7.7, "HIGH")
    assert record["accepts_image_or_other_findings"] is False and record["source_version"] == "2.41-12+deb13u4"


@pytest.mark.parametrize("altered", [
    RECORD_BYTES.replace(b'"highest_reported_score": 7.7,', b'"highest_reported_score": 7.6,'),
    RECORD_BYTES.replace(b"2.41-12+deb13u4", b"2.41-12+deb13u5"),
    RECORD_BYTES + b"\n",
    json.dumps(json.loads(RECORD_BYTES), sort_keys=True).encode("utf-8"),
], ids=["score", "version", "trailing-byte", "reserialized"])
def test_altered_record_bytes_refuse(altered: bytes) -> None:
    assert altered != RECORD_BYTES
    with pytest.raises(GlibcRiskError, match="SHA-256"):
        risk.load_approved_record(altered)
    result = risk.evaluate_glibc_disposition([_image()], record_bytes=altered)
    assert result["status"] == risk.REFUSED and "SHA-256" in result["refusal"]
    assert result["record_sha256"] == risk.APPROVED_RECORD_SHA256 and result["image_qualified"] is False


def test_record_file_reads_are_bounded(tmp_path: Path) -> None:
    (copy_path := tmp_path / "record.json").write_bytes(RECORD_BYTES)
    assert risk.read_record_bytes(copy_path) == RECORD_BYTES
    (big := tmp_path / "big.json").write_bytes(b" " * (risk.MAX_RECORD_BYTES + 1))
    with pytest.raises(GlibcRiskError, match="exceeds"):
        risk.read_record_bytes(big)
    with pytest.raises(GlibcRiskError, match="regular file"):
        risk.read_record_bytes(tmp_path)


def test_unreadable_record_is_a_retained_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreadable() -> bytes:
        raise PermissionError(13, "Permission denied", "/example/private-control/record.json")

    monkeypatch.setattr(risk, "read_record_bytes", unreadable)
    result = risk.evaluate_glibc_disposition([_image()])
    assert result["status"] == risk.REFUSED and result["refusal"].startswith("PermissionError")
    assert "/example/private-control" not in result["refusal"] and risk.RECORD_RELPATH in result["refusal"]
    assert result["images"][0]["image_id"] == CANDIDATE_ID and result["image_qualified"] is False


@pytest.mark.parametrize(("raw", "match"), [
    (b'{"a": 1, "a": 2}', "duplicate JSON key 'a'"), (b'{"o": {"k": 1, "k": 1}}', "duplicate JSON key 'k'"),
    (b'{"a": NaN}', "non-finite"), (b'{"a": -Infinity}', "non-finite"), (b"\xff{}", "UTF-8"),
    (b"", "size 0"), (b'{"a": 1', "strict UTF-8 JSON"), (b" " * (risk.MAX_RECORD_BYTES + 1), "size"),
])
def test_strict_json_refusals(raw: bytes, match: str) -> None:
    with pytest.raises(GlibcRiskError, match=match):
        risk.strict_json_loads(raw)


def _set(path: tuple[Any, ...], value: Any) -> Mutation:
    def mutate(data: dict[str, Any]) -> None:
        target: Any = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return mutate


def _future(data: dict[str, Any]) -> None:
    data["advisories"].append({**data["advisories"][-1], "id": "CVE-2026-99999"})


RECORD_MUTATIONS: list[tuple[str, Mutation, str]] = [
    ("missing-field", lambda d: d.pop("owner"), r"fields missing \['owner'\]"),
    ("extra-field", _set(("waiver",), "all"), r"extra \['waiver'\]"),
    ("future-finding", _future, r"foreign/future \['CVE-2026-99999'\]"),
    ("missing-finding", lambda d: d["advisories"].pop(), r"missing \['CVE-2026-97399'\]"),
    ("duplicate-finding", lambda d: d["advisories"].append(dict(d["advisories"][0])), "duplicate glibc finding"),
    ("non-string-id", _set(("advisories", 0, "id"), 1), "must be strings"),
    ("order", lambda d: d["advisories"].reverse(), "approved order"),
    ("foreign-component", _set(("component",), "openssl"), "component"),
    ("future-version", _set(("source_version",), "2.41-12+deb13u5"), "source_version"),
    ("owner", _set(("owner",), "Someone Else"), "owner"),
    ("platforms", _set(("platforms",), ["linux/arm64"]), "platforms"),
    ("postgres-index", _set(("postgres_index",), "sha256:" + "0" * 64), "postgres_index"),
    ("python-index", _set(("python_index",), release.GO_RELEASE_IMAGE), "python_index"),
    ("accepts-other", _set(("accepts_image_or_other_findings",), True), "accepts_image_or_other_findings"),
    ("bool-type", _set(("accepts_image_or_other_findings",), 0), "accepts_image_or_other_findings"),
    ("decision", _set(("decision",), "fixed"), "decision"),
    ("catalogue", _set(("retained_catalogue_sha256",), "0" * 64), "retained_catalogue_sha256"),
    ("class-fixed", _set(("advisories", 8, "class"), "fixed"), "CVE-2026-19499 class"),
    ("class-outside", _set(("advisories", 8, "class"), "outside_affected_range"), "CVE-2026-19499 class"),
    ("disposition", _set(("advisories", 0, "disposition"), "fixed"), "disposition"),
    ("finding-owner", _set(("advisories", 0, "owner"), "Other"), "CVE-2010-4756 owner"),
    ("score-bool", _set(("advisories", 0, "highest_reported_score"), True), "score"),
    ("score-nan", _set(("advisories", 0, "highest_reported_score"), float("nan")), "score"),
    ("score-range", _set(("advisories", 0, "highest_reported_score"), 11.0), "score"),
    ("band", _set(("advisories", 0, "highest_reported_band"), "SEVERE"), "band"),
    ("primary", _set(("advisories", 0, "primary"), "https://example.invalid/CVE-2010-4756"), "primary URL"),
    ("secondary", _set(("advisories", 0, "secondary"), "https://example.invalid/x.json"), "secondary URL"),
    ("secondary-sha", _set(("advisories", 0, "secondary_sha256"), "x"), "secondary_sha256"),
    ("finding-extra", _set(("advisories", 0, "fixed_in"), "2.42"), r"extra \['fixed_in'\]"),
    ("finding-object", _set(("advisories", 0), "CVE-2010-4756"), "must be strings"),
    ("advisories-type", _set(("advisories",), {}), "must be a list"),
]


@pytest.mark.parametrize(("mutate", "match"), [m[1:] for m in RECORD_MUTATIONS],
                         ids=[m[0] for m in RECORD_MUTATIONS])
def test_record_shape_refusals(mutate: Mutation, match: str) -> None:
    data = copy.deepcopy(json.loads(RECORD_BYTES))
    assert risk.validate_record(copy.deepcopy(data)) == data
    mutate(data)
    with pytest.raises(GlibcRiskError, match=match):
        risk.validate_record(data)
    with pytest.raises(GlibcRiskError, match="not a JSON object"):
        risk.validate_record([data])


def test_candidate_and_server_are_accepted_independently_with_original_findings() -> None:
    result = risk.evaluate_d12_post_build(
        candidate_image_id=CANDIDATE_ID, candidate_inventory=_inventory(), server_image_id=SERVER_ID,
        server_inventory=_inventory(), base_reference=HISTORICAL_POSTGRES, platform="linux/amd64",
        availability=NATIVE)
    assert result["status"] == risk.ACCEPTED == "accepted_unresolved"
    assert result["record_sha256"] == risk.APPROVED_RECORD_SHA256 and result["record_path"] == risk.RECORD_RELPATH
    assert result["findings"] == json.loads(RECORD_BYTES)["advisories"]
    assert result["image_qualified"] is False and result["accepts_image_or_other_findings"] is False
    assert [(i["label"], i["image_id"], i["platform"]) for i in result["images"]] == [
        ("candidate", CANDIDATE_ID, "linux/amd64"), ("server", SERVER_ID, "linux/amd64")]
    for image in result["images"]:
        assert image["base_reference"] == HISTORICAL_POSTGRES
        assert image["package"] == ["libc6", "2.41-12+deb13u4", "amd64"]
        assert image["glibc_packages"] == [["libc6", risk.SOURCE_VERSION, "amd64"],
                                           ["libc-bin", risk.SOURCE_VERSION, "amd64"]]
        assert image["libc"] == {"path": "/usr/lib/x86_64-linux-gnu/libc.so.6", "sha256": LIBC_SHA,
                                 "owner": "libc6", "md5": "match", "file_observations": 1, "ldd_observations": 1}
        assert image["notice"] == {"path": "/usr/share/doc/libc6/copyright", "sha256": NOTICE_SHA}
    assert len(json.dumps(result, sort_keys=True)) < 20_000


def test_native_arm64_raw_python_base_is_accepted() -> None:
    image = _image("python-base", "sha256:" + "7" * 64, "linux/arm64", HISTORICAL_PYTHON)
    result = risk.assess_glibc_disposition([image])
    assert result["status"] == risk.ACCEPTED
    assert result["images"][0]["libc"]["path"] == "/usr/lib/aarch64-linux-gnu/libc.so.6"
    assert result["images"][0]["os"] == ["Debian GNU/Linux 13 (trixie)", "aarch64", "arm64"]


def test_duplicate_observations_of_the_same_real_file_deduplicate_consistently() -> None:
    single = risk.assess_glibc_disposition([_image()])["images"][0]
    dup = _image(duplicate=True)
    forward = risk.assess_glibc_disposition([dup])["images"][0]
    dup["inventory"]["files"].reverse()
    dup["inventory"]["links"].reverse()
    backward = risk.assess_glibc_disposition([dup])["images"][0]
    assert forward == backward
    assert (forward["libc"]["file_observations"], forward["libc"]["ldd_observations"]) == (2, 2)
    strip = ("file_observations", "ldd_observations")
    assert {k: v for k, v in forward["libc"].items() if k not in strip} == {
        k: v for k, v in single["libc"].items() if k not in strip}


@pytest.mark.parametrize(("field", "value"), [
    ("sha256", "d" * 64), ("owner", "libc-bin"), ("md5", "mismatch"),
    ("resolved", "/usr/local/lib/libc.so.6"), ("kind", "other"), ("interpreter", "/bin/sh"),
])
def test_conflicting_observations_of_libc_refuse(field: str, value: str) -> None:
    image = _image(duplicate=True)
    _libc_rows(image)[1][field] = value
    with pytest.raises(GlibcRiskError, match="conflicting libc.so.6 observations"):
        risk.assess_glibc_disposition([image])


def _rows_where(key: str, predicate: Callable[[Any], bool], action: Callable[[Any], None]) -> Mutation:
    def mutate(image: dict[str, Any]) -> None:
        for row in [r for r in image["inventory"][key] if predicate(r)]:
            action(row)
    return mutate


def _libc_field(field: str, value: object) -> Mutation:
    return lambda image: _libc_rows(image)[0].__setitem__(field, value)


def _drop(key: str, predicate: Callable[[Any], bool]) -> Mutation:
    def mutate(image: dict[str, Any]) -> None:
        image["inventory"][key] = [r for r in image["inventory"][key] if not predicate(r)]
    return mutate


def _is_libc6(row: Any) -> bool:
    return bool(row[0] == "libc6")


def _is_libc_bin(row: Any) -> bool:
    return bool(row[0] == "libc-bin")


def _is_libc_link(row: Any) -> bool:
    return bool(row[1] == "libc.so.6")


def _is_libc_file(row: Any) -> bool:
    return bool(row["invoked"].endswith("/libc.so.6"))


INVENTORY_REFUSALS: list[tuple[str, Mutation, str]] = [
    ("platform", lambda i: i.update(platform="linux/386"), "approved native platform"),
    ("platform-type", lambda i: i.update(platform=["linux/amd64"]), "approved native platform"),
    ("emulated", lambda i: i.update(execution="emulated"), "is not native"),
    ("arch", lambda i: i["inventory"].update(os=["Debian GNU/Linux 13 (trixie)", "aarch64", "arm64"]),
     "os/architecture"),
    ("base-os", lambda i: i["inventory"].update(os=["Debian GNU/Linux 12 (bookworm)", "x86_64", "amd64"]),
     "os/architecture"),
    ("future-version", _rows_where("packages", _is_libc6, lambda r: r.__setitem__(1, "2.41-12+deb13u5")),
     "libc6 package rows"),
    ("package-arch", _rows_where("packages", _is_libc6, lambda r: r.__setitem__(2, "arm64")), "libc6 package rows"),
    ("package-missing", _drop("packages", _is_libc6), "libc6 package rows"),
    ("foreign-multiarch", lambda i: i["inventory"]["packages"].append(["libc6", risk.SOURCE_VERSION, "i386"]),
     "libc6 package rows"),
    ("libc-bin-version", _rows_where("packages", _is_libc_bin, lambda r: r.__setitem__(1, "2.41-12+deb13u5")),
     "libc-bin package rows"),
    ("libc-bin-missing", _drop("packages", _is_libc_bin), "libc-bin package rows"),
    ("owner", _libc_field("owner", "libc-bin"), "libc owner"),
    ("owner-unknown", _libc_field("owner", "-"), "libc owner"),
    ("md5-mismatch", _libc_field("md5", "mismatch"), "md5"),
    ("md5-unlisted", _libc_field("md5", "unlisted"), "md5"),
    ("sha-unknown", _libc_field("sha256", "-"), "libc SHA-256"),
    ("missing-file", _libc_field("kind", "missing"), "libc kind"),
    ("unresolved", _libc_field("resolved", "-"), "resolved path"),
    ("wrong-path", _libc_field("resolved", "/usr/local/lib/libc.so.6"), "resolved path"),
    ("non-string", _libc_field("md5", None), "incomplete"),
    ("no-file", _drop("files", _is_libc_file), "no observed libc.so.6"),
    ("notice-absent", lambda i: i["inventory"]["notices"].__setitem__(risk.LIBC_NOTICE, "absent"), "notice"),
    ("notice-missing", lambda i: i["inventory"]["notices"].pop(risk.LIBC_NOTICE), "notice"),
    ("no-ldd", _drop("links", _is_libc_link), "no ldd observation"),
    ("ldd-not-found", _rows_where("links", _is_libc_link, lambda r: r.__setitem__(2, "not")), "do not resolve"),
    ("ldd-foreign", _rows_where("links", _is_libc_link, lambda r: r.__setitem__(2, "/opt/libc.so.6")),
     "do not resolve"),
    ("files-type", lambda i: i["inventory"].update(files={}), "files must be a list"),
    ("inventory-type", lambda i: i.update(inventory=[]), "inventory is not an object"),
    ("image-id-none", lambda i: i.update(image_id=None), "image identity None"),
    ("image-id-malformed", lambda i: i.update(image_id="sha256:XYZ"), "image identity"),
    ("image-id-index", lambda i: i.update(image_id=risk.POSTGRES_INDEX), "index digest is not an image identity"),
    ("base-foreign", lambda i: i.update(base_reference=release.GO_RELEASE_IMAGE), "not an approved index"),
    ("base-tag-only", lambda i: i.update(base_reference="postgres:16.15-trixie"), "not an approved index"),
    ("label", lambda i: i.update(label=""), "label"),
]


@pytest.mark.parametrize(("mutate", "match"), [m[1:] for m in INVENTORY_REFUSALS],
                         ids=[m[0] for m in INVENTORY_REFUSALS])
def test_inventory_refusal_classes_despite_accepted_risk(mutate: Mutation, match: str) -> None:
    image = _image()
    assert risk.assess_glibc_disposition([copy.deepcopy(image)])["status"] == risk.ACCEPTED
    mutate(image)
    with pytest.raises(GlibcRiskError, match=match):
        risk.assess_glibc_disposition([image])
    refused = risk.evaluate_glibc_disposition([image])
    assert refused["status"] == risk.REFUSED and refused["image_qualified"] is False
    assert refused["record_sha256"] == risk.APPROVED_RECORD_SHA256


@pytest.mark.parametrize(("images", "match"), [
    ([_image(), _image("server")], "identities are not distinct"),
    ([_image(), _image(image_id=SERVER_ID)], "labels are not distinct"),
    ([], "at least one image"),
    ([_image(), "server"], "image entry is not an object"),
], ids=["same-identity", "same-label", "empty", "non-object"])
def test_multi_image_refusals(images: list[Any], match: str) -> None:
    with pytest.raises(GlibcRiskError, match=match):
        risk.assess_glibc_disposition(images)


def test_conflicting_libc_bytes_across_images_on_one_platform_refuse() -> None:
    server = _image("server", SERVER_ID)
    _libc_rows(server)[0]["sha256"] = "d" * 64
    with pytest.raises(GlibcRiskError, match="conflicting libc6 2.41-12\\+deb13u4 bytes or notices on linux/amd64"):
        risk.assess_glibc_disposition([_image(), server])
    server = _image("server", SERVER_ID)
    server["inventory"]["notices"][risk.LIBC_NOTICE] = "b" * 64
    with pytest.raises(GlibcRiskError, match="bytes or notices"):
        risk.assess_glibc_disposition([_image(), server])


def test_refusal_result_retains_bounded_identity_evidence() -> None:
    emulated = {**_image(label="x" * 5000), "execution": "emulated"}
    result = risk.evaluate_d12_post_build(
        candidate_image_id=CANDIDATE_ID, candidate_inventory=_inventory(), server_image_id=SERVER_ID,
        server_inventory=_inventory(), base_reference=HISTORICAL_POSTGRES, platform="linux/amd64",
        availability={**NATIVE, "execution": "emulated"})
    assert result["status"] == risk.REFUSED and "candidate: linux/amd64 execution 'emulated'" in result["refusal"]
    assert [(i["label"], i["image_id"], i["platform"]) for i in result["images"]] == [
        ("candidate", CANDIDATE_ID, "linux/amd64"), ("server", SERVER_ID, "linux/amd64")]
    assert "findings" not in result and result["accepts_image_or_other_findings"] is False
    foreign = risk.evaluate_d12_post_build(
        candidate_image_id=CANDIDATE_ID, candidate_inventory=_inventory(), server_image_id=SERVER_ID,
        server_inventory=_inventory(), base_reference=HISTORICAL_POSTGRES, platform="linux/amd64",
        availability={**NATIVE, "platform": "linux/arm64"})  # ARM availability is never substituted for AMD
    assert foreign["status"] == risk.REFUSED and "for 'linux/arm64'" in foreign["refusal"]
    long = risk.evaluate_glibc_disposition([emulated])
    assert len(long["refusal"]) <= 1200 and len(long["images"][0]["label"]) <= 600
    assert len(json.dumps(long)) < 4000


def test_current_runtime_pins_do_not_retroactively_extend_the_finite_approval() -> None:
    for current in (release.POSTGRES_RELEASE_IMAGE, release.PYTHON_RELEASE_IMAGE):
        assert current not in risk.BASE_REFERENCES
        result = risk.evaluate_glibc_disposition([_image(base=current)])
        assert result["status"] == risk.REFUSED and "not an approved index" in result["refusal"]
    assert (REPO_ROOT / risk.RECORD_RELPATH).read_bytes() == RECORD_BYTES
