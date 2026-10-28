"""Every link in the docs, READMEs and dashboard pages points at a file that exists, and at a heading in it."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/rwbh-lab/ldz-demand/blob/main/"
LINK = re.compile(r"\]\(([^)\s]+)\)")


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: the rendered text, lower case, punctuation dropped, spaces as hyphens."""
    text = re.sub(r"\[([^]]*)\]\([^)]*\)", r"\1", heading)  # a link renders as its text
    text = re.sub(r"[`*]", "", text).strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def anchors(path: Path) -> set[str]:
    """The anchors of a markdown file's headings (a repeated heading gets -1, -2, ... as on GitHub)."""
    seen: dict[str, int] = {}
    found = set()
    in_code = False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and (match := re.match(r"#{1,6} (.+)", line)):
            base = slug(match.group(1))
            found.add(base if base not in seen else f"{base}-{seen[base]}")
            seen[base] = seen.get(base, 0) + 1
    return found


def sources() -> list[Path]:
    docs = [p for p in ROOT.rglob("*.md") if not {".venv", "private", "node_modules", ".pytest_cache"} & set(p.parts)]
    return sorted(docs) + sorted((ROOT / "dashboard").glob("*.py"))


def broken(source: Path) -> list[str]:
    problems = []
    for target in LINK.findall(source.read_text()):
        if target.startswith(REPO):
            file, _, anchor = target.removeprefix(REPO).partition("#")
            path = ROOT / file
        elif target.startswith(("http", "mailto:", "/")) or source.suffix == ".py":
            continue  # other sites, and the dashboard's own page paths
        else:
            file, _, anchor = target.partition("#")
            path = (source.parent / file).resolve() if file else source
        if not path.exists():
            problems.append(f"{target}: no such file")
        elif anchor and path.suffix == ".md" and anchor not in anchors(path):
            problems.append(f"{target}: no such heading")
    return problems


def test_slug_matches_github():
    assert slug("4.2 How places inside an LDZ are weighted") == "42-how-places-inside-an-ldz-are-weighted"
    assert slug("C3. Write the shape as `E + Sc · g`") == "c3-write-the-shape-as-e--sc--g"
    assert slug("Against National Gas's day-ahead forecasts") == "against-national-gass-day-ahead-forecasts"


def test_every_link_resolves():
    problems = {str(source.relative_to(ROOT)): found for source in sources() if (found := broken(source))}
    assert problems == {}
