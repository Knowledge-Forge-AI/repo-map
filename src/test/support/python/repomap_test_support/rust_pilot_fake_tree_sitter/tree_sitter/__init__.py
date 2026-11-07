"""Stand-in for the binding surface the guest helper and runtime probe use.

Only byte offsets, node kinds, error flags, named fields and cursor
navigation exist here, mirroring the reviewed helper API subset.
"""

from . import _grammar

__version__ = "0.26.0"
LANGUAGE_VERSION = 15
MIN_COMPATIBLE_LANGUAGE_VERSION = 13


class Language:
    def __init__(self, marker):
        if getattr(marker, "name", None) != "rust":
            raise ValueError("unsupported language marker")
        self.abi_version = 15

    def id_for_node_kind(self, kind, named):
        return _grammar.KIND_IDS.get(kind) if named else None

    def field_id_for_name(self, name):
        return _grammar.FIELD_IDS.get(name)


class TreeCursor:
    def __init__(self, root):
        self._path = [root]
        self._indices = []

    @property
    def node(self):
        return self._path[-1]

    def goto_first_child(self):
        children = self._path[-1].children
        if not children:
            return False
        self._path.append(children[0])
        self._indices.append(0)
        return True

    def goto_next_sibling(self):
        if not self._indices:
            return False
        siblings = self._path[-2].children
        index = self._indices[-1] + 1
        if index >= len(siblings):
            return False
        self._path[-1] = siblings[index]
        self._indices[-1] = index
        return True

    def goto_parent(self):
        if not self._indices:
            return False
        self._path.pop()
        self._indices.pop()
        return True


class Tree:
    def __init__(self, root):
        self.root_node = root

    def walk(self):
        return TreeCursor(self.root_node)


class Parser:
    def __init__(self, language):
        if not isinstance(language, Language):
            raise TypeError("language required")
        self._parsed = False

    def parse(self, source):
        if type(source) is not bytes:
            raise TypeError("the stand-in accepts only bytes")
        if self._parsed:
            raise RuntimeError("the stand-in parser parses once")
        self._parsed = True
        return Tree(_grammar.parse_source(source))
