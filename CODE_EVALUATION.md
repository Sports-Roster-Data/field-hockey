# Scraper Code Evaluation

Evaluation of `src/fhockey_roster_scraper.py` and `src/enhance_roster_data.py`, with prioritized recommendations.

## Summary

The scraper is well-organized (clear separation between `FieldExtractors`, `URLBuilder`, `TeamConfig`, `StandardScraper`, and `RosterManager`) and handles the two main Sidearm roster formats (card list and table). However, it currently produces **zero usable data** because Sidearm's bot protection blocks all requests (per `SCRAPER_IMPROVEMENTS.md`, 0/15 teams succeeded — 100% returned 403), so the highest-value work is changing the fetch strategy, not the parsers. Beyond that, there are a handful of real correctness bugs (a dropped first player in table rosters, weight fields captured as height, misleading error reports, a crash path in the enhancement script that discards hours of work), significant copy-paste duplication, and no tests.

The recommendations are ordered so that fixing the fetch strategy comes first — until pages can actually be retrieved, parser fixes have no effect on output.

---

## 1. The 403 blocker (strategic; highest priority)

The scraper's requests-based fetching (even with cloudscraper, browser headers, and session warm-up) is fully blocked by Sidearm Sports sites. Recommendations, in order of leverage:

### 1a. Use stats.ncaa.org — the data source already in `teams.csv`

Every row of `teams.csv` already carries `playerstatsurl` and `matchstatsurl` pointing at `stats.ncaa.org` (e.g. `https://stats.ncaa.org/team/23/stats/16461`). The NCAA stats site publishes team rosters (jersey, name, position, class, height, hometown, high school for most teams) **without Sidearm's bot protection**. Building a `stats.ncaa.org` roster scraper would:

- cover all 83 teams from one consistent HTML format instead of ~83 team-site variants;
- eliminate the per-team URL-format guessing (`/roster/2025` vs `/roster` vs `/roster.aspx`);
- remove the need for cloudscraper entirely.

Caveats: stats.ncaa.org has its own rate limiting (be polite: ~1 request per 2–3 s with jitter) and does not include majors or previous schools. A hybrid works well: stats.ncaa.org as the primary source, team sites (via 1b) only for enrichment fields.

### 1b. Playwright for Sidearm sites

`SCRAPER_IMPROVEMENTS.md` already recommends this; it is the right call for the team-site path. Render the roster page in headless Chromium and feed `page.content()` into the existing BeautifulSoup extraction — the parsers (`_extract_players`, `_extract_players_from_table`) can stay unchanged. This also solves the JavaScript-rendered-roster problem that `TeamConfig.requires_js` was designed for but never implements.

### 1c. Try Sidearm's structured data before parsing HTML

Many Sidearm sites embed the full roster as JSON in the page (in `<script>` state blobs) or expose JSON roster endpoints. When fetching via Playwright anyway, checking for embedded JSON first yields cleaner data than scraping the rendered DOM. Worth a probe step before falling back to HTML parsing.

### 1d. Politeness and resilience

Whatever the fetch layer: honor `robots.txt`, use jittered delays, add retry-with-exponential-backoff for transient errors (5xx, timeouts), and cache successful team results to disk so re-runs only revisit failed teams. Currently a crash on team 60 of 83 loses everything.

---

## 2. Correctness bugs

### 2a. First player silently dropped in table-format rosters

`_extract_players_from_table` (`src/fhockey_roster_scraper.py:807`):

```python
tbody = table.find('tbody') or table
rows = tbody.find_all('tr')
for row in rows[1:]:  # Skip header if it's in tbody
```

`rows[1:]` skips the first row **unconditionally**. When the table has a proper `<thead>`/`<tbody>` split (the common Sidearm case), the tbody contains only player rows — so the first player on every table-format roster is silently lost. Fix: only skip the first row when it actually contains `<th>` cells / matches the detected header.

### 2b. Weight fields captured as height

