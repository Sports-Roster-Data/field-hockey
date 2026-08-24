# Field Hockey Roster Scraper

NCAA Field Hockey roster scraper based on the women's soccer scraper architecture.

## Features

- Scrapes field hockey rosters from NCAA Division I, II, and III teams
- Supports multiple roster formats:
  - Classic Sidearm Sports list rosters (`li.sidearm-roster-player`)
  - Modern Sidearm layouts: list (`roster-list-item`), card
    (`roster-card-item`, several field-markup variants), and the `s-person-card`
    design system
  - Table-based rosters
- Filters out coaches and support staff (who share the same markup as players on
  modern layouts) by requiring a jersey number
- Extracts player data:
  - Name
  - Jersey number
  - Position (GK, D, M, F)
  - Height
  - Academic year/class
  - Hometown
  - High school
  - Major
  - Profile URL

## Installation

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
uv sync                          # install dependencies into .venv
uv run playwright install chromium   # one-time: download the browser used for fetching
```

`uv run` executes commands inside the managed environment, so no manual
activation is needed.

## Fetching strategy

By default the scraper renders each roster page in a **real headless Chromium
browser** (via Playwright). This is what gets past the bot protection used by
Sidearm Sports team sites, which returns 403 to plain HTTP requests.

- `--fetch auto` (default): use the browser if Playwright is available, otherwise
  fall back to `requests`/`cloudscraper`.
- `--fetch browser`: require the browser (error if unavailable).
- `--fetch requests`: plain HTTP only (fast, but blocked by most team sites).

The browser fetcher blocks images/fonts/media, adds a short jittered delay
between requests, and retries transient failures with backoff.

> Note: headless Chromium gets past most, but not necessarily all, bot
> protection. Measure the real success rate by running against the live team
> sites from your machine.

## Roster URL patterns

The scraper builds the season roster URL as `{base}/roster/{season}` and, if
that 404s, retries in waves against the URL forms modern Sidearm sites use:

1. `{base}/roster/season/{season}` — the current Sidearm season-specific form
2. `{base}/roster` — the bare (current-season) roster
3. `{base}/roster.aspx` — legacy

This is why a team whose classic `/roster/{season}` URL 404s (e.g. Northwestern)
is still scraped correctly. Sites that label seasons by academic year (e.g.
Virginia's `2026-27`) fall through to the bare `/roster`, which serves the
current season.

## Speed

Roster and profile pages are fetched **concurrently** (one shared browser,
many pages at once), and profile pages are only fetched **when needed**, so a
full run takes minutes rather than hours. Controls:

- `--profiles {missing,always,never}` (default `missing`): fetch a player's
  individual profile page when the roster list is missing hometown, high school,
  or previous school. `never` is fastest (roster list only); `always` fetches
  every profile for maximum completeness.
- `--concurrency N` (default 6): max page loads in flight at once, across all
  sites.
- `--per-host N` (default 3): max concurrent page loads to any single site —
  keeps profile fetching (which all hits one team's site) polite.
- `--delay-min` / `--delay-max` (default 0.3 / 0.8s): jittered delay before
  each fetch.

Rules of thumb: raise `--concurrency` to go faster across many teams; keep
`--per-host` modest (2–4) to avoid rate-limiting on a single site; use
`--profiles never` when you only need what's on the roster list. Concurrency
applies to the browser path; the `requests` fallback stays serial.

## Usage

Paths default to the repository root, so these work from any directory.

### Scrape all teams

```bash
uv run src/fhockey_roster_scraper.py --season 2025
```

### Scrape first 10 teams (testing)

```bash
uv run src/fhockey_roster_scraper.py --limit 10 --season 2025
```

### Scrape specific team

```bash
uv run src/fhockey_roster_scraper.py --team 457 --season 2025
```

### Fastest run (skip profile pages)

```bash
uv run src/fhockey_roster_scraper.py --profiles never --season 2025
```

### Backfill stored profile URLs without re-scraping rosters

Use this for an existing season cache when roster membership must remain fixed.
It visits the stored player profile URLs, updates only blank hometown, high
school, and previous-school fields, rebuilds the aggregate JSON/CSV, and writes
a resumable enrichment report.

```bash
uv run src/backfill_profile_details.py --season 2026 --fetch browser \
  --concurrency 6 --per-host 3
