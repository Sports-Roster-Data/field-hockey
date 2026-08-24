import pytest

from fhockey_roster_scraper import FieldExtractors as FE, Player


@pytest.mark.parametrize("text,expected", [
    ("5'7\"", "5'7\""),
    ("6-2", "6-2"),
    ("1.88m", "1.88m"),
    ("Height: 5-9", "5-9"),
    ("", ""),
    ("no height here", ""),
    ("2024-25", ""),  # season range must not be read as a height
])
def test_extract_height(text, expected):
    assert FE.extract_height(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("#12", "12"),
    ("No. 7", "7"),
    ("Jersey Number: 23", "23"),
    ("  5  ", "5"),
    ("", ""),
])
def test_extract_jersey_number(text, expected):
    assert FE.extract_jersey_number(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("GK", "GK"), ("Goalkeeper", "GK"), ("Goalie", "GK"),
    ("D", "D"), ("Defender", "D"), ("Back", "D"),
    ("M", "M"), ("Midfielder", "M"),
    ("F", "F"), ("Forward", "F"), ("Attack", "F"),
    ("", ""),
])
def test_extract_position(text, expected):
    assert FE.extract_position(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Fr.", "Freshman"),
    ("JR", "Junior"),
    ("Sr", "Senior"),
    ("Gr.", "Graduate"),
    ("fr.", "Freshman"),        # case-insensitive
    ("Fourth", "Senior"),
    ("R-Jr.", "Redshirt Junior"),
    ("Unknown", "Unknown"),     # unmapped passes through
])
def test_normalize_academic_year(text, expected):
    assert FE.normalize_academic_year(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Doylestown, Pa. / Central Bucks East", ("Doylestown, Pa.", "Central Bucks East")),
    ("Reading, England (Rugby School)", ("Reading, England", "Rugby School")),
    ("Chester, Pa.", ("Chester, Pa.", "")),
    ("", ("", "")),
])
def test_extract_hometown_parts(text, expected):
    assert FE.extract_hometown_parts(text) == expected


@pytest.mark.parametrize("label,expected", [
    ("Position", "position"), ("Pos.", "position"),
    ("Height", "height"), ("Ht.", "height"),
    ("Weight", None),                 # must NOT map to height
    ("Wt.", None),
    ("Class", "year"), ("Academic Year", "year"), ("Yr.", "year"), ("Eligibility", "year"),
    ("Major", "major"),
    ("Hometown", "hometown"),
    ("High School", "high_school"), ("HS", "high_school"),
    ("Previous School", "previous_school"), ("Last School", "previous_school"),
    ("Nickname", None),
])
def test_match_bio_label(label, expected):
    assert FE.match_bio_label(label) == expected


def test_apply_bio_field_weight_does_not_leak_into_height():
    p = Player(team_id=1, team="X", season="2025")
    assert FE.apply_bio_field(p, "Weight", "150 lbs") is False
    assert p.height == ""


def test_apply_bio_field_only_fills_empty():
    p = Player(team_id=1, team="X", season="2025", position="GK")
    assert FE.apply_bio_field(p, "Position", "Forward") is False
    assert p.position == "GK"  # not overwritten


def test_apply_bio_field_hometown_splits_high_school():
    p = Player(team_id=1, team="X", season="2025")
    assert FE.apply_bio_field(p, "Hometown", "Media, Pa. / Penncrest") is True
    assert p.hometown == "Media, Pa."
    assert p.high_school == "Penncrest"


def test_apply_bio_field_dict_uses_class_key():
    row = {"position": "", "height": "", "class": "", "hometown": ""}
    assert FE.apply_bio_field(row, "Class", "So.") is True
    assert row["class"] == "Sophomore"


def test_high_school_clears_matching_previous_school():
    p = Player(team_id=1, team="X", season="2026", previous_school="Palmyra")
    assert FE.apply_bio_field(p, "High School", " palmyra ") is True
    assert p.high_school == "palmyra"
    assert p.previous_school == ""


def test_previous_school_is_not_added_when_it_duplicates_high_school():
    p = Player(team_id=1, team="X", season="2026", high_school="St. John's School")
    assert FE.apply_bio_field(p, "Previous School", "St Johns School") is False
    assert p.previous_school == ""


def test_dedupe_school_fields_prefers_high_school():
    row = {"high_school": "Erasmiaans Gymnasium", "previous_school": "ERASMIAANS GYMNASIUM"}
    assert FE.dedupe_school_fields(row) is True
    assert row == {"high_school": "Erasmiaans Gymnasium", "previous_school": ""}


@pytest.mark.parametrize("previous,high_school,remaining_previous", [
    ("Woodgrove HS", "Woodgrove HS", ""),
    ("Leigh High School", "Leigh High School", ""),
    ("Tabor Academy", "Tabor Academy", ""),
    ("Twin Valley HS / Liberty", "Twin Valley HS", "Liberty"),
    ("Duchesne Academy (UC Davis)", "Duchesne Academy", "UC Davis"),
])
def test_reclassify_explicit_high_school_from_previous(
        previous, high_school, remaining_previous):
    row = {"high_school": "", "previous_school": previous}
    assert FE.reclassify_high_school_from_previous(row) is True
    assert row["high_school"] == high_school
    assert row["previous_school"] == remaining_previous


@pytest.mark.parametrize("previous", [
    "University of Maryland", "Rider University", "Palmyra", "Boston College",
])
def test_reclassify_leaves_ambiguous_or_college_values(previous):
    row = {"high_school": "", "previous_school": previous}
    assert FE.reclassify_high_school_from_previous(row) is False
    assert row == {"high_school": "", "previous_school": previous}
