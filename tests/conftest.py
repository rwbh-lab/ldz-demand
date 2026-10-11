"""
Shared fixtures.

mysql_engine starts a throwaway MySQL 8.4 container on localhost for the session (random port,
random password, removed afterwards). Tests using it are skipped if Docker isn't available.
"""

import secrets
import shutil
import subprocess
import time
import uuid

import pytest

MYSQL_IMAGE = "mysql:8.4"
STARTUP_TIMEOUT = 180  # seconds; first init of the data directory is slow


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.fixture(scope="session")
def mysql_engine():
    if not docker_available():
        pytest.skip("Docker not available")
    sa = pytest.importorskip("sqlalchemy")
    pytest.importorskip("pymysql")
    from ldz_demand.db.connection import DbSettings, create_engine

    name = f"ldz-demand-test-{uuid.uuid4().hex[:8]}"
    password = secrets.token_hex(16)
    subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name,
            "-e", f"MYSQL_ROOT_PASSWORD={password}",
            "-e", "MYSQL_DATABASE=ldz_test",
            "-e", "MYSQL_USER=ldz_test",
            "-e", f"MYSQL_PASSWORD={password}",
            "-p", "127.0.0.1::3306",
            MYSQL_IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    try:
        mapping = subprocess.run(
            ["docker", "port", name, "3306/tcp"], check=True, capture_output=True, text=True
        ).stdout.split()[0]
        port = int(mapping.rsplit(":", 1)[1])
        engine = create_engine(DbSettings("127.0.0.1", port, "ldz_test", "ldz_test", password))

        deadline = time.monotonic() + STARTUP_TIMEOUT
        while True:
            try:
                with engine.connect() as conn:
                    conn.execute(sa.text("SELECT 1"))
                break
            except sa.exc.OperationalError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(2)
        yield engine
        engine.dispose()
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def drop_all_tables(engine) -> None:
    import sqlalchemy as sa

    with engine.begin() as conn:
        tables = conn.execute(sa.text("SHOW TABLES")).scalars().all()
        for table in tables:
            conn.execute(sa.text(f"DROP TABLE `{table}`"))