The label matching uses bare substring tests. `'ht' in label` (`src/fhockey_roster_scraper.py:548`, `:591`; `src/enhance_roster_data.py:128`, `:159`) matches **"weig​ht"**, so a `Weight` bio field populates `height`. Similarly `'hs' in label` matches any label containing "hs". Fix: match against a whitelist of exact normalized labels (`{'height', 'ht'}`, `{'high school', 'hs'}`) or use word-boundary regexes.

### 2c. `failed_teams` report can never populate

`StandardScraper.scrape_team` catches **all** exceptions internally and returns `[]` (`src/fhockey_roster_scraper.py:496–501`). The `try/except` around it in `RosterManager.scrape_teams` (`:995`) is therefore dead code: every failure — 403s, timeouts, parse crashes — is recorded as "zero players". The `failed_teams_*.json` report is effectively always empty and the `zero_players_*.json` report conflates "blocked", "errored", and "genuinely empty roster", which makes triage misleading. Fix: have `scrape_team` return a status (or raise) so the manager can distinguish HTTP failure / exception / empty roster.

### 2d. `enhance_csv` can crash at the very end and lose all work

`ProfileEnhancer.enhance_csv` (`src/enhance_roster_data.py:250–253`) creates `csv.DictWriter(f, fieldnames=fieldnames)` with the **input** file's header and no `extrasaction='ignore'`. If profile scraping adds a key the input CSV didn't have (e.g. `major` or `previous_school` on a hand-built input), `writerows` raises `ValueError` — after the entire multi-hour scrape has completed, discarding all of it. Fixes: pass `extrasaction='ignore'` (or extend `fieldnames` with the union of keys), and write rows incrementally (or checkpoint every N rows) so a crash doesn't lose completed work.

### 2e. Hardcoded absolute import path

`src/enhance_roster_data.py:32`:

```python
sys.path.insert(0, '/home/user/field-hockey/src')
```

This breaks on any machine where the repo isn't checked out at that exact path. Fix: `sys.path.insert(0, str(Path(__file__).resolve().parent))`, or make `src/` a package and use a relative import.

### 2f. Season verification is toothless

`SeasonVerifier.verify_season_on_page` checks whether the season string (e.g. `"2025"`) appears **anywhere** in the page text. Copyright footers ("© 2025 …") guarantee a match on essentially every page, so stale-roster detection never fires. Fix: check the season against the page `<title>`, the roster heading, or the URL the request actually resolved to after redirects.

---

## 3. Design issues and dead code

- **Dead URL-format machinery**: `URLBuilder.build_roster_url`'s `'default'` and `'fhockey'` branches return the identical string (`src/fhockey_roster_scraper.py:302–308`) — the actual path difference (`/sports/fhockey/` vs `/sports/field-hockey/`) already lives in the `teams.csv` URL. `TeamConfig.get_url_format` and its auto-detection therefore accomplish nothing. Either give the formats real behavior or delete the abstraction.
- **Never-called code**: `TeamConfig.requires_javascript` (`:351`) and `URLBuilder.extract_base_url` (`:316`) have no callers. `Player.player_id` and `Player.division` are never populated (the README claims Division I/II/III coverage, but `division` is always passed as `""`).
- **6× copy-pasted bio-field mapping**: the label→field dispatch block (~50 lines: position/height/class/major/hometown/high school/previous school) appears three times in `fhockey_roster_scraper.py` (`_scrape_player_profile` div format, dl format, table format) and three more times in `enhance_roster_data.py`. Any label fix (like 2b) must be applied in six places. Extract one shared helper, e.g. `apply_bio_field(target, label, value)`, used by both scripts — and have `enhance_roster_data.py` reuse `StandardScraper._scrape_player_profile` rather than re-implementing it.
- **Fragile table detection**: the fallback `table = html.find('table')` (`:768`) grabs the first table on the page, which on a full team-site page may be navigation or standings rather than the roster. Prefer requiring roster-indicative headers (name + one of jersey/position/class) before accepting a table.
- **Misc smells**:
  - bare `except: pass` on the session warm-up request (`:456–457`) — at minimum log at debug level and catch `requests.RequestException`;
  - `import time` inside functions (`:452`, `:517`) — move to module top;
  - `--scrape-profiles` is a no-op flag (`action='store_true'` with `default=True`); use `argparse.BooleanOptionalAction` for a real on/off pair;
  - player counts are logged twice per team (`scrape_team` and `scrape_teams`);
  - passing custom browser headers into a cloudscraper session can *defeat* cloudscraper, which manages its own User-Agent/TLS fingerprint consistency — if cloudscraper stays, let it own the headers.

