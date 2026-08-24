#!/usr/bin/env python3
"""
NCAA Field Hockey Roster Scraper
Adapted from women's soccer scraper for field hockey

Usage:
    uv run src/fhockey_roster_scraper.py --season 2025
    uv run src/fhockey_roster_scraper.py --team 457 --season 2025

Fetching:
    By default the scraper renders team roster pages in a real headless
    Chromium browser (via Playwright) to get past the bot protection used by
    Sidearm Sports sites. Use --fetch requests to fall back to plain HTTP
    (cloudscraper/requests), or --fetch browser to require the browser path.
    One-time browser setup on a new machine: `uv run playwright install chromium`.
"""

import re
import csv
import json
import time
import random
import asyncio
import threading
import argparse
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict, field
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
import tldextract

try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False

# Repo root, so default paths work regardless of the current working directory
REPO_ROOT = Path(__file__).resolve().parent.parent

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)


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


@dataclass
class TeamResult:
    """Outcome of scraping a single team's roster."""
    players: List[Player] = field(default_factory=list)
    status: str = "empty"   # ok | empty | http_error | error
    detail: str = ""


# ============================================================================
# FIELD EXTRACTORS
# ============================================================================

class FieldExtractors:
    """Common utilities for extracting player fields from text and HTML"""

    # Canonical bio field name -> the CSV/dict key it maps to (Player attrs match
    # the canonical name except 'year', which is written as 'class' in output).
    _FIELD_TO_DICT_KEY = {'year': 'class'}

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
            r"\b([4-7]-\d{1,2})\b",  # 6-2 (feet 4-7, avoids matching e.g. 2024-25)
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

        # Exact match first (preserves original behavior)
        if year_text in year_map:
            return year_map[year_text]

        # Case-insensitive match on the abbreviation, tolerating a trailing period
        key = year_text.strip().rstrip('.')
        for k, v in year_map.items():
            if k.rstrip('.').lower() == key.lower():
                return v

        # "4th Year" / "First Year" style: strip a trailing "year" and retry.
        stripped = re.sub(r'\s*years?\s*$', '', key, flags=re.IGNORECASE).strip()
        if stripped and stripped.lower() != key.lower():
            for k, v in year_map.items():
                if k.rstrip('.').lower() == stripped.lower():
                    return v

        return year_text

    # Full academic-year forms, used to classify unlabeled roster values.
    _YEAR_FORMS = {
        'freshman', 'sophomore', 'junior', 'senior', 'graduate',
        'redshirt freshman', 'redshirt sophomore', 'redshirt junior',
        'redshirt senior',
    }

    @staticmethod
    def looks_like_year(text: str) -> bool:
        """True if the text is (or abbreviates to) an academic year.

        Used for card layouts that render height and class as unlabeled,
        order-dependent values.
        """
        if not text:
            return False
        cleaned = FieldExtractors.clean_text(text)
        if cleaned.lower() in FieldExtractors._YEAR_FORMS:
            return True
        return FieldExtractors.normalize_academic_year(cleaned) != cleaned

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

        # Look for patterns like "City, State (High School)"
        match = re.match(r'(.+?)\s*\(([^)]+)\)\s*$', hometown_text)
        if match:
            return (match.group(1).strip(), match.group(2).strip())

        # No high school info, just hometown
        return (hometown_text.strip(), '')

    @staticmethod
    def match_bio_label(label: str) -> Optional[str]:
        """
        Map a roster/bio field label to a canonical Player field name.

        Uses whole-word matching (not substring), so 'Weight' does not match
        height ('ht') and 'High School' does not false-match on stray 'hs'.
        Returns one of: position, height, year, major, hometown, high_school,
        previous_school -- or None if the label is not recognized.
        """
        if not label:
            return None

        norm = re.sub(r'[^a-z0-9 ]', ' ', label.lower())
        words = set(norm.split())

        def has(*tokens: str) -> bool:
            return any(t in words for t in tokens)

        # Order matters: check more specific / combined labels first.
        if has('hometown') or 'home town' in norm:
            # A combined "Hometown / High School" label is handled at apply time.
            return 'hometown'
        if 'previous school' in norm or 'last school' in norm or has('transfer'):
            return 'previous_school'
        if 'high school' in norm or has('hs'):
            return 'high_school'
        if has('position', 'pos'):
            return 'position'
        if has('height', 'ht'):
            return 'height'
        if has('class', 'year', 'yr', 'eligibility', 'cl'):
            return 'year'
        if has('major', 'academic'):
            return 'major'
        return None

    @staticmethod
    def apply_bio_field(store, label: str, value: str) -> bool:
        """
        Apply a single bio label/value pair to a store (a Player or a dict row).

        Only fills fields that are currently empty (never overwrites existing
        data). Returns True if anything was written. This is the single shared
        implementation used by every profile/bio parsing path.
        """
        value = FieldExtractors.clean_text(value)
        if not value or value == '-':
            return False

        field_name = FieldExtractors.match_bio_label(label)
        if not field_name:
            return False

        is_dict = isinstance(store, dict)

        def get(f: str) -> str:
            key = FieldExtractors._FIELD_TO_DICT_KEY.get(f, f) if is_dict else f
            return (store.get(key) or '') if is_dict else (getattr(store, f, '') or '')

        def put(f: str, v: str) -> None:
            key = FieldExtractors._FIELD_TO_DICT_KEY.get(f, f) if is_dict else f
            if is_dict:
                store[key] = v
            else:
                setattr(store, f, v)

        if field_name == 'position':
            if not get('position'):
                put('position', FieldExtractors.extract_position(value))
                return True
        elif field_name == 'height':
            if not get('height'):
                put('height', FieldExtractors.extract_height(value) or value)
                return True
        elif field_name == 'year':
            if not get('year'):
                put('year', FieldExtractors.normalize_academic_year(value))
                return True
        elif field_name == 'major':
            if not get('major'):
                put('major', value)
                return True
        elif field_name == 'hometown':
            changed = False
            hometown, hs = FieldExtractors.extract_hometown_parts(value)
            if hometown and not get('hometown'):
                put('hometown', hometown)
                changed = True
            if hs and not get('high_school'):
                put('high_school', hs)
                changed = True
            return changed
        elif field_name == 'high_school':
            if not get('high_school'):
                put('high_school', value)
                return True
        elif field_name == 'previous_school':
            if not get('previous_school'):
                put('previous_school', value)
                return True
        return False


