from __future__ import annotations

import json
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

try:
    from datetime import datetime, UTC
except Exception:  # Python < 3.11
    from datetime import datetime, timezone as _tz
    UTC = _tz.utc


COMPANY = "Western Equipment"
SOURCE = "Western Equipment"

LIST_URL = (
    "https://www.paycomonline.net/v4/ats/web.php/jobs"
    "?clientkey=BEC705AAE8346DB92E3A5C60250EE84C"
)


def _now_utc_iso_seconds() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _extract_job_id(url: str) -> Optional[str]:
    """
    Pull the job ID from a Paycom job URL, e.g.
    .../jobs/181177 or ...ViewJobDetails?job=181177 -> "181177"
    """
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        job_ids = qs.get("job")
        if job_ids:
            return job_ids[0]
        m = re.search(r"/jobs/(\d+)", parsed.path)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


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

        page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)

        try:
            page.get_by_role("button", name=re.compile("Accept|Agree|OK", re.I)).click(
                timeout=3000
            )
        except Exception:
            pass

        selector = (
            'a[href*="/v4/ats/web.php/portal/BEC705AAE8346DB92E3A5C60250EE84C/jobs/"]'
        )
        try:
            page.wait_for_selector(selector, timeout=20000)
        except PWTimeout:
            browser.close()
            return []

        rows = page.eval_on_selector_all(
            selector,
            """els => els.map(a => {
                const href = a.getAttribute('href') || '';
                let url = href;
                try {
                    url = new URL(href, window.location.origin).href;
                } catch (e) {}

                const titleEl = a.querySelector('h2[data-testid="typography"]') || a.querySelector('h2');
                const title = titleEl ? titleEl.textContent.trim() : '';

                const pEls = Array.from(a.querySelectorAll('p[data-testid="typography"]'));
                const location = pEls.length > 0 ? pEls[0].textContent.trim() : '';
                const summary = pEls.length > 1 ? pEls[1].textContent.trim() : '';

                return { title, url, location, summary };
            })"""
        )

        browser.close()

    for r in rows:
        url = (r.get("url") or "").strip()
        title = (r.get("title") or "").strip()
        location = (r.get("location") or "").strip() or None

        if not url or not title:
            continue

        job_id = _extract_job_id(url) or title[:90]

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
