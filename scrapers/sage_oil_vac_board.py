from __future__ import annotations


from datetime import datetime
from typing import List, Dict, Optional, Any
import json
import asyncio
import requests
from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
import nest_asyncio
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

def _extract_positions(data: Any) -> List[Dict]:
    """Return the list of job dicts from a Next.js `__NEXT_DATA__` payload.

    • Primary path – `props → pageProps → positions` (or `.data.positions`).
    • Fallback – depth‑first search for a list whose first item is a dict
      containing a `title` field.
    """

    ptr = data
    for key in ("props", "pageProps"):
        ptr = ptr.get(key, {}) if isinstance(ptr, dict) else {}
    positions = ptr.get("positions") or ptr.get("data", {}).get("positions")
    if isinstance(positions, list) and positions:
        return positions

    def _find(obj: Any) -> List[Dict]:
        if isinstance(obj, list):
            if obj and isinstance(obj[0], dict) and "title" in obj[0]:
                return obj
            for item in obj:
                hit = _find(item)
                if hit:
                    return hit
        elif isinstance(obj, dict):
            for v in obj.values():
                hit = _find(v)
                if hit:
                    return hit
        return []

    return _find(data)

async def _fetch_html_playwright() -> str:
    """Return page HTML after Cloudflare JS has executed (headless)."""

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(user_agent=HEADERS["User-Agent"])
        page = await context.new_page()
        await page.goto(LIST_URL, timeout=120_000, wait_until="domcontentloaded")
        try:
            await page.wait_for_function(
                "() => document.querySelector('#__NEXT_DATA__') !== null",
                timeout=120_000,
            )
        except PWTimeout:
            html = await page.content()
            await browser.close()
            return html
        html = await page.content()
        await browser.close()
        return html

def _parse_jobs_from_html(html: str) -> List[Dict]:
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
    """Fetch Sage Oil Vac jobs; Playwright only if plain HTML lacks data."""

    try:
        resp = requests.get(LIST_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        jobs = _parse_jobs_from_html(resp.text)
        if jobs:
            return jobs
    except Exception:
        pass

    try:
        html = asyncio.run(_fetch_html_playwright())
    except RuntimeError:
        nest_asyncio.apply()
        html = asyncio.get_event_loop().run_until_complete(_fetch_html_playwright())

    return _parse_jobs_from_html(html)


if __name__ == "__main__":
    from pprint import pprint
    pprint(fetch_jobs()[:5])
