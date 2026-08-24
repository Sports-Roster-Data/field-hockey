from fhockey_roster_scraper import StandardScraper, Player, PROFILE_WAIT_SELECTOR


PROFILE_HTML = """
<html><body>
<div class="sidearm-roster-player-bio">
  <div class="sidearm-roster-player-bio-item">
    <span class="sidearm-roster-player-bio-label">Position</span>
    <span class="sidearm-roster-player-bio-value">Forward</span>
  </div>
  <div class="sidearm-roster-player-bio-item">
    <span class="sidearm-roster-player-bio-label">Height</span>
    <span class="sidearm-roster-player-bio-value">5-8</span>
  </div>
  <div class="sidearm-roster-player-bio-item">
    <span class="sidearm-roster-player-bio-label">Class</span>
    <span class="sidearm-roster-player-bio-value">Jr.</span>
  </div>
  <div class="sidearm-roster-player-bio-item">
    <span class="sidearm-roster-player-bio-label">Hometown</span>
    <span class="sidearm-roster-player-bio-value">Media, Pa.</span>
  </div>
</div>
</body></html>
"""


class RecordingFetcher:
    """Records fetch_many calls and returns a fixed profile page for each item."""
    def __init__(self):
        self.fetched_urls = []

    def fetch_many(self, items, wait_selector=None, wait_ms=None, concurrency=None):
        norm = [(i if isinstance(i, tuple) else (i, None)) for i in items]
        self.fetched_urls.extend(u for u, _ in norm)
        return [(200, PROFILE_HTML) for _ in norm]

    def fetch(self, *a, **k):
        raise AssertionError("enrich_profiles should use fetch_many")

    def warm(self, *a, **k):
        pass

    def close(self):
        pass


def complete_player():
    return Player(team_id=1, team="X", season="2025", name="Full",
                  position="D", height="5-6", year="Senior", hometown="Boston, Mass.",
                  high_school="Boston Latin", previous_school="Example College",
                  url="https://example.com/sports/field-hockey/roster/full")


def sparse_player():
    return Player(team_id=1, team="X", season="2025", name="Sparse",
                  url="https://example.com/sports/field-hockey/roster/sparse")


def test_missing_mode_skips_complete_players():
    rec = RecordingFetcher()
    scraper = StandardScraper(fetcher=rec, profiles_mode="missing")
    scraper.enrich_profiles([complete_player()])
    assert rec.fetched_urls == []  # nothing fetched


def test_missing_mode_fetches_sparse_players():
    rec = RecordingFetcher()
    scraper = StandardScraper(fetcher=rec, profiles_mode="missing")
    p = sparse_player()
    scraper.enrich_profiles([p])
    assert len(rec.fetched_urls) == 1
    assert p.position == "F" and p.height == "5-8" and p.year == "Junior"
    assert p.hometown == "Media, Pa."


def test_never_mode_fetches_nothing():
    rec = RecordingFetcher()
    scraper = StandardScraper(fetcher=rec, profiles_mode="never")
    scraper.enrich_profiles([sparse_player(), complete_player()])
    assert rec.fetched_urls == []


def test_always_mode_fetches_even_complete():
    rec = RecordingFetcher()
    scraper = StandardScraper(fetcher=rec, profiles_mode="always")
    scraper.enrich_profiles([complete_player()])
    assert len(rec.fetched_urls) == 1


def test_scrape_profiles_false_maps_to_never():
    rec = RecordingFetcher()
    scraper = StandardScraper(fetcher=rec, scrape_profiles=False)
    assert scraper.profiles_mode == "never"
    scraper.enrich_profiles([sparse_player()])
    assert rec.fetched_urls == []


def test_needs_profile_gate():
    assert StandardScraper._needs_profile(sparse_player()) is True
    assert StandardScraper._needs_profile(complete_player()) is False


def test_missing_mode_fetches_player_missing_only_high_school_or_previous_school():
    rec = RecordingFetcher()
    scraper = StandardScraper(fetcher=rec, profiles_mode="missing")
    player = complete_player()
    player.high_school = ""
    scraper.enrich_profiles([player])
    assert rec.fetched_urls == [player.url]

    rec = RecordingFetcher()
    scraper = StandardScraper(fetcher=rec, profiles_mode="missing")
    player = complete_player()
    player.previous_school = ""
    scraper.enrich_profiles([player])
    assert rec.fetched_urls == [player.url]
