import json
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

try:
    from datetime import datetime, UTC 
except Exception:
    from datetime import datetime, timezone as _tz  
    UTC = _tz.utc 

COMPANY = "Talon/LPE"
SOURCE = "Talon/LPE"
LIST_URL = "https://www.talonlpe.com/employment"


def _now_utc_iso_seconds() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _extract_teamengine_id(url: str) -> Optional[str]:
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    return parts[-1] if parts else None


def fetch_jobs() -> List[Dict[str, Optional[str]]]:
    jobs: List[Dict[str, Optional[str]]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ))
        page = ctx.new_page()
        page.goto(LIST_URL, wait_until="networkidle")

        try:
            page.get_by_role("button", name=re.compile("Accept|Agree|OK", re.I)).click(timeout=3000)
        except Exception:
            pass

        try:
            page.wait_for_selector('a[href^="https://apply.teamengine.io/apply/"]', timeout=20000)
        except PWTimeout:
            browser.close()
            return []

        rows = page.eval_on_selector_all(
            'tr:has(a[href^="https://apply.teamengine.io/apply/"])',
            '''els => els.map(tr => {
                const a = tr.querySelector('a[href^="https://apply.teamengine.io/apply/"]');
                const tds = Array.from(tr.querySelectorAll('td'));
                const loc = tds.length >= 2 ? tds[1].innerText.trim() : '';
                return { title: a ? a.innerText.trim() : '', url: a ? a.getAttribute('href') : '', location: loc };
            })'''
        )
        browser.close()

    for r in rows:
        url = (r.get("url") or "").strip()
        title = (r.get("title") or "").strip()
        location = (r.get("location") or "").strip() or None
        if not url or not title:
            continue
        job_id = _extract_teamengine_id(url)
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
