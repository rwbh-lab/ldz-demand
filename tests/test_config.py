from ldz_demand.config import create_config, get_project_root, resolve_path, use_database


def test_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("LDZ_DEMAND_CONFIG", str(tmp_path / "missing.ini"))
    config = create_config()

    assert use_database(config) is False
    assert resolve_path(config, "storage", "cache_dir") == get_project_root() / "data" / "cache"


def test_local_override(monkeypatch, tmp_path):
    local_ini = tmp_path / "local.ini"
    local_ini.write_text("[storage]\ndatabase = true\ncache_dir = ${HOME}/ldz-cache\n")
    monkeypatch.setenv("LDZ_DEMAND_CONFIG", str(local_ini))
    monkeypatch.setenv("HOME", str(tmp_path))
    config = create_config()

    assert use_database(config) is True
    assert resolve_path(config, "storage", "cache_dir") == tmp_path / "ldz-cache"
    # keys not overridden still come from default.ini
    assert resolve_path(config, "storage", "raw_dir") == get_project_root() / "data" / "raw"
