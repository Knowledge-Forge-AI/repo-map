"""Fixed one-parse Rust helper, run as the non-root parser principal (spec 6).

Reads one bounded header line and exactly ``n`` input bytes from stdin, makes
one ``Parser.parse(bytes)`` call and walks the tree with a single cursor. It
emits integer-only frames: kind tags, byte ranges, item indices and flags.
It never sends names, text or line numbers; the parent derives those from its
own retained bytes. Only byte offsets, kinds, error flags, named fields and
cursor navigation are used: no position objects, queries, edits, callbacks,
logging or upward node links. That avoids the known 0.26.0 borrowed-reference
defect's observed trigger; it is not a general memory-safety argument.
"""

import hashlib
import importlib
import json
import os
import sys
from typing import TypedDict

RUNTIME_ROOT = "/opt/repomap-rust"
MAX_INPUT = 1_048_576
MAX_HEADER_LINE = 256
MAX_FRAME = 512
MAX_FRAMES = 50_000
MAX_OUTPUT = 4 * 1_048_576
MAX_DEPTH = 256
MAX_VISITS = 2_000_000
MAX_ATTRIBUTES = 16
HEADER_KEYS = {"n", "nonce", "sha256", "v"}
HEX = frozenset("0123456789abcdef")
ITEM_TAGS = {
    "mod_item": 1, "function_item": 2, "function_signature_item": 3, "struct_item": 4,
    "enum_item": 5, "union_item": 6, "type_item": 7, "trait_item": 8, "impl_item": 9,
    "macro_definition": 10,
}
CONTAINERS = frozenset({"mod_item", "trait_item", "impl_item"})
UNSUPPORTED_TAGS = {
    "macro_invocation": 1, "const_item": 2, "static_item": 3, "use_declaration": 4,
    "extern_crate_declaration": 5, "inner_attribute_item": 7,
}
FOREIGN_TAGS = frozenset({"function_signature_item", "static_item"})
TRIVIA = frozenset({"line_comment", "block_comment", "empty_statement"})


class Scope(TypedDict):
    item: int
    depth: int
    foreign: bool
    pending: list[list[int]]


class InputRefused(Exception):
    pass


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputRefused("duplicate_key")
        result[key] = value
    return result


def reject_number(_value):
    raise InputRefused("number_refused")


def is_hex64(value):
    return type(value) is str and len(value) == 64 and set(value) <= HEX


def read_input(stream):
    line = stream.readline(MAX_HEADER_LINE + 1)
    if not line.endswith(b"\n") or len(line) > MAX_HEADER_LINE:
        raise InputRefused("header_line")
    try:
        header = json.loads(line.decode("ascii"), object_pairs_hook=unique_pairs,
                            parse_float=reject_number, parse_constant=reject_number)
    except (UnicodeDecodeError, ValueError):
        raise InputRefused("header_json") from None
    if (type(header) is not dict or set(header) != HEADER_KEYS
            or type(header["v"]) is not int or header["v"] != 1):
        raise InputRefused("header_keys")
    size = header["n"]
    if type(size) is not int or not 0 <= size <= MAX_INPUT:
        raise InputRefused("header_size")
    if not is_hex64(header["nonce"]) or not is_hex64(header["sha256"]):
        raise InputRefused("header_digest")
    buffer = bytearray()
    while len(buffer) < size:
        chunk = stream.read(min(65_536, size - len(buffer)))
        if not chunk:
            raise InputRefused("short_input")
        buffer.extend(chunk)
    if stream.read(1):
        raise InputRefused("trailing_input")
    data = bytes(buffer)
    if hashlib.sha256(data).hexdigest() != header["sha256"]:
        raise InputRefused("input_digest")
    return header["nonce"], data


class Frames:
    def __init__(self):
        self.lines: list[bytes] = []
        self.total = 0
        self.items = 0
        self.unsupported = 0
        self.full = False

    def add(self, value):
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
        if len(encoded) > MAX_FRAME + 1:
            raise RuntimeError("frame_too_large")
        if len(self.lines) + 2 > MAX_FRAMES or self.total + len(encoded) + MAX_FRAME + 1 > MAX_OUTPUT:
            self.full = True
            return False
        self.lines.append(encoded)
        self.total += len(encoded)
        return True


def span(node):
    return [node.start_byte, node.end_byte]


