"""
Build the LDZ geography reference data.

    python -m ldz_demand.geo fetch    # sources -> raw_dir/reference/ (broker pages, ONS place index,
                                      #   ONS boundaries, DESNZ gas use, OS Code-Point Open); skips files already there
    python -m ldz_demand.geo.postcode_sample check   # operator postcode lookups for the sample (paced, cached)
    python -m ldz_demand.geo build    # -> ldz_demand/geo/data/*.csv / *.geojson (committed)
"""

import argparse
import logging
import sys

from ldz_demand.config import create_config, resolve_path
from ldz_demand.geo import boundaries, gas_use, grid_weights, ldz_membership, postcode_sample


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.geo")
    parser.add_argument("command", choices=["fetch", "build"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    raw_dir = resolve_path(create_config(), "storage", "raw_dir")
    for module in (ldz_membership, boundaries, gas_use, postcode_sample, grid_weights):
        getattr(module, args.command)(raw_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
