from __future__ import annotations

"""Scraper for Sage Oil Vac job listings.

### What changed (2025‑08‑06)
* **More resilient JSON feed discovery** – try a short list of common iSolved
  feed URLs (`jobs?format=json`, `jobs/positions?format=json`, `jobs/list.json`,
  `jobs/positions.json`) with an `Accept: application/json` header.  Whichever
  returns a non‑empty array wins.
* **Verbose logging in CI** – when every feed returns empty *and* Playwright
  times out, we now upload `sage_debug_feed.txt` (feed responses) alongside the
  screenshot/HTML so we can see why the runner is blocked.

Dependencies remain unchanged.
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
CANDIDATE_FEEDS = [
    "jobs?format=json&page=1&per_page=100",
    "jobs/positions?format=json&page=1&per_page=100",
    "jobs/list.json",
    "jobs/positions.json",
]
LIST_URL = f"{BASE_URL}/jobs/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*;q=0.9",
}

################################################################################
# 1. Lightweight JSON feed (try several endpoints)
################################################################################

def _fetch_from_feed() -> Optional[List[Dict]]:
    feed_log = []
    for path in CANDIDATE_FEEDS:
        url = f"{BASE_URL}/{path}"
        try:
            resp = requests.get(url, timeout=20, headers=HEADERS)
            cont_type = resp.headers.get("content-type", "")
            feed_log.append(f"{url} → {resp.status_code} {cont_type} (len={len(resp.content)})")
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue  # try next candidate

        rows = data.get("positions", data) if isinstance(data, dict) else data
        if not rows:
            continue

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
        if jobs:
            return jobs  # success

    # save feed_log for CI debugging
    Path("sage_debug_feed.txt").write_text("\n".join(feed_log), encoding="utf-8")
    return None

################################################################################
# 2. Playwright fallback (async)
################################################################################

async def _scrape_async() -> List[Dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(user_agent=HEADERS["User-Agent"])
        page = await context.new_page()
        await page.goto(LIST_URL, timeout=120_000, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle")

        try:
            await page.wait_for_selector("a.job-name", timeout=120_000)
        except PWTimeout:
            # Save HTML + screenshot + feed log
            Path("sage_debug.html").write_text(await page.content(), encoding="utf-8")
            await page.screenshot(path="sage_debug.png", full_page=True)
            await browser.close()
            raise RuntimeError("Playwright fallback timed out – artefacts saved")

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
# Public helper
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
