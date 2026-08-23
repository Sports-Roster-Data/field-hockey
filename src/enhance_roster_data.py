#!/usr/bin/env python3
"""
Enhance an existing roster CSV by scraping individual player profile pages
for missing details.

Usage:
    uv run src/enhance_roster_data.py --input rosters_fhockey_2025.csv --output rosters_enhanced.csv
"""

import csv
import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

# Reuse the shared scraper utilities (portable: derive path from this file).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fhockey_roster_scraper import (  # noqa: E402
    parse_player_profile,
    build_fetcher,
    PROFILE_WAIT_SELECTOR,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ProfileEnhancer:
    """Enhance roster data by scraping player profiles concurrently."""

    def __init__(self, fetch_mode: str = 'auto', concurrency: int = 6, per_host: int = 3,
                 delay_min: float = 0.3, delay_max: float = 0.8):
        self.fetcher = build_fetcher(
            fetch_mode, max_concurrency=concurrency, max_per_host=per_host,
            min_delay=delay_min, max_delay=delay_max,
        )

    def close(self):
        self.fetcher.close()

    @staticmethod
    def _needs_enhance(row: Dict, force: bool) -> bool:
        if not (row.get('url') or '').strip():
            return False
        if force:
            return True
        # Skip rows that already have the core fields
        return not any([row.get('position'), row.get('height'),
                        row.get('class'), row.get('hometown')])

    def enhance_csv(self, input_file: str, output_file: str, force: bool = False,
                    team_filter: Optional[str] = None):
        """
        Read a roster CSV, enhance rows from their profile pages concurrently,
        and write the result. The output is written atomically at the end.
        """
        rows: List[Dict] = []
        with open(input_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            input_fieldnames = list(reader.fieldnames or [])
            for row in reader:
                rows.append(row)

        logger.info(f"Loaded {len(rows)} players from {input_file}")

        if team_filter:
            rows = [r for r in rows if (r.get('team', '') or '').lower() == team_filter.lower()]
            logger.info(f"Filtered to {len(rows)} players for team '{team_filter}'")

        # Fields enhancement may add that weren't in the input header
        extra_fields = ['position', 'height', 'class', 'major', 'hometown',
                        'high_school', 'previous_school']
        fieldnames = list(input_fieldnames)
        for k in extra_fields:
            if k not in fieldnames:
                fieldnames.append(k)

        # Select rows to enhance and fetch their profiles concurrently
        targets = [r for r in rows if self._needs_enhance(r, force)]
        logger.info(f"Fetching {len(targets)} profile page(s)")

        enhanced_count = 0
        if targets:
            def referer_for(url):
                url = url.strip()
                return url.split('/sports')[0] if '/sports' in url else None

            items = [(r['url'].strip(), referer_for(r['url'])) for r in targets]
            results = self.fetcher.fetch_many(items, wait_selector=PROFILE_WAIT_SELECTOR)

            for row, (status, html) in zip(targets, results):
                if status == 200 and html:
                    try:
                        if parse_player_profile(BeautifulSoup(html, 'html.parser'), row):
                            enhanced_count += 1
                            logger.info(f"OK Enhanced {row.get('name', 'Unknown')}")
                    except Exception as e:
                        logger.warning(f"Error parsing {row.get('url')}: {e}")
                else:
                    logger.warning(f"Failed to fetch {row.get('url')}: {status}")

        # Atomic write
        output_path = Path(output_file)
        tmp_path = output_path.with_suffix(output_path.suffix + '.tmp')
        with open(tmp_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        tmp_path.replace(output_path)

        logger.info(f"OK Enhanced {enhanced_count} players")
        logger.info(f"OK Wrote {len(rows)} players to {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Enhance roster CSV by scraping player profile pages'
    )
    parser.add_argument('--input', required=True, help='Input CSV file with existing roster data')
    parser.add_argument('--output', required=True, help='Output CSV file for enhanced data')
    parser.add_argument('--force', action='store_true',
                        help='Force re-scrape even if row has existing data')
    parser.add_argument('--team', help='Only enhance players from this team')
    parser.add_argument('--fetch', choices=['auto', 'browser', 'requests'], default='auto',
                        help='Fetch strategy: auto (browser if available), browser, or requests')
    parser.add_argument('--concurrency', type=int, default=6,
                        help='Max concurrent page loads, global (default: 6)')
    parser.add_argument('--per-host', type=int, default=3,
                        help='Max concurrent page loads per site (default: 3)')

    args = parser.parse_args()

    enhancer = ProfileEnhancer(fetch_mode=args.fetch, concurrency=args.concurrency,
                               per_host=args.per_host)
    try:
        enhancer.enhance_csv(args.input, args.output, force=args.force, team_filter=args.team)
    finally:
        enhancer.close()

    print("\n" + "=" * 80)
    print("ENHANCEMENT COMPLETE")
    print("=" * 80)
    print(f"Input: {args.input}")
    print(f"Output: {args.output}")
    print("=" * 80)


if __name__ == '__main__':
    main()
