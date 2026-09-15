from __future__ import annotations

import pytest

from repomap_test_support.scale28_fix11_patch_provenance import (
    PatchOperation,
    PatchParseError,
    parse_git_patch,
    resolve_object_ids,
    resolve_old_object_ids,
)


def _modified_patch(path: str = "tools/example.py") -> bytes:
    return (
        f"diff --git a/{path} b/{path}\n"
        "index 1234abcd..5678efab 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    ).encode()


def test_fix11_parses_modified_text_entry() -> None:
    (entry,) = parse_git_patch(_modified_patch(), expected_path_count=1)

    assert entry.operation is PatchOperation.MODIFY
    assert entry.old_path == "tools/example.py"
    assert entry.new_path == "tools/example.py"
    assert entry.old_mode == "100644"
    assert entry.new_mode == "100644"
    assert entry.old_object_id == "1234abcd"
    assert entry.new_object_id == "5678efab"
    assert not entry.binary


@pytest.mark.parametrize(
    ("patch", "operation", "old_path", "new_path"),
    (
        (
            b"diff --git a/dev/null b/tools/new.py\n"
            b"new file mode 100644\n"
            b"index 00000000..5678efab\n"
            b"--- /dev/null\n"
            b"+++ b/tools/new.py\n"
            b"@@ -0,0 +1 @@\n"
            b"+new\n",
            PatchOperation.ADD,
            None,
            "tools/new.py",
        ),
        (
            b"diff --git a/tools/old.py b/dev/null\n"
            b"deleted file mode 100644\n"
            b"index 1234abcd..00000000\n"
            b"--- a/tools/old.py\n"
            b"+++ /dev/null\n"
            b"@@ -1 +0,0 @@\n"
            b"-old\n",
            PatchOperation.DELETE,
            "tools/old.py",
            None,
        ),
        (
            b"diff --git a/tools/old.py b/tools/new.py\n"
            b"similarity index 100%\n"
            b"rename from tools/old.py\n"
            b"rename to tools/new.py\n",
            PatchOperation.RENAME,
            "tools/old.py",
            "tools/new.py",
        ),
        (
            b"diff --git a/tools/old.py b/tools/new.py\n"
            b"similarity index 100%\n"
            b"copy from tools/old.py\n"
            b"copy to tools/new.py\n",
            PatchOperation.COPY,
            "tools/old.py",
            "tools/new.py",
        ),
    ),
)
def test_fix11_parses_closed_operation_variants(
    patch: bytes,
    operation: PatchOperation,
    old_path: str | None,
    new_path: str | None,
) -> None:
    (entry,) = parse_git_patch(patch, expected_path_count=1)

    assert entry.operation is operation
    assert entry.old_path == old_path
    assert entry.new_path == new_path


def test_fix11_parses_binary_payload_and_mode_change() -> None:
    patch = (
        b"diff --git a/assets/data.bin b/assets/data.bin\n"
        b"old mode 100644\n"
        b"new mode 100755\n"
        b"index 1234abcd..5678efab\n"
        b"GIT binary patch\n"
        b"literal 1\n"
        b"LcmZQzKnB&%00m;O\n"
    )

    (entry,) = parse_git_patch(patch, expected_path_count=1)

    assert entry.binary
    assert entry.old_mode == "100644"
    assert entry.new_mode == "100755"


@pytest.mark.parametrize(
    ("patch", "match"),
    (
        (_modified_patch("/absolute.py"), "absolute"),
        (_modified_patch("../escape.py"), "traversal"),
        (_modified_patch() + _modified_patch(), "duplicate output"),
        (
            _modified_patch().replace(
                b"index 1234abcd..5678efab 100644\n",
                b"old mode 100755\n"
                b"new mode 100644\n"
                b"index 1234abcd..5678efab 100644\n",
            ),
            "conflicting mode",
        ),
        (
            b"diff --git a/assets/data.bin b/assets/data.bin\n"
            b"index 1234abcd..5678efab 100644\n"
            b"GIT binary patch\n"
            b"literal 1\n",
            "binary payload",
        ),
        (_modified_patch() + b"unexpected trailer\n", "trailer"),
        (_modified_patch().replace(b"@@ -1 +1 @@\n", b""), "partial"),
    ),
)
def test_fix11_parser_rejects_malformed_or_unsafe_patch(
    patch: bytes,
    match: str,
) -> None:
    with pytest.raises(PatchParseError, match=match):
        parse_git_patch(patch)


def test_fix11_parser_enforces_exact_changed_path_count() -> None:
    with pytest.raises(PatchParseError, match="path count"):
        parse_git_patch(_modified_patch(), expected_path_count=23)


def test_fix11_resolves_abbreviated_object_ids_uniquely() -> None:
    entries = parse_git_patch(_modified_patch(), expected_path_count=1)
    resolved = resolve_object_ids(
        entries,
        lambda prefix: ("a" * 40,) if prefix == "1234abcd" else ("b" * 40,),
    )

    assert resolved[0].old_object_id == "a" * 40
    assert resolved[0].new_object_id == "b" * 40


def test_fix11_resolves_preimages_before_new_objects_exist() -> None:
    entries = parse_git_patch(_modified_patch(), expected_path_count=1)
    resolved = resolve_old_object_ids(
        entries,
        lambda prefix: ("a" * 40,) if prefix == "1234abcd" else (),
    )

    assert resolved[0].old_object_id == "a" * 40
    assert resolved[0].new_object_id == "5678efab"


@pytest.mark.parametrize(
    ("matches", "match"),
    (((), "unresolved"), (("a" * 40, "b" * 40), "ambiguous")),
)
def test_fix11_rejects_unresolved_or_ambiguous_object_id(
    matches: tuple[str, ...],
    match: str,
) -> None:
    entries = parse_git_patch(_modified_patch(), expected_path_count=1)

    with pytest.raises(PatchParseError, match=match):
        resolve_object_ids(entries, lambda _prefix: matches)
