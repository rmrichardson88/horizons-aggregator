import asyncio
import datetime as dt
import json
import re
import sys
from typing import Dict, List

from bs4 import BeautifulSoup
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

# ---------------------------------------------------------------------------
# Constants & selectors
# ---------------------------------------------------------------------------
BASE_URL = "https://sageoilvac.isolvedhire.com"
LISTING_URL = f"{BASE_URL}/jobs/"
JOB_CARD_SELECTOR = "div.bdb1 a.job-name"

# ---------------------------------------------------------------------------
# Internal helpers (async crawls + parsing)
# ---------------------------------------------------------------------------

async def _get_page_html() -> str:
    """Return fully rendered HTML for the job listings page.

    • Launches headless Chromium.
    • Waits for Cloudflare's "Just a moment…" interstitial to pass.
    • Gives the site up to 90 s on CI before failing.
    """

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            # A realistic UA helps Cloudflare trust the browser a bit more.
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        # Navigate and wait for network to go idle (Cloudflare still shows if any).
        await page.goto(LISTING_URL, wait_until="networkidle", timeout=60_000)

        try:
            # CI runners are slower; give them 45 s to see the first card.
            await page.wait_for_selector(JOB_CARD_SELECTOR, state="attached", timeout=45_000)
        except PlaywrightTimeoutError:
            # Might still be on the Cloudflare challenge page – check & wait longer.
            if await page.locator("text=Just a moment").count() > 0:
                await page.wait_for_selector(JOB_CARD_SELECTOR, state="attached", timeout=90_000)
            else:
                raise  # real failure – re‑raise for visibility

        html = await page.content()
        await browser.close()
    return html


def _parse_cards(html: str) -> List[Dict]:
    """Parse the rendered HTML into a list of job dictionaries."""
    soup = BeautifulSoup(html, "html.parser")
    scraped_at = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    jobs: List[Dict] = []

    for card in soup.select("div.bdb1"):
        title_el = card.select_one("a.job-name")
        if not title_el:
            continue  # skip ad banners or malformed cards

        title = title_el.get_text(strip=True)
        href = title_el["href"]
        url = href if href.startswith("http") else f"{BASE_URL}{href}"
        job_id_match = re.search(r"/jobs/(\d+)", url)
        job_id = job_id_match.group(1) if job_id_match else ""

        # Convenient helper
        def _txt(sel: str) -> str:
            el = card.select_one(sel)
            return el.get_text(strip=True) if el else ""

        jobs.append(
            {
                "id": job_id,
                "title": title,
                "company": "Sage Oil Vac",
                "location": _txt(".job-location, .location, [data-testid='job-location']"),
                "employment_type": _txt(".job-type, .employment-type"),
                "salary": _txt(".job-salary, .salary, .compensation"),
                "posted": _txt(".job-date, .posted-date, time"),
                "url": url,
                "scraped_at": scraped_at,
                "source": "sageoilvac",
            }
        )

    return jobs

# ---------------------------------------------------------------------------
# Public API – synchronous facade
# ---------------------------------------------------------------------------

async def _fetch_jobs_async() -> List[Dict]:
    html = await _get_page_html()
    return _parse_cards(html)


def fetch_jobs() -> List[Dict]:  # noqa: D401 – simple wrapper
    """Run the async scraper and return its results synchronously."""
    return asyncio.run(_fetch_jobs_async())

# ---------------------------------------------------------------------------
# CLI entry point for local smoke‑testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    json.dump(fetch_jobs(), sys.stdout, indent=2)
    sys.stdout.write("\n")
