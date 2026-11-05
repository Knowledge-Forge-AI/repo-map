"""RepoMap-owned run-level probe source and its explicit gold (spec 5.6).

The probe text is original and synthetic: more than 300 lines, ending with a
function whose name starts beyond column 300 on a line beyond row 300. Its
gold was computed independently of the helper and is pinned here together
with the source digest; the run refuses before any target byte when the
helper's parent-derived result differs in any field.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from common_lore_index.observations.raw import RawObservation

LONG_NOTE = ("RepoMap runtime probe marker: this attribute is long on purpose so that the following "
             "function name begins beyond column three hundred on a line beyond row three hundred, "
             "which exercises byte offsets that would otherwise reach the avoided position API in "
             "the pinned binding during every pilot run")
PROBE_PATH = "repomap-rust-pilot-probe.rs"
PROBE_SOURCE_BYTES = 16_851
PROBE_SOURCE_SHA256 = "2e987c21fdf00f699bc818cc3d5e29aee7e2d8f385887f8213f5fe2f22867296"
PROBE_COMPLETENESS = "complete"
# (pointer, name, item_kind, start_line, end_line, start_byte, end_byte)
PROBE_GOLD: tuple[tuple[str, str | None, str, int, int, int, int], ...] = (
    ("/mod:probe_layout", "probe_layout", "mod", 3, 319, 79, 16495),
    ("/mod:probe_layout/struct:Cell", "Cell", "struct", 4, 7, 106, 185),
    ("/mod:probe_layout/impl:1", None, "impl", 9, 13, 191, 320),
    ("/mod:probe_layout/impl:1/fn:area", "area", "fn", 10, 12, 211, 314),
    ("/mod:probe_layout/fn:checksum", "checksum", "fn", 15, 318, 326, 16493),
    ("/fn:probe_far_column_marker", "probe_far_column_marker", "fn", 321, 321, 16805, 16850),
)


def probe_source() -> bytes:
    """Return the deterministic probe text; its digest is pinned above."""

    lines = ["//! RepoMap runtime probe source: item positions beyond 300 rows and columns.", "",
             "pub mod probe_layout {", "    pub struct Cell {", "        pub row_index: u32,",
             "        pub col_index: u32,", "    }", "", "    impl Cell {",
             "        pub fn area(&self) -> u64 {",
             "            u64::from(self.row_index) * u64::from(self.col_index)", "        }", "    }", "",
             "    pub fn checksum() -> u64 {", "        let mut acc: u64 = 17;"]
    lines += [f"        acc = acc.wrapping_mul(31).wrapping_add({step});" for step in range(1, 301)]
    lines += ["        acc", "    }", "}", "",
              f'#[doc = "{LONG_NOTE}"] pub fn probe_far_column_marker() -> u32 {{ 7 }}', ""]
    data = "\n".join(lines).encode("ascii")
    if len(data) != PROBE_SOURCE_BYTES or hashlib.sha256(data).hexdigest() != PROBE_SOURCE_SHA256:
        raise RuntimeError("probe_source_drift")
    return data


def probe_matches_gold(observations: Sequence[RawObservation]) -> bool:
    """True only when the parent-derived probe observations equal the gold exactly."""

    parses = [item for item in observations if item.kind == "rust.parse"]
    items = [item for item in observations if item.kind == "rust.item"]
    unsupported = [item for item in observations if item.kind == "rust.unsupported"]
    if len(parses) != 1 or unsupported or parses[0].metadata.get("completeness") != PROBE_COMPLETENESS:
        return False
    actual = tuple((item.metadata["pointer"], item.name, item.metadata["item_kind"], item.start_line,
                    item.end_line, item.metadata["start_byte"], item.metadata["end_byte"])
                   for item in items)
    return actual == PROBE_GOLD and all(item.metadata.get("usable_scope") is True for item in items)
