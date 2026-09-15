from __future__ import annotations

import threading

from repomap_kg.ops import source_generation
from repomap_kg.graph.discovery import discover_observations
from repomap_kg.ops.generations import source_generation as observation_generation
from repomap_kg.ops.generations import source_generation_records


def test_scan_source_generation_is_content_aware_and_path_independent(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root in (first, second):
        (root / "src").mkdir(parents=True)
        (root / "README.md").write_text("# Repo\n", encoding="utf-8")
        (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")

    first_result = source_generation.scan_source_generation(first)
    second_result = source_generation.scan_source_generation(second)

    assert first_result.category == "ready"
    assert first_result.generation == second_result.generation
    assert first_result.file_count == 2
    assert first_result.total_bytes == len("# Repo\n") + len("print('ok')\n")
    assert first_result.to_public() == {
        "category": "ready",
        "file_count": 2,
        "total_bytes": first_result.total_bytes,
    }


def test_scan_source_generation_matches_full_discovery_generation(tmp_path):
    root = tmp_path / "repository"
    (root / "src").mkdir(parents=True)
    (root / "README.md").write_text("# Repo\n", encoding="utf-8")
    (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")

    polled = source_generation.scan_source_generation(root)
    refreshed = observation_generation(discover_observations(root))

    assert polled.generation == refreshed


def test_source_generation_records_sort_paths_and_entry_types():
    first = source_generation_records(
        (
            ("b.txt", "file", "digest-b"),
            ("a.txt", "file", "digest-a"),
        )
    )
    second = source_generation_records(
        (
            ("a.txt", "file", "digest-a"),
            ("b.txt", "file", "digest-b"),
        )
    )

    assert first == second


def test_scan_source_generation_is_order_independent_and_exclusion_aware(tmp_path):
    root = tmp_path / "repository"
    (root / "src").mkdir(parents=True)
    (root / "ignored").mkdir()
    (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "README.md").write_text("# Repo\n", encoding="utf-8")
    (root / "ignored" / "secret.txt").write_text("secret\n", encoding="utf-8")

    before = source_generation.scan_source_generation(root, exclude_paths=("ignored",))
    (root / "ignored" / "secret.txt").write_text("changed\n", encoding="utf-8")
    after = source_generation.scan_source_generation(root, exclude_paths=("ignored",))

    assert before.generation == after.generation
    assert before.file_count == 2

    (root / "src" / "app.py").write_text("print('changed')\n", encoding="utf-8")
    changed = source_generation.scan_source_generation(root, exclude_paths=("ignored",))
    assert changed.generation != before.generation


def test_scan_source_generation_applies_glob_excludes_to_directory_contents(tmp_path):
    root = tmp_path / "repository"
    (root / "result-build" / "nested").mkdir(parents=True)
    (root / "result-build" / "nested" / "generated.txt").write_text(
        "generated\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# Repo\n", encoding="utf-8")

    result = source_generation.scan_source_generation(root, exclude_paths=("result-*",))

    assert result.category == "ready"
    assert result.file_count == 1


def test_scan_source_generation_preserves_unavailable_source_as_condition(tmp_path):
    result = source_generation.scan_source_generation(tmp_path / "missing")

    assert result.generation is None
    assert result.category == "source_unavailable"
    assert result.to_public() == {
        "category": "source_unavailable",
        "file_count": 0,
        "total_bytes": 0,
    }


def test_scan_source_generation_rejects_symlinked_entries(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    (root / "README.md").write_text("# Repo\n", encoding="utf-8")
    try:
        (root / "linked.md").symlink_to(root / "README.md")
    except OSError as error:
        import pytest

        pytest.skip(f"symlink creation unavailable: {error}")

    result = source_generation.scan_source_generation(root)

    assert result.generation is None
    assert result.category == "source_invalid"


def test_scan_source_generation_honors_bounds_and_cancellation(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    (root / "large.txt").write_text("0123456789", encoding="utf-8")

    limited = source_generation.scan_source_generation(
        root,
        limits=source_generation.SourceGenerationLimits(max_file_bytes=4),
    )
    assert limited.category == "source_limit_exceeded"
    assert limited.generation is None

    cancelled = threading.Event()
    cancelled.set()
    result = source_generation.scan_source_generation(root, cancel_event=cancelled)
    assert result.category == "cancelled"
    assert result.generation is None

    (root / "second.txt").write_text("abcdefghij", encoding="utf-8")
    total_limited = source_generation.scan_source_generation(
        root,
        limits=source_generation.SourceGenerationLimits(
            max_file_bytes=20, max_total_bytes=15
        ),
    )
    assert total_limited.category == "source_limit_exceeded"


def test_scan_source_generation_reports_persistent_file_instability(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    root.mkdir()
    source = root / "README.md"
    source.write_text("# Repo\n", encoding="utf-8")
    monkeypatch.setattr(
        source_generation,
        "_read_stable_file",
        lambda *args, **kwargs: None,
    )

    result = source_generation.scan_source_generation(
        root,
        limits=source_generation.SourceGenerationLimits(max_file_retries=1),
    )

    assert result.category == "source_unstable"
    assert result.generation is None
