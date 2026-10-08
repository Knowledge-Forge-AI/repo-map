from __future__ import annotations

from pathlib import Path

import json

import pytest

from ci.scanner_suppressions import Directive, classify, load_baseline, scan_paths


def _baseline(*records: Directive) -> tuple[Directive, ...]:
    return tuple(records)


def test_semantic_inventory_ignores_strings_docs_and_implementation_patterns(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        'TEXT = "# noqa: F401"\n'
        'DOC = """# type: ignore[attr-defined]"""\n'
        "value = 1  # noqa: F841\n",
        encoding="utf-8",
    )
    docs = tmp_path / "README.md"
    docs.write_text("Document `# noqa: F401` without an operative comment.\n", encoding="utf-8")
    implementation = tmp_path / "scanner_suppressions.py"
    implementation.write_text(
        'PATTERN = r"#\\s*noqa"\nvalue = 1  # noqa: F401\n',
        encoding="utf-8",
    )

    records = scan_paths((source, docs, implementation), root=tmp_path)

    assert [(record.path, record.line, record.kind, record.scope) for record in records] == [
        ("sample.py", 3, "ruff-noqa", ("F841",)),
        ("scanner_suppressions.py", 2, "ruff-noqa", ("F401",)),
    ]


def test_semantic_inventory_classifies_added_broadened_removed_and_unchanged(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "a = 1  # noqa: F401\n"
        "b = 2  # noqa: F401, F841\n"
        "c = 3  # type: ignore[arg-type]\n",
        encoding="utf-8",
    )
    current = scan_paths((source,), root=tmp_path)
    baseline = _baseline(
        current[0],
        Directive.create("ruff-noqa", "sample.py", 2, ("F401",)),
        Directive.create("type-ignore", "sample.py", 3, ("arg-type", "assignment")),
        Directive.create("security-nosec", "sample.py", 4, ("B101",)),
    )

    delta = classify(current, baseline)

    assert [record.line for record in delta.unchanged] == [1]
    assert [record.line for record in delta.broadened] == [2]
    assert [record.line for record in delta.removed] == [3, 4]
    assert delta.added == ()
    assert delta.blocking is True


def test_semantic_inventory_addition_blocks_while_removal_does_not(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("value = 1  # noqa\n", encoding="utf-8")
    current = scan_paths((source,), root=tmp_path)

    delta = classify(current, ())
    assert delta.blocking is True
    assert delta.added == current
    removed = classify((), current)
    assert removed.blocking is False
    assert removed.removed == current


def test_unchanged_inventory_and_fingerprints_are_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("value = 1  # noqa: F841, F401\n", encoding="utf-8")

    first = scan_paths((source,), root=tmp_path)
    second = scan_paths((source,), root=tmp_path)
    delta = classify(second, first)

    assert first == second
    assert first[0].scope == ("F401", "F841")
    assert len(first[0].fingerprint) == 64
    assert delta.unchanged == first
    assert delta.blocking is False


def test_record_level_baseline_requires_fingerprint_and_justification(
    tmp_path: Path,
) -> None:
    record = Directive.create("ruff-noqa", "sample.py", 1, ("F401",))
    entry = record.to_jsonable()
    baseline = tmp_path / "baseline.json"
    document = {
        "schema": "repomap-pre-review-baseline-v2",
        "ratchets": {
            "scanner-suppressions": {"inventory": [entry]}
        },
    }
    baseline.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="requires justification"):
        load_baseline(baseline)

    entry["justification"] = "reviewed pre-existing directive"
    baseline.write_text(json.dumps(document), encoding="utf-8")
    assert load_baseline(baseline) == (record,)


def test_relocation_pure_line_shift_is_unchanged(tmp_path: Path) -> None:
    baseline_directive = Directive.create(
        "ruff-noqa",
        "sample.py",
        2,
        ("N802",),
        target="def do_GET(self) -> None:",
        occurrence=1,
    )
    source = tmp_path / "sample.py"
    source.write_text(
        "# Header line 1\n"
        "# Header line 2\n"
        "# Header line 3\n"
        "def do_GET(self) -> None:  # noqa: N802\n"
        "    pass\n",
        encoding="utf-8",
    )
    current = scan_paths((source,), root=tmp_path)
    assert len(current) == 1
    assert current[0].line == 4
    assert current[0].target == "def do_GET(self) -> None:"

    delta = classify(current, (baseline_directive,))
    assert delta.unchanged == current
    assert delta.added == ()
    assert delta.broadened == ()
    assert delta.removed == ()
    assert delta.blocking is False


