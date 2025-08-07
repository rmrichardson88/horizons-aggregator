from __future__ import annotations

"""Sage Oil Vac scraper – *HTML‑only, no Cloudflare gymnastics*.

How it works
============
* One `GET https://sageoilvac.isolvedhire.com/jobs/` with a desktop User‑Agent.
* Parse the returned HTML.
* Extract the big `<script id="__NEXT_DATA__" type="application/json">…` blob
  that Next.js embeds server‑side.
* Load the JSON → `positions` array → build job dicts.

Why this is simpler
-------------------
Because the data is delivered *inside the initial HTML*, Cloudflare never blocks
it – even to GitHub runners. No JSON feed, no cookies, no Playwright.

Dependencies: `requests`, `beautifulsoup4`, `utils.build_job_id`.
"""

from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
import json
import requests
from bs4 import BeautifulSoup, Tag
from utils import build_job_id

BASE_URL = "https://sageoilvac.isolvedhire.com"
LIST_URL = f"{BASE_URL}/jobs/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_positions(data: Any) -> List[Dict]:
    """Traverse a Next.js `__NEXT_DATA__` payload and return positions list."""

    # Expected path: props → pageProps → positions
    ptr = data
    for key in ("props", "pageProps"):
        ptr = ptr.get(key, {}) if isinstance(ptr, dict) else {}
    positions = ptr.get("positions") or ptr.get("data", {}).get("positions")
    if not isinstance(positions, list):
        return []
    return positions


# ---------------------------------------------------------------------------
# Playwright HTML fallback (handles Cloudflare interstitial)
# ---------------------------------------------------------------------------

import asyncio
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
import nest_asyncio


async def _fetch_html_playwright() -> str:
    """Return page HTML after Cloudflare JS has executed (headless)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(user_agent=HEADERS["User-Agent"])
        page = await context.new_page()
        await page.goto(LIST_URL, timeout=120_000, wait_until="domcontentloaded")
        try:
            # Wait either for job card or for __NEXT_DATA__ script to appear
            await page.wait_for_function("() => document.querySelector('#__NEXT_DATA__') !== null", timeout=120_000)
        except PWTimeout:
            html = await page.content()
            await browser.close()
            return html  # Return whatever we have; caller will still attempt parse
        html = await page.content()
        await browser.close()
        return html


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _parse_jobs_from_html(html: str) -> List[Dict]:
    """Parse HTML and return jobs list (empty list if none)."""
    soup = BeautifulSoup(html, "html.parser")
    script: Optional[Tag] = soup.find("script", id="__NEXT_DATA__", type="application/json")
    if not script or not script.string:
        return []
    try:
        data = json.loads(script.string)
    except json.JSONDecodeError:
        return []
    rows = _extract_positions(data)
    jobs: List[Dict] = []
    for row in rows:
        title = row.get("title") or row.get("name", "")
        url_ = row.get("url") or row.get("applyUrl", "")
        location = (row.get("location") or "").replace(", USA", "").strip()
        posted = row.get("posted", row.get("postDate", ""))
        employment_type = row.get("employment_type", "")
        salary = row.get("pay", row.get("compensation", ""))
        jobs.append(
            {
                "id": build_job_id(str(row.get("id", url_.split("/")[-1])), title, location),
                "title": title,
                "company": "Sage Oil Vac",
                "location": location,
                "employment_type": employment_type,
                "salary": salary,
                "posted": posted,
                "url": url_,
                "scraped_at": datetime.utcnow().isoformat(timespec="seconds"),
                "source": "Sage Oil Vac",
            }
        )
    return jobs


def fetch_jobs() -> List[Dict]:
    """Fetch Sage Oil Vac jobs, HTML first, Playwright fallback if needed."""

    # 1. Simple requests HTML fetch
    try:
        resp = requests.get(LIST_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        jobs = _parse_jobs_from_html(resp.text)
        if jobs:
            return jobs
    except Exception:
        pass

    # 2. Fallback: Playwright to get HTML after Cloudflare JS challenge
    try:
        html = asyncio.run(_fetch_html_playwright())
    except RuntimeError:
        nest_asyncio.apply()
        html = asyncio.get_event_loop().run_until_complete(_fetch_html_playwright())

    jobs = _parse_jobs_from_html(html)
    return jobs


if __name__ == "__main__":
    from pprint import pprint
    pprint(fetch_jobs()[:5])
