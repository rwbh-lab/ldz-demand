"""
MySQL connection settings and engine.

Settings come from LDZ_DB_* environment variables, with .env in the project root loaded first
(variables already set in the environment win). Host selection, in order:

1. LDZ_DB_HOST         — if set, always used.
2. LDZ_DB_NETWORK      — "local" or "remote" forces LDZ_DB_HOST_LOCAL / LDZ_DB_HOST_REMOTE.
3. auto (default)      — use LOCAL if it answers on the port within PROBE_TIMEOUT, else REMOTE.
                         If LDZ_DB_HOME_GATEWAY is set, LOCAL is only tried when the machine's
                         default gateway matches it (i.e. on the home network).

The password is never logged and is excluded from DbSettings' repr.
"""

import logging
import os
import re
import socket
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from ldz_demand.config import get_project_root

logger = logging.getLogger(__name__)

PROBE_TIMEOUT = 0.5  # seconds
NETWORKS = ("auto", "local", "remote")


class DbConfigError(RuntimeError):
    """Missing or inconsistent LDZ_DB_* settings."""


@dataclass(frozen=True)
class DbSettings:
    host: str
    port: int
    name: str
    user: str
    password: str = field(repr=False)

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        probe: Callable[[str, int], bool] | None = None,
        gateway: Callable[[], str | None] | None = None,
    ) -> "DbSettings":
        """
        Build settings from env (default: os.environ after loading .env).

        probe and gateway are injectable for testing; defaults are a TCP connect test and the
        OS default gateway.
        """
        if env is None:
            load_env()
            env = os.environ

        port = int(env.get("LDZ_DB_PORT") or 3306)
        host, how = resolve_host(env, port, probe or can_connect, gateway or default_gateway)
        settings = cls(
            host=host,
            port=port,
            name=_require(env, "LDZ_DB_NAME"),
            user=_require(env, "LDZ_DB_USER"),
            password=_require(env, "LDZ_DB_PASSWORD"),
        )
        logger.info(f"MySQL host: {settings.host}:{settings.port} ({how}), database {settings.name}")
        return settings


def load_env() -> None:
    """Load .env from the project root, if python-dotenv is installed and the file exists."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(get_project_root() / ".env", override=False)


def resolve_host(
    env: Mapping[str, str],
    port: int,
    probe: Callable[[str, int], bool],
    gateway: Callable[[], str | None],
) -> tuple[str, str]:
    """Return (host, how it was chosen)."""
    if env.get("LDZ_DB_HOST"):
        return env["LDZ_DB_HOST"], "LDZ_DB_HOST"

    local = env.get("LDZ_DB_HOST_LOCAL") or None
    remote = env.get("LDZ_DB_HOST_REMOTE") or None
    network = (env.get("LDZ_DB_NETWORK") or "auto").lower()
    if network not in NETWORKS:
        raise DbConfigError(f"LDZ_DB_NETWORK must be one of {NETWORKS}, got '{network}'")
    if not local and not remote:
        raise DbConfigError("Set LDZ_DB_HOST, or LDZ_DB_HOST_LOCAL and/or LDZ_DB_HOST_REMOTE")

    if network == "local":
        if not local:
            raise DbConfigError("LDZ_DB_NETWORK=local but LDZ_DB_HOST_LOCAL is not set")
        return local, "local, forced"
    if network == "remote":
        if not remote:
            raise DbConfigError("LDZ_DB_NETWORK=remote but LDZ_DB_HOST_REMOTE is not set")
        return remote, "remote, forced"

    if local:
        home_gateway = env.get("LDZ_DB_HOME_GATEWAY") or None
        on_home_network = home_gateway is None or gateway() == home_gateway
        if on_home_network and probe(local, port):
            return local, "local, auto"
        if not remote:
            return local, "local, auto (no remote configured)"
    return remote, "remote, auto"


def can_connect(host: str, port: int, timeout: float = PROBE_TIMEOUT) -> bool:
    """True if a TCP connection to host:port succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def default_gateway() -> str | None:
    """The OS default gateway IP, or None if it can't be determined."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["route", "-n", "get", "default"], capture_output=True, text=True, timeout=2).stdout
            match = re.search(r"gateway:\s*(\S+)", out)
        else:
            out = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=2).stdout
            match = re.search(r"default via (\S+)", out)
    except (OSError, subprocess.SubprocessError):
        return None
    return match.group(1) if match else None


def create_engine(settings: DbSettings, **kwargs):
    """SQLAlchemy engine for settings (PyMySQL driver). Connects lazily on first use."""
    import sqlalchemy as sa

    url = sa.URL.create(
        "mysql+pymysql",
        username=settings.user,
        password=settings.password,
        host=settings.host,
        port=settings.port,
        database=settings.name,
        query={"charset": "utf8mb4"},
    )
    return sa.create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=3600,
        connect_args={"connect_timeout": 10},
        **kwargs,
    )


def _require(env: Mapping[str, str], key: str) -> str:
    value = env.get(key)
    if not value:
        raise DbConfigError(f"{key} is not set (see .env.example)")
    return value
