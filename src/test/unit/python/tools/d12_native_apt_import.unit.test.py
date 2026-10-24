"""ADR 0089 canonical helper import, executed-byte identity and end-to-end safe diagnostics.

No live apt, compiler, backend, image or container: CLI subprocesses refuse
before running any command, with an empty ``PATH``, and APT is a double.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ci import psycopg_bootstrap
from ci.python_retention_operations import dynamic_operations
import native_apt_prerequisites as apt
from repomap_test_support import resource_test_image_commands as commands

ROOT = Path(__file__).resolve().parents[5]
CANONICAL, WRAPPER = ROOT / "tools/native_apt_prerequisites.py", ROOT / "tools/test_sandbox/apt_prerequisites.py"
BOOTSTRAP = ROOT / "tools/ci/psycopg_bootstrap.py"


def test_bootstrap_and_tests_share_one_statically_imported_canonical_module():
    assert psycopg_bootstrap.apt is apt and Path(str(apt.__file__)).resolve() == CANONICAL
    assert psycopg_bootstrap.APT_PREREQUISITES.resolve() == CANONICAL
    for path in (CANONICAL, WRAPPER, BOOTSTRAP):
        assert dynamic_operations(ast.parse(path.read_bytes())) == [], path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_bytes())
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {str(node.module) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    return {name.split(".")[0] for name in names}


def test_canonical_module_is_stdlib_only_and_self_contained_for_image_staging():
    assert _imports(CANONICAL) <= set(sys.stdlib_module_names) | {"__future__"}
    assert "__file__" not in CANONICAL.read_text(encoding="utf-8"), "staged bytes run under another basename"


def test_compatibility_wrapper_is_a_small_static_cli_over_the_canonical_main():
    tree = ast.parse(WRAPPER.read_bytes())
    assert _imports(WRAPPER) == {"__future__", "pathlib", "sys", "native_apt_prerequisites"}
    assert not [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Lambda))]
    imported = [[alias.name for alias in node.names] for node in tree.body
                if isinstance(node, ast.ImportFrom) and node.module == "native_apt_prerequisites"]
    assert imported == [["main"]]
    assert ast.unparse(tree.body[-1]) == "if __name__ == '__main__':\n    raise SystemExit(main())"
    assert len(WRAPPER.read_text(encoding="utf-8").splitlines()) <= 25


def _cli(script: Path, tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    empty = tmp_path / "empty-path"
    empty.mkdir(exist_ok=True)
    return subprocess.run([sys.executable, "-I", str(script), *arguments], capture_output=True, text=True,
                          check=False, cwd=tmp_path, env={"PATH": str(empty)}, timeout=60)


def test_wrapper_cli_help_arguments_and_refusals_match_the_canonical_cli(tmp_path):
    def same(*arguments: str) -> subprocess.CompletedProcess[str]:
        old, new = _cli(WRAPPER, tmp_path, *arguments), _cli(CANONICAL, tmp_path, *arguments)

        def text(output: str, program: str) -> str:  # argparse wraps usage by program-name width
            return " ".join(output.replace(program, "<program>").split())
        assert (old.returncode, text(old.stdout, "apt_prerequisites.py"), text(old.stderr, "apt_prerequisites.py")) == (
            new.returncode, text(new.stdout, "native_apt_prerequisites.py"),
            text(new.stderr, "native_apt_prerequisites.py")), arguments
        return old
    shown = same("--help")
    assert shown.returncode == 0 and "Exact Debian prerequisite custody" in shown.stdout
    assert "{install,attest-libpq}" in shown.stdout and shown.stdout.startswith("usage: apt_prerequisites.py")
    missing = same()
    assert missing.returncode == 2 and "required: command" in missing.stderr
    no_cache = same("install", "gcc")
    assert no_cache.returncode == 2 and "required: --cache" in no_cache.stderr
    cache = tmp_path / "private-cache"
    cache.mkdir()
    (cache / "stale.deb").write_bytes(b"stale")
    refused = same("install", "--cache", str(cache), "gcc")
    assert (refused.returncode, refused.stdout) == (2, "")
    assert refused.stderr == "apt prerequisites refused: the private archive cache is not empty\n"
    unavailable = same("attest-libpq")  # the empty PATH means no dpkg-query process can start
    assert unavailable.returncode == 2 and "dpkg-query is unavailable" in unavailable.stderr
    assert str(tmp_path) not in refused.stderr + unavailable.stderr


def test_sandbox_builder_stages_hashes_and_labels_the_canonical_bytes_not_the_wrapper():
    import test_sandbox as sandbox

    images = sandbox._images
    inputs = images.sandbox_recipe_inputs(ROOT / "tools/test_sandbox/Dockerfile")
    canonical = CANONICAL.read_bytes()
    assert set(inputs) == {"Dockerfile", "apt_prerequisites.py"} and inputs["apt_prerequisites.py"] == canonical
    assert canonical != WRAPPER.read_bytes()
    manifest = {"schema": "repomap-sandbox-recipe-v2", "files": {
        "Dockerfile": hashlib.sha256(inputs["Dockerfile"]).hexdigest(),
        "apt_prerequisites.py": hashlib.sha256(canonical).hexdigest()}}
    assert images.sandbox_recipe(inputs) == hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_dependency_image_materializer_fingerprints_and_executes_the_canonical_text():
    sources = commands.read_materialization_sources()
    assert commands.APT_PREREQUISITES == "tools/native_apt_prerequisites.py"
    assert sources.apt_prerequisites.encode("utf-8") == CANONICAL.read_bytes()
    digest = hashlib.sha256(CANONICAL.read_bytes()).hexdigest()
    assert commands.materialization_inputs(sources)["apt_prerequisites_sha256"] == digest
    payload = json.loads(commands.install_and_probe_command(("psycopg[c]==3.3.6",), "3.3.6", sources)[2])
    assert payload[5] == sources.apt_prerequisites and payload[6] == digest


# The parent's failure shape: baseline noise, then a line the secret rule erases, then the actual cause.
CONSTRAINT = "libc6-dev : Depends: libc6 (= 2.41-12+deb13u4) but 2.41-12+deb13u2 is to be installed"
PRIVATE_ENV = "env-private-value-0123456789"
SENSITIVE = ("apt-cacher", "2a04:4e42::644", "2a04:4e42:600::644", "fe80::1", "10.1.2.3", "s3cr3t-pass",
             "private.mirror.internal", "/Users/alice", "tok-123456", PRIVATE_ENV, "relay-7")
STDOUT = ("openssl is already the newest version (3.5.1-1).\nopenssl set to manually installed.\n"
          "W: Key is stored in legacy trusted.gpg keyring, token tok-123456\n"
          "Some packages could not be installed. This may mean that you have requested an impossible situation.\n"
          f"The following packages have unmet dependencies:\n {CONSTRAINT}\n")
STDERR = ("Err:1 http://apt-cacher:3142/debian trixie InRelease\n  Could not resolve 'apt-cacher'\n"
          "W: Temporary failure resolving 'apt-cacher' [IP: 2a04:4e42:600::644 80]\n"
          "W: Could not connect to relay-7:3142 (2a04:4e42::644), connection to fe80::1%eth0 and 10.1.2.3 failed\n"
          f"W: https://user:s3cr3t-pass@private.mirror.internal/d for /Users/alice proxy {PRIVATE_ENV}\n"
          "E: Unable to correct problems, you have held broken packages.\n")


def _apt_double(tmp_path: Path):
    calls: list[list[str]] = []

    def run(command, **_options):
        calls.append(list(command))
        if command == ["apt-get", "update"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command == ["dpkg", "--print-architecture"]:
            return SimpleNamespace(returncode=0, stdout="arm64\n", stderr="")
        if command[:2] == ["dpkg-query", "-W"]:
            return SimpleNamespace(returncode=0, stdout="openssl\tarm64\t3.5.1-1\tii \topenssl\t3.5.1-1\n", stderr="")
        if command[:3] == ["apt-get", "install", "--simulate"]:
            return SimpleNamespace(returncode=100, stdout=STDOUT, stderr=STDERR)
        raise AssertionError(f"no command after the failed simulation: {command}")
    return run, calls


def test_complete_cli_failure_keeps_a_later_constraint_after_an_earlier_sensitive_line(tmp_path, monkeypatch, capsys):
    for name in list(apt.os.environ):  # hermetic: only the declared environment value is redacted
        monkeypatch.delenv(name)
    monkeypatch.setenv("REPOMAP_D12_PRIVATE_SETTING", PRIVATE_ENV)
    run, calls = _apt_double(tmp_path)
    assert apt.main(["install", "--cache", str(tmp_path / "cache"), "gcc", "libc6-dev"], run=run) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.startswith("apt prerequisites refused: apt-get install --simulate")
    error = captured.err
    for kept in (CONSTRAINT, "E: Unable to correct problems, you have held broken packages.", "Err:1 <url>",
                 "openssl is already the newest version (3.5.1-1).", "[IP: <address> 80]",
                 "resolving '<host>'", "connect to <host>:3142 (<address>)"):
        assert kept in error, (kept, error)
    assert [secret for secret in SENSITIVE if secret in error] == [], error
    assert "<<" not in error and error.count("<redacted>") == 1, error
    assert calls[-1][:3] == ["apt-get", "install", "--simulate"]


@pytest.mark.parametrize("line,expected", [
    ("Temporary failure resolving 'apt-cacher'", "Temporary failure resolving '<host>'"),
    ("Could not resolve host: apt-cacher", "Could not resolve host: <host>"),
    ("Connecting to apt-cacher (10.1.2.3)", "Connecting to <host> (<address>)"),
    ("Failed to connect to apt-cacher port 3142", "Failed to connect to <host> port 3142"),
    ("Unable to connect to apt-cacher:3142:", "Unable to connect to <host>:3142:"),
    ("reached relay-7:8080 then 2a04:4e42::644", "reached <host>:8080 then <address>"),
    ("[IP: 2a04:4e42:600::644 80] [2001:db8::1]:80 ::ffff:10.0.0.5", "[IP: <address> 80] [<address>]:80 <address>"),
    ("Get:1 Hit:2 Ign:3 libc6:arm64 1:2.36-9 22:23:17 Debian-Security:13/stable-security Debian:13.1/stable",
     "Get:1 Hit:2 Ign:3 libc6:arm64 1:2.36-9 22:23:17 Debian-Security:13/stable-security Debian:13.1/stable"),
    ("The following information may help to resolve the situation:",
     "The following information may help to resolve the situation:"),
])
def test_ipv6_and_single_label_hosts_are_redacted_while_package_facts_survive(line, expected):
    assert apt.redact(line, {}) == expected


def test_redaction_is_idempotent_and_markers_are_inert():
    for marker in ("<redacted>", "<url>", "<userinfo>", "<path>", "<host>", "<address>", "<environment>"):
        assert apt.redact(f"{marker} | {CONSTRAINT}", {"SECRET_HOST": "host"}) == f"{marker} | {CONSTRAINT}"
    for scheme in ("http", "https"):  # an environment value replaced first must not shield a URL
        assert apt.redact(f"Err:1 {scheme}://apt-cacher:3142/debian x", {"PROXY_SCHEME": "http"}) == "Err:1 <url> x"
    once = apt.redact(STDOUT + STDERR, {"REPOMAP_D12_PRIVATE_SETTING": PRIVATE_ENV})
    assert apt.redact(once, {"REPOMAP_D12_PRIVATE_SETTING": PRIVATE_ENV}) == once
    done = subprocess.CompletedProcess([], 100, STDOUT, STDERR)
    with pytest.raises(apt.PrerequisiteRefused) as refused:
        apt.command_output(lambda *_a, **_k: done, ["apt-get", "install", "--simulate", "gcc"])
    assert apt.redact(str(refused.value), {}) == str(refused.value), "the CLI's second pass must change nothing"


def test_bounded_tail_keeps_whole_redacted_lines_and_never_starts_inside_a_word():
    filler = "\n".join(f"pkg{index} is already the newest version (1.0-{index})." for index in range(200))
    tail = apt.bounded_tail(f"<redacted>\n{filler}\n {CONSTRAINT}\nE: last\n")
    lines = tail.split(" | ")
    assert lines[-2:] == [CONSTRAINT, "E: last"] and len(lines) == 40 and lines[0].startswith("pkg")
    rest = f"secret-1-0 {'y' * (4000 - 12 - len(CONSTRAINT))} {CONSTRAINT}"  # a raw cut would start at "secret"
    assert len(rest) == 4000 and CONSTRAINT not in apt.redact(rest, {}), "why a cut must not form a new word"
    wide = apt.bounded_tail(f"{'x' * 1000} lib{rest}")
    assert len(wide) <= 4000 and wide.startswith("y") and wide.endswith(CONSTRAINT)
    assert apt.redact(wide, {}) == wide
    assert len(apt.bounded_tail("\n".join("z" * 300 for _ in range(40)))) <= 4000