def parse_player_profile(html, store) -> bool:
    """
    Extract bio fields from a parsed player profile page into a store.

    Handles the three markup variants Sidearm sites use (bio-item spans,
    dl/dt/dd definition lists, and detail tables). `store` may be a Player or
    a CSV dict row. Returns True if any field was populated.
    """
    changed = False

    # 1. div.sidearm-roster-player-bio with label/value spans
    bio_section = html.find('div', class_='sidearm-roster-player-bio')
    if bio_section:
        for item in bio_section.find_all('div', class_='sidearm-roster-player-bio-item'):
            label_elem = item.find('span', class_='sidearm-roster-player-bio-label')
            value_elem = item.find('span', class_='sidearm-roster-player-bio-value')
            if label_elem and value_elem:
                if FieldExtractors.apply_bio_field(store, label_elem.get_text(), value_elem.get_text()):
                    changed = True

    # 2. dl/dt/dd definition list
    dl_section = html.find('dl', class_='sidearm-roster-player-bio')
    if dl_section:
        dts = dl_section.find_all('dt')
        dds = dl_section.find_all('dd')
        for dt, dd in zip(dts, dds):
            if FieldExtractors.apply_bio_field(store, dt.get_text(), dd.get_text()):
                changed = True

    # 3. detail tables (label in first cell, value in second)
    for table in html.find_all('table', class_='sidearm-table'):
        for row in table.find_all('tr'):
            cells = row.find_all(['th', 'td'])
            if len(cells) >= 2:
                if FieldExtractors.apply_bio_field(store, cells[0].get_text(), cells[1].get_text()):
                    changed = True

    return changed


# ============================================================================
# SEASON VERIFICATION
# ============================================================================

