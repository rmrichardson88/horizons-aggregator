# Horizons Job Aggregator

A small collection of scrapers + a Streamlit dashboard to aggregate open roles from partner organizations around the Texas Panhandle.

## What this repo contains

* **Scrapers** (Python) for multiple ATS/vendor types:

  * **Paycom** (e.g., FMC)
  * **Workday** (e.g., West Texas A\&M University)
  * **BrassRing / Kenexa** (e.g., TTUHSC)
  * **Team Engine** (e.g., Talon/LPE)
  * **Static/SSR career pages** (e.g., Amarillo National Bank)
* **Runner**: `run_scrapers.py` calls each scraper and writes a combined `data/latest_jobs.json`.
* **Dashboard**: `streamlit_dashboard.py` reads `data/latest_jobs.json` and provides a simple UI (search + filters + clickable links).
* **GitHub Actions** workflow (recommended) to run nightly and refresh data.

## Data model

Each scraper returns a list of dicts. The **core schema** used by the dashboard is:

```json
{
  "id": "string | null",
  "title": "string | null",
  "company": "string | null",
  "location": "string | null",
  "salary": "string | null",  // often null
  "url": "string | null",
  "scraped_at": "YYYY-MM-DDTHH:MM:SS", // UTC, second precision
  "source": "string" // short code for the board
}
```

Some scrapers may include **extra fields** (e.g., `department`, `city`, `state`, `postal_code`, `description_snippet`). These are ignored by the dashboard but can be useful for future enrichment. The runner should ensure the core fields above exist for every job before writing JSON.

> Tip: standardize timestamps with a tiny helper:
>
> ```python
> from datetime import datetime, UTC
> def now_utc_iso_seconds() -> str:
>     return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
> ```

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt  # or pip install streamlit requests beautifulsoup4 playwright
python -m playwright install chromium
```

Run scrapers and dashboard:

```bash
python run_scrapers.py               # writes data/latest_jobs.json
streamlit run app/streamlit_dashboard.py
```

## GitHub Actions (nightly refresh)

Install Python + Playwright and run the scrapers:

```yaml
name: Refresh Jobs
on:
  schedule:
    - cron: "0 9 * * *"  # 3am Central
  workflow_dispatch:

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install deps
        run: |
          pip install --upgrade pip
          pip install -r requirements.txt || true
          pip install playwright
          python -m playwright install --with-deps chromium
      - name: Run scrapers
        run: |
          python run_scrapers.py
      - name: Upload data artifact
        uses: actions/upload-artifact@v4
        with:
          name: latest_jobs
          path: data/latest_jobs.json
```

> If your CI hits Chromium sandbox errors, launch with `args=["--no-sandbox"]` in Playwright.

## Adding a new partner

1. Create `scrapers/<partner>_board.py` exposing `fetch_jobs() -> List[dict]`.
2. Return the **core schema** fields listed above (add extras if helpful).
3. Import and append results in `run_scrapers.py`.
4. Validate locally: `python scrapers/<partner>_board.py`.

### Patterns by vendor

* **Static/SSR pages**: Use `requests` + `BeautifulSoup` and stable selectors (e.g., `data-automation-id` attributes).
* **Workday**: Try the CXS endpoint (`/wday/cxs/.../jobs`) first; fallback to SSR HTML; finally use Playwright if content is JS-hydrated.
* **BrassRing / Kenexa**: Page often defaults to “Most Recent”. If you need location scoping (e.g., Amarillo), open **Advanced Search** and tick the campus checkbox (or keyword fallback), then paginate. We provide both **async** (local debug) and **sync** (CI) versions.
* **Team Engine**: Content is client-rendered; use Playwright and wait for the job rows before scraping.
* **Paycom**: Straightforward HTML list; parse job id from query and split the location line into parts.

## Streamlit dashboard

* Script: `app/streamlit_dashboard.py` (or wherever you place it).
* Reads `data/latest_jobs.json` and presents keyword/company/location filters.
* Uses `st.column_config.LinkColumn` so each row has a clickable **Open** link.
* Handles empty/missing JSON gracefully; shows friendly messages instead of tracebacks.

## Troubleshooting

* **Only 10 jobs from BrassRing**: You’re seeing the default “Most Recent” page. Use the Advanced Search flow (or keyword fallback) and paginate. We’ve implemented this in the TTUHSC scraper.
* **Playwright Sync API inside asyncio loop**: Use the **async** version locally (e.g., `*_async.py`) or the **sync** version in Actions. Don’t mix them within the same event loop.
* **`Browser.new_context: Object of type ellipsis is not JSON serializable`**: Don’t pass `user_agent=(...)`. Use a real string.
* **Timeout clicking a filter**: Scroll the facet panel into view, match dash variants (`- – —`), and allow label counts like `(16)`. Fall back to keyword search.
* **Empty HTML / JS-hydrated pages**: Switch to a Playwright scraper and `wait_for_selector` on a stable, semantic selector (e.g., `a[data-automation-id="jobTitle"]`).

## Code style & conventions

* Return UTC timestamps with second precision; omit timezone suffix to match existing data.
* Prefer stable attributes over brittle classnames (`data-automation-id` > `class` when possible).
* Keep scrapers idempotent and side-effect free (return data; `run_scrapers.py` handles writing files).
* Log minimally in CI; avoid noisy prints in production scrapers.

## License

MIT (or your choice). Add a `LICENSE` file before publishing.

## Acknowledgements

Thanks to the partner organizations for maintaining accessible job boards, and to the Playwright / Requests / BeautifulSoup communities for great tooling.
