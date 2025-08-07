import asyncio
import datetime as dt
import re
from typing import List, Dict

from bs4 import BeautifulSoup  # for easier DOM traversal
from playwright.async_api import async_playwright


BASE_URL = "https://sageoilvac.isolvedhire.com"
LISTING_URL = f"{BASE_URL}/jobs/"


async def _get_page_html() -> str:
    """Launch headless Chromium, navigate to the jobs page, and return full HTML."""
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
    jobs = []

    for card in soup.select("div.bdb1"):
        title_el = card.select_one("a.job-name")
        if not title_el:  # Skip malformed cards
            continue

        # Basic fields
        title = title_el.get_text(strip=True)
        href = title_el["href"]
        url = href if href.startswith("http") else f"{BASE_URL}{href}"
        job_id = re.search(r"/jobs/(\d+)", url).group(1)

        # Additional metadata (selectors vary slightly between themes)
        location = (
            card.select_one(".job-location, .location, [data-testid='job-location']")
            .get_text(strip=True)
            if card.select_one(".job-location, .location, [data-testid='job-location']")
            else ""
        )
        salary = (
            card.select_one(".job-salary, .salary, .compensation")
            .get_text(strip=True)
            if card.select_one(".job-salary, .salary, .compensation")
            else ""
        )

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


async def fetch_jobs() -> List[Dict]:
    """Public entry point: returns list of job dicts."""
    html = await _get_page_html()
    return _parse_cards(html)


# --------------------------------------------------------------------------- #
# CLI usage                                                                   #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    jobs = asyncio.run(fetch_jobs())
    for job in jobs:
        print(job)
