"""A small bracket scanner standing in for the Rust grammar (test support only).

It recognizes item-level syntax well enough to exercise the real guest
helper and the parent protocol: comments, attributes, visibility, modifiers,
items, impl type/trait fields, declaration lists, macros, foreign blocks,
error regions and a missing closing brace at end of input. Bodies are kept
opaque. It makes no claim to match Tree-sitter on any input.
"""

import os
import sys
import time
from typing import Any

from ._lexer import tokenize

KIND_IDS = {kind: index for index, kind in enumerate((
    "source_file", "mod_item", "function_item", "function_signature_item", "struct_item", "enum_item",
    "union_item", "type_item", "trait_item", "impl_item", "macro_definition", "macro_invocation",
    "const_item", "static_item", "use_declaration", "extern_crate_declaration", "foreign_mod_item",
    "inner_attribute_item", "attribute_item", "declaration_list", "visibility_modifier",
    "line_comment", "block_comment", "expression_statement", "empty_statement", "associated_type"), start=1)}
FIELD_IDS = {"name": 1, "type": 2, "trait": 3, "body": 4}
OPENERS = {b"(": b")", b"[": b"]", b"{": b"}"}
MODIFIERS = (b"async", b"unsafe", b"default", b"const", b"extern")


class Node:
    __slots__ = ("type", "start_byte", "end_byte", "children", "fields", "is_named", "is_error",
                 "is_missing", "has_error")

    def __init__(self, kind, start, end, children=(), fields=None, named=True, error=False, missing=False):
        self.type = kind
        self.start_byte = start
        self.end_byte = end
        self.children = [child for child in children if child is not None]
        self.fields = {key: value for key, value in (fields or {}).items() if value is not None}
        self.is_named = named
        self.is_error = error
        self.is_missing = missing
        self.has_error = error or missing or any(child.has_error for child in self.children)

    def child_by_field_name(self, name):
        return self.fields.get(name)


