import csv
import json

import backfill_profile_details as backfill


PROFILE_HTML = """
<div class="sidearm-roster-player-bio">
  <div class="sidearm-roster-player-bio-item">
    <span class="sidearm-roster-player-bio-label">Hometown</span>
    <span class="sidearm-roster-player-bio-value">Media, Pa.</span>
  </div>
  <div class="sidearm-roster-player-bio-item">
    <span class="sidearm-roster-player-bio-label">High School</span>
    <span class="sidearm-roster-player-bio-value">Penncrest</span>
  </div>
  <div class="sidearm-roster-player-bio-item">
    <span class="sidearm-roster-player-bio-label">Previous School</span>
    <span class="sidearm-roster-player-bio-value">Example Prep</span>
  </div>
</div>
"""


class RecordingFetcher:
    def __init__(self):
        self.items = []

    def fetch_many(self, items, **_kwargs):
        self.items.extend(items)
        return [(200, PROFILE_HTML) for _ in items]

    def close(self):
        pass


def write_cache(raw_dir):
    cache = {
        "team": "Example", "ncaa_id": 1, "status": "ok", "detail": "", "player_count": 2,
        "players": [
            {"team": "Example", "name": "Missing", "hometown": "", "high_school": "",
             "previous_school": "", "url": "https://example.test/sports/fh/roster/missing"},
            {"team": "Example", "name": "Complete", "hometown": "Boston, Mass.",
             "high_school": "Boston Latin", "previous_school": "Another College",
             "url": "https://example.test/sports/fh/roster/complete"},
        ],
    }
    path = raw_dir / "teams" / "1_2026.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(cache), encoding="utf-8")
    return path


def test_backfill_updates_cache_rebuilds_aggregates_and_resumes(tmp_path, monkeypatch):
    cache_path = write_cache(tmp_path)
    fetcher = RecordingFetcher()
    monkeypatch.setattr(backfill, "build_fetcher", lambda *_args, **_kwargs: fetcher)

    runner = backfill.ProfileBackfiller(tmp_path, "2026")
    report = runner.run(batch_size=1)
    runner.close()

    assert len(fetcher.items) == 1
    updated = json.loads(cache_path.read_text(encoding="utf-8"))["players"][0]
    assert updated["hometown"] == "Media, Pa."
    assert updated["high_school"] == "Penncrest"
    assert updated["previous_school"] == "Example Prep"
    assert report["before_missing"] == {"hometown": 1, "high_school": 1, "previous_school": 1}
    assert report["after_missing"] == {"hometown": 0, "high_school": 0, "previous_school": 0}
    assert report["summary"]["updated"] == 1
    assert report["summary"]["not_needed"] == 1

    with open(tmp_path / "csv" / "rosters_fhockey_2026.csv", newline="", encoding="utf-8") as handle:
        assert list(csv.DictReader(handle))[0]["high_school"] == "Penncrest"
    aggregate = json.loads((tmp_path / "json" / "rosters_fhockey_2026.json").read_text(encoding="utf-8"))
    assert aggregate == json.loads(cache_path.read_text(encoding="utf-8"))["players"]

    second_fetcher = RecordingFetcher()
    monkeypatch.setattr(backfill, "build_fetcher", lambda *_args, **_kwargs: second_fetcher)
    runner = backfill.ProfileBackfiller(tmp_path, "2026")
    resumed = runner.run()
    runner.close()
    assert second_fetcher.items == []
    assert resumed["before_missing"] == report["before_missing"]


def test_backfill_normalizes_duplicate_school_fields_without_fetching(tmp_path, monkeypatch):
    cache_path = write_cache(tmp_path)
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache["players"][1]["previous_school"] = "boston latin"
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    fetcher = RecordingFetcher()
    monkeypatch.setattr(backfill, "build_fetcher", lambda *_args, **_kwargs: fetcher)

    runner = backfill.ProfileBackfiller(tmp_path, "2026")
    report = runner.run(normalize_only=True)
    runner.close()

    normalized = json.loads(cache_path.read_text(encoding="utf-8"))["players"][1]
    assert normalized["high_school"] == "Boston Latin"
    assert normalized["previous_school"] == ""
    assert report["deduplicated_school_fields"] == 1
    assert fetcher.items == []
