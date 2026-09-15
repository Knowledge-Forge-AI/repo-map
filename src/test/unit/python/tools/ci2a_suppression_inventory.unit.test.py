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