class SeasonVerifier:
    """Verify season on roster pages"""

    @staticmethod
    def verify_season_on_page(html, season: str) -> bool:
        """
        Check if the expected season appears on the page.

        Looks at the page title and headings rather than the whole page text,
        because copyright footers (e.g. "(c) 2025") contain the year on almost
        every page and would make this check meaningless.
        """
        candidates = []
        if html.title and html.title.get_text():
            candidates.append(html.title.get_text())
        for tag in html.find_all(['h1', 'h2', 'h3']):
            candidates.append(tag.get_text())
        text = ' '.join(candidates)

        # Fall back to full page text only if we found no title/headings
        if not text.strip():
            text = html.get_text()

        # Check for season year (e.g., '2025')
        if season in text:
            return True

        # Check for season range (e.g., '2024-25' or '2024-2025' when season is '2025')
        try:
            year = int(season)
            prev_year = str(year - 1)
            if f"{prev_year}-{str(year)[-2:]}" in text:
                return True
            if f"{prev_year}-{year}" in text:
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
            'https://goheels.com/sports/field-hockey' -> 'https://goheels.com'
        """
        extracted = tldextract.extract(full_url)

        # Build domain with subdomain if present
        if extracted.subdomain:
            domain = f"{extracted.subdomain}.{extracted.domain}.{extracted.suffix}"
        else:
            domain = f"{extracted.domain}.{extracted.suffix}"

        return f"https://{domain}"

    @staticmethod
    def domain_for_url(base_url: str) -> str:
        """Return the host (with subdomain) for building absolute profile URLs."""
        extracted = tldextract.extract(base_url)
        domain = f"{extracted.domain}.{extracted.suffix}"
        if extracted.subdomain:
            domain = f"{extracted.subdomain}.{domain}"
        return domain


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
# FETCHERS
# ============================================================================

class RequestsFetcher:
    """Fetch pages with requests/cloudscraper (no JS rendering)."""

    def __init__(self, session: Optional[requests.Session] = None):
        if session:
            self.session = session
            self._cloud = False
        elif CLOUDSCRAPER_AVAILABLE:
            self.session = cloudscraper.create_scraper()
            self._cloud = True
            logger.info("RequestsFetcher: using cloudscraper to bypass bot protection")
        else:
            self.session = requests.Session()
            self._cloud = False
            logger.warning("RequestsFetcher: cloudscraper not available, using plain requests (403s likely)")

        # Custom headers are only applied for plain requests. cloudscraper manages
        # its own User-Agent/TLS fingerprint, and overriding them can break it.
        self.headers = {
            'User-Agent': DEFAULT_USER_AGENT,
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
            'Cache-Control': 'max-age=0',
        }

    def _request_headers(self, referer: Optional[str]) -> Dict[str, str]:
        headers = {} if self._cloud else self.headers.copy()
        if referer:
            headers['Referer'] = referer
            headers['Origin'] = referer
        return headers or None

    def warm(self, domain_base: str) -> None:
        """Visit the base domain to establish cookies/session (best effort)."""
        try:
            self.session.get(domain_base, headers=self._request_headers(None),
                             timeout=10, allow_redirects=True)
            time.sleep(0.5)
        except requests.RequestException as e:
            logger.debug(f"RequestsFetcher warm-up failed for {domain_base}: {e}")

    def fetch(self, url: str, referer: Optional[str] = None,
              wait_selector: Optional[str] = None, wait_ms: Optional[int] = None,
              timeout: int = 30) -> Tuple[int, bytes]:
        # wait_selector/wait_ms are accepted for API parity with BrowserFetcher
        response = self.session.get(url, headers=self._request_headers(referer),
                                    timeout=timeout, allow_redirects=True)
        return response.status_code, response.content

    def fetch_many(self, items, wait_selector=None, wait_ms=None, concurrency=None):
        """Serial fetch (the requests fallback does not parallelize)."""
        results = []
        for item in items:
            url, referer = item if isinstance(item, tuple) else (item, None)
            try:
                results.append(self.fetch(url, referer=referer))
            except requests.RequestException as e:
                logger.warning(f"RequestsFetcher error for {url}: {e}")
                results.append((0, None))
        return results

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass


# Wait for roster-specific content to render. A bare `table` is deliberately
# excluded: it matches stray page tables (nav/footer) in the initial HTML and
# would let the wait return before a Vue/JS roster mounts.
ROSTER_WAIT_SELECTOR = (
    'li.sidearm-roster-player, li.roster-list-item, .roster-card-item, '
    '.s-person-card, table.sidearm-table'
)
PROFILE_WAIT_SELECTOR = '.sidearm-roster-player-bio, table.sidearm-table'


class BrowserFetcher:
    """Fetch pages by rendering them in a real headless Chromium via Playwright.

    One browser + context is launched on a dedicated asyncio loop (running in a
    background thread) and reused for the whole run. Pages are fetched
    concurrently, bounded by a semaphore, so many profile pages can render at
    once. Images/fonts/media are blocked, a short jittered delay plus limited
    retries keep the scraper polite and resilient. The public API is synchronous
    so the rest of the scraper stays simple.
    """

    def __init__(self, headless: bool = True, block_assets: bool = True,
                 min_delay: float = 0.3, max_delay: float = 0.8, retries: int = 2,
                 nav_timeout_ms: int = 30000, content_wait_ms: int = 2500,
                 max_concurrency: int = 6, max_per_host: int = 3,
                 executable_path: Optional[str] = None):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.retries = retries
        self.nav_timeout_ms = nav_timeout_ms
        self.content_wait_ms = content_wait_ms
        self.max_concurrency = max(1, max_concurrency)
        self.max_per_host = max(1, max_per_host)
        self.pages_fetched = 0
        self._host_sems: Dict[str, "asyncio.Semaphore"] = {}

        # Dedicated event loop on a background thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self._run(self._async_init(headless, block_assets, executable_path))
        logger.info(f"BrowserFetcher: launched headless Chromium (max_concurrency={self.max_concurrency})")

    # -- event loop plumbing --------------------------------------------------

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    async def _async_init(self, headless, block_assets, executable_path) -> None:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
        self._PWTimeout = PWTimeout
        self._pw = await async_playwright().start()
        launch_kwargs: Dict[str, Any] = {'headless': headless}
        if executable_path:
            launch_kwargs['executable_path'] = executable_path
        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            viewport={'width': 1366, 'height': 900},
        )
        if block_assets:
            await self._context.route('**/*', self._route)

    @staticmethod
    async def _route(route):
        if route.request.resource_type in ('image', 'media', 'font'):
            await route.abort()
        else:
            await route.continue_()

    # -- fetching -------------------------------------------------------------

    def _host_sem(self, url: str) -> "asyncio.Semaphore":
        # Called only from the loop thread, so plain dict access is safe.
        host = urlparse(url).netloc
        sem = self._host_sems.get(host)
        if sem is None:
            sem = asyncio.Semaphore(self.max_per_host)
            self._host_sems[host] = sem
        return sem

    async def _fetch_one(self, sem, url, referer, wait_selector, wait_ms):
        host_sem = self._host_sem(url)
        async with sem, host_sem:
            if self.max_delay > 0:
                await asyncio.sleep(random.uniform(self.min_delay, self.max_delay))

            last_err = None
            for attempt in range(self.retries + 1):
                page = await self._context.new_page()
                try:
                    extra = {'referer': referer} if referer else {}
                    response = await page.goto(url, wait_until='domcontentloaded',
                                               timeout=self.nav_timeout_ms, **extra)
                    status = response.status if response else 200

                    # Best-effort bounded wait for content (never a hard tax)
                    if wait_selector:
                        try:
                            await page.wait_for_selector(wait_selector, timeout=wait_ms)
                        except self._PWTimeout:
                            pass

                    html = await page.content()
                    self.pages_fetched += 1
                    return (status, html)
                except Exception as e:
                    last_err = e
                    logger.warning(f"BrowserFetcher error ({attempt + 1}/{self.retries + 1}) for {url}: {e}")
                finally:
                    await page.close()

                if attempt < self.retries:
                    await asyncio.sleep(2 ** attempt)  # exponential backoff

            logger.error(f"BrowserFetcher failed for {url}: {last_err}")
            return (0, None)

    async def _fetch_many(self, items, wait_selector, wait_ms, concurrency):
        sem = asyncio.Semaphore(concurrency)
        tasks = [self._fetch_one(sem, url, referer, wait_selector, wait_ms)
                 for (url, referer) in items]
        return await asyncio.gather(*tasks)

    def fetch_many(self, items, wait_selector: Optional[str] = None,
                   wait_ms: Optional[int] = None, concurrency: Optional[int] = None):
        """Fetch many URLs concurrently.

        items: list of url strings or (url, referer) tuples.
        Returns a list of (status, html|None) aligned to the input order.
        """
        norm = [(i if isinstance(i, tuple) else (i, None)) for i in items]
        if not norm:
            return []
        wait_ms = self.content_wait_ms if wait_ms is None else wait_ms
        concurrency = self.max_concurrency if concurrency is None else max(1, concurrency)
        return self._run(self._fetch_many(norm, wait_selector, wait_ms, concurrency))

    def fetch(self, url: str, referer: Optional[str] = None,
              wait_selector: Optional[str] = ROSTER_WAIT_SELECTOR,
              wait_ms: Optional[int] = None) -> Tuple[int, Optional[str]]:
        return self.fetch_many([(url, referer)], wait_selector=wait_selector,
                               wait_ms=wait_ms, concurrency=1)[0]

    def warm(self, domain_base: str) -> None:
        # Navigation establishes cookies naturally; no separate warm-up needed.
        return

    async def _async_close(self) -> None:
        await self._context.close()
        await self._browser.close()
        await self._pw.stop()

    def close(self) -> None:
        try:
            self._run(self._async_close())
        except Exception:
            pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
        except Exception:
            pass


def build_fetcher(mode: str = 'auto', **browser_kwargs):
    """
    Construct a fetcher.

    mode:
        'browser'  - require Playwright browser rendering
        'requests' - use requests/cloudscraper only
        'auto'     - use the browser if Playwright is importable, else requests

    browser_kwargs are forwarded to BrowserFetcher (e.g. max_concurrency,
    min_delay, max_delay) and ignored by the requests fetcher.
    """
    if mode == 'requests':
        return RequestsFetcher()

    if mode in ('auto', 'browser'):
        try:
            return BrowserFetcher(**browser_kwargs)
        except Exception as e:
            if mode == 'browser':
                raise
            logger.warning(f"Falling back to requests fetcher (browser unavailable: {e})")
            return RequestsFetcher()

    logger.warning(f"Unknown fetch mode '{mode}', using auto")
    return build_fetcher('auto', **browser_kwargs)


# ============================================================================
# STANDARD SCRAPER
# ============================================================================

class StandardScraper:
    """Scraper for standard Sidearm Sports sites"""

    # Core roster fields; a player is "complete" (no profile fetch needed) when
    # all of these are present.
    CORE_FIELDS = ('position', 'height', 'year', 'hometown')

    def __init__(self, fetcher=None, fetch_mode: str = 'auto', profiles_mode: str = 'missing',
                 scrape_profiles: Optional[bool] = None, concurrency: int = 6,
                 per_host: int = 3, delay_min: float = 0.3, delay_max: float = 0.8):
        """Initialize scraper

        Args:
            fetcher: Optional pre-built fetcher (BrowserFetcher/RequestsFetcher)
            fetch_mode: 'auto' | 'browser' | 'requests' (used if fetcher is None)
            profiles_mode: 'missing' (fetch a profile only when core fields are
                missing), 'always', or 'never'
            scrape_profiles: Back-compat shim; True -> 'always', False -> 'never'
            concurrency: max concurrent page loads (global)
            per_host: max concurrent page loads per site
        """
        if scrape_profiles is not None:
            profiles_mode = 'always' if scrape_profiles else 'never'
        self.profiles_mode = profiles_mode

        if fetcher is not None:
            self.fetcher = fetcher
        else:
            self.fetcher = build_fetcher(
                fetch_mode, max_concurrency=concurrency, max_per_host=per_host,
                min_delay=delay_min, max_delay=delay_max,
            )

    def close(self) -> None:
        if self.fetcher:
            self.fetcher.close()

    @classmethod
    def _needs_profile(cls, player: Player) -> bool:
        """A player needs a profile fetch if any core field is still empty."""
        return any(not getattr(player, f, '') for f in cls.CORE_FIELDS)

    @staticmethod
    def _referer_for(url: str) -> Optional[str]:
        return url.split('/sports')[0] if '/sports' in url else None

    def scrape_team(self, team_id: int, team_name: str, base_url: str, season: str,
                    division: str = "") -> TeamResult:
        """Scrape a single team (roster + profile enrichment)."""
        result = self.scrape_rosters(
            [{'ncaa_id': team_id, 'team': team_name, 'url': base_url}], season, division
        )[0]
        if result.status == 'ok':
            self.enrich_profiles(result.players)
        return result

    def scrape_rosters(self, teams: List[Dict], season: str, division: str = "") -> List[TeamResult]:
        """
        Fetch and parse roster pages for several teams concurrently (no profile
        enrichment). Returns a TeamResult per team, aligned to `teams` order.

        404s on the season-specific URL are retried in waves (/roster, then
        /roster.aspx) so the fallback logic still applies under concurrency.
        """
        # entries: [team, current_url, referer]
        entries = []
        for t in teams:
            fmt = TeamConfig.get_url_format(t['ncaa_id'], t['url'])
            url = URLBuilder.build_roster_url(t['url'], season, fmt)
            entries.append([t, url, self._referer_for(t['url']) or t['url']])

        logger.info(f"Fetching {len(entries)} roster page(s)")
        results = list(self.fetcher.fetch_many(
            [(e[1], e[2]) for e in entries], wait_selector=ROSTER_WAIT_SELECTOR))

        def retry_wave(indices, suffix):
            items = [(entries[i][0]['url'].rstrip('/') + suffix, entries[i][2]) for i in indices]
            waved = self.fetcher.fetch_many(items, wait_selector=ROSTER_WAIT_SELECTOR)
            for j, i in enumerate(indices):
                results[i] = waved[j]
                entries[i][1] = items[j][0]

        # Modern Sidearm sites serve season rosters at /roster/season/<year>;
        # try that before the bare /roster (current season) and legacy .aspx.
        for suffix in (f'/roster/season/{season}', '/roster', '/roster.aspx'):
            todo = [i for i, (s, _h) in enumerate(results) if s == 404]
            if not todo:
                break
            logger.info(f"Retrying {len(todo)} team(s) with {suffix}")
            retry_wave(todo, suffix)

        out = []
        for (team, url, _ref), (status, html) in zip(entries, results):
            out.append(self._parse_roster_result(team, season, division, status, html))
        return out

    def _parse_roster_result(self, team: Dict, season: str, division: str,
                             status: int, html: Optional[str]) -> TeamResult:
        team_name = team['team']
        if status != 200 or not html:
            logger.warning(f"Failed to retrieve {team_name} - Status: {status}")
            return TeamResult(players=[], status='http_error', detail=f"HTTP {status}")

        soup = BeautifulSoup(html, 'html.parser')
        if not SeasonVerifier.verify_season_on_page(soup, season):
            logger.warning(f"Season mismatch for {team_name} (continuing anyway)")

        players = self._extract_players(soup, team['ncaa_id'], team_name, season, division, team['url'])
        if not players:
            logger.warning(f"{team_name}: page fetched but no players parsed")
            return TeamResult(players=[], status='empty', detail='no players parsed')

        logger.info(f"OK {team_name}: Found {len(players)} players")
        return TeamResult(players=players, status='ok')

    def enrich_profiles(self, players: List[Player]) -> None:
        """
        Concurrently fetch profile pages for the given players (in place),
        subject to profiles_mode. Fetches are bounded by the fetcher's global
        and per-host concurrency caps.
        """
        if self.profiles_mode == 'never':
            return

        targets = [p for p in players if p.url and
                   (self.profiles_mode == 'always' or self._needs_profile(p))]
        if not targets:
            return

        logger.info(f"Enriching {len(targets)} player profile(s)")
        items = [(p.url, self._referer_for(p.url)) for p in targets]
        results = self.fetcher.fetch_many(items, wait_selector=PROFILE_WAIT_SELECTOR)

        for player, (status, html) in zip(targets, results):
            if status == 200 and html:
                try:
                    parse_player_profile(BeautifulSoup(html, 'html.parser'), player)
                except Exception as e:
                    logger.warning(f"Error parsing profile for {player.name}: {e}")
            else:
                logger.warning(f"Failed to fetch profile for {player.name}: {status}")

    def _extract_players(self, html, team_id: int, team_name: str, season: str,
                         division: str, base_url: str) -> List[Player]:
        """Extract players from HTML"""
        players = []

        # Find all player list items (classic Sidearm pattern)
        roster_items = html.find_all('li', class_='sidearm-roster-player')

        if not roster_items:
            # Modern Sidearm layouts replaced the classic markup on many sites.
            # Try each newer layout, then fall back to a generic table.
            for extractor in (self._extract_list_items, self._extract_card_items,
                              self._extract_person_cards):
                players = extractor(html, team_id, team_name, season, division, base_url)
                if players:
                    return players
            logger.warning(f"No roster items found for {team_name} (expected class='sidearm-roster-player')")
            # Try table-based format
            return self._extract_players_from_table(html, team_id, team_name, season, division, base_url)

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
                        profile_url = self._absolute_url(base_url, name_link['href'])
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

                meta_fields = item.find_all('div', class_='sidearm-roster-player-custom-fields')
                for meta in meta_fields:
                    label_elem = meta.find('span', class_='sidearm-roster-player-custom-field-label')
                    value_elem = meta.find('span', class_='sidearm-roster-player-custom-field-value')

                    if label_elem and value_elem:
                        label = FieldExtractors.clean_text(label_elem.get_text())
                        value = FieldExtractors.clean_text(value_elem.get_text())
                        field_name = FieldExtractors.match_bio_label(label)

                        if field_name == 'position':
                            position = FieldExtractors.extract_position(value)
                        elif field_name == 'year':
                            year = FieldExtractors.normalize_academic_year(value)
                        elif field_name == 'hometown':
                            hometown, hs = FieldExtractors.extract_hometown_parts(value)
                            if hs:
                                high_school = hs
                        elif field_name == 'high_school':
                            high_school = value
                        elif field_name == 'height':
                            height = FieldExtractors.extract_height(value)

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
                    url=profile_url,
                )

                players.append(player)

            except Exception as e:
                logger.warning(f"Error parsing player in {team_name}: {e}")
                continue

        return players

    @staticmethod
    def _absolute_url(base_url: str, href: str) -> str:
        """Resolve a possibly-relative href against the roster page URL.

        Uses urljoin so the scheme/host/port are preserved correctly (more
        robust than reconstructing the host by hand).
        """
        if not href:
            return ''
        return urljoin(base_url if base_url.endswith('/') else base_url + '/', href)

    def _extract_list_items(self, html, team_id, team_name, season, division, base_url):
        """Extract players from the modern Sidearm list layout.

        Player is ``li.roster-list-item``; the name/profile link is
        ``a.roster-list-item__title`` and each bio field is a
        ``roster-player-list-profile-field`` element whose ``--modifier`` class
        (e.g. ``--class-level``, ``--position``, ``--hometown``) names the field.
        """
        players = []
        for item in html.find_all('li', class_='roster-list-item'):
            try:
                jersey_elem = item.find(class_='roster-list-item__jersey-number')
                jersey = FieldExtractors.extract_jersey_number(
                    FieldExtractors.clean_text(jersey_elem.get_text())) if jersey_elem else ''
                # Coaches/staff share this markup but carry no jersey number.
                if not jersey:
                    continue

                name_link = item.find('a', class_='roster-list-item__title', href=True)
                if not name_link:
                    continue
                name = FieldExtractors.clean_text(name_link.get_text())
                profile_url = self._absolute_url(base_url, name_link['href'])

                player = Player(team_id=team_id, team=team_name, season=season,
                                division=division, name=name, jersey=jersey, url=profile_url)

                for fld in item.find_all(class_='roster-player-list-profile-field'):
                    modifier = next((c.split('--', 1)[1] for c in (fld.get('class') or [])
                                     if '--' in c), '')
                    if modifier:
                        FieldExtractors.apply_bio_field(player, modifier.replace('-', ' '),
                                                        fld.get_text())
                players.append(player)
            except Exception as e:
                logger.warning(f"Error parsing list item in {team_name}: {e}")
        return players

    def _extract_card_items(self, html, team_id, team_name, season, division, base_url):
        """Extract players from the modern Sidearm card layout.

        Player is ``.roster-card-item``; name is ``a.roster-card-item__title-link``,
        position (which may be multi-position, e.g. ``M/F``) is
        ``.roster-card-item__position``, and remaining bio fields are
        ``span.profile-field-content`` (title/value) pairs.
        """
        players = []
        for item in html.find_all(class_='roster-card-item'):
            try:
                # Name/profile link: sites use either __title-link or the
                # __title--link modifier on the title anchor.
                name_link = (item.find('a', class_='roster-card-item__title-link', href=True)
                             or item.find('a', class_='roster-card-item__title--link', href=True)
                             or item.find('a', class_='roster-card-item__title', href=True))
                if not name_link:
                    continue
                name = FieldExtractors.clean_text(name_link.get_text())
                profile_url = self._absolute_url(base_url, name_link['href'])

                # Jersey lives under one of several class names across variants.
                jersey_elem = item.find(class_=['roster-card-item__jersey-number',
                                                'roster-card-jersey-number',
                                                'roster-card-item__number'])
                jersey = FieldExtractors.extract_jersey_number(
                    FieldExtractors.clean_text(jersey_elem.get_text())) if jersey_elem else ''
                # Coaches/staff share this markup but carry no jersey number.
                if not jersey:
                    continue

                player = Player(team_id=team_id, team=team_name, season=season,
                                division=division, name=name, jersey=jersey, url=profile_url)

                pos_elem = item.find(class_='roster-card-item__position')
                if pos_elem:
                    raw_pos = FieldExtractors.clean_text(pos_elem.get_text())
                    # Preserve multi-position codes (e.g. "D/M"); normalize a
                    # single full-word/abbrev position (e.g. "Back" -> "D").
                    player.position = raw_pos if '/' in raw_pos else \
                        (FieldExtractors.extract_position(raw_pos) or raw_pos)

                # Field markup A: span.profile-field-content (title/value pairs).
                for field_el in item.find_all(class_='profile-field-content'):
                    label_el = field_el.find(class_='profile-field-content__title')
                    value_el = field_el.find(class_='profile-field-content__value')
                    if label_el and value_el:
                        FieldExtractors.apply_bio_field(player, label_el.get_text(),
                                                        value_el.get_text())

                # Field markup B: div.roster-player-card-profile-field, where a
                # field is either labeled (__label + __value) or a run of
                # unlabeled, order-independent __value spans (height, class).
                for field_el in item.find_all(class_='roster-player-card-profile-field'):
                    label_el = field_el.find(class_='roster-player-card-profile-field__label')
                    values = field_el.find_all(class_='roster-player-card-profile-field__value')
                    if label_el:
                        for v in values:
                            FieldExtractors.apply_bio_field(player, label_el.get_text(), v.get_text())
                    else:
                        for v in values:
                            self._apply_unlabeled_value(player, v.get_text())

                # Field markup C: div.roster-card-component__profile-box holding
                # bare, unlabeled <strong>/<span> values (position, class, then
                # hometown, high school) in document order.
                for box in item.find_all(class_='roster-card-component__profile-box'):
                    for v in box.find_all(['strong', 'span']):
                        self._apply_unlabeled_value(player, v.get_text())
                players.append(player)
            except Exception as e:
                logger.warning(f"Error parsing card item in {team_name}: {e}")
        return players

    @staticmethod
    def _apply_unlabeled_value(player: Player, value: str) -> None:
        """Classify an unlabeled, order-dependent roster value by its content.

        Card layouts that omit field labels render values (height, class,
        position, hometown, high school) as bare spans. Each is classified by
        shape and written only to a still-empty field.
        """
        value = FieldExtractors.clean_text(value)
        if not value:
            return
        # Height, e.g. 5'5" / 1.72m
        if not player.height and FieldExtractors.extract_height(value):
            player.height = FieldExtractors.extract_height(value)
            return
        # Academic year, e.g. "Junior", "4th Year"
        if not player.year and FieldExtractors.looks_like_year(value):
            player.year = FieldExtractors.normalize_academic_year(value)
            return
        # Position: a short, comma-free code/word (e.g. "Defender", "D/M")
        if not player.position and ',' not in value and len(value) <= 20:
            pos = FieldExtractors.extract_position(value)
            if pos:
                player.position = value if '/' in value else pos
                return
        # Hometown: "City, State" style (contains a comma)
        if not player.hometown and ',' in value:
            hometown, hs = FieldExtractors.extract_hometown_parts(value)
            if hometown:
                player.hometown = hometown
            if hs and not player.high_school:
                player.high_school = hs
            return
        # High school: a leftover value that follows a hometown in the same group
        if not player.high_school and player.hometown:
            player.high_school = value

    def _extract_person_cards(self, html, team_id, team_name, season, division, base_url):
        """Extract players from the Sidearm ``s-person-card`` design-system layout.

        Only cards inside ``.c-rosterpage__players`` are players (coaches and
        support staff use the same card elsewhere on the page). Each bio field is
        an element with an inner ``.sr-only`` label followed by the value text.
        """
        container = html.find(class_='c-rosterpage__players') or html
        players = []
        seen = set()
        for item in container.find_all(class_='s-person-card'):
            try:
                name_link = item.find('a', href=True)
                heading = item.find('h3')
                if not (name_link and heading):
                    continue
                name = FieldExtractors.clean_text(heading.get_text())
                profile_url = self._absolute_url(base_url, name_link['href'])
                if profile_url in seen:
                    continue
                seen.add(profile_url)

                # This card design is shared by players and staff (coaches,
                # support). Players carry a jersey-number stamp; staff do not, so
                # a missing jersey number is the signal to skip a non-player card.
                stamp = item.find(class_='s-stamp__text')
                jersey = FieldExtractors.extract_jersey_number(
                    FieldExtractors.clean_text(self._text_without_sr_only(stamp))) if stamp else ''
                if not jersey:
                    continue

                player = Player(team_id=team_id, team=team_name, season=season,
                                division=division, name=name, jersey=jersey, url=profile_url)

                # Each bio field is a leaf element carrying its own .sr-only
                # label; several such leaves may share a container (hometown,
                # last school, major), so read the label from each leaf. Labels
                # apply_bio_field does not recognize (jersey, social links) are
                # ignored, so a blanket sweep of sr-only labels is safe.
                for label_el in item.find_all(class_='sr-only'):
                    leaf = label_el.parent
                    if leaf is None:
                        continue
                    value = self._text_without_sr_only(leaf)
                    FieldExtractors.apply_bio_field(player, label_el.get_text(), value)
                players.append(player)
            except Exception as e:
                logger.warning(f"Error parsing person card in {team_name}: {e}")
        return players

    @staticmethod
    def _text_without_sr_only(element) -> str:
        """Return an element's text with any nested ``.sr-only`` labels removed."""
        clone = BeautifulSoup(str(element), 'html.parser')
        for sr in clone.find_all(class_='sr-only'):
            sr.decompose()
        return FieldExtractors.clean_text(clone.get_text())

    @staticmethod
    def _row_is_header(row) -> bool:
        """A row is a header if it has <th> cells and no <td> cells."""
        return bool(row.find('th')) and not row.find('td')

    def _extract_players_from_table(self, html, team_id: int, team_name: str, season: str,
                                    division: str, base_url: str) -> List[Player]:
        """Extract players from table-based roster"""
        players = []

        # Find roster table (prefer the Sidearm table class)
        table = html.find('table', class_='sidearm-table')
        if not table:
            table = html.find('table')

        if not table:
            logger.warning(f"No table found for {team_name}")
            return players

        # Find header row to map columns
        header_row = table.find('thead')
        if header_row:
            header_row = header_row.find('tr') or header_row
        else:
            header_row = table.find('tr')

        if not header_row:
            logger.warning(f"No header row found in table for {team_name}")
            return players

        # Map column indices
        headers = [FieldExtractors.clean_text(th.get_text()) for th in header_row.find_all(['th', 'td'])]
        headers_lower = [h.lower() for h in headers]
        # Use the shared bio-label matcher so table headers (e.g. "Cl.", "Ht.")
        # resolve the same way as profile labels.
        bio_fields = [FieldExtractors.match_bio_label(h) for h in headers]

        def field_idx(field_name):
            return next((i for i, f in enumerate(bio_fields) if f == field_name), None)

        name_idx = next((i for i, h in enumerate(headers_lower) if 'name' in h), None)
        jersey_idx = next((i for i, h in enumerate(headers_lower)
                           if '#' in h or 'number' in h or 'jersey' in h), None)
        pos_idx = field_idx('position')
        year_idx = field_idx('year')
        height_idx = field_idx('height')
        hometown_idx = field_idx('hometown')
        hs_idx = field_idx('high_school')

        # Extract rows. Only skip the first row if it is actually a header
        # (fixes the previous bug that unconditionally dropped the first player).
        tbody = table.find('tbody') or table
        rows = tbody.find_all('tr')
        if rows and self._row_is_header(rows[0]):
            rows = rows[1:]

        for row in rows:
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
                        profile_url = self._absolute_url(base_url, name_link['href'])
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
                    position = FieldExtractors.extract_position(FieldExtractors.clean_text(cols[pos_idx].get_text()))

                # Year
                year = ''
                if year_idx is not None and year_idx < len(cols):
                    year = FieldExtractors.normalize_academic_year(FieldExtractors.clean_text(cols[year_idx].get_text()))

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
                    url=profile_url,
                )

                players.append(player)

            except Exception as e:
                logger.warning(f"Error parsing row in {team_name}: {e}")
                continue

        return players


