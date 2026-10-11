"""
SQL migration runner.

Migrations are db/migrations/NNN_description.sql, applied in number order and recorded in
schema_migrations (version, checksum, applied_at). Rules:

- Never edit a migration once it has been applied anywhere shared — add a new one. The runner
  refuses to continue if an applied file's checksum has changed.
- Migration numbers must be unique.
- MySQL commits DDL immediately, so a migration that fails part-way is not rolled back. Keep one
  logical change per file.

Statements are split on ';' at line end; full-line '--' comments are dropped. That covers plain
DDL/DML — stored procedures or triggers with embedded ';' are not supported.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ldz_demand.config import get_project_root

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = get_project_root() / "db" / "migrations"
FILENAME = re.compile(r"(\d{3})_[a-z0-9_]+\.sql")

SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version VARCHAR(255) NOT NULL,
  checksum CHAR(64) NOT NULL,
  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (version)
)
"""


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: str  # file stem, e.g. 001_create_ng_ldz_daily
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text()

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def statements(self) -> list[str]:
        lines = [line for line in self.sql.splitlines() if not line.strip().startswith("--")]
        return [s.strip() for s in re.split(r";\s*$", "\n".join(lines), flags=re.M) if s.strip()]


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Migration files in number order. Raises on badly named files or duplicate numbers."""
    migrations, numbers = [], {}
    for path in sorted(directory.glob("*.sql")):
        match = FILENAME.fullmatch(path.name)
        if not match:
            raise MigrationError(f"Bad migration filename '{path.name}' (expected NNN_lower_snake.sql)")
        number = match.group(1)
        if number in numbers:
            raise MigrationError(f"Duplicate migration number {number}: {numbers[number]} and {path.name}")
        numbers[number] = path.name
        migrations.append(Migration(path.stem, path))
    return migrations


def applied(engine) -> dict[str, str]:
    """version -> checksum for migrations already applied."""
    import sqlalchemy as sa

    with engine.begin() as conn:
        conn.execute(sa.text(SCHEMA_MIGRATIONS_DDL))
        rows = conn.execute(sa.text("SELECT version, checksum FROM schema_migrations")).all()
    return {version: checksum for version, checksum in rows}


def pending(engine, directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Migrations not yet applied. Raises if an applied migration file was changed or removed."""
    done = applied(engine)
    migrations = discover(directory)
    on_disk = {m.version for m in migrations}
    missing = sorted(set(done) - on_disk)
    if missing:
        raise MigrationError(f"Applied migrations missing from {directory}: {missing}")
    changed = [m.version for m in migrations if m.version in done and done[m.version] != m.checksum]
    if changed:
        raise MigrationError(f"Applied migrations were edited (add a new migration instead): {changed}")
    return [m for m in migrations if m.version not in done]


def migrate(engine, directory: Path = MIGRATIONS_DIR, dry_run: bool = False) -> list[str]:
    """Apply pending migrations in order. Returns the versions applied (or that would be)."""
    import sqlalchemy as sa

    todo = pending(engine, directory)
    for migration in todo:
        if dry_run:
            logger.info(f"Would apply {migration.version}")
            continue
        logger.info(f"Applying {migration.version}")
        with engine.begin() as conn:
            for statement in migration.statements():
                conn.execute(sa.text(statement))
            conn.execute(
                sa.text("INSERT INTO schema_migrations (version, checksum) VALUES (:v, :c)"),
                {"v": migration.version, "c": migration.checksum},
            )
    if not todo:
        logger.info("No pending migrations")
    return [m.version for m in todo]
