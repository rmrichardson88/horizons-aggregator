import json
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

try:
    from datetime import datetime, UTC  
except Exception:  
    from datetime import datetime, timezone as _tz  
    UTC = _tz.utc 

BASE = "https://tamus.wd1.myworkdayjobs.com"
SITE = "WTAMU_External"
START_URLS = [
    f"{BASE}/en-US/{SITE}",
    f"{BASE}/{SITE}",
]
COMPANY = "West Texas A&M University"
SOURCE = "WTAMU"


def _now_utc_iso_seconds() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _extract_req_id(text: str) -> Optional[str]:
    m = re.search(r"\b(R-\d+(?:-\d+)?)\b", text or "")
    return m.group(1) if m else None


def _scrape_listing_page(page, start_url: str) -> List[Dict[str, Optional[str]]]:
    jobs: List[Dict[str, Optional[str]]] = []
    try:
        page.wait_for_selector('a[data-automation-id="jobTitle"]', timeout=20000)
    except PWTimeout:
        return jobs

    anchors = page.query_selector_all('a[data-automation-id="jobTitle"]')
    for a in anchors:
        title = (a.text_content() or "").strip() or None
        href = (a.get_attribute("href") or "").strip()
        url = urljoin(start_url + "/", href.lstrip("/")) if href else start_url

        li = a.evaluate_handle("e => e.closest('li')")
        location = None
        req_id = None
        if li:
            loc_el = page.evaluate_handle(
                """(el) => el.querySelector('[data-automation-id="locations"]')""",
                li
            )
            if loc_el:
                location = (page.evaluate("e => e.innerText", loc_el) or "").strip() or None
            sub_el = page.evaluate_handle(
                """(el) => el.querySelector('ul[data-automation-id="subtitle"] li')""",
                li
            )

            if sub_el:
                sub_text = (page.evaluate("e => e.innerText", sub_el) or "").strip()
                rid = _extract_req_id(sub_text)
                if rid:
                    req_id = rid
        job_id = req_id or (href.rstrip("/").split("/")[-1] if href else None)

        jobs.append({
            "id": job_id,
            "title": title,
            "company": COMPANY,
            "location": location,
            "salary": None,
            "url": url,
            "scraped_at": _now_utc_iso_seconds(),
            "source": SOURCE,
        })
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

        collected = False
        for start in START_URLS:
            page_num = 1
            while page_num <= max_pages:
                url = start if page_num == 1 else f"{start}?page={page_num}"
                page.goto(url, wait_until="networkidle")
                try:
                    page.get_by_role("button", name=re.compile("Accept|Agree|OK", re.I)).click(timeout=2500)
                except Exception:
                    pass
                page_jobs = _scrape_listing_page(page, start)
                if not page_jobs:
                    break
                jobs.extend(page_jobs)
                page_num += 1
                collected = True
            if collected:
                break

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
