import pytest

from ldz_demand.db.connection import DbConfigError, DbSettings, resolve_host

# Example addresses only: TEST-NET-1 (RFC 5737) for the LAN, the shared range (RFC 6598) for a VPN.
LOCAL, REMOTE, HOME_GW = "192.0.2.10", "100.64.0.10", "192.0.2.1"


def resolve(env, reachable=(), gw=HOME_GW):
    return resolve_host(env, 3306, probe=lambda host, port: host in reachable, gateway=lambda: gw)


BOTH = {"LDZ_DB_HOST_LOCAL": LOCAL, "LDZ_DB_HOST_REMOTE": REMOTE}


def test_explicit_host_wins():
    assert resolve({**BOTH, "LDZ_DB_HOST": "db.example"})[0] == "db.example"


def test_forced_network():
    assert resolve({**BOTH, "LDZ_DB_NETWORK": "local"})[0] == LOCAL
    assert resolve({**BOTH, "LDZ_DB_NETWORK": "remote"}, reachable=[LOCAL])[0] == REMOTE
    with pytest.raises(DbConfigError, match="LDZ_DB_HOST_REMOTE is not set"):
        resolve({"LDZ_DB_HOST_LOCAL": LOCAL, "LDZ_DB_NETWORK": "remote"})
    with pytest.raises(DbConfigError, match="must be one of"):
        resolve({**BOTH, "LDZ_DB_NETWORK": "home"})


def test_auto_prefers_reachable_local():
    assert resolve(BOTH, reachable=[LOCAL, REMOTE]) == (LOCAL, "local, auto")
    assert resolve(BOTH, reachable=[REMOTE]) == (REMOTE, "remote, auto")


def test_auto_home_gateway_guard():
    env = {**BOTH, "LDZ_DB_HOME_GATEWAY": HOME_GW}
    assert resolve(env, reachable=[LOCAL])[0] == LOCAL
    # away from home: LOCAL is never probed, even if something answers there
    probed = []
    host, _ = resolve_host(env, 3306, probe=lambda h, p: probed.append(h) or True, gateway=lambda: "10.0.0.1")
    assert host == REMOTE
    assert probed == []
    # gateway unknown counts as away
    assert resolve(env, reachable=[LOCAL], gw=None)[0] == REMOTE


def test_auto_local_only_falls_back_to_local():
    assert resolve({"LDZ_DB_HOST_LOCAL": LOCAL})[0] == LOCAL


def test_no_hosts_configured():
    with pytest.raises(DbConfigError, match="Set LDZ_DB_HOST"):
        resolve({})


def test_settings_require_credentials_and_hide_password():
    env = {"LDZ_DB_HOST": "db.example", "LDZ_DB_NAME": "ldz_demand", "LDZ_DB_USER": "ldz_app"}
    with pytest.raises(DbConfigError, match="LDZ_DB_PASSWORD is not set"):
        DbSettings.from_env(env)

    settings = DbSettings.from_env({**env, "LDZ_DB_PASSWORD": "s3cret", "LDZ_DB_PORT": "3307"})
    assert settings.port == 3307
    assert "s3cret" not in repr(settings)
