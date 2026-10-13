"""The project map must match the code: everything it names exists, and every module is on it."""

import configparser
import importlib.util
import json
import re

import pytest

from ldz_demand import project_map as pm
from ldz_demand.charts import project_map as draw
from ldz_demand.charts.pages import PAGES
from ldz_demand.config import get_project_root
from ldz_demand.data import datasets

ROOT = get_project_root()
PACKAGE = ROOT / "src" / "ldz_demand"
TABLES = {d.name for d in vars(datasets).values() if isinstance(d, datasets.Dataset)}


def _everything():
    yield from pm.NODES
    yield from pm.EDGES


def test_ids_are_unique_and_edges_join_nodes():
    ids = [n.id for n in pm.NODES]
    assert len(ids) == len(set(ids))
    for e in pm.EDGES:
        assert e.source in ids and e.target in ids, e.id
    assert len({e.id for e in pm.EDGES}) == len(pm.EDGES)


def test_main_flow_is_connected_and_runs_left_to_right():
    for n in pm.NODES:
        if n.column is not None:
            assert any(n.id in (e.source, e.target) for e in pm.EDGES), f"{n.id} has no arrows"
    for e in pm.EDGES:
        s, t = pm.node(e.source), pm.node(e.target)
        assert s.column is not None and t.column is not None, e.id
        assert s.column < t.column or (s.column == t.column and s.row != t.row), f"{e.id} runs backwards"


@pytest.mark.parametrize("item", list(_everything()), ids=lambda i: i.id)
def test_everything_named_exists(item):
    for m in item.modules:
        assert importlib.util.find_spec(f"ldz_demand.{m}") is not None, m
    for d in getattr(item, "datasets", ()):
        assert d in TABLES, d
    for f in getattr(item, "files", ()):
        assert (ROOT / f).exists(), f
    for d in getattr(item, "docs", ()):
        assert (ROOT / d.split(":")[0]).exists(), d
    if getattr(item, "page", None):
        assert item.page in PAGES and (ROOT / "dashboard" / item.page).exists(), item.page
    for c in getattr(item, "commands", ()):
        module = re.match(r"python -m ldz_demand\.([\w.]+)", c)
        assert module, c
        spec = importlib.util.find_spec(f"ldz_demand.{module.group(1)}")
        assert spec is not None, c
        if spec.submodule_search_locations:  # a package: run through its __main__
            assert importlib.util.find_spec(f"ldz_demand.{module.group(1)}.__main__") is not None, c
    if getattr(item, "config", ()):
        ini = configparser.ConfigParser(interpolation=None)
        ini.read(ROOT / "config" / "default.ini")
        for section in item.config:
            assert ini.has_section(section), section


def test_every_module_is_on_the_map():
    on_map = {m for i in _everything() for m in i.modules}
    missing = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).with_suffix("")
        parts = rel.parts[:-1] if rel.name == "__init__" else rel.parts
        if not parts or parts in {("data",), ("data", "build"), ("data", "ingest"), ("charts",), ("models",)}:
            continue  # the package itself and namespace-only __init__ files
        module = ".".join(parts)
        if module not in on_map:
            missing.append(module)
    assert not missing, f"not on the project map (ldz_demand/project_map.py): {missing}"


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
def test_both_layouts_fit_every_box(orientation, monkeypatch):
    monkeypatch.setattr(draw, "ORIENTATION", orientation)
    if orientation == "vertical":
        assert all(n.at is not None for n in pm.NODES if n.column is not None), "every box needs at=(lane, depth)"
    lay = draw.layout()
    for x, y in lay["pos"].values():
        assert 0 <= x and x + lay["node_w"] <= lay["width"] and 0 <= y and y + draw.NODE_H <= lay["height"]
    boxes = sorted(lay["pos"].values())
    for (x1, y1), (x2, y2) in zip(boxes, boxes[1:]):  # no two boxes overlap
        assert abs(x1 - x2) >= lay["node_w"] or abs(y1 - y2) >= draw.NODE_H


def test_page_renders():
    page = draw.html_page()
    assert page.startswith("<!doctype html>") and "</html>" in page
    spec = json.loads(re.search(r'<script type="application/json" id="spec">(.*?)</script>', page, re.S).group(1)
                      .replace("<\\/", "</"))
    assert len(spec["nodes"]) == len(pm.NODES) and len(spec["edges"]) == len(pm.EDGES)
    assert all(f for n in spec["nodes"] for _, f in n["modules"])  # every module resolved to a file
