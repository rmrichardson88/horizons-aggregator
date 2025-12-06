from __future__ import annotations

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


COMPANY = "Sage Oil Vac"
SOURCE = "Sage Oil Vac"


LIST_URL = "https://www.sageoilvac.com/careers/"


BOARD_URL = (
    "https://www.sageoilvac.com/v4/ats/web.php/jobs"
    "?clientkey=B39186ACE47083BD491D331CA51B2261"
)


def _now_utc_iso_seconds() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _extract_clearcompany_id(url: str) -> Optional[str]:
    """
    Extract the numeric job id from the ViewJobDetails URL, e.g.:

    https://www.sageoilvac.com/v4/ats/web.php/jobs/ViewJobDetails?job=7064&clientkey=...
    -> "7064"
    """
    try:
        qs = parse_qs(urlparse(url).query)
        job_vals = qs.get("job") or qs.get("Job")
        if job_vals:
            return job_vals[0]
    except Exception:
        pass


    m = re.search(r"[?&]job=(\d+)", url)
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


        page.goto(BOARD_URL, wait_until="domcontentloaded", timeout=60000)


        try:
            page.get_by_role("button", name=re.compile("Accept|Agree|OK", re.I)).click(timeout=3000)
        except Exception:
            pass


        try:
            page.wait_for_selector("li.jobInfo.JobListing", timeout=20000)
        except PWTimeout:
            browser.close()
            return []


        rows = page.eval_on_selector_all(
            "li.jobInfo.JobListing",
            """els => els.map(li => {
                const a = li.querySelector('a.JobListing__container');
                const titleSpan = li.querySelector('.jobInfoLine.jobTitle');
                const locSpan = li.querySelector('.jobInfoLine.jobLocation');
                const title = titleSpan
                    ? titleSpan.innerText.trim()
                    : (a ? a.innerText.trim() : '');
                const url = a ? a.href : '';
                const location = locSpan ? locSpan.innerText.trim() : '';
                return { title, url, location };
            })"""
        )

        browser.close()

    for r in rows:
        url = (r.get("url") or "").strip()
        title = (r.get("title") or "").strip()
        location = (r.get("location") or "").strip() or None

        if not url or not title:
            continue

        job_id = _extract_clearcompany_id(url) or title[:90]

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
