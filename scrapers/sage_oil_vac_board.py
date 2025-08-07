from __future__ import annotations

"""Sage Oil Vac scraper with Cloudflare‑proof cookie seeding.

How it works
============
1. **Load a cached `cf_clearance` cookie** (``sage_cookie.json``) if present.
2. Hit the JSON feed. If Cloudflare still serves HTML:
   • Launch headless Playwright **once**, visit the public job list, solve the
     challenge, and save ``sage_cookie.json``.
   • Attach the fresh cookie to a ``cloudscraper`` session and retry the feed.
3. If *that* fails, fall back to full DOM scraping (Playwright) as a last
   resort.

Usage notes
-----------
* In CI you’ll need two artifact steps:
  ```yaml
  - name: Download CF cookie (if exists)
    uses: actions/download-artifact@v4
    with: { name: sage-oil-vac-cookie, path: . }

  - name: Run scrapers
    run: python run_scrapers.py

  - name: Upload CF cookie
    if: always()
    uses: actions/upload-artifact@v4
    with: { name: sage-oil-vac-cookie, path: sage_cookie.json }
  ```
* The cookie usually lives 7–14 days; the seeding step only triggers when the
  feed fails **and** the cached cookie is missing or expired.
* Toggle seeding with the env‑var ``CF_SEED_COOKIES=false`` if you ever want
  to skip Playwright entirely.

Dependencies
------------
* ``cloudscraper>=1.2,<2``
* ``playwright`` (already in repo)
* ``nest_asyncio`` (for nested event loops)
"""

from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from typing import List, Dict, Optional
import asyncio
import json
import os

import cloudscraper
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from utils import build_job_id

BASE_URL = "https://sageoilvac.isolvedhire.com"
LIST_URL = f"{BASE_URL}/jobs/"
COOKIE_FILE = Path("sage_cookie.json")

CANDIDATE_FEEDS = [
    "jobs?format=json&per_page=100&page=1",
    "jobs/positions?format=json&per_page=100&page=1",
    "jobs/positions.json",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": LIST_URL,
}

# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def _load_cookies(scraper: cloudscraper.CloudScraper) -> None:
    """Attach cookies from COOKIE_FILE to scraper session if file exists."""
    if not COOKIE_FILE.exists():
        return
    try:
        state = json.loads(COOKIE_FILE.read_text())
        for c in state.get("cookies", []):
            scraper.cookies.set(c.get("domain"), c.get("name"), c.get("value"), path=c.get("path", "/"))
    except Exception:
        # bad file – ignore and continue
        pass


async def _seed_cookie_playwright() -> None:
    """Run headless Chromium once to obtain a fresh cf_clearance cookie."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(LIST_URL, timeout=120_000, wait_until="networkidle")
        # Saving storage state captures cf_clearance + other cookies
        await context.storage_state(path=COOKIE_FILE)
        await browser.close()


# ---------------------------------------------------------------------------
# Feed discovery (fast path)
# ---------------------------------------------------------------------------

def _get_scraper() -> cloudscraper.CloudScraper:
    scraper = cloudscraper.create_scraper(browser="chrome")
    scraper.headers.update(HEADERS)
    _load_cookies(scraper)
    return scraper


def _try_json_feed(scraper: cloudscraper.CloudScraper, feed_log: List[str]) -> Optional[List[Dict]]:
    """Return jobs list if any JSON endpoint succeeds."""
    for path in CANDIDATE_FEEDS:
        url = f"{BASE_URL}/{path}"
        try:
            resp = scraper.get(url, timeout=20)
            ctype = resp.headers.get("content-type", "")
            feed_log.append(f"{url} → {resp.status_code} {ctype} (len={len(resp.content)})")
            if "application/json" not in ctype:
                continue
            data = resp.json()
        except Exception:
            continue

        rows = (
            data.get("positions")
            or data.get("data", {}).get("positions")
            or (data if isinstance(data, list) else None)
        ) or []
        if not rows:
            continue

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
        return jobs
    return None


def _fetch_from_feed() -> Optional[List[Dict]]:
    """Try JSON endpoints with optional cookie seeding."""

    feed_log: List[str] = []
    scraper = _get_scraper()

    # First attempt using current cookie jar
    jobs = _try_json_feed(scraper, feed_log)
    if jobs:
        return jobs

    # If feed failed and seeding is allowed, run Playwright once
    if os.getenv("CF_SEED_COOKIES", "true").lower() in {"1", "true", "yes"}:
        try:
            asyncio.run(_seed_cookie_playwright())
        except RuntimeError:
            import nest_asyncio
            nest_asyncio.apply()
            asyncio.get_event_loop().run_until_complete(_seed_cookie_playwright())

        # Reload scraper with fresh cookie
        scraper = _get_scraper()
        jobs = _try_json_feed(scraper, feed_log)
        if jobs:
            return jobs

    # Save log for debugging
    Path("sage_debug_feed.txt").write_text("\n".join(feed_log), "utf-8")
    return None

# ---------------------------------------------------------------------------
# Playwright DOM fallback
# ---------------------------------------------------------------------------

async def _scrape_async() -> List[Dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(user_agent=HEADERS["User-Agent"])
        page = await context.new_page()
        await page.goto(LIST_URL, timeout=120_000, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle")

        try:
            await page.wait_for_selector("a.job-name", timeout=120_000)
        except PWTimeout:
            Path("sage_debug.html").write_text(await page.content(), "utf-8")
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
            location, employment_type, salary = (spans + ["", "", ""])[0:3]

            posted_span = await card.query_selector("div.pt1 span")
            posted = (
                (await posted_span.inner_text()).replace("Posted:", "").strip() if posted_span else ""
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
# Public API
# ---------------------------------------------------------------------------

def fetch_jobs() -> List[Dict]:
    """Return job list using JSON feed when possible; otherwise Playwright."""

    jobs = _fetch_from_feed()
    if jobs:
        return jobs

    # Final fallback: full DOM scrape
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
