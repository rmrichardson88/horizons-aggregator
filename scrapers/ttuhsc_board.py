import json
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

try:
    from datetime import datetime, UTC
except Exception: 
    from datetime import datetime, timezone as _tz
    UTC = _tz.utc 

START_URL = (
    "https://sjobs.brassring.com/TGnewUI/Search/Home/Home"
    "?partnerid=25898&siteid=5283#Campus=HSC%20-%20Amarillo&keyWordSearch="
)
COMPANY = "Texas Tech University Health Sciences Center"
SOURCE = "TTUHSC"


def _now_utc_iso_seconds() -> str:

    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _extract_job_id(href: str) -> Optional[str]:

    try:
        q = parse_qs(urlparse(href).query)
        v = q.get("jobid")
        return v[0] if v else None
    except Exception:
        return None


def _scrape_listing_page(page, base_url: str) -> List[Dict[str, Optional[str]]]:
    jobs: List[Dict[str, Optional[str]]] = []
    try:
        page.wait_for_selector('div.liner.lightBorder a.jobProperty.jobtitle', timeout=25000)
    except PWTimeout:
        return jobs

    cards = page.query_selector_all('div.liner.lightBorder')
    for card in cards:
        a = card.query_selector('a.jobProperty.jobtitle')
        if not a:
            continue
        title = (a.inner_text() or "").strip() or None
        href = (a.get_attribute("href") or "").strip()
        url = href if href.startswith("http") else href

        loc_el = card.query_selector('p.jobProperty.position1')
        location = (loc_el.inner_text().strip() if loc_el else None) or None

        job_id = _extract_job_id(url) or (url.split("jobid=")[-1] if "jobid=" in url else None)

        jobs.append(
            {
                "id": job_id,
                "title": title,
                "company": COMPANY,
                "location": location,
                "salary": None,
                "url": url,
                "scraped_at": _now_utc_iso_seconds(),
                "source": SOURCE,
            }
        )
    return jobs


def fetch_jobs(max_pages: int = 10) -> List[Dict[str, Optional[str]]]:
    jobs: List[Dict[str, Optional[str]]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ))
        page = ctx.new_page()
        page.goto(START_URL, wait_until="networkidle")

        page_index = 1
        seen_total = 0
        while page_index <= max_pages:
            page_jobs = _scrape_listing_page(page, START_URL)
            if not page_jobs:
                break
            jobs.extend(page_jobs)

            advanced = False
            for sel in [
                'a[aria-label="Next"]:not([aria-disabled="true"])',
                'button[aria-label="Next"]:not([disabled])',
                'li.paginationNext a',
                'a[title="Next"]',
            ]:
                btn = page.query_selector(sel)
                if btn:
                    try:
                        btn.click()
                        page.wait_for_load_state("networkidle")
                        advanced = True
                        break
                    except Exception:
                        pass
            if not advanced:
                break
            page_index += 1
            if len(jobs) == seen_total:
                break
            seen_total = len(jobs)

        browser.close()

    seen = set()
    uniq: List[Dict[str, Optional[str]]] = []
    for j in jobs:
        key = (j.get("id"), j.get("url"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(j)
    return uniq


if __name__ == "__main__":
    print(json.dumps(fetch_jobs(), ensure_ascii=False))
