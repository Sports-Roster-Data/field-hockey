# Field Hockey Roster Scraper

NCAA Field Hockey roster scraper based on the women's soccer scraper architecture.

## Features

- Scrapes 2025 field hockey rosters from NCAA Division I, II, and III teams
- Supports multiple roster formats:
  - Sidearm Sports list-based rosters
  - Table-based rosters
  - Custom roster layouts
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

```bash
pip install -r requirements.txt
```

## Usage

### Scrape all teams

```bash
python src/fhockey_roster_scraper.py --season 2025
```

### Scrape first 10 teams (testing)

```bash
python src/fhockey_roster_scraper.py --limit 10 --season 2025
```

### Scrape specific team

```bash
python src/fhockey_roster_scraper.py --team 457 --season 2025
```

### Custom teams CSV path

```bash
python src/fhockey_roster_scraper.py --teams-csv path/to/teams.csv --season 2025
```

### Custom output directory

```bash
python src/fhockey_roster_scraper.py --output-dir data/output --season 2025
```

## Output

The scraper generates the following output files:

- `data/raw/json/rosters_fhockey_2025.json` - All player data in JSON format
- `data/raw/csv/rosters_fhockey_2025.csv` - All player data in CSV format
- `data/raw/reports/zero_players_fhockey_2025.json` - Teams with zero players found
- `data/raw/reports/failed_teams_fhockey_2025.json` - Teams that failed to scrape

## Known Limitations

### Bot Protection (403 Errors)

Many NCAA athletic websites (particularly those using Sidearm Sports) have bot protection (Cloudflare, PerimeterX, etc.) that blocks automated requests with 403 Forbidden errors. This affects the majority of field hockey teams.

**Solutions:**

1. **Use browser automation tools** like Selenium or Playwright:
   ```python
   # Example with Selenium
   from selenium import webdriver
   from selenium.webdriver.chrome.options import Options

   options = Options()
   options.add_argument('--headless')
   driver = webdriver.Chrome(options=options)
   driver.get(roster_url)
   html = driver.page_source
   # Then parse with BeautifulSoup
   ```

2. **Use a proxy service** or residential IPs

3. **Rate limiting**: Add delays between requests (though this may not solve 403 errors)

4. **Manual data collection**: For small datasets, manual collection may be more efficient

### JavaScript-Rendered Content

Some sites load roster data dynamically via JavaScript. For these sites, you'll need to:

- Use Selenium/Playwright to render the page
- Wait for JavaScript to load the content
- Then extract the data from the rendered HTML

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
- **FieldExtractors**: Utilities for extracting and cleaning player fields
- **URLBuilder**: Constructs roster URLs from base URLs
- **TeamConfig**: Team-specific configuration and categorization
- **StandardScraper**: Main scraping logic for standard HTML sites
- **RosterManager**: Batch processing and error tracking

This architecture is based on the [women's soccer scraper](https://github.com/Sports-Roster-Data/soccer).

## Contributing

To add support for new roster formats:

1. Add a new extraction method to `StandardScraper`
2. Update `_extract_players()` to detect the new format
3. Add team-specific configuration if needed

## License

See LICENSE file for details.
