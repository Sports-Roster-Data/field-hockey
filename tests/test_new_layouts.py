"""Tests for the modern (Vue / s-* design-system) Sidearm roster layouts.

These layouts replaced the classic ``li.sidearm-roster-player`` markup on many
team sites and previously parsed to zero players. Fixtures below are trimmed but
faithful copies of the real markup captured from live pages.
"""

from bs4 import BeautifulSoup

from fhockey_roster_scraper import StandardScraper


class DummyFetcher:
    def warm(self, *a, **k):
        pass

    def fetch(self, *a, **k):
        raise AssertionError("fetch should not be called in parser tests")

    def fetch_many(self, *a, **k):
        raise AssertionError("fetch_many should not be called in parser tests")

    def close(self):
        pass


def make_scraper():
    return StandardScraper(fetcher=DummyFetcher(), scrape_profiles=False)


def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    return make_scraper()._extract_players(
        soup, 1, "Test", "2026", "", "https://example.com/sports/field-hockey"
    )


# ---------------------------------------------------------------------------
# List layout (e.g. Northwestern): li.roster-list-item
# ---------------------------------------------------------------------------

LIST_ROSTER = """
<html><head><title>2026 Field Hockey Roster</title></head><body>
<ul class="roster-list">
  <li class="roster-list-item">
    <strong class="roster-list-item__jersey-number">1</strong>
    <div class="roster-list-item__info">
      <h3 class="roster-list-item__title-wrapper">
        <a class="roster-list-item__title" href="/sports/field-hockey/roster/player/lindsey-brown">Lindsey Brown</a>
      </h3>
      <div class="roster-list-item__profile-fields-wrapper">
        <div class="roster-list-item__profile-fields">
          <strong class="roster-player-list-profile-field roster-player-list-profile-field--class-level">Sophomore</strong>
        </div>
        <div class="roster-list-item__profile-fields">
          <strong class="roster-player-list-profile-field roster-player-list-profile-field--position">M</strong>
          <span class="roster-player-list-profile-field roster-player-list-profile-field--hometown">Boylston, Massachusetts</span>
        </div>
      </div>
    </div>
  </li>
</ul>
</body></html>
"""


def test_list_layout_excludes_staff_without_jersey():
    html = LIST_ROSTER.replace("</ul>", """
      <li class="roster-list-item">
        <div class="roster-list-item__info">
          <h3 class="roster-list-item__title-wrapper">
            <a class="roster-list-item__title" href="/p/coach">Coach Person</a>
          </h3>
        </div>
      </li>
    </ul>""")
    players = parse(html)
    assert [p.name for p in players] == ["Lindsey Brown"]


def test_list_layout_extraction():
    players = parse(LIST_ROSTER)
    assert len(players) == 1
    p = players[0]
    assert p.name == "Lindsey Brown"
    assert p.jersey == "1"
    assert p.position == "M"
    assert p.year == "Sophomore"
    assert p.hometown == "Boylston, Massachusetts"
    assert p.url == "https://example.com/sports/field-hockey/roster/player/lindsey-brown"


# ---------------------------------------------------------------------------
# Card layout (e.g. Penn St., Stanford, Old Dominion, Virginia): .roster-card-item
# ---------------------------------------------------------------------------

CARD_ROSTER = """
<html><head><title>Field Hockey 2026</title></head><body>
<div class="roster-cards">
  <div class="roster-card-item">
    <div class="roster-card-item__thumb">
      <strong class="roster-card-jersey-number roster-card-item__jersey-number">#1</strong>
    </div>
    <div class="roster-card-item__info">
      <div class="roster-card-item__heading">
        <h3 class="roster-card-item__title">
          <a class="roster-card-item__title-link" href="/sports/field-hockey/roster/player/natalie-freeman">Natalie Freeman</a>
        </h3>
        <div class="roster-card-item__position">M/F</div>
      </div>
      <div class="roster-players-cards-item__profile-fields-wrapper">
        <div class="roster-players-cards-item__profile-fields">
          <span class="profile-field-content">
            <strong class="profile-field-content__title">Class</strong>
            <span class="profile-field-content__value">Senior</span>
          </span>
        </div>
        <div class="roster-players-cards-item__profile-fields">
          <span class="profile-field-content">
            <strong class="profile-field-content__title">Hometown</strong>
            <span class="profile-field-content__value">Ellicott City, Md.</span>
          </span>
          <span class="profile-field-content">
            <strong class="profile-field-content__title">High School</strong>
            <span class="profile-field-content__value">Garrison Forest School</span>
          </span>
        </div>
      </div>
    </div>
  </div>
</div>
</body></html>
"""


def test_card_layout_extraction():
    players = parse(CARD_ROSTER)
    assert len(players) == 1
    p = players[0]
    assert p.name == "Natalie Freeman"
    assert p.jersey == "1"
    assert p.position == "M/F"
    assert p.year == "Senior"
    assert p.hometown == "Ellicott City, Md."
    assert p.high_school == "Garrison Forest School"
    assert p.url == "https://example.com/sports/field-hockey/roster/player/natalie-freeman"


