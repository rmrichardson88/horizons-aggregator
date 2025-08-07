from __future__ import annotations

"""Scraper for Sage Oil Vac job listings.

Changelog (2025‑08‑06)
----------------------
* Switch to the same XHR headers the iSolved front‑end uses so Cloudflare
  returns JSON instead of an HTML error page.
* Broaden JSON extraction (`data.get("data", {}).get("positions")`).
* Skip Playwright fallback entirely when the feed is reachable.
* Preserve verbose feed logging for CI debugging.

Dependencies: requests, playwright‑python, utils.build_job_id.
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
LIST_URL = f"{BASE_URL}/jobs/"

# ---------------------------------------------------------------------------
# 1. JSON feed discovery (preferred path)
# ---------------------------------------------------------------------------

CANDIDATE_FEEDS = [
    "jobs?format=json&per_page=100&page=1",
    "jobs/positions?format=json&per_page=100&page=1",
    "jobs/positions.json",
]

XHR_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",  # Marks request as an AJAX call
    "Referer": LIST_URL,
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    **XHR_HEADERS,  # Merge dictionaries (requires Python 3.9+)
}


def _fetch_from_feed() -> Optional[List[Dict]]:
    """Try the lightweight JSON endpoints first. Returns jobs or None."""

    feed_log: List[str] = []

    for path in CANDIDATE_FEEDS:
        url = f"{BASE_URL}/{path}"
        try:
            resp = requests.get(url, timeout=20, headers=HEADERS)
            ctype = resp.headers.get("content-type", "")
            feed_log.append(f"{url} → {resp.status_code} {ctype} (len={len(resp.content)})")

            # If it's not JSON, bail out early – Cloudflare likely blocked us.
            if "application/json" not in ctype:
                continue

            data = resp.json()
        except Exception:
            continue  # Try the next candidate feed

        # iSolved sometimes wraps positions under data -> positions
        rows = (
            data.get("positions")
            or data.get("data", {}).get("positions")
            or (data if isinstance(data, list) else None)
        )
        if not rows:
            continue  # Feed is empty – fall through to next URL

        jobs: List[Dict] = []
        for row in rows:
            title = row.get("title") or row.get("name", "")
            url_ = row.get("url") or row.get("applyUrl", "")
            location = row.get("location", "").replace(", USA", "").strip()

            jobs.append(
                {
                    "id": build_job_id(str(row.get("id", url_.split("/")[-1])), title, location),
                    "title": title,
                    "company": "Sage Oil Vac",
                    "location": location,
                    "employment_type": row.get("employment_type", ""),
                    "salary": row.get("pay", row.get("compensation", "")),
                    "posted": row.get("posted", row.get("postDate", "")),
                    "url": url_,
                    "scraped_at": datetime.utcnow().isoformat(timespec="seconds"),
                    "source": "Sage Oil Vac",
                }
            )

        if jobs:
            return jobs  # Success – no need for Playwright

    # If every candidate feed failed or returned empty, save the log for CI.
    Path("sage_debug_feed.txt").write_text("\n".join(feed_log), encoding="utf-8")
    return None


# ---------------------------------------------------------------------------
# 2. Playwright fallback (only if feed is blocked)
# ---------------------------------------------------------------------------

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
            # Save artefacts for debugging in CI
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

            # Extract spans (location | employment type | salary)
            spans = [
                (await s.inner_text()).strip()
                for s in await card.query_selector_all("div.w-card__content span")
            ]
            spans = [t for t in spans if t and t != "|"]
            location, employment_type, salary = (spans + ["", "", ""])[0:3]

            posted_span = await card.query_selector("div.pt1 span")
            posted = (
                (await posted_span.inner_text()).replace("Posted:", "").strip()
                if posted_span
                else ""
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


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------

def fetch_jobs() -> List[Dict]:
    """Return a list of jobs. Prefer JSON feed; fall back to Playwright."""

    if jobs := _fetch_from_feed():
        return jobs  # Fast path

    # Feed failed – resort to Playwright.
    try:
        return asyncio.run(_scrape_async())
    except RuntimeError as err:
        # If we're already inside an event loop (e.g. notebook), nest it.
        if "asyncio.run() cannot be called from a running event loop" not in str(err):
            raise
        import nest_asyncio

        nest_asyncio.apply()
        return asyncio.get_event_loop().run_until_complete(_scrape_async())


if __name__ == "__main__":
    from pprint import pprint

    pprint(fetch_jobs()[:5])
