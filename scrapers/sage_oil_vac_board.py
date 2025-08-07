import asyncio
import datetime as dt
import json
import re
import sys
from typing import Dict, List

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://sageoilvac.isolvedhire.com"
LISTING_URL = f"{BASE_URL}/jobs/"

# ---------------------------------------------------------------------------
# Internal helpers (async + parsing)
# ---------------------------------------------------------------------------

async def _get_page_html() -> str:
    """Launch headless Chromium, navigate to the jobs page, and return HTML."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(LISTING_URL, wait_until="networkidle")

        # Wait until at least one job card is present
        await page.wait_for_selector("div.bdb1 a.job-name", timeout=15_000)

        html = await page.content()
        await browser.close()
    return html


def _parse_cards(html: str) -> List[Dict]:
    """Extract job data from the HTML produced by Playwright."""
    soup = BeautifulSoup(html, "html.parser")
    scraped_at = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    jobs: List[Dict] = []

    for card in soup.select("div.bdb1"):
        title_el = card.select_one("a.job-name")
        if not title_el:
            continue  # skip malformed or ad cards

        # Required fields
        title = title_el.get_text(strip=True)
        href = title_el["href"]
        url = href if href.startswith("http") else f"{BASE_URL}{href}"
        job_id_match = re.search(r"/jobs/(\d+)", url)
        job_id = job_id_match.group(1) if job_id_match else ""

        # Optional metadata – selectors vary slightly across themes.
        def _txt(selector: str) -> str:
            el = card.select_one(selector)
            return el.get_text(strip=True) if el else ""

        location = _txt(".job-location, .location, [data-testid='job-location']")
        employment_type = _txt(".job-type, .employment-type")
        salary = _txt(".job-salary, .salary, .compensation")
        posted = _txt(".job-date, .posted-date, time")

        jobs.append(
            {
                "id": job_id,
                "title": title,
                "company": "Sage Oil Vac",
                "location": location,
                "salary": salary,
                "url": url,
                "scraped_at": scraped_at,
                "source": "sageoilvac",
            }
        )

    return jobs

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def _fetch_jobs_async() -> List[Dict]:
    """Internal async implementation used by the sync wrapper."""
    html = await _get_page_html()
    return _parse_cards(html)


def fetch_jobs() -> List[Dict]:
    """Synchronous entry point expected by run_scrapers.py (Option B)."""
    return asyncio.run(_fetch_jobs_async())

# ---------------------------------------------------------------------------
# CLI entry point (for ad‑hoc testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    json.dump(fetch_jobs(), sys.stdout, indent=2)
    sys.stdout.write("\n")