# ---------------------------------------------------------------------------
# Card layout, "roster-player-card-profile-field" variant (e.g. Stanford).
# Name link uses the `--link` modifier, some values are unlabeled and ordered
# (height, then class), the rest are labeled.
# ---------------------------------------------------------------------------

CARD_ROSTER_STANFORD = """
<html><head><title>Field Hockey 2026</title></head><body>
<div class="roster-card-item">
  <div class="roster-card-item__body">
    <strong class="roster-card-item__jersey-number">1</strong>
    <div class="roster-card-item__content">
      <strong class="roster-card-item__position">GK</strong>
      <a class="roster-card-item__title roster-card-item__title--link" href="/sports/field-hockey/roster/player/anya-jackson">Anya Jackson</a>
      <div class="roster-players-cards-item__profile-fields-wrapper">
        <div class="roster-players-cards-item__profile-fields roster-players-cards-item__profile-fields--basic">
          <div class="roster-player-card-profile-field">
            <span class="roster-player-card-profile-field__value roster-player-card-profile-field__value--basic">5&#8242;5&#8243;</span>
            <span class="roster-player-card-profile-field__value roster-player-card-profile-field__value--basic">Junior</span>
          </div>
        </div>
        <div class="roster-players-cards-item__profile-fields roster-players-cards-item__profile-fields--additional">
          <div class="roster-player-card-profile-field">
            <strong class="roster-player-card-profile-field__label">Hometown</strong>
            <span class="roster-player-card-profile-field__value roster-player-card-profile-field__value--hometown">Lytham St Annes, England</span>
          </div>
          <div class="roster-player-card-profile-field">
            <strong class="roster-player-card-profile-field__label">High School</strong>
            <span class="roster-player-card-profile-field__value roster-player-card-profile-field__value--school">Kirkham Grammar School</span>
          </div>
          <div class="roster-player-card-profile-field">
            <strong class="roster-player-card-profile-field__label">Major</strong>
            <span class="roster-player-card-profile-field__value roster-player-card-profile-field__value--major">Undeclared</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</body></html>
"""


def test_card_layout_stanford_variant():
    players = parse(CARD_ROSTER_STANFORD)
    assert len(players) == 1
    p = players[0]
    assert p.name == "Anya Jackson"
    assert p.jersey == "1"
    assert p.position == "GK"
    assert p.height == "5′5″"
    assert p.year == "Junior"
    assert p.hometown == "Lytham St Annes, England"
    assert p.high_school == "Kirkham Grammar School"
    assert p.major == "Undeclared"
    assert p.url == "https://example.com/sports/field-hockey/roster/player/anya-jackson"


# Card layout, unlabeled "Nth Year" academic year and full-word position
# (e.g. Virginia): position "Back" normalizes to "D", "4th Year" to "Senior".

CARD_ROSTER_VIRGINIA = """
<html><head><title>Field Hockey 2026-27</title></head><body>
<div class="roster-card-item">
  <strong class="roster-card-item__jersey-number">#1</strong>
  <h3 class="roster-card-item__title">
    <a class="roster-card-item__title-link" href="/sports/fhockey/roster/player/ria-chhina">Ria Chhina</a>
  </h3>
  <div class="roster-card-item__position">Back</div>
  <div class="roster-players-cards-item__profile-fields-wrapper">
    <div class="roster-players-cards-item__profile-fields roster-players-cards-item__profile-fields--basic">
      <div class="roster-player-card-profile-field">
        <span class="roster-player-card-profile-field__value roster-player-card-profile-field__value--basic">5&#8242;5&#8243;</span>
        <span class="roster-player-card-profile-field__value roster-player-card-profile-field__value--basic">4th Year</span>
      </div>
    </div>
    <div class="roster-players-cards-item__profile-fields roster-players-cards-item__profile-fields--additional">
      <div class="roster-player-card-profile-field">
        <strong class="roster-player-card-profile-field__label">Hometown</strong>
        <span class="roster-player-card-profile-field__value roster-player-card-profile-field__value--hometown">Chantilly, Va.</span>
      </div>
      <div class="roster-player-card-profile-field">
        <strong class="roster-player-card-profile-field__label">High School</strong>
        <span class="roster-player-card-profile-field__value roster-player-card-profile-field__value--school">Riverside High</span>
      </div>
    </div>
  </div>
</div>
</body></html>
"""


def test_card_layout_virginia_variant():
    players = parse(CARD_ROSTER_VIRGINIA)
    assert len(players) == 1
    p = players[0]
    assert p.name == "Ria Chhina"
    assert p.jersey == "1"
    assert p.position == "D"          # "Back" normalizes to D
    assert p.year == "Senior"         # "4th Year" normalizes to Senior
    assert p.height == "5′5″"
    assert p.hometown == "Chantilly, Va."
    assert p.high_school == "Riverside High"


# Card layout, "roster-card-component" variant (e.g. Old Dominion): jersey in
# __number, all bio fields unlabeled inside profile-box groups
# (box 1: position, class; box 2: hometown, high school).

