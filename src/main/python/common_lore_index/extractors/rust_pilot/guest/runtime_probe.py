"""Run-level runtime probe, run as the parser principal (spec 5.6).

Records interpreter, ABI, platform, kernel and encoding facts in stdlib-only
order, then imports the pinned pair from the sealed site directory and
records version, language ABI, node-kind and field identifiers. It never
parses, and never touches ``Point`` or ``Query``. Every value is an
observation for the parent to compare, not a pin.
"""

import importlib
import json
import locale
import os
import platform
import sys
import sysconfig

RUNTIME_ROOT = "/opt/repomap-rust"
NODE_KINDS = (
    "source_file", "mod_item", "function_item", "function_signature_item", "struct_item", "enum_item",
    "union_item", "type_item", "trait_item", "impl_item", "macro_definition", "macro_invocation",
    "const_item", "static_item", "use_declaration", "extern_crate_declaration", "foreign_mod_item",
    "inner_attribute_item", "attribute_item", "declaration_list", "visibility_modifier",
    "line_comment", "block_comment", "expression_statement", "empty_statement", "associated_type",
)
FIELD_NAMES = ("name", "type", "trait", "body")


def stdlib_path():
    return [entry for entry in sys.path
            if entry and os.path.isabs(entry) and "site-packages" not in entry and "dist-packages" not in entry]


def main():
    if sys.argv[1:] == ["--cost-only"]:
        peak = None
        for path in ("/sys/fs/cgroup/memory.peak", "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"):
            try:
                with open(path, "rb") as handle:
                    value = handle.read(64).strip()
                if value.isdigit():
                    peak = int(value)
                    break
            except OSError:
                pass
        sys.stdout.write(json.dumps({"t": "cost", "memory_peak_bytes": peak,
                                     "unavailable_reason": None if peak is not None else "cgroup_peak_unavailable"},
                                    sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    facts = {
        "t": "probe",
        "executable": sys.executable,
        "version": sys.version.split(" ", 1)[0],
        "cache_tag": sys.implementation.cache_tag,
        "soabi": sysconfig.get_config_var("SOABI"),
        "abiflags": getattr(sys, "abiflags", None),
        "machine": platform.machine(),
        "libc": list(platform.libc_ver()),
        "kernel": os.uname().release,
        "fs_encoding": sys.getfilesystemencoding(),
        "preferred_encoding": locale.getpreferredencoding(False),
        "flags": {"isolated": sys.flags.isolated, "no_site": sys.flags.no_site,
                  "dont_write_bytecode": sys.flags.dont_write_bytecode, "utf8_mode": sys.flags.utf8_mode},
        "lc_all": os.environ.get("LC_ALL"),
    }
    sys.path[:] = [RUNTIME_ROOT + "/site", *stdlib_path()]
    modules = []
    try:
        for name in ("tree_sitter", "tree_sitter_rust"):
            modules.append(importlib.import_module(name))
    except ImportError:
        facts["import"] = "failed"
        sys.stdout.write(json.dumps(facts, sort_keys=True, separators=(",", ":")) + "\n")
        return 4
    binding, grammar = modules
    language = binding.Language(grammar.language())
    facts.update({
        "import": "ok",
        "ts_version": binding.__version__,
        "language_version": binding.LANGUAGE_VERSION,
        "min_compatible_language_version": binding.MIN_COMPATIBLE_LANGUAGE_VERSION,
        "module_files": [binding.__file__, grammar.__file__],
        "abi_version": language.abi_version,
        "kind_ids": {kind: language.id_for_node_kind(kind, True) for kind in NODE_KINDS},
        "field_ids": {name: language.field_id_for_name(name) for name in FIELD_NAMES},
    })
    sys.stdout.write(json.dumps(facts, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
