import base64
import subprocess
from pathlib import Path

import pytest

from ldz_demand import publish
from ldz_demand.publish import BASE, PRIVATE, relink


def test_relink_pages_and_overview():
    html = r'<a href=\"/backtesting-results\">R</a> <a href="/">O</a>'
    assert relink(html) == rf'<a href=\"{BASE}/backtesting-results/\">R</a> <a href="{BASE}/">O</a>'


def test_relink_leaves_other_links():
    html = '<a href="/somewhere-else">x</a> <a href="https://example.com/results">y</a>'
    assert relink(html) == html


def test_private_paths_and_addresses_caught():
    for text in ["/Users/someone/x", "/Volumes/share/raw", "/volume1/share", "192.168.0.4", "10.1.2.3", "100.82.1.1"]:
        assert PRIVATE.search(text), text


def test_ordinary_text_not_caught():
    for text in [f"{BASE}/backtesting-results/", "version 10.5", "100.5 GWh", "2026-10-20"]:
        assert not PRIVATE.search(text), text


# --- page checks, and pushing from the daily job ------------------------------------------------------

# a callout as marimo's exported HTML carries it (escaped twice), and other kinds
WARN_HTML = "\\u003Cmarimo-callout-output data-html='x' data-kind='\\u0026quot;warn\\u0026quot;'\\u003E"


def test_a_warning_callout_is_caught_and_other_callouts_are_not():
    assert publish.WARN_CALLOUT.search(WARN_HTML)
    for kind in ("info", "neutral", "success"):
        assert not publish.WARN_CALLOUT.search(WARN_HTML.replace("warn", kind)), kind


def test_a_page_showing_a_warning_is_not_published(tmp_path, monkeypatch):
    def marimo(command, **kwargs):
        Path(command[command.index("-o") + 1]).write_text(f"<html>{WARN_HTML}</html>")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(publish.subprocess, "run", marimo)
    target = tmp_path / "page" / "index.html"
    with pytest.raises(RuntimeError, match="shows a warning"):
        publish.export(tmp_path / "page.py", target, {})
    assert not target.exists()


def test_the_token_reaches_git_only_through_its_environment():
    url, env = publish.push_target({publish.TOKEN_ENV: "github_pat_SECRET"})
    assert url == f"https://github.com/{publish.REPO}.git" and "SECRET" not in url
    header = env["GIT_CONFIG_VALUE_0"].removeprefix("AUTHORIZATION: basic ")
    assert base64.b64decode(header).decode() == "x-access-token:github_pat_SECRET"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader" and env["GIT_TERMINAL_PROMPT"] == "0"
    url, _ = publish.push_target({publish.TOKEN_ENV: "t", publish.REPO_ENV: "someone/fork"})
    assert url == "https://github.com/someone/fork.git"


def test_without_a_token_the_checkout_remote_is_used_and_none_is_nothing(monkeypatch):
    monkeypatch.setattr(publish, "_git_out", lambda *args: "https://github.com/x/y.git")
    assert publish.push_target({}) == ("https://github.com/x/y.git", {})
    monkeypatch.setattr(publish, "_git_out", lambda *args: "")  # the Docker image: no checkout
    assert publish.push_target({}) is None


def test_the_author_falls_back_from_the_environment_to_git_to_a_generic_name(monkeypatch):
    monkeypatch.setattr(publish, "_git_out", lambda *args: "")
    assert publish.author({}) == publish.AUTHOR
    assert publish.author({publish.NAME_ENV: "N", publish.EMAIL_ENV: "e@x"}) == ("N", "e@x")


def test_if_configured_does_nothing_where_no_push_target_is_set(monkeypatch):
    monkeypatch.setattr(publish, "push_target", lambda: None)
    monkeypatch.setattr(publish, "build", lambda out: pytest.fail("built without a push target"))
    assert publish.main(["--push", "--if-configured"]) == 0
    assert publish.main(["--push"]) == 1       # asked to push, with nowhere to push to


def test_push_replaces_the_branch_with_one_snapshot_commit(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    monkeypatch.setattr(publish, "author", lambda: ("Job", "job@example.com"))
    site = tmp_path / "site"
    for day in ("1", "2"):  # twice: the second push replaces the first
        site.mkdir(exist_ok=True)
        (site / "index.html").write_text(f"day {day}")
        publish.push(site, f"{day} November 2026", (str(remote), {}))
    git = ["git", "-C", str(remote)]
    log = subprocess.run([*git, "log", "--format=%an <%ae> %s", publish.BRANCH], capture_output=True, text=True).stdout
    assert log.strip().splitlines() == ["Job <job@example.com> Dashboard snapshot, data to 2 November 2026"]
    shown = subprocess.run([*git, "show", f"{publish.BRANCH}:index.html"], capture_output=True, text=True).stdout
    assert shown == "day 2"