CARD_ROSTER_ODU = """
<html><head><title>Field Hockey 2026</title></head><body>
<div class="roster-card-item roster-card-component">
  <strong class="roster-card-item__number">#2</strong>
  <div class="roster-card-item__body">
    <h3 class="roster-card-item__title">
      <a class="roster-card-item__title-link" href="/sports/field-hockey/roster/player/anna-riesser">Anna Riesser</a>
    </h3>
    <div class="roster-card-component__profile-fields">
      <div class="roster-card-component__profile-box">
        <strong>Defender</strong>
        <span>First Year</span>
      </div>
      <div class="roster-card-component__profile-box">
        <span>Midlothian, Va.</span>
        <span>Trinity Episcopal School</span>
      </div>
    </div>
  </div>
</div>
<div class="roster-card-item roster-card-component">
  <div class="roster-card-item__body">
    <h3 class="roster-card-item__title">
      <a class="roster-card-item__title-link" href="/sports/field-hockey/roster/coaches/head-coach/9">Head Coach</a>
    </h3>
    <div class="roster-card-component__profile-box"><span>Head Coach</span></div>
  </div>
</div>
</body></html>
"""


def test_card_layout_odu_variant():
    # The staff card (no jersey number) is excluded.
    players = parse(CARD_ROSTER_ODU)
    assert len(players) == 1
    p = players[0]
    assert p.name == "Anna Riesser"
    assert p.jersey == "2"
    assert p.position == "D"          # "Defender" normalizes to D
    assert p.year == "Freshman"       # "First Year" normalizes to Freshman
    assert p.hometown == "Midlothian, Va."
    assert p.high_school == "Trinity Episcopal School"


def test_card_layout_excludes_staff_without_jersey():
    """Staff share the roster-card-item class but carry no jersey number."""
    html = """
    <html><body>
    <div class="roster-card-item">
      <strong class="roster-card-item__jersey-number">#5</strong>
      <h3 class="roster-card-item__title">
        <a class="roster-card-item__title-link" href="/p/player">Real Player</a>
      </h3>
      <div class="roster-card-item__position">M</div>
    </div>
    <div class="roster-card-item">
      <h3 class="roster-card-item__title">
        <a class="roster-card-item__title-link" href="/p/coach">Some Coach</a>
      </h3>
      <div class="roster-card-item__position">Head Coach</div>
    </div>
    </body></html>
    """
    players = parse(html)
    assert [p.name for p in players] == ["Real Player"]


# ---------------------------------------------------------------------------
# s-person-card layout (e.g. James Madison): .c-rosterpage__players .s-person-card
# Each bio field is a leaf span carrying an .sr-only label; hometown, last
# school and major share one container, so fields must be read per-leaf.
# ---------------------------------------------------------------------------

PERSON_CARD_ROSTER = """
<html><head><title>2026 Field Hockey Roster</title></head><body>
<div class="c-rosterpage__players">
  <div class="s-person-card s-person-card--list">
    <div class="s-person-thumbnail">
      <span class="s-stamp__text"><span class="sr-only">Jersey Number</span>1</span>
    </div>
    <div class="s-person-details__detail-wrapper">
      <div class="s-person-details__personal-single-line">
        <a href="/sports/field-hockey/roster/ava-drexleramey/24414"><h3>Ava Drexler-Amey</h3></a>
      </div>
      <div class="s-person-details__bio-stats">
        <span class="s-person-details__bio-stats-item"><span class="sr-only">Position</span>M</span>
        <span class="s-person-details__bio-stats-item"><span class="sr-only">Academic Year</span>Sr.</span>
        <span class="s-person-details__bio-stats-item"><span class="sr-only">Height</span>5' 3''</span>
      </div>
      <div class="s-person-card__content__location s-text-details">
        <span class="s-person-card__content__person__location-item"><span class="sr-only">Hometown</span>Severna Park, Md.</span>
        <span class="s-person-card__content__person__high-school-item"><span class="sr-only">Last School</span>Severna Park</span>
        <span class="s-person-card__content__person__person-mayor-item"><span class="sr-only">Major</span>Sociology</span>
      </div>
    </div>
  </div>
  <div class="s-person-card s-person-card--list">
    <div class="s-person-details__detail-wrapper">
      <div class="s-person-details__personal-single-line">
        <a href="/sports/field-hockey/roster/coaches/jane-coach/99"><h3>Jane Coach</h3></a>
      </div>
      <div class="s-person-details__bio-stats">
        <span class="s-person-details__bio-stats-item"><span class="sr-only">Title</span>Head Coach</span>
      </div>
    </div>
  </div>
</div>
</body></html>
"""


def test_person_card_layout_extraction():
    # The coach card (no jersey number) must be excluded; only the player remains.
    players = parse(PERSON_CARD_ROSTER)
    assert len(players) == 1
    p = players[0]
    assert p.name == "Ava Drexler-Amey"
    assert p.jersey == "1"
    assert p.position == "M"
    assert p.year == "Senior"
    assert p.height == "5' 3''"
    assert p.hometown == "Severna Park, Md."
    assert p.previous_school == "Severna Park"
    assert p.major == "Sociology"
    assert p.url == "https://example.com/sports/field-hockey/roster/ava-drexleramey/24414"
