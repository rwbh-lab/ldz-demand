"""
Config loading.

Reads config/default.ini (committed), then config/local.ini (gitignored) on top, so local.ini only
needs the keys it overrides. Environment variables are available for interpolation, e.g.
cache_dir = ${HOME}/data/ldz-demand/cache.

Set LDZ_DEMAND_CONFIG to read a different override file in place of config/local.ini.
"""

import os
import logging
import configparser
from pathlib import Path

logger = logging.getLogger(__name__)


def get_project_root() -> Path:
    return Path(__file__).parent.parent.parent


def create_config() -> configparser.ConfigParser:
    config_parser = configparser.ConfigParser(os.environ, interpolation=configparser.ExtendedInterpolation())
    default_ini = get_project_root() / "config" / "default.ini"
    local_ini = Path(os.environ.get("LDZ_DEMAND_CONFIG", get_project_root() / "config" / "local.ini"))
    if not default_ini.exists():
        raise FileNotFoundError(f"Default config not found at '{default_ini}'")
    read = config_parser.read([default_ini, local_ini])
    logger.info(f"Read INI from file(s) {read}")
    return config_parser


def use_database(config: configparser.ConfigParser) -> bool:
    return config.getboolean("storage", "database")


def resolve_path(config: configparser.ConfigParser, section: str, key: str) -> Path:
    """Path from config; relative paths are taken relative to the project root."""
    path = Path(config[section][key]).expanduser()
    return path if path.is_absolute() else get_project_root() / path


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    config = create_config()
    print(f"database = {use_database(config)}")
    print(f"cache_dir = {resolve_path(config, 'storage', 'cache_dir')}")
