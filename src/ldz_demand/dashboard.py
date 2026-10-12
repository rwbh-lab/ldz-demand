"""
Serve every dashboard page from one local server, with the overview page at /.

    python -m ldz_demand.dashboard              # http://localhost:2718
    python -m ldz_demand.dashboard --port 8080
"""

import argparse
import sys

from ldz_demand.charts.pages import INDEX, PAGES
from ldz_demand.config import get_project_root


def build_app():
    import marimo

    folder = get_project_root() / "dashboard"
    builder = marimo.create_asgi_app()
    for file, page in PAGES.items():
        builder = builder.with_app(path=page.path, root=str(folder / file))
    return builder.with_app(path="/", root=str(folder / INDEX)).build()


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    parser = argparse.ArgumentParser(prog="python -m ldz_demand.dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2718)
    args = parser.parse_args(argv)
    print(f"LDZ demand dashboard: http://{args.host}:{args.port}")
    uvicorn.run(build_app(), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
