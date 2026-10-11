"""
Database command line.

    python -m ldz_demand.db status            show applied / pending migrations
    python -m ldz_demand.db migrate           apply pending migrations
    python -m ldz_demand.db migrate --dry-run list what would be applied
    python -m ldz_demand.db draft <dataset>   print CREATE TABLE for a dataset (to start a migration)

Connection details come from .env / LDZ_DB_* (see .env.example).
"""

import argparse
import logging
import sys

from ldz_demand.data.datasets import DATASETS
from ldz_demand.db.connection import DbConfigError, DbSettings, create_engine
from ldz_demand.db.ddl import create_table_sql
from ldz_demand.db.migrate import applied, migrate, pending


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.db")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    migrate_parser = sub.add_parser("migrate")
    migrate_parser.add_argument("--dry-run", action="store_true")
    draft_parser = sub.add_parser("draft")
    draft_parser.add_argument("dataset", choices=sorted(DATASETS))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.command == "draft":
        print(create_table_sql(DATASETS[args.dataset]), end="")
        return 0

    try:
        settings = DbSettings.from_env()
    except DbConfigError as e:
        print(f"Database config error: {e}", file=sys.stderr)
        return 2
    engine = create_engine(settings)
    if args.command == "status":
        done = applied(engine)
        for version in sorted(done):
            print(f"applied  {version}")
        for migration in pending(engine):
            print(f"pending  {migration.version}")
    elif args.command == "migrate":
        migrate(engine, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
