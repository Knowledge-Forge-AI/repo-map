"""Same-layer builder hygiene; fake tools do not qualify a real image build."""

import os
from pathlib import Path
import subprocess

import pytest


RECIPE = Path(__file__).resolve().parents[5] / "tools/test_sandbox/Dockerfile"
INSTALL = "github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.6.2"


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
