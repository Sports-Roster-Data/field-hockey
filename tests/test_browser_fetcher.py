import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

import pytest

from bs4 import BeautifulSoup
from fhockey_roster_scraper import StandardScraper

playwright = pytest.importorskip("playwright")


ROSTER_HTML = b"""
<html><head><title>2025 Field Hockey Roster</title></head><body>
<ul>
  <li class="sidearm-roster-player">
    <span class="sidearm-roster-player-jersey-number">9</span>
    <h3><a href="/p/kim">Kim Player</a></h3>
    <div class="sidearm-roster-player-custom-fields">
      <span class="sidearm-roster-player-custom-field-label">Pos.</span>
      <span class="sidearm-roster-player-custom-field-value">Defender</span>
    </div>
  </li>
</ul>
</body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(ROSTER_HTML)

    def log_message(self, *args):
        pass


class _SlowHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(0.4)  # simulate a slow page
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(ROSTER_HTML)

    def log_message(self, *args):
        pass


def _serve(handler, threaded=False):
    server_cls = ThreadingHTTPServer if threaded else HTTPServer
    server = server_cls(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


@pytest.fixture()
def local_server():
    server, base = _serve(_Handler)
    yield base
    server.shutdown()


@pytest.fixture()
def slow_server():
    server, base = _serve(_SlowHandler, threaded=True)
    yield base
    server.shutdown()


def _make_browser_fetcher(**kwargs):
    from fhockey_roster_scraper import BrowserFetcher
    params = dict(min_delay=0, max_delay=0, retries=0)
    params.update(kwargs)
    try:
        return BrowserFetcher(**params)
    except Exception as e:
        pytest.skip(f"Chromium not available: {e}")


def test_browser_fetcher_renders_localhost(local_server):
    fetcher = _make_browser_fetcher()
    try:
        status, html = fetcher.fetch(f"{local_server}/roster/2025")
        assert status == 200
        soup = BeautifulSoup(html, "html.parser")
        assert soup.find("li", class_="sidearm-roster-player") is not None
    finally:
        fetcher.close()


def test_browser_fetcher_end_to_end_via_scraper(local_server):
    fetcher = _make_browser_fetcher()
    scraper = StandardScraper(fetcher=fetcher, scrape_profiles=False)
    try:
        result = scraper.scrape_team(
            team_id=1, team_name="Local", base_url=f"{local_server}/sports/field-hockey",
            season="2025",
        )
        assert result.status == "ok"
        assert len(result.players) == 1
        assert result.players[0].name == "Kim Player"
        assert result.players[0].position == "D"
    finally:
        scraper.close()


def test_fetch_many_runs_concurrently(slow_server):
    """6 pages that each take ~0.4s must finish well under the 2.4s serial time."""
    fetcher = _make_browser_fetcher(max_concurrency=6, max_per_host=6)
    try:
        urls = [f"{slow_server}/roster/{i}" for i in range(6)]
        start = time.time()
        results = fetcher.fetch_many(urls, wait_selector=None)
        elapsed = time.time() - start

        assert len(results) == 6
        assert all(status == 200 for status, _ in results)
        assert elapsed < 1.8, f"expected concurrent fetch, took {elapsed:.2f}s"
    finally:
        fetcher.close()


def test_per_host_cap_limits_concurrency(slow_server):
    """With per-host cap of 1, 3 slow same-host pages run serially (~1.2s+)."""
    fetcher = _make_browser_fetcher(max_concurrency=6, max_per_host=1)
    try:
        urls = [f"{slow_server}/roster/{i}" for i in range(3)]
        start = time.time()
        results = fetcher.fetch_many(urls, wait_selector=None)
        elapsed = time.time() - start
        assert len(results) == 3
        assert elapsed >= 1.0, f"per-host cap not enforced, took {elapsed:.2f}s"
    finally:
        fetcher.close()
