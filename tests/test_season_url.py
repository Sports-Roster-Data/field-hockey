"""The season-specific roster URL fallback.

Modern Sidearm sites serve season rosters at ``/roster/season/<year>`` instead
of ``/roster/<year>``. When the classic URL 404s, the scraper must retry the
``/roster/season/<year>`` form before falling back to the bare ``/roster``.
"""

from fhockey_roster_scraper import StandardScraper


CARD_HTML = """
<html><head><title>Field Hockey 2026</title></head><body>
<div class="roster-card-item">
  <strong class="roster-card-item__jersey-number">#1</strong>
  <h3 class="roster-card-item__title">
    <a class="roster-card-item__title-link" href="/sports/field-hockey/roster/player/jane-doe">Jane Doe</a>
  </h3>
  <div class="roster-card-item__position">M</div>
</div>
</body></html>
"""


class SeasonUrlFetcher:
    """404s the classic /roster/<year> URL, serves a roster at /roster/season/<year>."""

    def __init__(self):
        self.requested = []

    def fetch_many(self, items, wait_selector=None, wait_ms=None, concurrency=None):
        norm = [(i if isinstance(i, tuple) else (i, None)) for i in items]
        out = []
        for url, _ref in norm:
            self.requested.append(url)
            if url.endswith("/roster/season/2026"):
                out.append((200, CARD_HTML))
            else:
                out.append((404, None))
        return out

    def warm(self, *a, **k):
        pass

    def close(self):
        pass


def test_season_url_fallback_recovers_players():
    fetcher = SeasonUrlFetcher()
    scraper = StandardScraper(fetcher=fetcher, scrape_profiles=False)
    teams = [{"ncaa_id": 509, "team": "Northwestern",
              "url": "https://nusports.com/sports/field-hockey"}]

    results = scraper.scrape_rosters(teams, "2026")

    assert results[0].status == "ok"
    assert [p.name for p in results[0].players] == ["Jane Doe"]
    # The classic URL was tried first, then the season-specific URL.
    assert "https://nusports.com/sports/field-hockey/roster/2026" in fetcher.requested
    assert "https://nusports.com/sports/field-hockey/roster/season/2026" in fetcher.requested
