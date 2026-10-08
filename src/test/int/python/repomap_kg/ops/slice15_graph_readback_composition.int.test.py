"""Slice15 repair: load real layered configuration and consume resolved records."""
from pathlib import Path

from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.ops.config_status import ops_config_status_to_jsonable
from repomap_test_support.ops_refresh import VALID_REFRESH_CONFIG


def test_s15_b07_ops_config_payload_merging_matrix(tmp_path: Path) -> None:
    (tmp_path / "base.rp.toml").write_text(
        VALID_REFRESH_CONFIG.format(repo_root=tmp_path, private_root=tmp_path / "private")
    )
    (tmp_path / "overlay.rpl.toml").write_text(
        'schema_version = 1\n[service]\nlog_level = "debug"\n'
        '[postgres]\nport = 5433\n'
    )
    config = load_ops_config_home(tmp_path)
    assert config.service.mode == "local"
    assert config.service.log_level == "debug"
    assert config.postgres.port == 5433
    assert config.config_files == ("base.rp.toml", "overlay.rpl.toml")
    codes = {diagnostic.code for diagnostic in config.diagnostics}
    assert {"service-overlay", "postgres-overlay"} <= codes
    payload = ops_config_status_to_jsonable(config)
    assert payload["service"]["log_level"] == "debug"
    assert payload["postgres"]["port"] == 5433
    (tmp_path / "overlay.rpl.toml").unlink()
    restored = load_ops_config_home(tmp_path)
    assert restored.service.log_level == "info"
    assert restored.postgres.port == 5432
    assert not {"service-overlay", "postgres-overlay"} & {
        diagnostic.code for diagnostic in restored.diagnostics
    }
