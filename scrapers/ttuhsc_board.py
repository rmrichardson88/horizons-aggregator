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

# Core selector we rely on (titles inside result cards)
JOB_ANCHOR_SEL = "div.liner.lightBorder a.jobProperty.jobtitle"
CARD_SEL = "div.liner.lightBorder"


def _now_utc_iso_seconds() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _extract_job_id(href: str) -> Optional[str]:
    try:
        q = parse_qs(urlparse(href).query)
        v = q.get("jobid")
        return v[0] if v else None
    except Exception:
        return None


def _safe_wait_for_results(page, timeout: int = 25000) -> None:
    """
    Wait for the results list to be present on the page (instead of networkidle).
    """
    page.wait_for_selector(JOB_ANCHOR_SEL, timeout=timeout)


def _accept_cookies_if_any(page) -> None:
    try:
        page.get_by_role("button", name=re.compile("Accept|Agree|OK|Got it|I Accept|Close", re.I)).click(timeout=2500)
    except Exception:
        pass


def _safe_goto(page, url: str) -> None:
    """
    Navigate without relying on 'networkidle' which often never fires on BrassRing.
    """
    page.set_default_navigation_timeout(60000)  # 60s nav budget
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except PWTimeout:
        # Retry with 'load' as a fallback
        page.goto(url, wait_until="load", timeout=60000)
    _accept_cookies_if_any(page)


def _fallback_search_keyword(page) -> None:
    """
    As a last resort, type a query and press Enter to trigger results.
    """
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
            # Wait for list to render
            _safe_wait_for_results(page, timeout=20000)
            return
        except Exception:
            continue


def _apply_amarillo(page) -> None:
    """
    Try Advanced Search and select the 'HSC – Amarillo' campus filter.
    Falls back to a keyword search if the advanced panel doesn't load.
    """
    # Open Advanced Search
    try:
        page.get_by_role("link", name=re.compile(r"^\s*Advanced Search\s*$", re.I)).click(timeout=7000)
    except Exception:
        try:
            page.locator(".powerSearchLink a.UnderLineLink", has_text=re.compile("Advanced Search", re.I)).first.click(
                timeout=7000
            )
        except Exception:
            _fallback_search_keyword(page)
            return

    # Wait for filter labels in the advanced panel
    try:
        page.wait_for_selector("label.checkboxLabel", timeout=10000)
    except PWTimeout:
        _fallback_search_keyword(page)
        return

    # Check the Amarillo campus box
    try:
        page.get_by_label(re.compile(r"HSC\s*[-–—]\s*Amarillo", re.I)).check(timeout=8000, force=True)
    except Exception:
        lbl = page.locator("label.checkboxLabel", has_text=re.compile(r"HSC\s*[-–—]\s*Amarillo", re.I)).first
        try:
            lbl.scroll_into_view_if_needed()
        except Exception:
            pass
        lbl.click(timeout=8000)

    # Click something that applies/submits
    for name in ["Search", "Apply", "Done", "Update", "Go"]:
        try:
            page.get_by_role("button", name=re.compile(fr"^\s*{name}\s*$", re.I)).click(timeout=3000)
            break
        except Exception:
            continue

    # Wait for list to render after applying filter
    _safe_wait_for_results(page, timeout=20000)


def _scrape_listing_page(page) -> List[Dict[str, Optional[str]]]:
    jobs: List[Dict[str, Optional[str]]] = []
    try:
        _safe_wait_for_results(page, timeout=25000)
    except PWTimeout:
        return jobs

    cards = page.query_selector_all(CARD_SEL)
    for card in cards:
        a = card.query_selector(JOB_ANCHOR_SEL)
        if not a:
            continue
        title = (a.inner_text() or "").strip() or None
        href = (a.get_attribute("href") or "").strip()
        url = href if href.startswith("http") else href

        loc_el = card.query_selector("p.jobProperty.position1")
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
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()

        # Safer nav + real readiness
        _safe_goto(page, START_URL)
        try:
            _apply_amarillo(page)
        except PWTimeout:
            pass
        # Ensure first batch rendered
        try:
            _safe_wait_for_results(page, timeout=25000)
        except PWTimeout:
            # dump for debugging in CI
            try:
                with open("ttuhsc_debug_initial.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
            finally:
                browser.close()
                return []

        page_index = 1
        seen_total = 0
        while page_index <= max_pages:
            page_jobs = _scrape_listing_page(page)
            if not page_jobs:
                break
            jobs.extend(page_jobs)

            # Scroll to bottom to reveal pager/load-more if needed
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass

            # Capture current count to detect change on next page
            try:
                prev_count = len(page.query_selector_all(JOB_ANCHOR_SEL))
            except Exception:
                prev_count = 0

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
                        # Wait for the list to actually change (SPA-friendly)
                        try:
                            page.wait_for_function(
                                "prev => document.querySelectorAll(arguments[0]).length > prev",
                                prev_count,
                                argument=JOB_ANCHOR_SEL,
                                timeout=10000,
                            )
                        except Exception:
                            # As a fallback, wait for any job anchor (in case of same count)
                            _safe_wait_for_results(page, timeout=10000)
                        advanced = True
                        break
                    except Exception:
                        pass

            if not advanced:
                break

            page_index += 1
            if len(jobs) == seen_total:
                # No net new added this iteration → stop
                break
            seen_total = len(jobs)

        browser.close()

    # If nothing says "Amarillo" explicitly, prefer location startswith Amarillo
    if not any("amarillo" in (j.get("location") or "").lower() for j in jobs):
        jobs = [j for j in jobs if (j.get("location") or "").lower().startswith("amarillo")]

    # De-dupe by (id, url)
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