def test_changed_suppression_kind_is_added_and_removed(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("x = 1  # type: ignore[assignment]\n", encoding="utf-8")
    current = scan_paths((source,), root=tmp_path)

    baseline_directive = Directive.create(
        "ruff-noqa", "sample.py", 1, ("F841",), target="x = 1", occurrence=1
    )
    delta = classify(current, (baseline_directive,))
    assert delta.added == current
    assert delta.removed == (baseline_directive,)
    assert delta.unchanged == ()
    assert delta.blocking is True


def test_relocated_broadened_scope_is_broadened_and_blocking(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "# Shift\n"
        "import os  # noqa: F401, F811\n",
        encoding="utf-8",
    )
    current = scan_paths((source,), root=tmp_path)
    baseline_directive = Directive.create(
        "ruff-noqa", "sample.py", 1, ("F401",), target="import os", occurrence=1
    )
    delta = classify(current, (baseline_directive,))
    assert delta.broadened == current
    assert delta.added == ()
    assert delta.removed == ()
    assert delta.blocking is True


def test_truly_new_suppression_is_added_and_blocking(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "import os  # noqa: F401\n"
        "import sys  # noqa: F401\n",
        encoding="utf-8",
    )
    current = scan_paths((source,), root=tmp_path)
    baseline_directive = Directive.create(
        "ruff-noqa", "sample.py", 1, ("F401",), target="import os", occurrence=1
    )
    delta = classify(current, (baseline_directive,))
    assert delta.unchanged == (current[0],)
    assert delta.added == (current[1],)
    assert delta.blocking is True


def test_suppression_removal_is_visible_and_non_blocking(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("import os\n", encoding="utf-8")
    current = scan_paths((source,), root=tmp_path)
    baseline_directive = Directive.create(
        "ruff-noqa", "sample.py", 1, ("F401",), target="import os", occurrence=1
    )
    delta = classify(current, (baseline_directive,))
    assert delta.removed == (baseline_directive,)
    assert delta.added == ()
    assert delta.unchanged == ()
    assert delta.blocking is False


def test_identical_suppressions_in_same_file_do_not_collapse(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "x = 1  # noqa: F841\n"
        "y = 2\n"
        "x = 1  # noqa: F841\n",
        encoding="utf-8",
    )
    scanned = scan_paths((source,), root=tmp_path)
    assert len(scanned) == 2
    assert scanned[0].occurrence == 1
    assert scanned[1].occurrence == 2
    assert scanned[0].fingerprint != scanned[1].fingerprint

    # Shift lines by inserting header
    shifted_source = tmp_path / "sample.py"
    shifted_source.write_text(
        "# Header 1\n"
        "# Header 2\n"
        "x = 1  # noqa: F841\n"
        "y = 2\n"
        "x = 1  # noqa: F841\n",
        encoding="utf-8",
    )
    current = scan_paths((shifted_source,), root=tmp_path)
    assert current[0].occurrence == 1
    assert current[1].occurrence == 2
    delta = classify(current, scanned)
    assert delta.unchanged == current
    assert delta.added == ()
    assert delta.removed == ()

    # If occurrence 2 is deleted:
    only_first_source = tmp_path / "sample.py"
    only_first_source.write_text(
        "x = 1  # noqa: F841\n"
        "y = 2\n",
        encoding="utf-8",
    )
    cur_first = scan_paths((only_first_source,), root=tmp_path)
    delta_first = classify(cur_first, scanned)
    assert delta_first.unchanged == (cur_first[0],)
    assert delta_first.removed == (scanned[1],)


def test_moving_suppression_to_different_semantic_target_is_added_and_removed(
    tmp_path: Path,
) -> None:
    # 1. Relocated line with different semantic target
    source_relocated = tmp_path / "sample_relocated.py"
    source_relocated.write_text(
        "# Some comment\n"
        "b = 2  # noqa: F841\n",
        encoding="utf-8",
    )
    current_relocated = scan_paths((source_relocated,), root=tmp_path)
    baseline_relocated = Directive.create(
        "ruff-noqa", "sample_relocated.py", 1, ("F841",), target="a = 1", occurrence=1
    )
    delta_relocated = classify(current_relocated, (baseline_relocated,))
    assert delta_relocated.added == current_relocated
    assert delta_relocated.removed == (baseline_relocated,)
    assert delta_relocated.unchanged == ()
    assert delta_relocated.blocking is True

    # 2. Same-line with different semantic target (Pass 1 must not match different targets)
    source_sameline = tmp_path / "sample_sameline.py"
    source_sameline.write_text(
        "b = 2  # noqa: F841\n",
        encoding="utf-8",
    )
    current_sameline = scan_paths((source_sameline,), root=tmp_path)
    baseline_sameline = Directive.create(
        "ruff-noqa", "sample_sameline.py", 1, ("F841",), target="a = 1", occurrence=1
    )
    delta_sameline = classify(current_sameline, (baseline_sameline,))
    assert delta_sameline.added == current_sameline
    assert delta_sameline.removed == (baseline_sameline,)
    assert delta_sameline.unchanged == ()
    assert delta_sameline.blocking is True


def test_classify_rejects_duplicate_baseline_locations() -> None:
    d1 = Directive.create("ruff-noqa", "a.py", 1, ("F841",), target="x = 1", occurrence=1)
    d2 = Directive.create("ruff-noqa", "a.py", 1, ("F841",), target="x = 1", occurrence=1)
    with pytest.raises(ValueError, match="duplicate suppression directive location in baseline"):
        classify((d1,), (d1, d2))
