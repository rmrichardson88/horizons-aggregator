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
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

def _now_utc_iso_seconds() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")

def _extract_job_id(href: str) -> Optional[str]:
    try:
        q = parse_qs(urlparse(href).query)
        v = q.get("jobid")
        return v[0] if v else None
    except Exception:
        return None

def _fallback_search_keyword(page) -> None:
    selectors = [
        "input#keywordsearch",
        "input[name='keywordsearch']",
        "input[ng-model*='Keyword']",
        "input[placeholder*='keyword' i]",
        "input[aria-label*='keyword' i]",
        "input[type='search']",
    ]
    for sel in selectors:
        try:
            inp = page.locator(sel).first
            if inp.count() == 0:
                continue
            inp.fill("")
            inp.type("Amarillo, Texas")
            inp.press("Enter")
            page.wait_for_load_state("networkidle")
            return
        except Exception:
            continue

def _apply_amarillo(page) -> None:
    try:
        page.get_by_role("link", name=re.compile(r"^\s*Advanced Search\s*$", re.I)).click(timeout=7000)
    except Exception:
        try:
            page.locator(".powerSearchLink a.UnderLineLink", has_text=re.compile("Advanced Search", re.I)).first.click(timeout=7000)
        except Exception:
            _fallback_search_keyword(page)
            return

    try:
        page.wait_for_selector("label.checkboxLabel", timeout=10000)
    except PWTimeout:
        _fallback_search_keyword(page)
        return

    try:
        page.get_by_label(re.compile(r"HSC\s*[-–—]\s*Amarillo", re.I)).check(timeout=8000, force=True)
    except Exception:
        lbl = page.locator("label.checkboxLabel", has_text=re.compile(r"HSC\s*[-–—]\s*Amarillo", re.I)).first
        lbl.scroll_into_view_if_needed()
        lbl.click(timeout=8000)

    for name in ["Search", "Apply", "Done", "Update", "Go"]:
        try:
            page.get_by_role("button", name=re.compile(fr"^\s*{name}\s*$", re.I)).click(timeout=3000)
            break
        except Exception:
            continue

def _scrape_listing_page(page) -> List[Dict[str, Optional[str]]]:
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
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"]) 
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()

        page.goto(START_URL, wait_until="networkidle")
        try:
            _apply_amarillo(page)
        except PWTimeout:
            pass

        page_index = 1
        seen_total = 0
        while page_index <= max_pages:
            page_jobs = _scrape_listing_page(page)
            if not page_jobs:
                break
            jobs.extend(page_jobs)

            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass

            advanced = False
            for sel in [
                'a[aria-label="Next"]:not([aria-disabled="true"])',
                'button[aria-label="Next"]:not([disabled])',
                'li.paginationNext a',
                'a[title="Next"]',
                'button:has-text("Load more")',
                'button:has-text("Show more")',
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

    if not any("amarillo" in (j.get("location") or "").lower() for j in jobs):
        jobs = [j for j in jobs if (j.get("location") or "").lower().startswith("amarillo")]

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
