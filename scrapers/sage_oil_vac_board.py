from __future__ import annotations
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from typing import List, Dict
import asyncio

from playwright.async_api import async_playwright
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
        await page.goto(LIST_URL, timeout=45_000)

        # Wait for at least one job card (div.bdb1) to be injected
        await page.wait_for_selector("div.bdb1 >> a.job-name", timeout=20_000)

        jobs: List[Dict] = []
        for card in await page.query_selector_all("div.bdb1"):
            anchor = await card.query_selector("a.job-name")
            if not anchor:
                continue
            title = (await anchor.inner_text()).strip()
            href = (await anchor.get_attribute("href")) or ""
            abs_url = urljoin(BASE_URL + "/", href.lstrip("/"))

            # Spans inside the metadata row (location | employment type | salary)
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
        # Normal scripts → no loop running
        return asyncio.run(_scrape_async())
    except RuntimeError as err:
        if "asyncio.run() cannot be called from a running event loop" not in str(err):
            raise
        # Inside an existing loop (e.g. Jupyter). Patch it and schedule.
        import nest_asyncio  # lightweight; only imported on this path

        nest_asyncio.apply()
        return asyncio.get_event_loop().run_until_complete(_scrape_async())
