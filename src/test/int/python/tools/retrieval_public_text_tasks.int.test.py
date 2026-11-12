"""The registered pins select exactly 24 calibration records from the real hash-pinned catalog.

This is the only owner that reads the real task catalog. Held-out objects are
located lexically and never decoded; no question or gold value is logged.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from retrieval_public_text_census import retained_task_sha256, task_sha256
import retrieval_public_text_tasks as tasks_module
from retrieval_public_text_tasks import (
    CATALOG_FILE_SHA256, HISTORICAL_SEMANTIC_CATALOG_IDENTITY, SELECTED_TASKS, load_selected_calibration_tasks,
    registered_task_pins,
)

CATALOG = Path(__file__).resolve().parents[3] / "fixtures" / "retrieval_evaluation" / "mixed-v1" / "tasks" / "catalog-v1.json"


class _DecodeSpy:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.lengths: list[int] = []
        self.task_ids: list[str | None] = []

    def __call__(self, raw: bytes) -> Any:
        value = self.inner(raw)
        self.lengths.append(len(raw))
        self.task_ids.append(value.get("task_id") if isinstance(value, dict) else None)
        return value


def test_retained_and_v1_task_digests_keep_their_distinct_schemes() -> None:
    pins = registered_task_pins()
    selected = load_selected_calibration_tasks(CATALOG, pins)
    retained = {t: d for t, _g, d in pins.tasks}
    differences = set()
    for task in selected.tasks:
        ascii_digest = "sha256:" + hashlib.sha256(json.dumps(
            task.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
        assert ascii_digest == retained[task.task_id]
        if task_sha256(task) != retained[task.task_id]:
            differences.add(task.task_id)
    assert differences == {"cal-20"}


def test_registered_pins_decode_exactly_the_24_selected_calibration_records(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _DecodeSpy(tasks_module._decode_json)
    monkeypatch.setattr(tasks_module, "_decode_json", spy)
    selected = load_selected_calibration_tasks(CATALOG, registered_task_pins())
    assert hashlib.sha256(CATALOG.read_bytes()).hexdigest() == CATALOG_FILE_SHA256
    assert spy.task_ids == [task_id for task_id, _g, _d in SELECTED_TASKS]
    assert len(spy.lengths) == 24
    assert [(t.task_id, t.generation, retained_task_sha256(t)) for t in selected.tasks] == list(SELECTED_TASKS)
    assert all(task.split == "calibration" for task in selected.tasks)
    assert (len(selected.for_generation(1)), len(selected.for_generation(2))) == (23, 1)
    assert [task.task_id for task in selected.for_generation(2)] == ["cal-23"]
    assert selected.retained_digests(2) == {"cal-23": SELECTED_TASKS[22][2]}
    public = json.dumps(selected.to_dict(), sort_keys=True)
    assert selected.pins.historical_semantic_catalog_identity == HISTORICAL_SEMANTIC_CATALOG_IDENTITY
    assert HISTORICAL_SEMANTIC_CATALOG_IDENTITY != "sha256:" + CATALOG_FILE_SHA256
    for task in selected.tasks:
        assert task.question not in public
