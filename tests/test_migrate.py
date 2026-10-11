import pytest

from ldz_demand.data.datasets import DATASETS
from ldz_demand.db.ddl import INFO_SCHEMA_TYPES
from ldz_demand.db.migrate import MIGRATIONS_DIR, MigrationError, discover, migrate, pending


def write(directory, name, sql="SELECT 1;\n"):
    path = directory / name
    path.write_text(sql)
    return path


# --- file rules (no database) -------------------------------------------------------------------

def test_repo_migrations_are_valid():
    assert [m.version for m in discover()][0] == "001_create_ng_ldz_daily"


def test_duplicate_numbers_rejected(tmp_path):
    write(tmp_path, "001_a.sql")
    write(tmp_path, "001_b.sql")
    with pytest.raises(MigrationError, match="Duplicate migration number 001"):
        discover(tmp_path)


def test_bad_filenames_rejected(tmp_path):
    write(tmp_path, "1_a.sql")
    with pytest.raises(MigrationError, match="Bad migration filename"):
        discover(tmp_path)


def test_statements_split_and_comments_dropped(tmp_path):
    path = write(tmp_path, "001_a.sql", "-- header; not a statement\nCREATE TABLE a (x INT);\n\nINSERT INTO a VALUES (1);\n")
    assert discover(tmp_path)[0].statements() == ["CREATE TABLE a (x INT)", "INSERT INTO a VALUES (1)"]
    assert path.exists()


# --- against MySQL ------------------------------------------------------------------------------

@pytest.fixture
def engine(mysql_engine):
    from conftest import drop_all_tables

    drop_all_tables(mysql_engine)
    return mysql_engine


def test_migrate_applies_once_and_records(engine, tmp_path):
    write(tmp_path, "001_create_a.sql", "CREATE TABLE a (x INT);\n")
    write(tmp_path, "002_insert_a.sql", "INSERT INTO a VALUES (1);\nINSERT INTO a VALUES (2);\n")

    assert migrate(engine, tmp_path, dry_run=True) == ["001_create_a", "002_insert_a"]
    assert len(pending(engine, tmp_path)) == 2
    assert migrate(engine, tmp_path) == ["001_create_a", "002_insert_a"]
    assert migrate(engine, tmp_path) == []

    import sqlalchemy as sa

    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM a")).scalar() == 2


def test_edited_or_removed_migration_is_refused(engine, tmp_path):
    first = write(tmp_path, "001_create_a.sql", "CREATE TABLE a (x INT);\n")
    migrate(engine, tmp_path)

    first.write_text("CREATE TABLE a (x BIGINT);\n")
    with pytest.raises(MigrationError, match="were edited"):
        migrate(engine, tmp_path)

    first.unlink()
    with pytest.raises(MigrationError, match="missing"):
        migrate(engine, tmp_path)


def test_repo_migrations_match_dataset_schemas(engine):
    """Schema drift check: tables built by the real migrations match the Dataset definitions."""
    import sqlalchemy as sa

    migrate(engine, MIGRATIONS_DIR)
    with engine.connect() as conn:
        for dataset in DATASETS.values():
            rows = conn.execute(
                sa.text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() AND table_name = :t ORDER BY ordinal_position"
                ),
                {"t": dataset.name},
            ).all()
            expected = [(col, INFO_SCHEMA_TYPES[dtype]) for col, dtype in dataset.columns.items()]
            assert [(c.lower(), t.lower()) for c, t in rows] == expected, dataset.name

            keys = conn.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.key_column_usage "
                    "WHERE table_schema = DATABASE() AND table_name = :t AND constraint_name = 'PRIMARY' "
                    "ORDER BY ordinal_position"
                ),
                {"t": dataset.name},
            ).scalars().all()
            assert tuple(k.lower() for k in keys) == dataset.keys, dataset.name
