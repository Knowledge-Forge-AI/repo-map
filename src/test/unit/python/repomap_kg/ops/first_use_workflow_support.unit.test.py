"""Pure contracts and deletion guards for first-use workflow owners."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from repomap_test_support.first_use_workflow import (
    FirstUseBindingExpectation,
    first_use_expectations,
    guard_first_use_root,
)


def _expectations(*aliases: str) -> dict[str, FirstUseBindingExpectation]:
    return {item.alias: item for item in first_use_expectations(aliases)}


def test_first_use_expectations_follow_mixed_v1_policy_for_each_binding_class() -> None:
    expectations = _expectations("core", "companion", "feeds", "mailbox")
    assert expectations == {
        "core": FirstUseBindingExpectation(
            "core", "public-dev", "full-authorized", "full-authorized", "eligible"
        ),
        "companion": FirstUseBindingExpectation(
            "companion", "public-dev", "full-authorized", "full-authorized", "eligible"
        ),
        "feeds": FirstUseBindingExpectation(
            "feeds", "public-dev", "metadata-only", "metadata-only", "refused"
        ),
        "mailbox": FirstUseBindingExpectation(
            "mailbox", "private-memory", "metadata-only", "metadata-only", "refused"
        ),
    }


def test_first_use_expectations_deduplicate_and_follow_changed_alias_sets() -> None:
    assert tuple(_expectations("companion", "core", "companion")) == ("core", "companion")
    assert tuple(_expectations("core", "feeds")) == ("core", "feeds")
    assert tuple(_expectations("mailbox")) == ("mailbox",)
    assert first_use_expectations(()) == ()
    with pytest.raises(ValueError, match="first-use-alias-unknown"):
        first_use_expectations(("core", "not-a-mixed-v1-binding"))
    with pytest.raises(ValueError, match="first-use-aliases-invalid"):
        first_use_expectations(cast(Any, ("core", ["feeds"])))


def test_first_use_root_guard_allows_only_disposable_descendants(tmp_path: Path) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    target = temporary / "working-copy"
    assert guard_first_use_root(target, temporary) == target.resolve()

    with pytest.raises(ValueError, match="first-use-root-outside-temporary-root"):
        guard_first_use_root(temporary, temporary)
    with pytest.raises(ValueError, match="first-use-root-outside-temporary-root"):
        guard_first_use_root(tmp_path / "outside", temporary)


def test_first_use_root_guard_rejects_symlink_escape_and_fixture_tree(tmp_path: Path) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = temporary / "linked-working-copy"
    escaped.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="first-use-root-outside-temporary-root"):
        guard_first_use_root(escaped, temporary)

    sibling = temporary / "sibling"
    sibling.mkdir()
    in_root_alias = temporary / "linked-sibling"
    in_root_alias.symlink_to(sibling, target_is_directory=True)
    with pytest.raises(ValueError, match="first-use-root-outside-temporary-root"):
        guard_first_use_root(in_root_alias, temporary)
    with pytest.raises(ValueError, match="first-use-root-outside-temporary-root"):
        guard_first_use_root(in_root_alias / "rebuild-target", temporary)

    fixture_parent = temporary / "fixture-parent"
    fixture = fixture_parent / "fixture-source"
    fixture.mkdir(parents=True)
    with pytest.raises(ValueError, match="first-use-root-is-fixture"):
        guard_first_use_root(fixture, temporary, fixture_root=fixture)
    with pytest.raises(ValueError, match="first-use-root-is-fixture"):
        guard_first_use_root(fixture / "nested", temporary, fixture_root=fixture)
    with pytest.raises(ValueError, match="first-use-root-is-fixture"):
        guard_first_use_root(fixture_parent, temporary, fixture_root=fixture)
