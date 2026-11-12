"""Selected-only task loading over a hash-pinned raw catalog; unselected bodies are never decoded.

Catalogs here are run-owned synthetic public files. The real catalog is read
only by the selected-loader integration owner.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from repomap_test_support.w5_semantic_support import make_w5_calibration_task
from retrieval_evaluation_schema import TASK_CATALOG_SCHEMA_VERSION
from retrieval_public_text_census import retained_task_sha256, task_sha256
import retrieval_public_text_tasks as tasks_module
from retrieval_public_text_tasks import (
    CATALOG_FILE_SHA256, HISTORICAL_SEMANTIC_CATALOG_IDENTITY, ORIGINAL_MANIFEST_SHA256, SELECTED_TASKS,
    TASK_PINS_SCHEMA, SelectedTaskPins, TaskSelectionRefusal, load_selected_calibration_tasks, parse_task_pins,
    registered_task_pins,
)

HELD_OUT_MARKER = "HELD-OUT-BODY-NEVER-DECODED-5521"
_REGISTERED_ROWS = """
cal-01 1 86f343b80be32c5a785fd886603a511e7bac9354c0ed42864c9f897e821dce0e
cal-02 1 92c19d7af627b4306330f0d9f87b973df88bf5a5bb331a80fefc5cb557a36ca2
cal-03 1 cc0a3905abd7564143df29ce99f16191b8ddaad233abb55536adac47e5a10188
cal-04 1 455a5d7ba69583612cbea6b1bbf0dbbebd5f1d9cf23fbdf094bb72548e429c82
cal-05 1 6d6f5c4b1e9efd29d3334d6b6c7fb76da119c0c5aa6f488450bfeaeb2011af98
cal-06 1 9c1fb3c236bb1469a1190b4b8fd2661f1b4cbd0316ff337cdfe56120c55f084a
cal-07 1 81215c2291a73204191443b9539dee390a6d1c198000e21676f6db0731bbd9eb
cal-08 1 877744572e3fdc7abb3c91595a944fb01b77858b8644334053f59fb772d4a13d
cal-09 1 8eb256815a9b6869b17ec4edf159e146e3a4532f4da38fa1f587016417a4795b
cal-10 1 74fbfb669ff04b803a4ab7480e9ca05d4d609441a79a31868d6ebdad48a63fcf
cal-11 1 69bc0aa1e97aa9768acad50ec3e1a146833e08646fc93877769487dd93874e69
cal-12 1 d5b778d84623ff380d0ca2b550d759302c04a2c2d0a58ce04563f35cd8513e8e
cal-13 1 fe176f87553dee59dfd54cf3df9be6b6911a9920b04ddb8c82a857da5e796069
cal-14 1 e2cffa3685bf46217416e882b9446355d9d5d5877d449710eead2297e3ebd726
cal-15 1 f99a7614cbf0d58a245d9cc830e3c65341e938c5611619bb650d9fcaa53906d0
cal-16 1 766de752781b87a3055cf4010380deca4e620b54ca87d65963040f9f010b0c59
cal-17 1 d19c8888c0af02388c5d2e01b1cfa98f3d5ac80374f93e87ffed8080828d1302
cal-18 1 143d964c74a8a3f883a0aa8bbadd807b6fcffca115baa23d086853aaa5813cdf
cal-19 1 025f6bb3535853b9d1a68fbc0660ef3d0efc4e469ef1491b8238ab7b9f8eb63b
cal-20 1 5f18b608154eea8c1254c2f741676ceb775eb0d13d5ccf91029e3c95468533a3
cal-21 1 9405f7722f3a614c24db974f99df979bd4817b02f61badbdd0ab42dd7e78bbb5
cal-22 1 ec150d9a6c3d6bb632771e19b9ae73b56faa19fe26f41c418b42c13e0f02e937
cal-23 2 5bb268734bdfef24cfa9ac3521da0c15036c846756c3880634245b280e90ac66
cal-24 1 ffe7481f32dfdd3924a9fbe0cf50f2c04a17e2dc3c7bc1ef863ce219725efcef
"""


def _registered_input() -> dict[str, Any]:
    rows = [line.split() for line in _REGISTERED_ROWS.strip().splitlines()]
    return {
        "catalog_file_sha256": "10a34e261ee625dbfffb31e30d450bca270878291890f165e6031a86b3bf6d38",
        "held_out_decoded": False,
        "historical_semantic_catalog_identity":
            "sha256:8da52c1a477a78ba5f467892690e2f59045326d18ba371d693dda157736a80a1",
        "original_manifest_sha256": "33b417da06658f8aac3be851d4df5ad3655b2cbd1157d2009b0da65cbffa1155",
        "schema": "cloe-public-text-selected-task-pins-v1",
        "tasks": [{"generation": int(g), "task_id": t, "task_sha256": "sha256:" + d} for t, g, d in rows],
    }


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_module_constants_equal_the_registered_task_pins_input() -> None:
    raw = json.dumps(_registered_input(), indent=2, sort_keys=True).encode("utf-8")
    parsed = parse_task_pins(raw)
    assert parsed == registered_task_pins()
    assert (parsed.catalog_file_sha256, parsed.historical_semantic_catalog_identity, parsed.original_manifest_sha256) == (
        CATALOG_FILE_SHA256, HISTORICAL_SEMANTIC_CATALOG_IDENTITY, ORIGINAL_MANIFEST_SHA256)
    assert parsed.tasks == SELECTED_TASKS and len(SELECTED_TASKS) == 24
    assert [t for t, g, _d in SELECTED_TASKS if g == 2] == ["cal-23"]
    assert parsed.identity() == registered_task_pins().identity() and parsed.identity().startswith("sha256:")
    assert parsed.to_dict()["held_out_decoded"] is False and TASK_PINS_SCHEMA == _registered_input()["schema"]


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(extra=1), lambda d: d.pop("original_manifest_sha256"), lambda d: d.update(held_out_decoded=True),
    lambda d: d.update(schema="other"), lambda d: d.update(catalog_file_sha256="sha256:" + "0" * 64),
    lambda d: d.update(historical_semantic_catalog_identity="0" * 64), lambda d: d.update(tasks=[]),
    lambda d: d["tasks"][0].update(generation=True), lambda d: d["tasks"][0].update(generation=3),
    lambda d: d["tasks"][0].update(task_sha256="sha256:XYZ"), lambda d: d["tasks"][1].update(task_id="cal-01"),
    lambda d: d["tasks"][0].update(task_id="cal 01"), lambda d: d["tasks"][0].update(extra=1),
    lambda d: d.update(tasks=d["tasks"] * 2),
])
def test_pin_parser_is_strict_and_closed(mutate: Any) -> None:
    value = _registered_input()
    mutate(value)
    with pytest.raises(TaskSelectionRefusal) as error:
        parse_task_pins(json.dumps(value).encode("utf-8"))
    assert error.value.code == "task_pins_invalid"


@pytest.mark.parametrize("raw", [b"", b"[]", b'{"a":1,"a":1}', b'{"x": NaN}', b"\xff", "x".encode() * 70000])
def test_pin_parser_refuses_malformed_bytes(raw: bytes) -> None:
    with pytest.raises(TaskSelectionRefusal) as error:
        parse_task_pins(raw)
    assert error.value.code == "task_pins_invalid"


def _tasks() -> tuple[Any, ...]:
    held = replace(make_w5_calibration_task(task_id="ho-01", split="held_out"), question=HELD_OUT_MARKER).validate()
    return (
        make_w5_calibration_task(task_id="cal-02"), held, make_w5_calibration_task(task_id="cal-01"),
        make_w5_calibration_task(task_id="cal-09", generation=2, grading_rule="absent_answer", gold_targets=()),
        replace(make_w5_calibration_task(task_id="ho-02", split="held_out"), question=HELD_OUT_MARKER + "-2").validate(),
    )


def _catalog(tasks: tuple[Any, ...], **top: Any) -> bytes:
    body = {"schema_version": TASK_CATALOG_SCHEMA_VERSION, "fixture_id": "synthetic-public", **top,
            "tasks": [task.to_dict() for task in tasks]}
    return json.dumps(body, indent=2, ensure_ascii=True).encode("ascii")


def _pins(raw: bytes, selected: tuple[tuple[str, int, str], ...] | None = None) -> SelectedTaskPins:
    if selected is None:
        by_id = {task.task_id: task for task in _tasks()}
        selected = tuple((tid, by_id[tid].generation, retained_task_sha256(by_id[tid])) for tid in ("cal-01", "cal-02", "cal-09"))
    return parse_task_pins(json.dumps({
        "catalog_file_sha256": _sha(raw), "held_out_decoded": False,
        "historical_semantic_catalog_identity": "sha256:" + "8" * 64, "original_manifest_sha256": "3" * 64,
        "schema": TASK_PINS_SCHEMA,
        "tasks": [{"generation": g, "task_id": t, "task_sha256": d} for t, g, d in selected],
    }).encode("utf-8"))


def _write(tmp_path: Path, raw: bytes) -> Path:
    path = tmp_path / "catalog.json"
    path.write_bytes(raw)
    return path


class _DecodeSpy:
    def __init__(self, inner: Any, on_first: Any = None) -> None:
        self.inner, self.on_first = inner, on_first
        self.inputs: list[bytes] = []

    def __call__(self, raw: bytes) -> Any:
        self.inputs.append(bytes(raw))
        if self.on_first is not None and len(self.inputs) == 1:
            self.on_first()
        return self.inner(raw)


def test_loader_decodes_only_selected_objects_in_pin_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _catalog(_tasks())
    spy = _DecodeSpy(tasks_module._decode_json)
    monkeypatch.setattr(tasks_module, "_decode_json", spy)
    loaded = load_selected_calibration_tasks(_write(tmp_path, raw), _pins(raw))
    assert [task.task_id for task in loaded.tasks] == ["cal-01", "cal-02", "cal-09"]
    assert len(spy.inputs) == 3 and all(HELD_OUT_MARKER.encode() not in item for item in spy.inputs)
    assert all(b"ho-0" not in item for item in spy.inputs)
    assert [t.task_id for t in loaded.for_generation(1)] == ["cal-01", "cal-02"]
    assert [t.task_id for t in loaded.for_generation(2)] == ["cal-09"]
    assert loaded.retained_digests(2) == {"cal-09": retained_task_sha256(loaded.tasks[2])}
    assert loaded.pins.historical_semantic_catalog_identity == "sha256:" + "8" * 64
    assert loaded.identity() == load_selected_calibration_tasks(_write(tmp_path, raw), _pins(raw)).identity()
    assert HELD_OUT_MARKER not in repr(loaded) and HELD_OUT_MARKER not in json.dumps(loaded.to_dict())


def test_raw_hash_is_recomputed_and_never_the_historical_identity(tmp_path: Path) -> None:
    raw = _catalog(_tasks())
    pins = replace(_pins(raw), catalog_file_sha256=_sha(raw + b" "))
    with pytest.raises(TaskSelectionRefusal) as error:
        load_selected_calibration_tasks(_write(tmp_path, raw), pins)
    assert error.value.code == "task_catalog_hash_mismatch"


def _refusal(tmp_path: Path, raw: bytes, selected: Any = None) -> str:
    with pytest.raises(TaskSelectionRefusal) as error:
        load_selected_calibration_tasks(_write(tmp_path, raw), _pins(raw, selected))
    return error.value.code


def test_duplicate_and_missing_selected_ids_refuse(tmp_path: Path) -> None:
    tasks = _tasks()
    assert _refusal(tmp_path, _catalog(tasks + (tasks[0],))) == "task_selected_duplicate"
    assert _refusal(tmp_path, _catalog(tasks[:2] + tasks[3:])) == "task_selected_missing"
    escaped = _catalog(tasks).replace(b'"task_id": "cal-01"', b'"task_id": "cal\\u002d01"')
    assert _refusal(tmp_path, escaped) == "task_selected_missing"


def _deep(levels: int) -> Any:
    value: Any = 0
    for _ in range(levels):
        value = [value]
    return value


@pytest.mark.parametrize("case", [
    "trailing", "duplicate_top", "schema", "non_string_id", "deep_held_out", "control_byte", "tasks_object",
    "element_scalar", "escaped_key", "missing_tasks", "two_task_ids", "unterminated",
])
def test_structural_locator_refusals(tmp_path: Path, case: str) -> None:
    tasks = _tasks()
    raw = _catalog(tasks)
    if case == "trailing":
        raw += b" x"
    elif case == "duplicate_top":
        raw = raw.replace(b'"fixture_id"', b'"schema_version": "x", "fixture_id"', 1)
    elif case == "schema":
        raw = raw.replace(TASK_CATALOG_SCHEMA_VERSION.encode(), b"cloe-retrieval-task-catalog-v0")
    elif case == "non_string_id":
        raw = raw.replace(b'"task_id": "ho-01"', b'"task_id": 7')
    elif case == "deep_held_out":
        raw = _catalog(tasks[:1] + (replace(tasks[1], permitted_query_plan={"deep": _deep(70)}),) + tasks[2:])
    elif case == "control_byte":
        raw = raw.replace(HELD_OUT_MARKER.encode(), b"HELD\x01OUT")
    elif case == "tasks_object":
        raw = json.dumps({"schema_version": TASK_CATALOG_SCHEMA_VERSION, "tasks": {"a": 1}}).encode()
    elif case == "element_scalar":
        raw = raw.replace(b'"tasks": [', b'"tasks": [1, ', 1)
    elif case == "escaped_key":
        raw = raw.replace(b'"task_id": "ho-01"', b'"task\\u005fid": "ho-01"')
    elif case == "missing_tasks":
        raw = json.dumps({"schema_version": TASK_CATALOG_SCHEMA_VERSION}).encode()
    elif case == "two_task_ids":
        raw = raw.replace(b'"task_id": "ho-01"', b'"task_id": "ho-01", "task_id": "ho-03"')
    else:
        raw = raw[:-3]
    assert _refusal(tmp_path, raw) == "task_catalog_structure"


def test_selected_decode_split_generation_and_digest_refusals(tmp_path: Path) -> None:
    tasks = _tasks()
    raw = _catalog(tasks)
    digest = {t.task_id: retained_task_sha256(t) for t in tasks}
    assert _refusal(tmp_path, raw, (("ho-01", 1, digest["ho-01"]),)) == "task_split_mismatch"
    assert _refusal(tmp_path, raw, (("cal-01", 2, digest["cal-01"]),)) == "task_generation_mismatch"
    assert _refusal(tmp_path, raw, (("cal-01", 1, digest["cal-02"]),)) == "task_digest_mismatch"
    broken = raw.replace(b'"family": "exact_symbol_and_partial_name"', b'"family": "unknown_family"', 1)
    assert _refusal(tmp_path, broken, (("cal-02", 1, digest["cal-02"]),)) == "task_selected_invalid"
    duplicated_key = raw.replace(b'"task_id": "cal-01",', b'"task_id": "cal-01", "split": "calibration",')
    assert _refusal(tmp_path, duplicated_key, (("cal-01", 1, digest["cal-01"]),)) == "task_selected_invalid"


def test_unavailable_catalogs_refuse_before_any_decode(tmp_path: Path) -> None:
    raw = _catalog(_tasks())
    pins = _pins(raw)
    target = _write(tmp_path, raw)
    link = tmp_path / "link.json"
    os.symlink(target, link)
    for path in (tmp_path / "missing.json", link, tmp_path):
        with pytest.raises(TaskSelectionRefusal) as error:
            load_selected_calibration_tasks(path, pins)
        assert error.value.code == "task_catalog_unavailable"
    with pytest.raises(TaskSelectionRefusal) as oversized:
        load_selected_calibration_tasks(target, pins, max_bytes=len(raw) - 1)
    assert oversized.value.code == "task_catalog_unavailable"


def test_a_change_between_the_two_reads_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _catalog(_tasks())
    path = _write(tmp_path, raw)
    spy = _DecodeSpy(tasks_module._decode_json, on_first=lambda: path.write_bytes(raw + b"\n"))
    monkeypatch.setattr(tasks_module, "_decode_json", spy)
    with pytest.raises(TaskSelectionRefusal) as error:
        load_selected_calibration_tasks(path, _pins(raw))
    assert error.value.code == "task_catalog_changed"


def test_refusal_codes_are_closed() -> None:
    with pytest.raises(ValueError):
        TaskSelectionRefusal("free text")
    assert str(TaskSelectionRefusal("task_selected_missing")) == "task_selected_missing"


def test_unicode_selected_task_preserves_retained_and_v1_digest_schemes(tmp_path: Path) -> None:
    task = replace(make_w5_calibration_task(task_id="cal-unicode"), question="Find café").validate()
    raw = _catalog((task,))
    pins = _pins(raw, selected=((task.task_id, task.generation, retained_task_sha256(task)),))
    path = tmp_path / "unicode.json"
    path.write_bytes(raw)
    selected = load_selected_calibration_tasks(path, pins)
    assert selected.tasks == (task,)
    assert selected.retained_digests(1)[task.task_id] == retained_task_sha256(task) != task_sha256(task)
