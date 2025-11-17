#!/usr/bin/env python3
"""
NCAA Field Hockey Roster Scraper
Adapted from women's soccer scraper for field hockey

Usage:
    python src/fhockey_roster_scraper.py --season 2025
    python src/fhockey_roster_scraper.py --team 457 --url https://goheels.com/sports/field-hockey --season 2025
"""

import os
import re
import csv
import json
import argparse
import logging
import subprocess
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import tldextract

try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class Player:
    """Player data structure for NCAA field hockey rosters"""
    team_id: int
    team: str
    season: str
    division: str = ""
    player_id: Optional[str] = None
    name: str = ""
    jersey: str = ""
    position: str = ""
    height: str = ""
    year: str = ""  # Academic year (class)
    major: str = ""
    hometown: str = ""
    high_school: str = ""
    previous_school: str = ""
    url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for CSV output"""
        d = asdict(self)

        # Clean string fields to remove excessive whitespace/newlines before output
        for k, v in list(d.items()):
            if isinstance(v, str):
                d[k] = FieldExtractors.clean_text(v)

        # Map 'year' field to 'class' for CSV output
        d['class'] = d.pop('year', '')
        # Map team_id to ncaa_id
        d['ncaa_id'] = d.pop('team_id')
        # Remove player_id from CSV output (internal use only)
        d.pop('player_id', None)
        return d


# ============================================================================
# FIELD EXTRACTORS
# ============================================================================

class FieldExtractors:
    """Common utilities for extracting player fields from text and HTML"""

    @staticmethod
    def clean_text(text: str) -> str:
        """Clean text by removing extra whitespace and newlines"""
        if not text:
            return ''
        # Replace multiple whitespace/newlines with single space
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @staticmethod
    def extract_jersey_number(text: str) -> str:
        """Extract jersey number from various text patterns"""
        if not text:
            return ''

        patterns = [
            r'Jersey Number[:\s]+(\d+)',
            r'#(\d{1,2})\b',
            r'No\.?[:\s]*(\d{1,2})\b',
            r'\b(\d{1,2})\s+(?=[A-Z])',  # Number followed by capitalized name
            r'^\s*(\d{1,2})\s*$',  # Plain number (1-2 digits)
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return ''

    @staticmethod
    def extract_height(text: str) -> str:
        """
        Extract height from various formats (imperial and metric)

        Formats supported:
        - 6'2" or 6-2 (imperial)
        - 6'2" / 1.88m (both)
        - 1.88m (metric only)
        """
        if not text:
            return ''

        patterns = [
            r"(\d+['\′]\s*\d+[\"\″']{1,2}(?:\s*/\s*\d+\.\d+m)?)",  # 6'2" or 6'2" / 1.88m
            r"(\d+['\′]\s*\d+[\"\″']{1,2})",  # 6'2"
            r"(\d+-\d+)",  # 6-2
            r"(\d+\.\d+m)",  # 1.88m
            r"Height:\s*([^\,\n]+)",  # Height: label format
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return ''

    @staticmethod
    def extract_position(text: str) -> str:
        """
        Extract position from text - FIELD HOCKEY VERSION

        Field Hockey positions: GK, D, M, F (Goalkeeper, Defense/Back, Midfield, Forward/Attack)
        """
        if not text:
            return ''

        # Clean the text
        text = text.strip()

        # Look for abbreviated position patterns
        position_match = re.search(
            r'\b(GK|G|GOALKEEPER|GOALIE|'  # Goalkeeper variations
            r'D|DEF|DEFENSE|DEFENDER|B|BACK|'  # Defense/Back variations
            r'M|MF|MID|MIDFIELDER|MIDFIELD|'  # Midfielder variations
            r'F|FW|FOR|FORWARD|A|ATT|ATTACK|ATTACKER|O|OFFENSE)\b',
            text,
            re.IGNORECASE
        )
        if position_match:
            pos = position_match.group(1).upper()

            # Normalize variations to standard positions (GK, D, M, F)
            # Goalkeeper
            if pos in ('GK', 'G', 'GOALKEEPER', 'GOALIE'):
                return 'GK'
            # Defense/Back
            elif pos in ('DEF', 'D', 'DEFENSE', 'DEFENDER', 'B', 'BACK'):
                return 'D'
            # Midfielder
            elif pos in ('MID', 'MF', 'MIDFIELDER', 'MIDFIELD'):
                return 'M'
            # Forward/Attack
            elif pos in ('FOR', 'FW', 'F', 'FORWARD', 'A', 'ATT', 'ATTACK', 'ATTACKER', 'O', 'OFFENSE'):
                return 'F'
            # Return as-is if it's one of the standard forms
            return pos

        # Look for full position names (fallback)
        text_upper = text.upper()
        if 'GOALKEEPER' in text_upper or 'GOALIE' in text_upper or 'KEEPER' in text_upper:
            return 'GK'
        elif 'DEFENSE' in text_upper or 'DEFENDER' in text_upper or 'BACK' in text_upper:
            return 'D'
        elif 'MIDFIELDER' in text_upper or 'MIDFIELD' in text_upper:
            return 'M'
        elif 'FORWARD' in text_upper or 'ATTACK' in text_upper or 'OFFENSE' in text_upper:
            return 'F'

        return ''

    @staticmethod
    def normalize_academic_year(year_text: str) -> str:
        """Normalize academic year abbreviations to full forms"""
        if not year_text:
            return ''

        year_map = {
            'Fr': 'Freshman', 'Fr.': 'Freshman', 'FR': 'Freshman',
            'So': 'Sophomore', 'So.': 'Sophomore', 'SO': 'Sophomore',
            'Jr': 'Junior', 'Jr.': 'Junior', 'JR': 'Junior',
            'Sr': 'Senior', 'Sr.': 'Senior', 'SR': 'Senior',
            'Gr': 'Graduate', 'Gr.': 'Graduate', 'GR': 'Graduate',
            'R-Fr': 'Redshirt Freshman', 'R-Fr.': 'Redshirt Freshman',
            'R-So': 'Redshirt Sophomore', 'R-So.': 'Redshirt Sophomore',
            'R-Jr': 'Redshirt Junior', 'R-Jr.': 'Redshirt Junior',
            'R-Sr': 'Redshirt Senior', 'R-Sr.': 'Redshirt Senior',
            '1st': 'Freshman', 'First': 'Freshman',
            '2nd': 'Sophomore', 'Second': 'Sophomore',
            '3rd': 'Junior', 'Third': 'Junior',
            '4th': 'Senior', 'Fourth': 'Senior',
            '5th': 'Graduate', 'Fifth': 'Graduate',
        }

        return year_map.get(year_text, year_text)

    @staticmethod
    def extract_hometown_parts(hometown_text: str) -> tuple:
        """
        Extract hometown and high school from combined text

        Returns:
            (hometown, high_school) tuple
        """
        if not hometown_text:
            return ('', '')

        # Look for patterns like "City, State / High School"
        match = re.match(r'([^/]+?)\s*/\s*(.+)', hometown_text)
        if match:
            return (match.group(1).strip(), match.group(2).strip())

        # No high school info, just hometown
        return (hometown_text.strip(), '')


# ============================================================================
# SEASON VERIFICATION
# ============================================================================

class SeasonVerifier:
    """Verify season on roster pages"""

    @staticmethod
    def verify_season_on_page(html, season: str) -> bool:
        """
        Check if the expected season appears on the page

        Args:
            html: BeautifulSoup parsed HTML
            season: Expected season (e.g., '2025')

        Returns:
            True if season found on page, False otherwise
        """
        page_text = html.get_text()

        # Check for season year (e.g., '2025')
        if season in page_text:
            return True

        # Check for season range (e.g., '2024-25' if season is '2025')
        try:
            year = int(season)
            prev_year = str(year - 1)
            next_year = str(year + 1)[-2:]
            season_range = f"{prev_year}-{next_year}"
            if season_range in page_text:
                return True
        except ValueError:
            pass

        return False


# ============================================================================
# URL BUILDER
# ============================================================================

class URLBuilder:
    """Build roster URLs for different site patterns"""

    @staticmethod
    def build_roster_url(base_url: str, season: str, url_format: str = 'default') -> str:
        """
        Build roster URL from base URL and season

        Args:
            base_url: Base URL from teams.csv
            season: Season year (e.g., '2025')
            url_format: URL format pattern

        Returns:
            Full roster URL
        """
        # Remove trailing slash for consistency
        base_url = base_url.rstrip('/')

        if url_format == 'default':
            # Standard Sidearm Sports: /sports/field-hockey/roster/YEAR
            return f"{base_url}/roster/{season}"

        elif url_format == 'fhockey':
            # /sports/fhockey/roster/YEAR format (e.g., Iowa, Ohio)
            return f"{base_url}/roster/{season}"

        else:
            # Fallback to default
            logger.warning(f"Unknown url_format '{url_format}', using default")
            return f"{base_url}/roster/{season}"

    @staticmethod
    def extract_base_url(full_url: str) -> str:
        """
        Extract base domain URL from full team URL

        Example:
            'https://goheels.com/sports/field-hockey' → 'https://goheels.com'
        """
        extracted = tldextract.extract(full_url)

        # Build domain with subdomain if present
        if extracted.subdomain:
            domain = f"{extracted.subdomain}.{extracted.domain}.{extracted.suffix}"
        else:
            domain = f"{extracted.domain}.{extracted.suffix}"

        return f"https://{domain}"


# ============================================================================
# TEAM CONFIGURATION
# ============================================================================

class TeamConfig:
    """Team-specific configuration"""

    # Team-specific configurations
    # Format: ncaa_id: {'url_format': 'format_type', 'requires_js': bool, 'notes': '...'}
    TEAM_CONFIGS = {
        # Teams that use /sports/fhockey/ instead of /sports/field-hockey/
        312: {'url_format': 'fhockey', 'requires_js': False, 'notes': 'Iowa - /sports/fhockey/'},
        519: {'url_format': 'fhockey', 'requires_js': False, 'notes': 'Ohio - /sports/fhockey/'},
        # Add more team-specific configs as needed
    }

    @classmethod
    def requires_javascript(cls, team_id: int) -> bool:
        """Check if a team requires JavaScript rendering"""
        if team_id in cls.TEAM_CONFIGS:
            return cls.TEAM_CONFIGS[team_id].get('requires_js', False)
        return False

    @classmethod
    def get_url_format(cls, team_id: int, team_url: str = '') -> str:
        """
        Get URL format for a team

        Args:
            team_id: NCAA team ID
            team_url: Team URL for auto-detection

        Returns:
            URL format string
        """
        # Check if explicitly configured
        if team_id in cls.TEAM_CONFIGS:
            return cls.TEAM_CONFIGS[team_id].get('url_format', 'default')

        # Auto-detect from URL if provided
        if team_url:
            if '/sports/fhockey' in team_url:
                return 'fhockey'
            elif '/sports/field-hockey' in team_url:
                return 'default'

        # Default to standard Sidearm pattern
        return 'default'


# ============================================================================
# STANDARD SCRAPER
# ============================================================================

class StandardScraper:
    """Scraper for standard Sidearm Sports sites"""

    def __init__(self, session: Optional[requests.Session] = None, scrape_profiles: bool = True):
        """Initialize scraper

        Args:
            session: Optional requests session
            scrape_profiles: Whether to scrape individual player profile pages for detailed info
        """
        if session:
            self.session = session
        elif CLOUDSCRAPER_AVAILABLE:
            # Use cloudscraper to bypass bot protection
            self.session = cloudscraper.create_scraper()
            logger.info("Using cloudscraper to bypass bot protection")
        else:
            self.session = requests.Session()
            logger.warning("cloudscraper not available, using standard requests (may encounter 403 errors)")

        self.scrape_profiles = scrape_profiles
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

    def scrape_team(self, team_id: int, team_name: str, base_url: str, season: str, division: str = "") -> List[Player]:
        """
        Scrape roster for a single team

        Args:
            team_id: NCAA team ID
            team_name: Team name
            base_url: Base URL for team site
            season: Season string (e.g., '2025')
            division: Division

        Returns:
            List of Player objects
        """
        try:
            # Build roster URL
            url_format = TeamConfig.get_url_format(team_id, base_url)
            roster_url = URLBuilder.build_roster_url(base_url, season, url_format)

            logger.info(f"Scraping {team_name} - {roster_url}")

            # Update headers with referer for this specific domain
            request_headers = self.headers.copy()
            domain_base = base_url.split('/sports')[0] if '/sports' in base_url else base_url
            request_headers['Referer'] = domain_base
            request_headers['Origin'] = domain_base

            # First visit the base domain to establish session (mimic normal browsing)
            import time
            try:
                self.session.get(domain_base, headers=self.headers, timeout=10, allow_redirects=True)
                time.sleep(0.5)  # Small delay to mimic human behavior
            except:
                pass  # Continue even if base page fails

            # Fetch roster page
            response = self.session.get(roster_url, headers=request_headers, timeout=30, allow_redirects=True)

            # Try alternative URLs if failed
            if response.status_code == 404:
                # Try without year
                logger.info(f"Got 404, trying /roster without year for {team_name}")
                alternative_url = f"{base_url.rstrip('/')}/roster"
                response = self.session.get(alternative_url, headers=request_headers, timeout=30, allow_redirects=True)
                if response.status_code == 200:
                    roster_url = alternative_url
                else:
                    # Try .aspx format
                    logger.info(f"Got 404, trying /roster.aspx for {team_name}")
                    alternative_url = f"{base_url.rstrip('/')}/roster.aspx"
                    response = self.session.get(alternative_url, headers=request_headers, timeout=30, allow_redirects=True)
                    if response.status_code == 200:
                        roster_url = alternative_url

            if response.status_code != 200:
                logger.warning(f"Failed to retrieve {team_name} - Status: {response.status_code}")
                return []

            # Parse HTML
            html = BeautifulSoup(response.content, 'html.parser')

            # Verify season
            if not SeasonVerifier.verify_season_on_page(html, season):
                logger.warning(f"Season mismatch for {team_name}")
                # Continue anyway

            # Extract players
            players = self._extract_players(html, team_id, team_name, season, division, base_url)

            logger.info(f"✓ {team_name}: Found {len(players)} players")
            return players

        except requests.RequestException as e:
            logger.error(f"Request error for {team_name}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error scraping {team_name}: {e}")
            return []

    def _scrape_player_profile(self, player: Player) -> Player:
        """
        Scrape individual player profile page for detailed information

        Args:
            player: Player object with URL populated

        Returns:
            Updated Player object with profile details
        """
        if not player.url:
            return player

        try:
            import time
            time.sleep(0.5)  # Rate limiting

            response = self.session.get(player.url, headers=self.headers, timeout=30)
            if response.status_code != 200:
                logger.warning(f"Failed to fetch profile for {player.name}: {response.status_code}")
                return player

            html = BeautifulSoup(response.content, 'html.parser')

            # Extract from bio/details section
            bio_section = html.find('div', class_='sidearm-roster-player-bio')
            if bio_section:
                # Find all bio fields
                bio_items = bio_section.find_all('div', class_='sidearm-roster-player-bio-item')
                for item in bio_items:
                    label_elem = item.find('span', class_='sidearm-roster-player-bio-label')
                    value_elem = item.find('span', class_='sidearm-roster-player-bio-value')

                    if label_elem and value_elem:
                        label = FieldExtractors.clean_text(label_elem.get_text()).lower()
                        value = FieldExtractors.clean_text(value_elem.get_text())

                        if not value or value == '-':
                            continue

                        # Position
                        if 'position' in label or 'pos' in label:
                            if not player.position:
                                player.position = FieldExtractors.extract_position(value)
                        # Height
                        elif 'height' in label or 'ht' in label:
                            if not player.height:
                                player.height = FieldExtractors.extract_height(value) or value
                        # Year/Class
                        elif 'class' in label or 'year' in label or 'eligibility' in label:
                            if not player.year:
                                player.year = FieldExtractors.normalize_academic_year(value)
                        # Major
                        elif 'major' in label or 'academic' in label:
                            if not player.major:
                                player.major = value
                        # Hometown
                        elif 'hometown' in label:
                            if not player.hometown:
                                hometown, hs = FieldExtractors.extract_hometown_parts(value)
                                player.hometown = hometown
                                if hs and not player.high_school:
                                    player.high_school = hs
                        # High School
                        elif 'high school' in label or 'hs' in label:
                            if not player.high_school:
                                player.high_school = value
                        # Previous School
                        elif 'previous school' in label or 'last school' in label or 'transfer' in label:
                            if not player.previous_school:
                                player.previous_school = value

            # Also check for dl/dt/dd format (common alternative)
            dl_section = html.find('dl', class_='sidearm-roster-player-bio')
            if dl_section:
                dts = dl_section.find_all('dt')
                dds = dl_section.find_all('dd')

                for dt, dd in zip(dts, dds):
                    label = FieldExtractors.clean_text(dt.get_text()).lower()
                    value = FieldExtractors.clean_text(dd.get_text())

                    if not value or value == '-':
                        continue

                    if 'position' in label or 'pos' in label:
                        if not player.position:
                            player.position = FieldExtractors.extract_position(value)
                    elif 'height' in label or 'ht' in label:
                        if not player.height:
                            player.height = FieldExtractors.extract_height(value) or value
                    elif 'class' in label or 'year' in label or 'eligibility' in label:
                        if not player.year:
                            player.year = FieldExtractors.normalize_academic_year(value)
                    elif 'major' in label or 'academic' in label:
                        if not player.major:
                            player.major = value
                    elif 'hometown' in label:
                        if not player.hometown:
                            hometown, hs = FieldExtractors.extract_hometown_parts(value)
                            player.hometown = hometown
                            if hs and not player.high_school:
                                player.high_school = hs
                    elif 'high school' in label or 'hs' in label:
                        if not player.high_school:
                            player.high_school = value
                    elif 'previous school' in label or 'last school' in label or 'transfer' in label:
                        if not player.previous_school:
                            player.previous_school = value

            # Look for any table with player details
            detail_tables = html.find_all('table', class_='sidearm-table')
            for table in detail_tables:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['th', 'td'])
                    if len(cells) >= 2:
                        label = FieldExtractors.clean_text(cells[0].get_text()).lower()
                        value = FieldExtractors.clean_text(cells[1].get_text())

                        if not value or value == '-':
                            continue

                        if 'position' in label:
                            if not player.position:
                                player.position = FieldExtractors.extract_position(value)
                        elif 'height' in label:
                            if not player.height:
                                player.height = FieldExtractors.extract_height(value) or value
                        elif 'class' in label or 'year' in label:
                            if not player.year:
                                player.year = FieldExtractors.normalize_academic_year(value)
                        elif 'major' in label:
                            if not player.major:
                                player.major = value
                        elif 'hometown' in label:
                            if not player.hometown:
                                hometown, hs = FieldExtractors.extract_hometown_parts(value)
                                player.hometown = hometown
                                if hs and not player.high_school:
                                    player.high_school = hs
                        elif 'high school' in label:
                            if not player.high_school:
                                player.high_school = value
                        elif 'previous school' in label:
                            if not player.previous_school:
                                player.previous_school = value

        except requests.RequestException as e:
            logger.warning(f"Request error fetching profile for {player.name}: {e}")
        except Exception as e:
            logger.warning(f"Error parsing profile for {player.name}: {e}")

        return player

    def _extract_players(self, html, team_id: int, team_name: str, season: str, division: str, base_url: str) -> List[Player]:
        """Extract players from HTML"""
        players = []

        # Find all player list items (Sidearm pattern)
        roster_items = html.find_all('li', class_='sidearm-roster-player')

        if not roster_items:
            logger.warning(f"No roster items found for {team_name} (expected class='sidearm-roster-player')")

            # Try table-based format
            return self._extract_players_from_table(html, team_id, team_name, season, division, base_url)

        # Extract base domain for URLs
        extracted = tldextract.extract(base_url)
        domain = f"{extracted.domain}.{extracted.suffix}"
        if extracted.subdomain:
            domain = f"{extracted.subdomain}.{domain}"

        for item in roster_items:
            try:
                # Jersey number
                jersey_elem = item.find('span', class_='sidearm-roster-player-jersey-number')
                jersey = FieldExtractors.clean_text(jersey_elem.get_text()) if jersey_elem else ''

                # Name and URL
                name_elem = item.find('h3') or item.find('h2')
                if name_elem:
                    name_link = name_elem.find('a', href=True)
                    if name_link:
                        name = FieldExtractors.clean_text(name_link.get_text())
                        rel_url = name_link['href']
                        # Build absolute URL
                        if rel_url.startswith('http'):
                            profile_url = rel_url
                        else:
                            profile_url = f"https://{domain}{rel_url}" if rel_url.startswith('/') else f"https://{domain}/{rel_url}"
                    else:
                        name = FieldExtractors.clean_text(name_elem.get_text())
                        profile_url = ''
                else:
                    name = ''
                    profile_url = ''

                # Position, Year, Hometown (from meta fields)
                position = ''
                year = ''
                hometown = ''
                high_school = ''
                height = ''

                # Find all metadata fields
                meta_fields = item.find_all('div', class_='sidearm-roster-player-custom-fields')
                for meta in meta_fields:
                    label_elem = meta.find('span', class_='sidearm-roster-player-custom-field-label')
                    value_elem = meta.find('span', class_='sidearm-roster-player-custom-field-value')

                    if label_elem and value_elem:
                        label = FieldExtractors.clean_text(label_elem.get_text()).lower()
                        value = FieldExtractors.clean_text(value_elem.get_text())

                        if 'position' in label or 'pos' in label:
                            position = FieldExtractors.extract_position(value)
                        elif 'class' in label or 'year' in label:
                            year = FieldExtractors.normalize_academic_year(value)
                        elif 'hometown' in label:
                            hometown, hs = FieldExtractors.extract_hometown_parts(value)
                            if hs:
                                high_school = hs
                        elif 'high school' in label:
                            high_school = value
                        elif 'height' in label:
                            height = FieldExtractors.extract_height(value)

                # Create player
                player = Player(
                    team_id=team_id,
                    team=team_name,
                    season=season,
                    division=division,
                    name=name,
                    jersey=jersey,
                    position=position,
                    height=height,
                    year=year,
                    hometown=hometown,
                    high_school=high_school,
                    url=profile_url
                )

                # Scrape player profile page if enabled and URL exists
                if self.scrape_profiles and profile_url:
                    player = self._scrape_player_profile(player)

                players.append(player)

            except Exception as e:
                logger.warning(f"Error parsing player in {team_name}: {e}")
                continue

        return players

    def _extract_players_from_table(self, html, team_id: int, team_name: str, season: str, division: str, base_url: str) -> List[Player]:
        """Extract players from table-based roster"""
        players = []

        # Find roster table
        table = html.find('table', class_='sidearm-table')
        if not table:
            # Try generic table
            table = html.find('table')

        if not table:
            logger.warning(f"No table found for {team_name}")
            return players

        # Extract base domain for URLs
        extracted = tldextract.extract(base_url)
        domain = f"{extracted.domain}.{extracted.suffix}"
        if extracted.subdomain:
            domain = f"{extracted.subdomain}.{domain}"

        # Find header row to map columns
        header_row = table.find('thead')
        if not header_row:
            header_row = table.find('tr')

        if not header_row:
            logger.warning(f"No header row found in table for {team_name}")
            return players

        # Map column indices
        headers = []
        for th in header_row.find_all(['th', 'td']):
            headers.append(FieldExtractors.clean_text(th.get_text()).lower())

        # Find column indices
        name_idx = next((i for i, h in enumerate(headers) if 'name' in h), None)
        jersey_idx = next((i for i, h in enumerate(headers) if '#' in h or 'number' in h or 'jersey' in h), None)
        pos_idx = next((i for i, h in enumerate(headers) if 'pos' in h), None)
        year_idx = next((i for i, h in enumerate(headers) if 'year' in h or 'class' in h), None)
        height_idx = next((i for i, h in enumerate(headers) if 'height' in h or 'ht' in h), None)
        hometown_idx = next((i for i, h in enumerate(headers) if 'hometown' in h), None)
        hs_idx = next((i for i, h in enumerate(headers) if 'high school' in h or 'hs' in h), None)

        # Extract rows
        tbody = table.find('tbody') or table
        rows = tbody.find_all('tr')

        for row in rows[1:]:  # Skip header if it's in tbody
            cols = row.find_all(['td', 'th'])
            if len(cols) < 2:
                continue

            try:
                # Name and URL
                name = ''
                profile_url = ''
                if name_idx is not None and name_idx < len(cols):
                    name_cell = cols[name_idx]
                    name_link = name_cell.find('a', href=True)
                    if name_link:
                        name = FieldExtractors.clean_text(name_link.get_text())
                        rel_url = name_link['href']
                        # Build absolute URL
                        if rel_url.startswith('http'):
                            profile_url = rel_url
                        else:
                            profile_url = f"https://{domain}{rel_url}" if rel_url.startswith('/') else f"https://{domain}/{rel_url}"
                    else:
                        name = FieldExtractors.clean_text(name_cell.get_text())

                # Jersey
                jersey = ''
                if jersey_idx is not None and jersey_idx < len(cols):
                    jersey = FieldExtractors.clean_text(cols[jersey_idx].get_text())
                    jersey = FieldExtractors.extract_jersey_number(jersey) or jersey

                # Position
                position = ''
                if pos_idx is not None and pos_idx < len(cols):
                    pos_text = FieldExtractors.clean_text(cols[pos_idx].get_text())
                    position = FieldExtractors.extract_position(pos_text)

                # Year
                year = ''
                if year_idx is not None and year_idx < len(cols):
                    year_text = FieldExtractors.clean_text(cols[year_idx].get_text())
                    year = FieldExtractors.normalize_academic_year(year_text)

                # Height
                height = ''
                if height_idx is not None and height_idx < len(cols):
                    height_text = FieldExtractors.clean_text(cols[height_idx].get_text())
                    height = FieldExtractors.extract_height(height_text) or height_text

                # Hometown
                hometown = ''
                high_school = ''
                if hometown_idx is not None and hometown_idx < len(cols):
                    hometown_text = FieldExtractors.clean_text(cols[hometown_idx].get_text())
                    hometown, hs = FieldExtractors.extract_hometown_parts(hometown_text)
                    if hs:
                        high_school = hs

                # High School
                if hs_idx is not None and hs_idx < len(cols):
                    high_school = FieldExtractors.clean_text(cols[hs_idx].get_text())

                # Create player
                player = Player(
                    team_id=team_id,
                    team=team_name,
                    season=season,
                    division=division,
                    name=name,
                    jersey=jersey,
                    position=position,
                    height=height,
                    year=year,
                    hometown=hometown,
                    high_school=high_school,
                    url=profile_url
                )

                # Scrape player profile page if enabled and URL exists
                if self.scrape_profiles and profile_url:
                    player = self._scrape_player_profile(player)

                players.append(player)

            except Exception as e:
                logger.warning(f"Error parsing row in {team_name}: {e}")
                continue

        return players


# ============================================================================
# ROSTER MANAGER
# ============================================================================

class RosterManager:
    """Manages batch scraping of rosters with error tracking"""

    def __init__(self, season: str = '2025', output_dir: str = 'data/raw', scrape_profiles: bool = True):
        """
        Initialize RosterManager

        Args:
            season: Season string (e.g., '2025')
            output_dir: Base output directory
            scrape_profiles: Whether to scrape individual player profile pages
        """
        self.season = season
        self.output_dir = Path(output_dir)
        self.scraper = StandardScraper(scrape_profiles=scrape_profiles)

        # Error tracking
        self.zero_player_teams = []
        self.failed_teams = []
        self.successful_teams = []

    def load_teams(self, csv_path: str) -> List[Dict]:
        """
        Load teams from CSV

        Args:
            csv_path: Path to teams.csv

        Returns:
            List of team dictionaries
        """
        teams = []
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Skip empty rows
                if row.get('school') and row.get('url'):
                    teams.append({
                        'team': row['school'],
                        'ncaa_id': int(row['org_id']),
                        'url': row['url']
                    })

        logger.info(f"Loaded {len(teams)} teams")
        return teams

    def scrape_teams(self, teams: List[Dict], max_teams: Optional[int] = None) -> List[Player]:
        """
        Scrape rosters for multiple teams

        Args:
            teams: List of team dictionaries from CSV
            max_teams: Optional limit on number of teams to scrape

        Returns:
            List of all Player objects
        """
        all_players = []
        teams_to_scrape = teams[:max_teams] if max_teams else teams

        logger.info(f"Starting scrape of {len(teams_to_scrape)} teams")
        logger.info("=" * 80)

        for i, team in enumerate(teams_to_scrape, 1):
            team_id = team['ncaa_id']
            team_name = team['team']
            team_url = team['url']

            logger.info(f"[{i}/{len(teams_to_scrape)}] {team_name}")

            try:
                players = self.scraper.scrape_team(
                    team_id=team_id,
                    team_name=team_name,
                    base_url=team_url,
                    season=self.season,
                    division=""
                )

                if len(players) == 0:
                    logger.warning(f"  ⚠️  Zero players found")
                    self.zero_player_teams.append({
                        'team': team_name,
                        'ncaa_id': team_id,
                        'url': team_url
                    })
                else:
                    logger.info(f"  ✓ {len(players)} players")
                    all_players.extend(players)
                    self.successful_teams.append({
                        'team': team_name,
                        'ncaa_id': team_id,
                        'player_count': len(players)
                    })

            except Exception as e:
                logger.error(f"  ✗ Error: {e}")
                self.failed_teams.append({
                    'team': team_name,
                    'ncaa_id': team_id,
                    'url': team_url,
                    'error': str(e)
                })

        logger.info("=" * 80)
        logger.info(f"Scraping complete:")
        logger.info(f"  Successful: {len(self.successful_teams)} teams, {len(all_players)} players")
        logger.info(f"  Zero players: {len(self.zero_player_teams)} teams")
        logger.info(f"  Failed: {len(self.failed_teams)} teams")

        return all_players

    def save_results(self, players: List[Player]):
        """
        Save results to JSON and CSV

        Args:
            players: List of Player objects
        """
        # Determine filenames
        json_file = self.output_dir / 'json' / f'rosters_fhockey_{self.season}.json'
        csv_file = self.output_dir / 'csv' / f'rosters_fhockey_{self.season}.csv'

        # Create directories
        json_file.parent.mkdir(parents=True, exist_ok=True)
        csv_file.parent.mkdir(parents=True, exist_ok=True)

        # Save JSON
        players_dicts = [p.to_dict() for p in players]
        with open(json_file, 'w') as f:
            json.dump(players_dicts, f, indent=2)
        logger.info(f"✓ Saved JSON: {json_file} ({len(players)} players)")

        # Save CSV
        if players_dicts:
            fieldnames = players_dicts[0].keys()
            with open(csv_file, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(players_dicts)
            logger.info(f"✓ Saved CSV: {csv_file}")

        # Save error reports
        self._save_error_reports()

    def _save_error_reports(self):
        """Save error reports for teams with issues"""
        reports_dir = self.output_dir / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)

        # Zero players report
        if self.zero_player_teams:
            zero_file = reports_dir / f'zero_players_fhockey_{self.season}.json'
            with open(zero_file, 'w') as f:
                json.dump(self.zero_player_teams, f, indent=2)
            logger.info(f"✓ Saved zero players report: {zero_file}")

        # Failed teams report
        if self.failed_teams:
            failed_file = reports_dir / f'failed_teams_fhockey_{self.season}.json'
            with open(failed_file, 'w') as f:
                json.dump(self.failed_teams, f, indent=2)
            logger.info(f"✓ Saved failed teams report: {failed_file}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='NCAA Field Hockey Roster Scraper',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scrape all teams
  python src/fhockey_roster_scraper.py --season 2025

  # Scrape first 10 teams (testing)
  python src/fhockey_roster_scraper.py --limit 10 --season 2025

  # Scrape specific team
  python src/fhockey_roster_scraper.py --team 457 --season 2025
        """
    )

    parser.add_argument(
        '--season',
        default='2025',
        help='Season year (default: 2025)'
    )

    parser.add_argument(
        '--team',
        type=int,
        help='Scrape specific team by NCAA ID'
    )

    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of teams to scrape (for testing)'
    )

    parser.add_argument(
        '--teams-csv',
        default='teams.csv',
        help='Path to teams.csv (default: teams.csv)'
    )

    parser.add_argument(
        '--output-dir',
        default='data/raw',
        help='Output directory (default: data/raw)'
    )

    parser.add_argument(
        '--scrape-profiles',
        action='store_true',
        default=True,
        help='Scrape individual player profile pages for detailed info (default: True)'
    )

    parser.add_argument(
        '--no-scrape-profiles',
        action='store_false',
        dest='scrape_profiles',
        help='Skip scraping individual player profile pages'
    )

    args = parser.parse_args()

    # Initialize manager
    manager = RosterManager(season=args.season, output_dir=args.output_dir, scrape_profiles=args.scrape_profiles)

    # Load teams
    if args.team:
        # Scrape specific team
        teams = manager.load_teams(args.teams_csv)
        teams = [t for t in teams if t['ncaa_id'] == args.team]
        if not teams:
            logger.error(f"Team {args.team} not found in {args.teams_csv}")
            return
        logger.info(f"Scraping specific team: {teams[0]['team']}")
    else:
        # Load all teams
        teams = manager.load_teams(args.teams_csv)

    if not teams:
        logger.error("No teams to scrape")
        return

    # Scrape teams
    players = manager.scrape_teams(teams, max_teams=args.limit)

    # Save results
    if players:
        manager.save_results(players)
    else:
        logger.warning("No players scraped - no output files generated")

    # Summary
    print("\n" + "=" * 80)
    print("SCRAPING SUMMARY")
    print("=" * 80)
    print(f"Season: {args.season}")
    print(f"Teams attempted: {len(teams) if not args.limit else min(len(teams), args.limit)}")
    print(f"Successful: {len(manager.successful_teams)} teams")
    print(f"Total players: {len(players)}")
    print(f"Zero players: {len(manager.zero_player_teams)} teams")
    print(f"Failed: {len(manager.failed_teams)} teams")
    print("=" * 80)


if __name__ == '__main__':
    main()