# ============================================================================
# ROSTER MANAGER
# ============================================================================

class RosterManager:
    """Manages batch scraping of rosters with error tracking and caching."""

    def __init__(self, season: str = '2025', output_dir: str = None,
                 profiles_mode: str = 'missing', fetch_mode: str = 'auto',
                 concurrency: int = 6, per_host: int = 3,
                 delay_min: float = 0.3, delay_max: float = 0.8):
        self.season = season
        self.output_dir = Path(output_dir) if output_dir else (REPO_ROOT / 'data' / 'raw')
        self.concurrency = max(1, concurrency)
        self.scraper = StandardScraper(
            fetch_mode=fetch_mode, profiles_mode=profiles_mode,
            concurrency=concurrency, per_host=per_host,
            delay_min=delay_min, delay_max=delay_max,
        )

        # Error tracking
        self.zero_player_teams = []
        self.failed_teams = []
        self.successful_teams = []

    def load_teams(self, csv_path: str) -> List[Dict]:
        """Load teams from CSV"""
        teams = []
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not (row.get('school') and row.get('url')):
                    continue
                try:
                    ncaa_id = int(row['org_id'])
                except (ValueError, KeyError):
                    logger.warning(f"Skipping row with invalid org_id: {row.get('school')}")
                    continue
                teams.append({'team': row['school'], 'ncaa_id': ncaa_id, 'url': row['url']})

        logger.info(f"Loaded {len(teams)} teams")
        return teams

    def _cache_file(self, team_id: int) -> Path:
        return self.output_dir / 'teams' / f'{team_id}_{self.season}.json'

    def _load_cache(self, team: Dict) -> Optional[Dict]:
        """Return cached data for a team if it is a settled (ok/empty) result.

        Prior failures return None so they are retried automatically.
        """
        cache_file = self._cache_file(team['ncaa_id'])
        if not cache_file.exists():
            return None
        try:
            with open(cache_file) as f:
                cached = json.load(f)
        except Exception as e:
            logger.warning(f"  Cache read failed for {team['team']}, re-scraping: {e}")
            return None
        if cached.get('status') in ('ok', 'empty'):
            return cached
        logger.info(f"  Retrying previously failed team (cached status={cached.get('status')})")
        return None

    def _write_cache(self, team: Dict, result: "TeamResult", player_dicts: List[Dict]) -> None:
        try:
            with open(self._cache_file(team['ncaa_id']), 'w') as f:
                json.dump({
                    'team': team['team'], 'ncaa_id': team['ncaa_id'], 'url': team['url'],
                    'status': result.status, 'detail': result.detail,
                    'player_count': len(player_dicts), 'players': player_dicts,
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"  Failed to write cache for {team['team']}: {e}")

    def scrape_teams(self, teams: List[Dict], max_teams: Optional[int] = None,
                     refresh: bool = False) -> List[Dict]:
        """
        Scrape rosters for multiple teams, caching each team's result to disk so
        an interrupted run can resume without re-scraping completed teams.

        Returns a list of player dicts (CSV/JSON-ready).
        """
        all_player_dicts: List[Dict] = []
        teams_to_scrape = teams[:max_teams] if max_teams else teams

        (self.output_dir / 'teams').mkdir(parents=True, exist_ok=True)

        logger.info(f"Starting scrape of {len(teams_to_scrape)} teams "
                    f"(concurrency={self.concurrency})")
        logger.info("=" * 80)

        # Process teams in batches; roster pages and profiles within a batch are
        # fetched concurrently (bounded by the fetcher's global/per-host caps).
        for start in range(0, len(teams_to_scrape), self.concurrency):
            batch = teams_to_scrape[start:start + self.concurrency]

            # Serve settled teams straight from cache; scrape the rest.
            pending: List[Dict] = []
            for offset, team in enumerate(batch, start=start + 1):
                logger.info(f"[{offset}/{len(teams_to_scrape)}] {team['team']}")
                cached = self._load_cache(team) if not refresh else None
                if cached is not None:
                    status = cached.get('status', 'empty')
                    logger.info(f"  (cached) status={status} players={cached.get('player_count', 0)}")
                    self._record(team, status, cached.get('players', []), cached.get('detail', ''))
                    all_player_dicts.extend(cached.get('players', []))
                else:
                    pending.append(team)

            if not pending:
                continue

            results = self.scraper.scrape_rosters(pending, self.season)

            # Enrich profiles for the whole batch in one concurrent pass
            batch_players = [p for r in results for p in r.players]
            self.scraper.enrich_profiles(batch_players)

            for team, result in zip(pending, results):
                player_dicts = [p.to_dict() for p in result.players]
                self._write_cache(team, result, player_dicts)
                self._record(team, result.status, player_dicts, result.detail)
                all_player_dicts.extend(player_dicts)

        logger.info("=" * 80)
        logger.info("Scraping complete:")
        logger.info(f"  Successful: {len(self.successful_teams)} teams, {len(all_player_dicts)} players")
        logger.info(f"  Zero players: {len(self.zero_player_teams)} teams")
        logger.info(f"  Failed: {len(self.failed_teams)} teams")

        return all_player_dicts

    def _record(self, team: Dict, status: str, player_dicts: List[Dict], detail: str) -> None:
        """Categorize a team's outcome into the correct report bucket."""
        team_name = team['team']
        team_id = team['ncaa_id']
        team_url = team['url']

        if status == 'ok' and player_dicts:
            self.successful_teams.append({
                'team': team_name, 'ncaa_id': team_id, 'player_count': len(player_dicts),
            })
        elif status in ('http_error', 'error'):
            logger.warning(f"  FAILED: {detail}")
            self.failed_teams.append({
                'team': team_name, 'ncaa_id': team_id, 'url': team_url, 'error': detail,
            })
        else:  # 'empty' or ok-with-zero
            logger.warning("  Zero players found")
            self.zero_player_teams.append({
                'team': team_name, 'ncaa_id': team_id, 'url': team_url,
            })

    def save_results(self, player_dicts: List[Dict]):
        """Save results to JSON and CSV"""
        json_file = self.output_dir / 'json' / f'rosters_fhockey_{self.season}.json'
        csv_file = self.output_dir / 'csv' / f'rosters_fhockey_{self.season}.csv'

        json_file.parent.mkdir(parents=True, exist_ok=True)
        csv_file.parent.mkdir(parents=True, exist_ok=True)

        with open(json_file, 'w') as f:
            json.dump(player_dicts, f, indent=2)
        logger.info(f"OK Saved JSON: {json_file} ({len(player_dicts)} players)")

        if player_dicts:
            # Use the union of keys so no field is silently dropped
            fieldnames = list(player_dicts[0].keys())
            for d in player_dicts:
                for k in d:
                    if k not in fieldnames:
                        fieldnames.append(k)
            with open(csv_file, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(player_dicts)
            logger.info(f"OK Saved CSV: {csv_file}")

        self._save_error_reports()

    def _save_error_reports(self):
        """Save error reports for teams with issues"""
        reports_dir = self.output_dir / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)

        if self.zero_player_teams:
            zero_file = reports_dir / f'zero_players_fhockey_{self.season}.json'
            with open(zero_file, 'w') as f:
                json.dump(self.zero_player_teams, f, indent=2)
            logger.info(f"OK Saved zero players report: {zero_file}")

        if self.failed_teams:
            failed_file = reports_dir / f'failed_teams_fhockey_{self.season}.json'
            with open(failed_file, 'w') as f:
                json.dump(self.failed_teams, f, indent=2)
            logger.info(f"OK Saved failed teams report: {failed_file}")

    def close(self):
        self.scraper.close()


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
  # Scrape all teams (browser rendering by default)
  uv run src/fhockey_roster_scraper.py --season 2025

  # Scrape first 10 teams (testing)
  uv run src/fhockey_roster_scraper.py --limit 10 --season 2025

  # Scrape specific team
  uv run src/fhockey_roster_scraper.py --team 457 --season 2025

  # Faster: skip profile pages entirely (roster list only)
  uv run src/fhockey_roster_scraper.py --profiles never --season 2025

  # Force plain HTTP instead of a browser
  uv run src/fhockey_roster_scraper.py --fetch requests --season 2025
        """
    )

    parser.add_argument('--season', default='2025', help='Season year (default: 2025)')
    parser.add_argument('--team', type=int, help='Scrape specific team by NCAA ID')
    parser.add_argument('--limit', type=int, help='Limit number of teams to scrape (for testing)')
    parser.add_argument('--teams-csv', default=str(REPO_ROOT / 'teams.csv'),
                        help='Path to teams.csv (default: <repo>/teams.csv)')
    parser.add_argument('--output-dir', default=str(REPO_ROOT / 'data' / 'raw'),
                        help='Output directory (default: <repo>/data/raw)')
    parser.add_argument('--fetch', choices=['auto', 'browser', 'requests'], default='auto',
                        help='Fetch strategy: auto (browser if available), browser, or requests')
    parser.add_argument('--refresh', action='store_true',
                        help='Ignore cached per-team results and re-scrape')
    parser.add_argument('--profiles', choices=['missing', 'always', 'never'], default='missing',
                        help="When to fetch player profile pages: 'missing' (only when the "
                             "roster omits core fields; default), 'always', or 'never' (fastest)")
    # Back-compat alias: --no-scrape-profiles == --profiles never
    parser.add_argument('--no-scrape-profiles', dest='profiles', action='store_const',
                        const='never', help=argparse.SUPPRESS)
    parser.add_argument('--concurrency', type=int, default=6,
                        help='Max concurrent page loads, global (default: 6)')
    parser.add_argument('--per-host', type=int, default=3,
                        help='Max concurrent page loads per site, e.g. profiles (default: 3)')
    parser.add_argument('--delay-min', type=float, default=0.3,
                        help='Minimum jittered delay before each fetch, seconds (default: 0.3)')
    parser.add_argument('--delay-max', type=float, default=0.8,
                        help='Maximum jittered delay before each fetch, seconds (default: 0.8)')

    args = parser.parse_args()

    start_time = time.time()
    manager = RosterManager(season=args.season, output_dir=args.output_dir,
                            profiles_mode=args.profiles, fetch_mode=args.fetch,
                            concurrency=args.concurrency, per_host=args.per_host,
                            delay_min=args.delay_min, delay_max=args.delay_max)

    try:
        teams = manager.load_teams(args.teams_csv)

        if args.team:
            teams = [t for t in teams if t['ncaa_id'] == args.team]
            if not teams:
                logger.error(f"Team {args.team} not found in {args.teams_csv}")
                return
            logger.info(f"Scraping specific team: {teams[0]['team']}")

        if not teams:
            logger.error("No teams to scrape")
            return

        player_dicts = manager.scrape_teams(teams, max_teams=args.limit, refresh=args.refresh)

        if player_dicts:
            manager.save_results(player_dicts)
        else:
            logger.warning("No players scraped - no output files generated")
            manager._save_error_reports()
    finally:
        manager.close()

    # Summary
    print("\n" + "=" * 80)
    print("SCRAPING SUMMARY")
    print("=" * 80)
    print(f"Season: {args.season}")
    print(f"Teams attempted: {len(teams) if not args.limit else min(len(teams), args.limit)}")
    print(f"Successful: {len(manager.successful_teams)} teams")
    print(f"Total players: {len(player_dicts)}")
    print(f"Zero players: {len(manager.zero_player_teams)} teams")
    print(f"Failed: {len(manager.failed_teams)} teams")
    print(f"Pages fetched: {getattr(manager.scraper.fetcher, 'pages_fetched', 'n/a')}")
    print(f"Elapsed: {time.time() - start_time:.1f}s")
    print("=" * 80)


if __name__ == '__main__':
    main()