---

## 4. Robustness and performance gaps

- **No retry/backoff**: a transient timeout or 5xx permanently fails the team for that run.
- **No caching or resume**: profile scraping is serial and inline — roughly 83 teams × ~25 players × (0.5 s sleep + request time) is multiple hours per run, restarted from zero on any interruption. Cache each team's result (e.g. one JSON per team keyed by `ncaa_id` + season) and skip completed teams on re-run.
- **`load_teams` fragility**: `int(row['org_id'])` will raise `ValueError` on any malformed row and abort the entire run; wrap and skip with a warning.

---

## 5. Extraction-quality improvements (lower priority)

- `normalize_academic_year` is exact-match only: lowercase `"fr."`, `"FR."`, `"Frosh"`, `"Fifth Year"`, `"Grad Student"`, `"5th Year"` all pass through unnormalized. Normalize the key (strip trailing period, title-case) before the lookup.
- `extract_hometown_parts` only splits on `/`; some sites use `City, ST (High School)` — add the parenthesized pattern.
- `extract_height`'s `(\d+-\d+)` pattern will happily match things like `2024-25` if it's ever fed non-height text; anchor the digits (`\b([4-7]-\d{1,2})\b`) since heights are 4–7 feet.
- `extract_position`'s single-letter alternations (`G`, `D`, `M`, `F`, `A`, `B`, `O`) with `re.IGNORECASE` are safe on position-labeled fields but dangerous on free text — keep this function restricted to position-labeled values (as it is today) or require the whole string to be a known token.

---

## 6. Testing

There are currently no tests. The highest-value, lowest-effort additions:

1. **Unit tests for `FieldExtractors`** — pure functions, ideal for table-driven tests (heights in all four formats, jersey patterns, year normalization, hometown splitting, the weight/height label bug in 2b).
2. **Parser fixture tests** — save two or three real roster HTML pages (one card-list, one thead/tbody table, one player profile) under `tests/fixtures/` and assert on the extracted `Player` lists. This locks in the 2a fix and protects against Sidearm markup drift.
3. A `--limit 1`-style smoke test wired to a fixture rather than the network.

---

## Prioritized action list

| Priority | Action |
|----------|--------|
| P0 | Switch primary data source to stats.ncaa.org (URLs already in `teams.csv`) and/or add Playwright fetching for Sidearm sites — nothing else matters while every request 403s |
| P0 | Fix dropped first player in table rosters (2a) |
| P0 | Fix weight-as-height label matching (2b) |
| P0 | Fix `enhance_csv` end-of-run crash + add incremental writes (2d) |
| P0 | Remove hardcoded `sys.path` (2e) |
| P1 | Make error reporting truthful — distinguish HTTP failure / exception / empty roster (2c) |
| P1 | Deduplicate the 6× bio-field mapping into one shared helper |
| P1 | Add retry/backoff, per-team caching, and resume support |
| P2 | Delete dead code (URL formats, `requires_javascript`, `extract_base_url`) or implement it for real |
| P2 | Add `FieldExtractors` unit tests and roster-HTML fixture tests |
| P2 | Strengthen season verification; broaden year/hometown/height normalization |
