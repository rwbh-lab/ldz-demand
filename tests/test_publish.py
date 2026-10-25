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
