# Field Hockey Roster Scraper - Improvements & Bot Protection Issue

## Summary

Enhanced the field hockey roster scraper to extract detailed player information from individual profile pages. However, the Sidearm Sports platform (used by most NCAA field hockey teams) has implemented strong bot protection that blocks automated access.

## Improvements Made

### 1. Profile Page Scraping (`src/fhockey_roster_scraper.py`)

- **Added `_scrape_player_profile()` method**: Scrapes individual player profile pages to extract detailed information including:
  - Position
  - Height
  - Academic year/class
  - Major
  - Hometown
  - High school
  - Previous school

- **Enhanced headers**: Updated User-Agent and added browser-like headers (Referer, Origin, etc.) to appear more legitimate

- **Session establishment**: Visits base domain first to establish cookies/session before accessing roster pages

- **Cloudscraper integration**: Uses cloudscraper library to attempt bypassing Cloudflare/bot protection

- **Command-line flags**: Added `--scrape-profiles` and `--no-scrape-profiles` flags to control profile scraping

### 2. CSV Enhancement Script (`src/enhance_roster_data.py`)

Created a standalone script to enhance existing CSV files by:
- Reading existing roster data with player URLs
- Scraping each individual player profile page
- Filling in missing details (position, height, class, hometown, etc.)
- Writing enhanced data to new CSV file

Usage:
```bash
python src/enhance_roster_data.py --input rosters.csv --output rosters_enhanced.csv
python src/enhance_roster_data.py --input rosters.csv --output rosters_enhanced.csv --team "American"
```

### 3. Updated Dependencies

Added `cloudscraper>=1.2.71` to requirements.txt for bot protection bypass attempts.

## Bot Protection Issue

### Problem

The Sidearm Sports platform (used by American, App State, Ball St., Bellarmine, Boston College, and most other teams) returns **403 Forbidden** errors for automated requests, even with:
- Cloudscraper (Cloudflare bypass)
- Browser-like headers
- Session establishment
- Referer/Origin headers
- Delays between requests

This affects both:
- Roster list pages (e.g., `/sports/field-hockey/roster`)
- Individual player profile pages

### Potential Solutions

1. **Browser Automation** (Recommended):
   - Use Playwright or Selenium to control a real browser
   - Slower but more reliable
   - Example:
     ```python
     from playwright.sync_api import sync_playwright

     with sync_playwright() as p:
         browser = p.chromium.launch()
         page = browser.new_page()
         page.goto(url)
         content = page.content()
     ```

2. **Residential Proxies**:
   - Use proxy services with residential IPs
   - Expensive but effective

3. **Manual Collection**:
   - Export data manually from websites
   - Most reliable but time-consuming

4. **API Access**:
   - Contact Sidearm Sports for official API access
   - Unlikely for scraping purposes

5. **Rate Limiting**:
   - Very slow requests (e.g., 1 per 5-10 seconds)
   - May work but very time-consuming

## Testing Results

Tested with first 15 teams (American through Dartmouth):
- **Successful**: 0 teams
- **403 Errors**: 15 teams (100%)
- **Players scraped**: 0

All teams using Sidearm Sports platform are currently blocked.

## Code Structure

### Main Scraper (`fhockey_roster_scraper.py`)

```python
StandardScraper
├── __init__(): Initialize with cloudscraper if available
├── scrape_team(): Scrape roster page for a team
├── _scrape_player_profile(): Scrape individual player profile (NEW)
├── _extract_players(): Extract players from roster list
└── _extract_players_from_table(): Extract from table format

RosterManager
├── __init__(): Takes scrape_profiles parameter
├── load_teams(): Load teams from CSV
├── scrape_teams(): Batch scrape multiple teams
└── save_results(): Save to JSON and CSV
```

### Enhancement Script (`enhance_roster_data.py`)

```python
ProfileEnhancer
├── __init__(): Initialize with cloudscraper
├── scrape_player_profile(): Scrape and enhance single player
└── enhance_csv(): Process entire CSV file
```

## Files Modified

- `src/fhockey_roster_scraper.py`: Added profile scraping functionality
- `src/enhance_roster_data.py`: New CSV enhancement script
- `requirements.txt`: Added cloudscraper dependency

## Recommendations

Given the bot protection issue, the recommended approach is:

1. **Short-term**: If you have existing CSV data with URLs, the enhancement script is ready to use once bot protection is bypassed

2. **Medium-term**: Implement browser automation (Playwright/Selenium) to scrape data:
   - Replace requests/cloudscraper with Playwright
   - Add stealth plugins to avoid detection
   - Implement proper rate limiting

3. **Long-term**: Consider contacting Sidearm Sports for official data access or partnership

## Next Steps

1. Evaluate browser automation tools (Playwright recommended)
2. Test with smaller subset of teams
3. Implement proper error handling and retry logic
4. Add caching to avoid re-scraping successfully collected data
