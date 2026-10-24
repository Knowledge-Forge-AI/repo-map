"""Same-layer builder hygiene; fake tools do not qualify a real image build."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest


RECIPE = Path(__file__).resolve().parents[5] / "tools/test_sandbox/Dockerfile"
INSTALL = "github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.6.2"
HELPER = "/usr/local/lib/repomap/apt_prerequisites.py"
KEYRING = "/usr/share/keyrings/debian-archive-keyring.pgp"
KEYRING_SHA256 = "506b815cbb32d9b6066b4a2aa524071e071761e7e7f68c3ac74f3061ba852017"
SOURCE = "etc/apt/sources.list.d/repomap-snapshot-20260406.sources"
PINS = "etc/apt/preferences.d/repomap-snapshot-headers.pref"
LISTS = "/var/lib/apt/lists"
NATIVE = ["bash", "ca-certificates", "gcc", "git", "iproute2", "iptables", "libc6-dev", "libpq-dev",
          "postgresql-17", "postgresql-client-17", "procps", "util-linux"]
SNAPSHOT_SOURCE = ("Types: deb\nURIs: https://snapshot.debian.org/archive/debian/20260406T000000Z/\n"
                   "Suites: trixie\nComponents: main\nSigned-By: {keyring}\nCheck-Valid-Until: no\n")
SNAPSHOT_PINS = ("Package: libc6-dev\nPin: version 2.41-12+deb13u2\nPin-Priority: 999\n\n"
                 "Package: libc-dev-bin\nPin: version 2.41-12+deb13u2\nPin-Priority: 999\n\n"
                 "Package: libssl-dev\nPin: version 3.5.5-1~deb13u1\nPin-Priority: 999\n\n"
                 "Package: perl\nPin: version 5.40.1-6\nPin-Priority: 999\n\n"
                 "Package: libperl5.40\nPin: version 5.40.1-6\nPin-Priority: 999\n\n"
                 "Package: perl-modules-5.40\nPin: version 5.40.1-6\nPin-Priority: 999\n\n"
                 'Package: *\nPin: origin "snapshot.debian.org"\nPin-Priority: 100\n')
# Doubles: a real SHA-256 checker for `sha256sum --check --strict -`, and a helper that records
# what APT configuration exists when it starts. Neither proves a signature, a pin or an install.
CHECKER = """import hashlib, os, sys
assert sys.argv[1:] == ["--check", "--strict", "-"], sys.argv
status, lines = 0, sys.stdin.read().splitlines()
for line in lines:
    digest, separator, path = line.partition("  ")
    try:
        ok = bool(separator) and hashlib.sha256(open(path, "rb").read()).hexdigest() == digest
    except OSError:
        ok = False
    status = status or (0 if ok else 1)
    with open(os.environ["FIXTURE_CALLS"], "a") as calls:
        calls.write(f"sha256sum {'OK' if ok else 'FAILED'} {os.path.basename(path)}\\n")
sys.exit(status if lines else 1)
"""
HELPER_DOUBLE = """import json, os, sys
root = os.environ["FIXTURE_ROOT"]
def read(name):
    path = os.path.join(root, name)
    return open(path).read() if os.path.exists(path) else None
seen = {"argv": sys.argv[1:], "source": read(os.environ["FIXTURE_SOURCE"]), "pins": read(os.environ["FIXTURE_PINS"])}
with open(os.environ["FIXTURE_CALLS"], "a") as calls:
    calls.write("helper " + json.dumps(seen) + "\\n")
