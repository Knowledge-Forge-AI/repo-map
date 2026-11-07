"""Guest-side standard-library text for the Rust pilot container (ADR 0155 D6).

These modules are package data in module form so the existing package
configuration ships them. Host code reads them as text through
``importlib.resources`` and injects them into a fresh container; it never
imports them. Each one runs only as ``__main__`` and has no import-time
side effects.
"""
