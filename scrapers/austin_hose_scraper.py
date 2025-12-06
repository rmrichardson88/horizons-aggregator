from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

try:
    from datetime import datetime, UTC
except Exception:
    from datetime import datetime, timezone as _tz
    UTC = _tz.utc


COMPANY = "Austin Hose"
SOURCE = "Austin Hose"
LIST_URL = "https://recruiting.paylocity.com/recruiting/jobs/All/0a932b3f-65a0-4207-b5be-70d84a78ecaa/Austin-Hose"


def _now_utc_iso_seconds() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _slug(s: str) -> str:
    s = s.replace("\xa0", " ").strip()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _extract_paylocity_id(url: str) -> Optional[str]:
    """
    Extract the numeric job id from a Paylocity details URL, e.g.
    https://recruiting.paylocity.com/Recruiting/Jobs/Details/3753813
    -> "3753813"
    """
    m = re.search(r"/Details/(\d+)", url)
    return m.group(1) if m else None


def fetch_jobs() -> List[Dict[str, Optional[str]]]:
    jobs: List[Dict[str, Optional[str]]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()
        page.goto(LIST_URL, wait_until="networkidle")

        try:
            page.get_by_role("button", name=re.compile("Accept|Agree|OK", re.I)).click(timeout=3000)
        except Exception:
            pass

        try:
            page.wait_for_selector("div.row.job-listing-job-item", timeout=20000)
        except PWTimeout:
            browser.close()
            return []


        rows = page.eval_on_selector_all(
            "div.row.job-listing-job-item",
            """els => els.map(row => {
                const a = row.querySelector('.job-title-column .job-item-title a');
                const locSpan = row.querySelector('.location-column span');
                const title = a ? a.innerText.trim() : '';
                const href = a ? (a.getAttribute('href') || '').trim() : '';
                let absUrl = '';
                if (href) {
                    try {
                        absUrl = new URL(href, window.location.origin).toString();
                    } catch (e) {
                        absUrl = href;
                    }
                }
                const location = locSpan ? locSpan.innerText.trim() : '';
                return { title, url: absUrl, location };
            })"""
        )

        browser.close()

    for r in rows:
        url = (r.get("url") or "").strip()
        title = (r.get("title") or "").strip()
        location = (r.get("location") or "").strip() or None

        if not url or not title:
            continue

        job_id = _extract_paylocity_id(url)
        if not job_id:
            job_id = _slug(f"austinhose-{title}")[:90]

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


if __name__ == "__main__":
    print(json.dumps(fetch_jobs(), ensure_ascii=False))