sys.exit(int(os.environ["HELPER_STATUS"]))
"""


def builder_run():
    instructions = RECIPE.read_text().replace("\\\n", " ").splitlines()
    stage = instructions[1:next(i for i, line in enumerate(instructions[1:], 1)
                                if line.startswith("FROM "))]
    runs = [line.removeprefix("RUN ") for line in stage if line.startswith("RUN ")]
    assert len(runs) == 1
    assert runs[0].split() == [
        "GOBIN=/opt/repomap/bin", "go", "install", INSTALL,
        "&&", "go", "clean", "-cache", "-modcache",
    ]
    return runs[0]


@pytest.mark.parametrize("install_status,clean_status", [(0, 0), (17, 0), (0, 19)])
def test_builder_install_and_clean_share_one_fail_closed_layer(
    tmp_path, install_status, clean_status
):
    command = builder_run()
    tools = tmp_path / "tools"
    tools.mkdir()
    go = tools / "go"
    go.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$FIXTURE_ROOT/calls\"\n"
        "if [ \"$1\" = install ]; then\n"
        "  [ \"$INSTALL_STATUS\" = 0 ] || exit \"$INSTALL_STATUS\"\n"
        "  mkdir -p \"$GOBIN\" \"$FIXTURE_ROOT/cache\" \"$FIXTURE_ROOT/modules\"\n"
        "  printf '#!/bin/sh\\necho golangci-lint has version 2.6.2\\n' > \"$GOBIN/golangci-lint\"\n"
        "  chmod +x \"$GOBIN/golangci-lint\"\n"
        "elif [ \"$*\" = 'clean -cache -modcache' ]; then\n"
        "  [ \"$CLEAN_STATUS\" = 0 ] || exit \"$CLEAN_STATUS\"\n"
        "  rmdir \"$FIXTURE_ROOT/cache\" \"$FIXTURE_ROOT/modules\"\n"
        "else exit 23; fi\n"
    )
    go.chmod(0o755)
    goroot = tmp_path / "goroot"
    goroot.mkdir()
    (goroot / "compiler").write_text("intact")
    command = command.replace("/opt/repomap/bin", '"' + str(tmp_path / "bin") + '"')
    result = subprocess.run(
        ["sh", "-c", command], capture_output=True, text=True, check=False,
        env=dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
                 FIXTURE_ROOT=str(tmp_path), INSTALL_STATUS=str(install_status),
                 CLEAN_STATUS=str(clean_status)),
    )
    assert result.returncode == (install_status or clean_status)
    calls = (tmp_path / "calls").read_text().splitlines()
    assert calls == [f"install {INSTALL}"] + ([] if install_status else ["clean -cache -modcache"])
    assert (goroot / "compiler").read_text() == "intact"
    if install_status == clean_status == 0:
        assert not (tmp_path / "cache").exists()
        assert not (tmp_path / "modules").exists()
        binary = tmp_path / "bin/golangci-lint"
        assert os.access(binary, os.X_OK)
        assert subprocess.check_output([str(binary), "version"], text=True).strip() == (
            "golangci-lint has version 2.6.2"
        )


def test_runtime_copies_only_goroot_and_installed_linter_from_builder():
    copies = [line for line in RECIPE.read_text().splitlines()
              if line.startswith("COPY --from=go-toolchain")]
    assert copies == [
        "COPY --from=go-toolchain /usr/local/go /usr/local/go",
        "COPY --from=go-toolchain /opt/repomap/bin/golangci-lint /usr/local/bin/golangci-lint",
    ]


def test_psycopg_c_probes_import_psycopg_first_in_fresh_isolated_processes():
    # Text only: no recipe Python runs here; the canonical SDK build loads the real package.
    run = next(line for line in RECIPE.read_text().replace("\\\n", " ").splitlines() if "attest-libpq" in line)
    words = shlex.split(run)
    starts = [i for i, word in enumerate(words) if word == "-c" and words[i - 2:i] == ["python3", "-I"]]
    probes = [words[i + 1] for i in starts]
    assert len(probes) == 2 and words[starts[0] - 5:starts[0] - 2] == ["env", "-u", "PSYCOPG_IMPL"]
    for probe in probes:
        modules = [name.split(" as ")[0] for name in probe.split(";")[0].removeprefix("import ").split(", ")]
        assert "psycopg" in modules and modules.index("psycopg") < modules.index(
            next(name for name in modules if name.startswith("psycopg_c"))), probe
    assert "assert pq.__impl__ == 'c'; assert pq.version() == pq.__build_version__" in probes[0]
    assert "assert u.find_spec('psycopg_binary') is None" in probes[0]
    assert probes[1] == (
        "import psycopg, psycopg_c._psycopg as a, psycopg_c.pq as b; print(a.__file__); print(b.__file__)")
    loop = " ".join(run[run.index(probes[1]):].split())
    assert '> /tmp/psycopg-c-extensions.txt && while read -r extension; do readelf -d "${extension}"' in loop
    assert "grep -qF 'Shared library: [libpq.so.5]' /tmp/psycopg-c-dynamic.txt || exit 1; done" in loop


def prerequisite_run():
    instructions = RECIPE.read_text().replace("\\\n", " ").splitlines()
    runs = [line.removeprefix("RUN ") for line in instructions
            if line.startswith("RUN ") and f"{HELPER} install" in line]
    assert len(runs) == 1
    return runs[0]


def test_archived_header_configuration_is_fixed_ordered_and_adds_no_trust_bypass():
    command = " ".join(prerequisite_run().split())
    helper_check = (
        f"printf '%s %s\\n' \"${{REPOMAP_SANDBOX_APT_HELPER_SHA256}}\" {HELPER} | sha256sum --check --strict -")
    keyring_check = f"printf '%s %s\\n' {KEYRING_SHA256} {KEYRING} | sha256sum --check --strict -"
    steps = [helper_check, keyring_check, "set -C", f"> /{SOURCE}", f"> /{PINS}", f"{HELPER} install",
             f"rm /{SOURCE} /{PINS}", f"rm -rf {LISTS}/*"]
    positions = [command.find(step) for step in steps]
    assert -1 not in positions and positions == sorted(positions), positions
    assert command.startswith(helper_check + " && " + keyring_check + " && set -C && printf ")
    assert command.count(KEYRING_SHA256) == 1 and f"'Signed-By: {KEYRING}'" in command
    for forbidden in ("Trusted", "allow-", "Acquire::", "--force", "apt-get", "libpq5", "postgresql-1"):
        assert forbidden not in command[:command.index(f"{HELPER} install")], forbidden
    helper_call, *after = command[command.index(f"{HELPER} install"):].split(" && ")
    assert helper_call.split()[1:] == ["install", "--cache", "/var/cache/repomap-apt-prerequisites",
                                       "--evidence", "/usr/local/share/repomap/apt-prerequisites.json", *NATIVE]
    # Only after the helper succeeds: exactly the two created files, then the lists.
    assert after == [f"rm /{SOURCE} /{PINS}", f"rm -rf {LISTS}/*"]


@pytest.mark.parametrize("case", ["helper-digest", "keyring-digest", "existing-source", "helper-error", "installed"])
def test_archived_header_shell_stops_before_the_helper_and_propagates_its_error(tmp_path, case):
    root, tools, calls = tmp_path / "root", tmp_path / "tools", tmp_path / "calls"
    for directory in ("etc/apt/sources.list.d", "etc/apt/preferences.d", "var/lib/apt/lists", "keys", "lib"):
        (root / directory).mkdir(parents=True)
    tools.mkdir()
    base = root / "etc/apt/sources.list.d/debian.sources"
    base.write_text("base repositories\n")
    other_pins = root / "etc/apt/preferences.d/base.pref"
    other_pins.write_text("base preferences\n")
    (root / "var/lib/apt/lists/index").write_text("index\n")
    keyring, helper = root / "keys/debian-archive-keyring.pgp", root / "lib/apt_prerequisites.py"
    fixture_key = b"fixture keyring"
    keyring.write_bytes(b"another keyring" if case == "keyring-digest" else fixture_key)
    helper.write_text(HELPER_DOUBLE)
    if case == "existing-source":
        (root / SOURCE).write_text("operator source\n")
    (tools / "checker.py").write_text(CHECKER)
    python = shlex.quote(sys.executable)
    (tools / "sha256sum").write_text(f"#!/bin/sh\nexec {python} -I {shlex.quote(str(tools / 'checker.py'))} \"$@\"\n")
    (tools / "python3").write_text(f"#!/bin/sh\nexec {python} \"$@\"\n")
    for name in ("sha256sum", "python3"):
        (tools / name).chmod(0o755)
    command = prerequisite_run()
    for real, fixture in ((HELPER, str(helper)), (KEYRING, str(keyring)), (LISTS, str(root / "var/lib/apt/lists")),
                          (KEYRING_SHA256, hashlib.sha256(fixture_key).hexdigest()), ("/etc/apt/", f"{root}/etc/apt/")):
        assert command.count(real) >= 1, real
        command = command.replace(real, fixture)
    for unsafe in ("/etc/", "/var/lib/", "/usr/share/keyrings/", "/usr/local/lib/"):  # never the host's real paths
        assert command.count(unsafe) == command.count(f"{root}{unsafe}"), unsafe
    digest = hashlib.sha256(helper.read_bytes()).hexdigest()
    status = 7 if case == "helper-error" else 0
    result = subprocess.run(
        ["sh", "-c", command], capture_output=True, text=True, check=False,
        env=dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"], FIXTURE_ROOT=str(root),
                 FIXTURE_CALLS=str(calls), FIXTURE_SOURCE=SOURCE, FIXTURE_PINS=PINS, HELPER_STATUS=str(status),
                 REPOMAP_SANDBOX_APT_HELPER_SHA256="0" * 64 if case == "helper-digest" else digest),
    )
    seen = calls.read_text().splitlines()
    checks = ["sha256sum OK apt_prerequisites.py", "sha256sum OK debian-archive-keyring.pgp"]
    assert base.read_text() == "base repositories\n" and other_pins.read_text() == "base preferences\n"
    assert keyring.read_bytes() == (b"another keyring" if case == "keyring-digest" else fixture_key)
    if case in ("helper-digest", "keyring-digest", "existing-source"):
        assert result.returncode != 0
        assert seen == {"helper-digest": ["sha256sum FAILED apt_prerequisites.py"],
                        "keyring-digest": [checks[0], "sha256sum FAILED debian-archive-keyring.pgp"],
                        "existing-source": checks}[case]
        assert (root / SOURCE).exists() == (case == "existing-source") and not (root / PINS).exists()
        if case == "existing-source":
            assert (root / SOURCE).read_text() == "operator source\n"
        assert (root / "var/lib/apt/lists/index").exists()
        return
    assert result.returncode == status, result.stderr
    assert seen[:2] == checks and len(seen) == 3 and seen[2].startswith("helper ")
    started = json.loads(seen[2].removeprefix("helper "))
    assert started["argv"] == ["install", "--cache", "/var/cache/repomap-apt-prerequisites",
                               "--evidence", "/usr/local/share/repomap/apt-prerequisites.json", *NATIVE]
    expected_source = SNAPSHOT_SOURCE.format(keyring=keyring)
    assert started["source"] == expected_source and started["pins"] == SNAPSHOT_PINS
    if status:  # a failed helper leaves the transaction configuration and lists for diagnosis
        assert (root / SOURCE).read_text() == expected_source and (root / PINS).read_text() == SNAPSHOT_PINS
    else:
        assert not (root / SOURCE).exists() and not (root / PINS).exists()
    assert (root / "var/lib/apt/lists/index").exists() == bool(status)
