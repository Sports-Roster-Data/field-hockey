#!/usr/bin/env python3
"""Backfill roster detail fields from the profile URLs already in team caches.

This intentionally does not re-fetch roster pages.  It updates the existing
per-team cache files in small, resumable batches, then rebuilds the aggregate
JSON and CSV from those cache files.
"""

import argparse
import csv
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from bs4 import BeautifulSoup

from fhockey_roster_scraper import (
    PROFILE_WAIT_SELECTOR,
    REPO_ROOT,
    build_fetcher,
    parse_player_profile,
)


logger = logging.getLogger(__name__)
TARGET_FIELDS = ("hometown", "high_school", "previous_school")
FINAL_STATES = {"updated", "no_values", "not_needed"}


def atomic_json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
    temp_path.replace(path)


def field_counts(players: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    players = list(players)
    return {
        field: sum(not (player.get(field) or "").strip() for player in players)
        for field in TARGET_FIELDS
    }


def needs_backfill(player: Dict[str, Any]) -> bool:
    return bool((player.get("url") or "").strip()) and any(
        not (player.get(field) or "").strip() for field in TARGET_FIELDS
    )


class ProfileBackfiller:
    def __init__(self, raw_dir: Path, season: str, fetch_mode: str = "auto",
                 concurrency: int = 6, per_host: int = 3,
                 delay_min: float = 0.3, delay_max: float = 0.8):
        self.raw_dir = raw_dir
        self.season = str(season)
        self.fetcher = build_fetcher(
            fetch_mode, max_concurrency=concurrency, max_per_host=per_host,
            min_delay=delay_min, max_delay=delay_max,
        )
        self.report_path = raw_dir / "reports" / f"profile_enrichment_fhockey_{season}.json"

    def close(self) -> None:
        self.fetcher.close()

    def _cache_paths(self) -> List[Path]:
        return sorted((self.raw_dir / "teams").glob(f"*_{self.season}.json"))

    def _load_caches(self) -> List[Tuple[Path, Dict[str, Any]]]:
        caches = []
        for path in self._cache_paths():
            with open(path, encoding="utf-8") as handle:
                cache = json.load(handle)
            if cache.get("status") == "ok":
                caches.append((path, cache))
        return caches

    @staticmethod
    def _player_key(cache: Dict[str, Any], index: int) -> str:
        return f"{cache.get('ncaa_id')}:{index}"

    def _load_previous_report(self) -> Dict[str, Any]:
        if not self.report_path.exists():
            return {}
        try:
            with open(self.report_path, encoding="utf-8") as handle:
                report = json.load(handle)
            if str(report.get("season")) == self.season:
                return report
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("Ignoring unreadable prior profile report: %s", error)
        return {}

    def _write_report(self, baseline: Dict[str, int], caches: List[Tuple[Path, Dict[str, Any]]],
                      results: Dict[str, Dict[str, Any]]) -> None:
        players = [player for _, cache in caches for player in cache.get("players", [])]
        statuses = Counter(result["status"] for result in results.values())
        report = {
            "season": self.season,
            "target_fields": list(TARGET_FIELDS),
            "player_count": len(players),
            "before_missing": baseline,
            "after_missing": field_counts(players),
            "summary": {
                "attempted": sum(statuses[state] for state in ("updated", "no_values", "failed")),
                "updated": statuses["updated"],
                "no_values": statuses["no_values"],
                "failed": statuses["failed"],
                "not_needed": statuses["not_needed"],
                "pending": statuses["pending"],
            },
            "player_results": results,
        }
        atomic_json_dump(self.report_path, report)

    def _rebuild_aggregates(self, caches: List[Tuple[Path, Dict[str, Any]]]) -> None:
        players = [player for _, cache in caches for player in cache.get("players", [])]
        atomic_json_dump(self.raw_dir / "json" / f"rosters_fhockey_{self.season}.json", players)

        csv_path = self.raw_dir / "csv" / f"rosters_fhockey_{self.season}.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = csv_path.with_suffix(csv_path.suffix + ".tmp")
        fieldnames: List[str] = []
        for player in players:
            for field in player:
                if field not in fieldnames:
                    fieldnames.append(field)
        with open(temp_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(players)
        temp_path.replace(csv_path)

    def run(self, batch_size: int = 50, retry_all: bool = False,
            max_profiles: int = None, retry_no_values: bool = False,
            retry_field: str = None) -> Dict[str, Any]:
        caches = self._load_caches()
        if not caches:
            raise RuntimeError(f"No successful {self.season} team caches found in {self.raw_dir / 'teams'}")

        players = [player for _, cache in caches for player in cache.get("players", [])]
        prior_report = self._load_previous_report()
        prior_results = prior_report.get("player_results", {})
        baseline = prior_report.get("before_missing") or field_counts(players)
        results: Dict[str, Dict[str, Any]] = {}
        targets = []

        for cache_index, (_, cache) in enumerate(caches):
            for player_index, player in enumerate(cache.get("players", [])):
                key = self._player_key(cache, player_index)
                prior = prior_results.get(key, {})
                record = {
                    "team": cache.get("team", ""),
                    "ncaa_id": cache.get("ncaa_id"),
                    "name": player.get("name", ""),
                    "url": player.get("url", ""),
                    "status": prior.get("status", "pending"),
                }
                results[key] = record
                if not needs_backfill(player):
                    record["status"] = "not_needed"
                elif prior.get("status") == "not_needed":
                    # Reports written by an interrupted older run used
                    # "not_needed" as a placeholder for unvisited players.
                    # A still-incomplete row is therefore pending, not final.
                    record["status"] = "pending"
                    targets.append((cache_index, player_index, key))
                elif retry_field:
                    if not (player.get(retry_field) or '').strip():
                        targets.append((cache_index, player_index, key))
                elif retry_no_values:
                    if prior.get("status") == "no_values":
                        targets.append((cache_index, player_index, key))
                elif retry_all or prior.get("status") not in FINAL_STATES:
                    targets.append((cache_index, player_index, key))

        if max_profiles is not None:
            targets = targets[:max(0, max_profiles)]
        logger.info("Profile backfill: %d player(s), %d URL(s) to fetch", len(players), len(targets))
        for start in range(0, len(targets), max(1, batch_size)):
            batch = targets[start:start + max(1, batch_size)]
            items = []
            for cache_index, player_index, _ in batch:
                player = caches[cache_index][1]["players"][player_index]
                url = player["url"].strip()
                referer = url.split("/sports")[0] if "/sports" in url else None
                items.append((url, referer))
            # The page is already loaded at DOMContentLoaded; a short wait is
            # enough for known bio widgets while avoiding a 2.5s timeout for
            # sites that simply do not expose one of those selectors.
            fetched = self.fetcher.fetch_many(
                items, wait_selector=PROFILE_WAIT_SELECTOR, wait_ms=500
            )
            changed_caches = set()
            for (cache_index, player_index, key), (status, html) in zip(batch, fetched):
                player = caches[cache_index][1]["players"][player_index]
                record = results[key]
                before = {field: player.get(field, "") for field in TARGET_FIELDS}
                if status == 200 and html:
                    try:
                        parse_audit: Dict[str, Any] = {}
                        parse_player_profile(
                            BeautifulSoup(html, "html.parser"), player, audit=parse_audit
                        )
                        after = {field: player.get(field, "") for field in TARGET_FIELDS}
                        record["status"] = "updated" if after != before else "no_values"
                        record["filled_fields"] = [
                            field for field in TARGET_FIELDS if not before[field] and after[field]
                        ]
                        if parse_audit.get("low_confidence_fields"):
                            record["low_confidence_fields"] = parse_audit["low_confidence_fields"]
                        changed_caches.add(cache_index)
                    except Exception as error:
                        record["status"] = "failed"
                        record["detail"] = f"parse error: {error}"
                else:
                    record["status"] = "failed"
                    record["detail"] = f"HTTP {status}"

            for cache_index in changed_caches:
                path, cache = caches[cache_index]
                atomic_json_dump(path, cache)
            self._write_report(baseline, caches, results)

        self._rebuild_aggregates(caches)
        self._write_report(baseline, caches, results)
        with open(self.report_path, encoding="utf-8") as handle:
            return json.load(handle)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill cached roster profiles without re-scraping rosters")
    parser.add_argument("--season", required=True, help="Roster season to backfill")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "data" / "raw"),
                        help="Raw data directory containing teams/, json/, csv/, and reports/")
    parser.add_argument("--fetch", choices=("auto", "browser", "requests"), default="auto")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--per-host", type=int, default=3)
    parser.add_argument("--delay-min", type=float, default=0.3)
    parser.add_argument("--delay-max", type=float, default=0.8)
    parser.add_argument("--batch-size", type=int, default=50,
                        help="Profiles per checkpointed batch (default: 50)")
    parser.add_argument("--retry-all", action="store_true",
                        help="Revisit profiles already recorded as updated or no-values")
    parser.add_argument("--retry-no-values", action="store_true",
                        help="Revisit only profiles previously fetched with no parsed target details")
    parser.add_argument("--retry-field", choices=TARGET_FIELDS,
                        help="Revisit every profile still missing this specific target field")
    parser.add_argument("--max-profiles", type=int,
                        help="Process at most this many profiles, then checkpoint and exit")
    args = parser.parse_args()

    backfiller = ProfileBackfiller(
        Path(args.output_dir), args.season, args.fetch, args.concurrency, args.per_host,
        args.delay_min, args.delay_max,
    )
    try:
        report = backfiller.run(
            args.batch_size, args.retry_all, args.max_profiles, args.retry_no_values,
            args.retry_field,
        )
    finally:
        backfiller.close()
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