class Walk:
    """One cursor, one depth-first walk over item-level scopes only."""

    def __init__(self, cursor, frames):
        self.cursor = cursor
        self.frames = frames
        self.visits = 0
        self.errors = 0
        self.missing = 0
        self.truncated = 0

    def emit_unsupported(self, scope, tag, node):
        if self.frames.add({"t": "u", "p": scope["item"], "k": tag, "s": node.start_byte, "e": node.end_byte}):
            self.frames.unsupported += 1

    def visibility(self):
        cursor = self.cursor
        found = None
        if cursor.goto_first_child():
            while True:
                self.visits += 1
                if cursor.node.type == "visibility_modifier":
                    found = span(cursor.node)
                    break
                if not cursor.goto_next_sibling():
                    break
            cursor.goto_parent()
        return found

    def field_span(self, node, field):
        child = node.child_by_field_name(field)
        return None if child is None else span(child)

    def emit_item(self, scope, node):
        kind = node.type
        flags = (1 if node.has_error else 0) | (4 if kind == "function_signature_item" else 0)
        body = node.child_by_field_name("body") if kind in CONTAINERS else None
        if kind == "mod_item" and body is None:
            flags |= 2
        impl = kind == "impl_item"
        frame = {
            "t": "n", "i": self.frames.items, "p": scope["item"], "k": ITEM_TAGS[kind],
            "s": node.start_byte, "e": node.end_byte, "n": None if impl else self.field_span(node, "name"),
            "a": scope["pending"][:MAX_ATTRIBUTES], "v": self.visibility(),
            "y": self.field_span(node, "type") if impl else None,
            "r": self.field_span(node, "trait") if impl else None, "f": flags,
        }
        scope["pending"] = []
        if not self.frames.add(frame):
            return None
        self.frames.items += 1
        return None if body is None else (body, frame["i"], False)

    def classify(self, scope):
        """Handle the node under the cursor; return (body, item, foreign) to descend."""

        node = self.cursor.node
        if node.is_missing:
            self.missing += 1
            return None
        if not node.is_named or node.type in TRIVIA:
            return None
        kind = node.type
        if kind == "attribute_item":
            if len(scope["pending"]) < MAX_ATTRIBUTES:
                scope["pending"].append(span(node))
            else:
                self.truncated = 1
            return None
        if node.is_error:
            self.errors += 1
            scope["pending"] = []
            self.emit_unsupported(scope, 8, node)
            return None
        if scope["foreign"]:
            scope["pending"] = []
            self.emit_unsupported(scope, 6 if kind in FOREIGN_TAGS else 9, node)
            return None
        if kind in ITEM_TAGS:
            return self.emit_item(scope, node)
        scope["pending"] = []
        if kind == "foreign_mod_item":
            body = node.child_by_field_name("body")
            if body is None:
                self.emit_unsupported(scope, 9, node)
                return None
            return (body, scope["item"], True)
        if kind == "expression_statement":
            tag = 9
            if self.cursor.goto_first_child():
                self.visits += 1
                if self.cursor.node.type == "macro_invocation":
                    tag = 1
                self.cursor.goto_parent()
            self.emit_unsupported(scope, tag, node)
            return None
        self.emit_unsupported(scope, UNSUPPORTED_TAGS.get(kind, 9), node)
        return None

    def enter_body(self, body):
        """Move from an item to its body's first child; restore the item on failure."""

        cursor = self.cursor
        if not cursor.goto_first_child():
            return False
        while True:
            self.visits += 1
            node = cursor.node
            if node.type == "declaration_list" and span(node) == span(body):
                if cursor.goto_first_child():
                    return True
                break
            if not cursor.goto_next_sibling():
                break
        cursor.goto_parent()
        return False

    def finish_scope(self, scope):
        for pending in scope["pending"]:
            if self.frames.add({"t": "u", "p": scope["item"], "k": 9, "s": pending[0], "e": pending[1]}):
                self.frames.unsupported += 1

    def run(self):
        cursor = self.cursor
        if not cursor.goto_first_child():
            return
        stack: list[Scope] = [
            {"item": -1, "depth": 1, "foreign": False, "pending": []},
        ]
        while stack:
            self.visits += 1
            if self.visits > MAX_VISITS or self.frames.full:
                self.truncated = 1
                return
            scope = stack[-1]
            descend = self.classify(scope)
            if descend is not None:
                body, item, foreign = descend
                depth = scope["depth"] + 1
                if depth > MAX_DEPTH:
                    self.truncated = 1
                elif self.enter_body(body):
                    stack.append({"item": item, "depth": depth, "foreign": foreign, "pending": []})
                    continue
            while not cursor.goto_next_sibling():
                self.finish_scope(stack.pop())
                if not stack:
                    return
                cursor.goto_parent()
                cursor.goto_parent()


def stdlib_path():
    return [entry for entry in sys.path
            if entry and os.path.isabs(entry) and "site-packages" not in entry and "dist-packages" not in entry]


def main():
    try:
        nonce, data = read_input(sys.stdin.buffer)
    except InputRefused:
        return 3
    sys.path[:] = [RUNTIME_ROOT + "/site", *stdlib_path()]
    modules = []
    for name in ("tree_sitter", "tree_sitter_rust"):
        modules.append(importlib.import_module(name))
    binding, grammar = modules
    language = binding.Language(grammar.language())
    parser = binding.Parser(language)
    frames = Frames()
    frames.add({"t": "hello", "v": 1, "nonce": nonce, "ts": str(binding.__version__)[:32],
                "abi": int(language.abi_version)})
    tree = parser.parse(data)
    cursor = tree.walk()
    root_error = 1 if cursor.node.has_error else 0
    walker = Walk(cursor, frames)
    walker.run()
    truncated = 1 if (walker.truncated or frames.full) else 0
    frames.lines.append(json.dumps({
        "t": "end", "nonce": nonce, "root_error": root_error, "errors": walker.errors,
        "missing": walker.missing, "items": frames.items, "unsupported": frames.unsupported,
        "truncated": truncated,
    }, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n")
    sys.stdout.buffer.write(b"".join(frames.lines))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