```

Failed profile pages are retried on the next run; pass `--retry-all` to revisit
pages already recorded as successfully checked.

To revisit only players still missing a particular detail after parser changes:

```bash
uv run src/backfill_profile_details.py --season 2026 --fetch browser \
  --retry-field high_school
```

Biography-derived high-school values are stored with their evidence under
`low_confidence_fields` in the season's profile-enrichment report.

### Tune concurrency

```bash
uv run src/fhockey_roster_scraper.py --concurrency 10 --per-host 3 --season 2025
```

### Plain HTTP instead of a browser

```bash
uv run src/fhockey_roster_scraper.py --fetch requests --season 2025
```

### Custom teams CSV / output directory

```bash
uv run src/fhockey_roster_scraper.py --teams-csv path/to/teams.csv --output-dir data/output --season 2025
```

## Caching and resume

Each team's result is cached to `data/raw/teams/{ncaa_id}_{season}.json` as it
completes. Re-running skips teams that already succeeded (status `ok`) or
returned an empty roster, and automatically **retries** teams that previously
failed — so an interrupted run resumes without re-scraping everything. Use
`--refresh` to ignore the cache and re-scrape all teams.

## Testing

```bash
uv run pytest
```

Unit tests cover the field extractors and label matching; parser tests cover the
classic card-list and table roster formats against fixture HTML; `test_new_layouts.py`
covers each modern layout (list, card variants, `s-person-card`) and staff
filtering; `test_season_url.py` covers the `/roster/season/{season}` URL
fallback; and a browser test renders a local fixture page through Playwright
(skipped automatically if Chromium is unavailable).

## Output

The scraper generates the following output files:

- `data/raw/json/rosters_fhockey_2025.json` - All player data in JSON format
- `data/raw/csv/rosters_fhockey_2025.csv` - All player data in CSV format
- `data/raw/reports/zero_players_fhockey_2025.json` - Teams with zero players found
- `data/raw/reports/failed_teams_fhockey_2025.json` - Teams that failed to scrape

## Known Limitations

### Bot Protection (403 Errors)

Many NCAA athletic websites (particularly those using Sidearm Sports) have bot
protection (Cloudflare, PerimeterX, etc.) that blocks plain automated requests
with 403 Forbidden errors. The default **browser fetching** path (Playwright +
headless Chromium) is designed to get past this by loading pages the way a real
browser does, and it also handles JavaScript-rendered rosters for free.

If some teams still fail after a browser run, options include:

1. **Residential/rotating proxies** for the hardest sites.
2. **Slower pacing** — increase the delay in `BrowserFetcher` (the `min_delay` /
   `max_delay` constructor arguments).
3. **Manual collection** for the small number of remaining holdouts.

## Field Hockey Positions

The scraper normalizes positions to these standard abbreviations:

- **GK**: Goalkeeper/Goalie
- **D**: Defense/Back/Defender
- **M**: Midfielder/Midfield
- **F**: Forward/Attack/Offense

## Team Configuration

Team-specific configurations can be added to the `TEAM_CONFIGS` dictionary in the scraper:

```python
TEAM_CONFIGS = {
    312: {'url_format': 'fhockey', 'requires_js': False, 'notes': 'Iowa - /sports/fhockey/'},
    519: {'url_format': 'fhockey', 'requires_js': False, 'notes': 'Ohio - /sports/fhockey/'},
}
```

## Architecture

The scraper follows a modular architecture:

- **Player dataclass**: Structured player data
- **FieldExtractors**: Utilities for extracting and cleaning player fields, plus
  the shared `match_bio_label` / `apply_bio_field` label mapping used by every
  parsing path
- **BrowserFetcher / RequestsFetcher**: Pluggable fetch layer (`build_fetcher`
  selects one); `BrowserFetcher` renders pages in headless Chromium
- **URLBuilder**: Constructs roster URLs from base URLs
- **TeamConfig**: Team-specific configuration and categorization
- **StandardScraper**: Roster parsing over a fetcher — classic list, modern
  list/card/`s-person-card` layouts, and table formats, plus the season-URL
  fallback and jersey-based staff filtering
- **RosterManager**: Batch processing, per-team caching/resume, and error tracking

This architecture is based on the [women's soccer scraper](https://github.com/Sports-Roster-Data/soccer).

## Contributing

To add support for new roster formats:

1. Add a new extraction method to `StandardScraper`
2. Update `_extract_players()` to detect the new format
3. Add team-specific configuration if needed

## License

See LICENSE file for details.
