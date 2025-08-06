from __future__ import annotations

"""Scraper for Sage Oil Vac job listings.

⚠️  The site’s Vue front‑end sometimes withholds data from headless browsers
(e.g., on GitHub Actions).  To make the scraper *reliable* we:

1. **Hit the board’s JSON feed first** – almost every iSolvedHire site exposes
   `/jobs?format=json&page=1&per_page=100` (or the same array under a
   `positions` key).  This returns instantly and bypasses any UI or bot‑block.
2. Fall back to Playwright *only* if the feed is missing or empty, with a
   custom, non‑headless user‑agent to dodge basic bot filters.

Dependencies (unchanged):
    pip install requests playwright nest_asyncio
    playwright install chromium
"""

from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from typing import List, Dict, Optional
import asyncio
import json
import requests
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from utils import build_job_id

BASE_URL = "https://sageoilvac.isolvedhire.com"
JSON_URL = f"{BASE_URL}/jobs?format=json&page=1&per_page=100"
LIST_URL = f"{BASE_URL}/jobs/"

################################################################################
# 1. Lightweight JSON feed
################################################################################

def _fetch_from_feed() -> Optional[List[Dict]]:
    try:
        resp = requests.get(JSON_URL, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None  # feed not available or malformed

    rows = data.get("positions", data) if isinstance(data, dict) else data
    if not rows:
        return None

    jobs: List[Dict] = []
    for row in rows:
        title = row.get("title") or row.get("name", "")
        url = row.get("url") or row.get("applyUrl", "")
        location = row.get("location", "").replace(", USA", "").strip()

        jobs.append(
            {
                "id": build_job_id(str(row.get("id", url.split("/")[-1])), title, location),
                "title": title,
                "company": "Sage Oil Vac",
                "location": location,
                "employment_type": row.get("employment_type", ""),
                "salary": row.get("pay", row.get("compensation", "")),
                "posted": row.get("posted", row.get("postDate", "")),
                "url": url,
                "scraped_at": datetime.utcnow().isoformat(timespec="seconds"),
                "source": "Sage Oil Vac",
            }
        )
    return jobs

################################################################################
# 2. Playwright fallback (async)
################################################################################

async def _scrape_async() -> List[Dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(  # slower but only used when feed fails
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        await page.goto(LIST_URL, timeout=120_000, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle")

        await page.wait_for_selector("a.job-name", timeout=90_000)

        jobs: List[Dict] = []
        for card in await page.query_selector_all("div.bdb1"):
            anchor = await card.query_selector("a.job-name")
            if not anchor:
                continue
            title = (await anchor.inner_text()).strip()
            href = (await anchor.get_attribute("href")) or ""
            abs_url = urljoin(BASE_URL + "/", href.lstrip("/"))

            spans = [
                (await s.inner_text()).strip()
                for s in await card.query_selector_all("div.w-card__content span")
            ]
            spans = [t for t in spans if t and t != "|"]
            location = spans[0] if len(spans) >= 1 else ""
            employment_type = spans[1] if len(spans) >= 2 else ""
            salary = spans[2] if len(spans) >= 3 else ""

            posted_span = await card.query_selector("div.pt1 span")
            posted = (
                (await posted_span.inner_text()).replace("Posted:", "").strip()
                if posted_span else ""
            )

            jobs.append(
                {
                    "id": build_job_id(Path(abs_url).stem, title, location),
                    "title": title,
                    "company": "Sage Oil Vac",
                    "location": location,
                    "employment_type": employment_type,
                    "salary": salary,
                    "posted": posted,
                    "url": abs_url,
                    "scraped_at": datetime.utcnow().isoformat(timespec="seconds"),
                    "source": "Sage Oil Vac",
                }
            )

        await browser.close()
        return jobs

################################################################################
# Public helper that chooses the best path
################################################################################

def fetch_jobs() -> List[Dict]:
    """Return job list from feed if available; otherwise use Playwright."""
    if jobs := _fetch_from_feed():
        return jobs

    # Feed failed → fall back to browser scrape.
    try:
        return asyncio.run(_scrape_async())
    except RuntimeError as err:
        if "asyncio.run() cannot be called from a running event loop" not in str(err):
            raise
        import nest_asyncio

        nest_asyncio.apply()
        return asyncio.get_event_loop().run_until_complete(_scrape_async())


if __name__ == "__main__":
    from pprint import pprint

    pprint(fetch_jobs()[:5])
