from bs4 import BeautifulSoup

from fhockey_roster_scraper import StandardScraper, parse_player_profile, Player


class DummyFetcher:
    """No-op fetcher so parser tests never launch a browser or hit the network."""
    def warm(self, *a, **k):
        pass

    def fetch(self, *a, **k):
        raise AssertionError("fetch should not be called in parser tests")

    def close(self):
        pass


def make_scraper():
    return StandardScraper(fetcher=DummyFetcher(), scrape_profiles=False)


CARD_ROSTER = """
<html><head><title>2025 Field Hockey Roster</title></head><body>
<ul>
  <li class="sidearm-roster-player">
    <span class="sidearm-roster-player-jersey-number">7</span>
    <h3><a href="/sports/field-hockey/roster/jane-doe/1">Jane Doe</a></h3>
    <div class="sidearm-roster-player-custom-fields">
      <span class="sidearm-roster-player-custom-field-label">Pos.</span>
      <span class="sidearm-roster-player-custom-field-value">Midfielder</span>
    </div>
    <div class="sidearm-roster-player-custom-fields">
      <span class="sidearm-roster-player-custom-field-label">Cl.</span>
      <span class="sidearm-roster-player-custom-field-value">Jr.</span>
    </div>
    <div class="sidearm-roster-player-custom-fields">
      <span class="sidearm-roster-player-custom-field-label">Hometown</span>
      <span class="sidearm-roster-player-custom-field-value">Media, Pa. / Penncrest</span>
    </div>
  </li>
  <li class="sidearm-roster-player">
    <span class="sidearm-roster-player-jersey-number">12</span>
    <h3><a href="https://example.com/p/2">Amy Smith</a></h3>
    <div class="sidearm-roster-player-custom-fields">
      <span class="sidearm-roster-player-custom-field-label">Pos.</span>
      <span class="sidearm-roster-player-custom-field-value">Goalkeeper</span>
    </div>
  </li>
</ul>
</body></html>
"""


def test_card_roster_extraction():
    html = BeautifulSoup(CARD_ROSTER, 'html.parser')
    scraper = make_scraper()
    players = scraper._extract_players(html, 1, "Test", "2025", "", "https://example.com/sports/field-hockey")

    assert len(players) == 2
    jane = players[0]
    assert jane.name == "Jane Doe"
    assert jane.jersey == "7"
    assert jane.position == "M"
    assert jane.year == "Junior"
    assert jane.hometown == "Media, Pa."
    assert jane.high_school == "Penncrest"
    assert jane.url == "https://example.com/sports/field-hockey/roster/jane-doe/1"

    amy = players[1]
    assert amy.name == "Amy Smith"
    assert amy.position == "GK"
    assert amy.url == "https://example.com/p/2"


TABLE_ROSTER = """
<html><head><title>2025 Roster</title></head><body>
<table class="sidearm-table">
  <thead>
    <tr><th>#</th><th>Name</th><th>Pos.</th><th>Cl.</th><th>Ht.</th><th>Hometown</th></tr>
  </thead>
  <tbody>
    <tr><td>1</td><td><a href="/p/first">First Player</a></td><td>F</td><td>Sr.</td><td>5-6</td><td>Boston, Mass.</td></tr>
    <tr><td>2</td><td>Second Player</td><td>D</td><td>Fr.</td><td>5-9</td><td>Miami, Fla.</td></tr>
  </tbody>
</table>
</body></html>
"""


def test_table_roster_keeps_first_player():
    """Regression: the first player in a thead/tbody table must not be dropped."""
    html = BeautifulSoup(TABLE_ROSTER, 'html.parser')
    scraper = make_scraper()
    players = scraper._extract_players(html, 1, "Test", "2025", "", "https://example.com/sports/field-hockey")

    assert len(players) == 2
    assert players[0].name == "First Player"
    assert players[0].position == "F"
    assert players[0].year == "Senior"
    assert players[0].height == "5-6"
    assert players[1].name == "Second Player"


PROFILE_PAGE = """
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
    <span class="sidearm-roster-player-bio-label">Weight</span>
    <span class="sidearm-roster-player-bio-value">140 lbs</span>
  </div>
  <div class="sidearm-roster-player-bio-item">
    <span class="sidearm-roster-player-bio-label">Major</span>
    <span class="sidearm-roster-player-bio-value">Biology</span>
  </div>
</div>
</body></html>
"""


def test_profile_parsing_and_weight_not_height():
    html = BeautifulSoup(PROFILE_PAGE, 'html.parser')
    p = Player(team_id=1, team="X", season="2025")
    changed = parse_player_profile(html, p)
    assert changed is True
    assert p.position == "F"
    assert p.height == "5-8"      # from Height, not Weight
    assert p.major == "Biology"


def test_profile_parsing_compact_sidearm_fields():
    html = BeautifulSoup("""
    <div class="flex-item-1"><span class="sidearm-roster-player-field-label">Hometown</span><span>Downingtown, Pa.</span></div>
    <div class="flex-item-1"><span class="sidearm-roster-player-field-label">High School</span><span>Downingtown West</span></div>
    <div class="flex-item-1"><span class="sidearm-roster-player-field-label">Previous School</span><span>Example College</span></div>
    """, 'html.parser')
    p = Player(team_id=1, team="X", season="2026")
    assert parse_player_profile(html, p) is True
    assert p.hometown == "Downingtown, Pa."
    assert p.high_school == "Downingtown West"
    assert p.previous_school == "Example College"


def test_profile_parsing_generic_definition_lists():
    html = BeautifulSoup("""
    <dl class="s-text-regular">
      <dt data-test-id="roster-bio-player-fields-component__ranked-field-label-value">High School:</dt>
      <dd data-test-id="roster-bio-player-fields-component__ranked-field-label-value">Palmyra</dd>
    </dl>
    <dl><dt>Previous School:</dt><dd>Example University</dd></dl>
    """, 'html.parser')
    p = Player(team_id=1, team="X", season="2026")
    assert parse_player_profile(html, p) is True
    assert p.high_school == "Palmyra"
    assert p.previous_school == "Example University"


def test_profile_biography_high_school_candidate_is_audited():
    html = BeautifulSoup("""
    <div class="sidearm_prose"><strong>High School:</strong>
      Won a county championship with Downingtown West … named First Team All-League.
    </div>
    """, 'html.parser')
    p = Player(team_id=1, team="X", season="2026")
    audit = {}
    assert parse_player_profile(html, p, audit=audit) is True
    assert p.high_school == "Downingtown West"
    assert audit["low_confidence_fields"]["high_school"]["source"] == "profile_biography"


def test_profile_biography_does_not_override_structured_high_school():
    html = BeautifulSoup("""
    <dl><dt>High School:</dt><dd>Official Academy</dd></dl>
    <div><strong>High School:</strong> Won a title with Another School …</div>
    """, 'html.parser')
    p = Player(team_id=1, team="X", season="2026")
    audit = {}
    assert parse_player_profile(html, p, audit=audit) is True
    assert p.high_school == "Official Academy"
    assert "low_confidence_fields" not in audit
