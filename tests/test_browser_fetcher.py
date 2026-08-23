import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

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


@pytest.fixture()
def local_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield f"http://{host}:{port}"
    server.shutdown()


def _make_browser_fetcher():
    from fhockey_roster_scraper import BrowserFetcher
    try:
        return BrowserFetcher(min_delay=0, max_delay=0, retries=0)
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
