"""Isolated Rust source-parser pilot (ADR 0155).

Host modules in this package import only the standard library and RepoMap's
dependency-free contracts. Nothing here imports ``tree_sitter`` or
``tree_sitter_rust``: the native pair runs only inside a fresh container, and
the ``guest`` package holds stdlib text that is injected, never imported.
"""
