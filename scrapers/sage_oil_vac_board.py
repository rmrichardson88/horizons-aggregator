from __future__ import annotations

import json
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

try:
    from datetime import datetime, UTC
except Exception:
    from datetime import datetime, timezone as _tz
    UTC = _tz.utc


COMPANY = "Sage Oil Vac"
SOURCE = "Sage Oil Vac"

LIST_URL = (
    "https://www.paycomonline.net/v4/ats/web.php/jobs"
    "?clientkey=A2551499AF9F0B92169C5FA32A8E8354"
)


def _now_utc_iso_seconds() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _extract_job_id(url: str) -> Optional[str]:
    """
    Pull the job ID from the Paycom URL, e.g.
    ...ViewJobDetails?clientkey=...&job=7064  -> "7064"
    """
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        job_ids = qs.get("job")
        if job_ids:
            return job_ids[0]
        m = re.search(r"/(\d+)(?:/)?$", parsed.path)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _fetch_location(detail_url: str) -> Optional[str]:
    """
    Grab "Job Location" from the detail page. The Paycom detail page
    has a "Job Location" heading followed by the address line.
    """
    try:
        r = requests.get(
            detail_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=20,
        )
        r.raise_for_status()
    except Exception:
        return None

    try:
        from bs4 import BeautifulSoup 
    except Exception:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    for i, ln in enumerate(lines):
        if ln == "Job Location" and i + 1 < len(lines):
            return lines[i + 1]
    return None


def fetch_jobs() -> List[Dict[str, Optional[str]]]:
    jobs: List[Dict[str, Optional[str]]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()
        page.goto(LIST_URL, wait_until="domcontentloaded")


        try:
            page.get_by_role("button", name=re.compile("Accept", re.I)).click(timeout=3000)
        except Exception:
            pass


        try:
            page.wait_for_selector("li.jobInfo.JobListing, li.JobListing", timeout=20000)
        except PWTimeout:
            browser.close()
            return []

        rows = page.eval_on_selector_all(
            "li.jobInfo.JobListing, li.JobListing",
            """els => els.map(li => {
                const a = li.querySelector('a.JobListing__container, a[href*="ViewJobDetails"]');
                const titleSpan = li.querySelector('.jobTitle') || a;
                const descrSpan = li.querySelector('.jobDescription');
                const href = a ? (a.getAttribute('href') || '') : '';
                let url = href;
                try {
                    url = href ? new URL(href, window.location.origin).href : '';
                } catch (e) {}
                return {
                    title: titleSpan ? titleSpan.textContent.trim() : '',
                    url,
                    summary: descrSpan ? descrSpan.textContent.trim() : ''
                };
            })"""
        )

        browser.close()

    for row in rows:
        title = (row.get("title") or "").strip()
        url = (row.get("url") or "").strip()
        if not title or not url:
            continue

        job_id = _extract_job_id(url) or title[:90]

        location = _fetch_location(url)

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
