from __future__ import annotations



AWK_CALL_EXPORTS = (
    "awk2_observations",
    "awk_metadata",
    "builtin_call_observation",
    "builtin_call_observations",
    "include_extension_observations",
    "user_function_call_observations",
)


def test_rootpkg28_awk_reexports_call_observation_builders() -> None:
    import repomap_kg.extractors.shell.awk as awk
    import repomap_kg.extractors.shell.awk_calls as calls
    for name in AWK_CALL_EXPORTS:
        assert getattr(awk, name) is getattr(calls, name)
