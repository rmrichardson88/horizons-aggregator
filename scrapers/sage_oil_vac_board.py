from __future__ import annotations

"""Scraper for Sage Oil Vac job listings (Playwright, async).

GitHub‑hosted runners can be *slow* to spin up headless Chromium and fetch
client‑rendered pages, so the original 20‑second selector timeout sometimes
fires.  This revision:

* waits for **networkidle** after navigation, giving Vue time to pull data
* bumps the selector timeout to **60 000 ms**
* falls back to a 2‑minute navigation timeout
* (optional) saves a screenshot ``debug_sageoilvac.png`` when no listings are
  found, making CI debugging easier

Dependencies remain the same:
    pip install playwright nest_asyncio
    playwright install chromium
"""

from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from typing import List, Dict
import asyncio
import os

from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from utils import build_job_id

BASE_URL = "https://sageoilvac.isolvedhire.com"
LIST_URL = f"{BASE_URL}/jobs/"


# ---------------------------------------------------------------------------
# Async scraping routine
# ---------------------------------------------------------------------------

async def _scrape_async() -> List[Dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(LIST_URL, timeout=120_000, wait_until="domcontentloaded")
        # Wait until all fetch/XHR have quieted down.
        await page.wait_for_load_state("networkidle")

        try:
            await page.wait_for_selector("a.job-name", timeout=60_000)
        except PWTimeout:
            # Debug aid for CI: dump HTML + screenshot so we can inspect why.
            html = await page.content()
            Path("sage_debug.html").write_text(html, encoding="utf‑8")
            await page.screenshot(path="sage_debug.png", full_page=True)
            await browser.close()
            raise RuntimeError("Sage Oil Vac listings did not load within 60 s – saved sage_debug.html/png for inspection")

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

            job_id = build_job_id(Path(abs_url).stem, title, location)

            jobs.append(
                {
                    "id": job_id,
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


# ---------------------------------------------------------------------------
# Public helper that works in both CLI and Jupyter
# ---------------------------------------------------------------------------

def fetch_jobs() -> List[Dict]:
    """Run the async scraper, adapting to the current event‑loop context."""
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