class _Parser:
    def __init__(self, data):
        self.data = data
        self.tokens = tokenize(data)
        self.i = 0

    def peek(self, offset=0):
        index = self.i + offset
        return self.tokens[index] if index < len(self.tokens) else None

    def word(self, token):
        return None if token is None else self.data[token[1]:token[2]]

    def punct(self, token, value):
        return token is not None and token[0] == "punct" and self.word(token) == value

    def ident(self, token, value=None):
        return token is not None and token[0] == "ident" and (value is None or self.word(token) == value)

    def balanced(self):
        """Consume one bracketed group starting at the current opener."""

        stack = [OPENERS[self.word(self.peek())]]
        self.i += 1
        while stack:
            token = self.peek()
            if token is None:
                return len(self.data), False
            self.i += 1
            value = self.word(token)
            if token[0] == "punct" and value in OPENERS:
                stack.append(OPENERS[value])
            elif token[0] == "punct" and value == stack[-1]:
                stack.pop()
        return token[2], True

    def scan(self, stops):
        """Skip tokens until a stop punctuation at depth zero; do not consume it."""

        while True:
            token = self.peek()
            if token is None or (token[0] == "punct" and self.word(token) in stops):
                return token
            if token[0] == "punct" and self.word(token) in OPENERS:
                self.balanced()
            else:
                self.i += 1

    def semicolon_end(self):
        token = self.scan((b";",))
        if token is None:
            return len(self.data), False
        self.i += 1
        return token[2], True

    def name(self, kind):
        token = self.peek()
        if not self.ident(token):
            return None
        self.i += 1
        return Node(kind, token[1], token[2])

    def declaration_list(self, scope):
        opener = self.peek()
        self.i += 1
        children = [Node("{", opener[1], opener[2], named=False)]
        while True:
            token = self.peek()
            if token is None:
                end = len(self.data)
                children.append(Node("}", end, end, named=False, missing=True))
                return Node("declaration_list", opener[1], end, children)
            if self.punct(token, b"}"):
                self.i += 1
                children.append(Node("}", token[1], token[2], named=False))
                return Node("declaration_list", opener[1], token[2], children)
            children.extend(self.item(scope))

    def error(self, start):
        token = self.scan((b";", b"{"))
        if token is None:
            end = len(self.data)
        elif self.word(token) == b"{":
            end, _ = self.balanced()
        else:
            self.i += 1
            end = token[2]
        return [Node("ERROR", start, end, error=True)]

    def item(self, scope):
        token = self.peek()
        if token[0] in ("line_comment", "block_comment"):
            self.i += 1
            return [Node(token[0], token[1], token[2])]
        if self.punct(token, b";"):
            self.i += 1
            return [Node("empty_statement", token[1], token[2])]
        if self.punct(token, b"#"):
            inner = self.punct(self.peek(1), b"!")
            self.i += 2 if inner else 1
            if not self.punct(self.peek(), b"["):
                return self.error(token[1])
            end, ok = self.balanced()
            return [Node("inner_attribute_item" if inner else "attribute_item", token[1], end, error=not ok)]
        start, prefix = token[1], []
        if self.ident(token, b"pub"):
            self.i += 1
            end = token[2]
            if self.punct(self.peek(), b"("):
                end, _ = self.balanced()
            prefix.append(Node("visibility_modifier", token[1], end))
        while self.word(self.peek()) in MODIFIERS and self._is_modifier():
            self.i += 1
            if self.peek() is not None and self.peek()[0] == "literal":
                self.i += 1
        return self.keyword_item(scope, start, prefix)

    def _is_modifier(self):
        word, following = self.word(self.peek()), self.word(self.peek(1))
        if word == b"extern":
            return following in (b"fn", b"unsafe") or (self.peek(1) and self.peek(1)[0] == "literal"
                                                       and self.word(self.peek(2)) == b"fn")
        if word == b"const":
            return following in (b"fn", b"unsafe", b"async", b"extern")
        return following in (b"fn", b"impl", b"trait", b"extern", b"unsafe", b"async")

    def keyword_item(self, scope, start, prefix):
        token = self.peek()
        word = self.word(token)
        if token is None:
            return [Node("ERROR", start, len(self.data), prefix, error=True)]
        if word == b"extern" and self.ident(self.peek(1), b"crate"):
            end, _ = self.semicolon_end()
            return [Node("extern_crate_declaration", start, end, prefix)]
        if word == b"extern":
            self.i += 1
            if self.peek() is not None and self.peek()[0] == "literal":
                self.i += 1
            if not self.punct(self.peek(), b"{"):
                return self.error(start)
            body = self.declaration_list("foreign")
            return [Node("foreign_mod_item", start, body.end_byte, [*prefix, body], {"body": body})]
        if word in (b"use", b"const", b"static"):
            end, _ = self.semicolon_end()
            kind = {b"use": "use_declaration", b"const": "const_item", b"static": "static_item"}[word]
            return [Node(kind, start, end, prefix)]
        if self.ident(token) and self.punct(self.peek(1), b"!") and word != b"macro_rules":
            return self.macro_invocation(scope, start)
        self.i += 1
        handler = {b"mod": self.module, b"fn": self.function, b"struct": self.adt, b"enum": self.adt,
                   b"union": self.adt, b"type": self.alias, b"trait": self.trait,
                   b"impl": self.impl, b"macro_rules": self.macro_rules}.get(word)
        if handler is None:
            self.i -= 1
            return self.error(start)
        return [handler(scope, start, prefix, word)]

    def module(self, scope, start, prefix, word):
        name = self.name("identifier")
        if self.punct(self.peek(), b"{"):
            body = self.declaration_list("module")
            return Node("mod_item", start, body.end_byte, [*prefix, name, body], {"name": name, "body": body})
        end, ok = self.semicolon_end()
        return Node("mod_item", start, end, [*prefix, name], {"name": name}, error=not ok or name is None)

    def opaque_errors(self, tokens, *, field_types=False):
        # This stand-in models only missing operands/types; macro token trees
        # stay opaque. It does not infer full Rust expression validity.
        tokens = [token for token in tokens if token[0] not in ("line_comment", "block_comment")]
        errors: list[Node] = []
        index = 0
        while index + 1 < len(tokens):
            token, following = tokens[index:index + 2]
            if (self.ident(token) and self.punct(following, b"!") and index + 2 < len(tokens)
                    and self.word(tokens[index + 2]) in OPENERS):
                stack = [OPENERS[self.word(tokens[index + 2])]]
                index += 3
                while index < len(tokens) and stack:
                    value = self.word(tokens[index])
                    if tokens[index][0] == "punct" and value in OPENERS:
                        stack.append(OPENERS[value])
                    elif self.punct(tokens[index], stack[-1]):
                        stack.pop()
                    index += 1
                continue
            if (token[0] == following[0] == "punct"
                    and (self.word(token) in (b"+", b"-", b"*", b"/", b"%", b"=", b"&", b"|", b"^")
                         and self.word(following) == b";"
                         or field_types and self.word(token) == b":" and self.word(following) in (b",", b"}"))):
                errors.append(Node("ERROR", token[1], following[2], error=True))
            index += 1
        return errors

    def function(self, scope, start, prefix, word):
        name = self.name("identifier")
        stop = self.scan((b";", b"{"))
        if stop is not None and self.word(stop) == b"{":
            begin = self.i
            end, ok = self.balanced()
            block = Node("block", stop[1], end, self.opaque_errors(self.tokens[begin:self.i]), error=not ok)
            return Node("function_item", start, end, [*prefix, name, block], {"name": name, "body": block})
        end, ok = self.semicolon_end()
        return Node("function_signature_item", start, end, [*prefix, name], {"name": name}, error=not ok)

    def adt(self, scope, start, prefix, word):
        name = self.name("type_identifier")
        stop = self.scan((b";", b"{", b"("))
        begin = self.i
        if stop is not None and self.word(stop) == b"(":
            self.balanced()
            end, ok = self.semicolon_end()
        elif stop is not None and self.word(stop) == b"{":
            end, ok = self.balanced()
        else:
            end, ok = self.semicolon_end()
        kind = {b"struct": "struct_item", b"enum": "enum_item", b"union": "union_item"}[word]
        errors = self.opaque_errors(self.tokens[begin:self.i], field_types=True)
        return Node(kind, start, end, [*prefix, name, *errors], {"name": name}, error=not ok)

    def alias(self, scope, start, prefix, word):
        name = self.name("type_identifier")
        before = self.i
        end, ok = self.semicolon_end()
        has_value = any(self.punct(token, b"=") for token in self.tokens[before:self.i])
        kind = "associated_type" if scope == "trait" and not has_value else "type_item"
        return Node(kind, start, end, [*prefix, name], {"name": name}, error=not ok)

    def trait(self, scope, start, prefix, word):
        name = self.name("type_identifier")
        if self.scan((b"{", b";")) is None or not self.punct(self.peek(), b"{"):
            return Node("ERROR", start, len(self.data), [*prefix], error=True)
        body = self.declaration_list("trait")
        return Node("trait_item", start, body.end_byte, [*prefix, name, body], {"name": name, "body": body})

    def impl(self, scope, start, prefix, word):
        if self.punct(self.peek(), b"<"):
            self.angles()
        depth = 0
        parts: list[list[Any]] = []
        current: list[Any] = []
        while True:
            token = self.peek()
            if token is None:
                return Node("ERROR", start, len(self.data), prefix, error=True)
            if depth == 0 and (self.punct(token, b"{") or self.ident(token, b"where")):
                break
            if depth == 0 and self.ident(token, b"for") and current:
                parts.append(current)
                current = []
            else:
                if self.punct(token, b"<"):
                    depth += 1
                elif self.punct(token, b">") and not (current and self.punct(current[-1], b"-")):
                    depth -= 1
                current.append(token)
            self.i += 1
        parts.append(current)
        fields, children = {}, list(prefix)
        for field, tokens in zip(("trait", "type") if len(parts) == 2 else ("type",), parts):
            if tokens:
                node = Node("type_identifier" if len(tokens) == 1 else "generic_type", tokens[0][1], tokens[-1][2])
                fields[field] = node
                children.append(node)
        if self.scan((b"{",)) is None:
            return Node("ERROR", start, len(self.data), children, error=True)
        body = self.declaration_list("impl")
        fields["body"] = body
        return Node("impl_item", start, body.end_byte, [*children, body], fields)

    def angles(self):
        depth = 0
        while self.peek() is not None:
            token = self.peek()
            self.i += 1
            if self.punct(token, b"<"):
                depth += 1
            elif self.punct(token, b">") and not self.punct(self.tokens[self.i - 2], b"-"):
                depth -= 1
                if depth == 0:
                    return

    def macro_rules(self, scope, start, prefix, word):
        self.i += 1
        name = self.name("identifier")
        if not self.punct(self.peek(), b"{") and self.word(self.peek()) not in OPENERS:
            return Node("ERROR", start, len(self.data), prefix, error=True)
        opener = self.word(self.peek())
        end, ok = self.balanced()
        if opener != b"{":
            end, ok = self.semicolon_end()
        return Node("macro_definition", start, end, [*prefix, name], {"name": name}, error=not ok)

    def macro_invocation(self, scope, start):
        self.i += 2
        if self.word(self.peek()) not in OPENERS:
            return self.error(start)
        end, ok = self.balanced()
        macro = Node("macro_invocation", start, end, error=not ok)
        token = self.peek()
        if not self.punct(token, b";"):
            return [macro]
        self.i += 1
        if scope == "root":
            return [Node("expression_statement", start, token[2], [macro])]
        return [macro, Node("empty_statement", token[1], token[2])]


def parse_source(data):
    if b"//@fake:sleep" in data:
        time.sleep(30)
    if b"//@fake:noise" in data:
        sys.stdout.write("noise\n")
        sys.stdout.flush()
    if b"//@fake:abort" in data:
        os.abort()
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10_000))
    parser = _Parser(data)
    children = []
    while parser.peek() is not None:
        children.extend(parser.item("root"))
    return Node("source_file", 0, len(data), children)
