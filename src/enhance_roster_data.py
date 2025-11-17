#!/usr/bin/env python3
"""
Enhance existing roster CSV by scraping individual player profile pages
for missing details

Usage:
    python src/enhance_roster_data.py --input rosters_fhockey_2025.csv --output rosters_enhanced.csv
"""

import csv
import argparse
import logging
import time
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Import field extractors from main scraper
import sys
sys.path.insert(0, '/home/user/field-hockey/src')
from fhockey_roster_scraper import FieldExtractors


class ProfileEnhancer:
    """Enhance roster data by scraping individual player profiles"""

    def __init__(self, delay: float = 0.5):
        """Initialize enhancer

        Args:
            delay: Delay between requests in seconds
        """
        if CLOUDSCRAPER_AVAILABLE:
            self.session = cloudscraper.create_scraper()
            logger.info("Using cloudscraper to bypass bot protection")
        else:
            self.session = requests.Session()
            logger.warning("cloudscraper not available, using standard requests")

        self.delay = delay
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        }

    def scrape_player_profile(self, row: Dict, force: bool = False) -> Dict:
        """
        Scrape player profile and enhance row data

        Args:
            row: CSV row dict
            force: Force re-scrape even if data exists

        Returns:
            Enhanced row dict
        """
        url = row.get('url', '').strip()
        if not url:
            return row

        # Skip if already has data (unless force)
        if not force:
            has_data = any([
                row.get('position'),
                row.get('height'),
                row.get('class'),
                row.get('hometown')
            ])
            if has_data:
                logger.debug(f"Skipping {row.get('name')} - already has data")
                return row

        try:
            time.sleep(self.delay)

            # Add referer from URL domain
            request_headers = self.headers.copy()
            if 'https://' in url:
                domain = url.split('/sports')[0] if '/sports' in url else '/'.join(url.split('/')[:3])
                request_headers['Referer'] = domain

            response = self.session.get(url, headers=request_headers, timeout=30)
            if response.status_code != 200:
                logger.warning(f"Failed to fetch {url}: {response.status_code}")
                return row

            html = BeautifulSoup(response.content, 'html.parser')

            # Extract from bio/details section
            bio_section = html.find('div', class_='sidearm-roster-player-bio')
            if bio_section:
                bio_items = bio_section.find_all('div', class_='sidearm-roster-player-bio-item')
                for item in bio_items:
                    label_elem = item.find('span', class_='sidearm-roster-player-bio-label')
                    value_elem = item.find('span', class_='sidearm-roster-player-bio-value')

                    if label_elem and value_elem:
                        label = FieldExtractors.clean_text(label_elem.get_text()).lower()
                        value = FieldExtractors.clean_text(value_elem.get_text())

                        if not value or value == '-':
                            continue

                        if ('position' in label or 'pos' in label) and not row.get('position'):
                            row['position'] = FieldExtractors.extract_position(value)
                        elif ('height' in label or 'ht' in label) and not row.get('height'):
                            row['height'] = FieldExtractors.extract_height(value) or value
                        elif ('class' in label or 'year' in label or 'eligibility' in label) and not row.get('class'):
                            row['class'] = FieldExtractors.normalize_academic_year(value)
                        elif ('major' in label or 'academic' in label) and not row.get('major'):
                            row['major'] = value
                        elif 'hometown' in label and not row.get('hometown'):
                            hometown, hs = FieldExtractors.extract_hometown_parts(value)
                            row['hometown'] = hometown
                            if hs and not row.get('high_school'):
                                row['high_school'] = hs
                        elif ('high school' in label or 'hs' in label) and not row.get('high_school'):
                            row['high_school'] = value
                        elif ('previous school' in label or 'last school' in label or 'transfer' in label) and not row.get('previous_school'):
                            row['previous_school'] = value

            # Also check for dl/dt/dd format
            dl_section = html.find('dl', class_='sidearm-roster-player-bio')
            if dl_section:
                dts = dl_section.find_all('dt')
                dds = dl_section.find_all('dd')

                for dt, dd in zip(dts, dds):
                    label = FieldExtractors.clean_text(dt.get_text()).lower()
                    value = FieldExtractors.clean_text(dd.get_text())

                    if not value or value == '-':
                        continue

                    if ('position' in label or 'pos' in label) and not row.get('position'):
                        row['position'] = FieldExtractors.extract_position(value)
                    elif ('height' in label or 'ht' in label) and not row.get('height'):
                        row['height'] = FieldExtractors.extract_height(value) or value
                    elif ('class' in label or 'year' in label or 'eligibility' in label) and not row.get('class'):
                        row['class'] = FieldExtractors.normalize_academic_year(value)
                    elif ('major' in label or 'academic' in label) and not row.get('major'):
                        row['major'] = value
                    elif 'hometown' in label and not row.get('hometown'):
                        hometown, hs = FieldExtractors.extract_hometown_parts(value)
                        row['hometown'] = hometown
                        if hs and not row.get('high_school'):
                            row['high_school'] = hs
                    elif ('high school' in label or 'hs' in label) and not row.get('high_school'):
                        row['high_school'] = value
                    elif ('previous school' in label or 'last school' in label or 'transfer' in label) and not row.get('previous_school'):
                        row['previous_school'] = value

            # Look for tables with player details
            detail_tables = html.find_all('table', class_='sidearm-table')
            for table in detail_tables:
                rows_html = table.find_all('tr')
                for row_html in rows_html:
                    cells = row_html.find_all(['th', 'td'])
                    if len(cells) >= 2:
                        label = FieldExtractors.clean_text(cells[0].get_text()).lower()
                        value = FieldExtractors.clean_text(cells[1].get_text())

                        if not value or value == '-':
                            continue

                        if ('position' in label) and not row.get('position'):
                            row['position'] = FieldExtractors.extract_position(value)
                        elif ('height' in label) and not row.get('height'):
                            row['height'] = FieldExtractors.extract_height(value) or value
                        elif ('class' in label or 'year' in label) and not row.get('class'):
                            row['class'] = FieldExtractors.normalize_academic_year(value)
                        elif ('major' in label) and not row.get('major'):
                            row['major'] = value
                        elif ('hometown' in label) and not row.get('hometown'):
                            hometown, hs = FieldExtractors.extract_hometown_parts(value)
                            row['hometown'] = hometown
                            if hs and not row.get('high_school'):
                                row['high_school'] = hs
                        elif ('high school' in label) and not row.get('high_school'):
                            row['high_school'] = value
                        elif ('previous school' in label) and not row.get('previous_school'):
                            row['previous_school'] = value

            logger.info(f"✓ Enhanced {row.get('name', 'Unknown')}")

        except requests.RequestException as e:
            logger.warning(f"Request error for {url}: {e}")
        except Exception as e:
            logger.warning(f"Error processing {url}: {e}")

        return row

    def enhance_csv(self, input_file: str, output_file: str, force: bool = False, team_filter: Optional[str] = None):
        """
        Read CSV, enhance data, write new CSV

        Args:
            input_file: Input CSV path
            output_file: Output CSV path
            force: Force re-scrape even if data exists
            team_filter: Optional team name to filter (only enhance this team)
        """
        rows = []
        with open(input_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                rows.append(row)

        logger.info(f"Loaded {len(rows)} players from {input_file}")

        if team_filter:
            rows = [r for r in rows if r.get('team', '').lower() == team_filter.lower()]
            logger.info(f"Filtered to {len(rows)} players for team '{team_filter}'")

        enhanced_count = 0
        for i, row in enumerate(rows, 1):
            logger.info(f"[{i}/{len(rows)}] Processing {row.get('team')} - {row.get('name')}")

            original_row = row.copy()
            enhanced_row = self.scrape_player_profile(row, force=force)

            # Check if anything changed
            if enhanced_row != original_row:
                enhanced_count += 1

        # Write output
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        logger.info(f"✓ Enhanced {enhanced_count} players")
        logger.info(f"✓ Wrote {len(rows)} players to {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Enhance roster CSV by scraping player profile pages'
    )

    parser.add_argument(
        '--input',
        required=True,
        help='Input CSV file with existing roster data'
    )

    parser.add_argument(
        '--output',
        required=True,
        help='Output CSV file for enhanced data'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Force re-scrape even if row has existing data'
    )

    parser.add_argument(
        '--team',
        help='Only enhance players from this team'
    )

    parser.add_argument(
        '--delay',
        type=float,
        default=0.5,
        help='Delay between requests in seconds (default: 0.5)'
    )

    args = parser.parse_args()

    enhancer = ProfileEnhancer(delay=args.delay)
    enhancer.enhance_csv(args.input, args.output, force=args.force, team_filter=args.team)

    print("\n" + "=" * 80)
    print("ENHANCEMENT COMPLETE")
    print("=" * 80)
    print(f"Input: {args.input}")
    print(f"Output: {args.output}")
    print("=" * 80)


if __name__ == '__main__':
    main()
