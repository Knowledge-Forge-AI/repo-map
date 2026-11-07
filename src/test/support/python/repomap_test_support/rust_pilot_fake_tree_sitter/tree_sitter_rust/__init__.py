"""Stand-in grammar module: ``language()`` returns an inert marker object."""


class _RustLanguageMarker:
    name = "rust"


def language():
    return _RustLanguageMarker()
