import shutil
import subprocess

import pytest

from ldz_demand.config import get_project_root

ROOT = get_project_root()


def test_every_top_level_folder_has_a_readme():
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("needs the git checkout")
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    folders = {path.split("/")[0] for path in tracked.splitlines() if "/" in path and not path.startswith(".")}
    missing = sorted(f for f in folders if not (ROOT / f / "README.md").exists())
    assert not missing, f"add a short README.md to: {missing}"
