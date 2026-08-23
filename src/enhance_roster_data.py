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
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ProfileEnhancer:
    """Enhance roster data by scraping individual player profiles."""

    def __init__(self, fetch_mode: str = 'auto'):
        self.fetcher = build_fetcher(fetch_mode)

    def close(self):
        self.fetcher.close()

    def scrape_player_profile(self, row: Dict, force: bool = False) -> bool:
        """
        Scrape a player profile and fill missing fields in `row` (in place).

        Returns True if the row was modified.
        """
        url = (row.get('url') or '').strip()
        if not url:
            return False

        # Skip if the row already has the core fields (unless force)
        if not force:
            has_data = any([row.get('position'), row.get('height'),
                            row.get('class'), row.get('hometown')])
            if has_data:
                logger.debug(f"Skipping {row.get('name')} - already has data")
                return False

        try:
            referer = url.split('/sports')[0] if '/sports' in url else None
            status, content = self.fetcher.fetch(url, referer=referer)
            if status != 200:
                logger.warning(f"Failed to fetch {url}: {status}")
                return False

            html = BeautifulSoup(content, 'html.parser')
            changed = parse_player_profile(html, row)
            if changed:
                logger.info(f"OK Enhanced {row.get('name', 'Unknown')}")
            return changed

        except Exception as e:
            logger.warning(f"Error processing {url}: {e}")
            return False

    def enhance_csv(self, input_file: str, output_file: str, force: bool = False,
                    team_filter: Optional[str] = None, checkpoint_every: int = 25):
        """
        Read a roster CSV, enhance rows from their profile pages, and write the
        result. Output is written incrementally (checkpointed) so a crash does
        not discard completed work.
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

        enhanced_count = 0
        output_path = Path(output_file)
        tmp_path = output_path.with_suffix(output_path.suffix + '.tmp')

        for i, row in enumerate(rows, 1):
            logger.info(f"[{i}/{len(rows)}] Processing {row.get('team')} - {row.get('name')}")
            if self.scrape_player_profile(row, force=force):
                enhanced_count += 1

            # Checkpoint: flush progress to a temp file periodically
            if checkpoint_every and i % checkpoint_every == 0:
                self._write_rows(tmp_path, fieldnames, rows)
                logger.info(f"  Checkpoint written ({i}/{len(rows)})")

        # Final write, then atomically move into place
        self._write_rows(tmp_path, fieldnames, rows)
        tmp_path.replace(output_path)

        logger.info(f"OK Enhanced {enhanced_count} players")
        logger.info(f"OK Wrote {len(rows)} players to {output_file}")

    @staticmethod
    def _write_rows(path: Path, fieldnames: List[str], rows: List[Dict]):
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)


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

    args = parser.parse_args()

    enhancer = ProfileEnhancer(fetch_mode=args.fetch)
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
