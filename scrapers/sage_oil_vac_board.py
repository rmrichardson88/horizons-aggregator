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
CLIENT_KEY = "A2551499AF9F0B92169C5FA32A8E8354"

LIST_URL = (
    "https://www.paycomonline.net/v4/ats/web.php/jobs"
    f"?clientkey={CLIENT_KEY}"
)
DETAIL_URL = "https://www.paycomonline.net/v4/ats/web.php/jobs/ViewJobDetails"
PORTAL_JOB_SELECTOR = f'a[href*="/v4/ats/web.php/portal/{CLIENT_KEY}/jobs/"]'
LEGACY_JOB_SELECTOR = 'a.JobListing__container, a[href*="ViewJobDetails"]'
JOB_LINK_SELECTOR = f"{PORTAL_JOB_SELECTOR}, {LEGACY_JOB_SELECTOR}"


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
        m = re.search(r"/jobs/(\d+)(?:/)?$", parsed.path)
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
    m = re.search(r"Job\s+Location\s+(.+?,\s*[A-Z]{2}(?:\s+\d{5})?)", text, re.I)
    if m:
        return m.group(1).strip()
    return None


def _legacy_detail_url(job_id: str) -> str:
    return f"{DETAIL_URL}?clientkey={CLIENT_KEY}&job={job_id}"


def fetch_jobs() -> List[Dict[str, Optional[str]]]:
    jobs: List[Dict[str, Optional[str]]] = []
    seen_ids: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
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
            page.wait_for_selector(JOB_LINK_SELECTOR, timeout=20000)
        except PWTimeout:
            browser.close()
            return []

        rows = page.eval_on_selector_all(
            JOB_LINK_SELECTOR,
            """els => els.map(a => {
                const card = a.closest('li, article, div[data-testid], div') || a;
                const titleSpan = card.querySelector('h2[data-testid="typography"], h2, .jobTitle, [class*="jobTitle"]') || a;
                const pEls = Array.from(card.querySelectorAll('p[data-testid="typography"], p'));
                const legacyDescrSpan = card.querySelector('.jobDescription, .JobListing__subTitle, [class*="jobLocation"]');
                const href = a ? (a.getAttribute('href') || '') : '';
                let url = href;
                try {
                    url = href ? new URL(href, window.location.origin).href : '';
                } catch (e) {}
                return {
                    title: titleSpan ? titleSpan.textContent.trim() : '',
                    url,
                    location: pEls.length > 0 ? pEls[0].textContent.trim() : '',
                    summary: legacyDescrSpan ? legacyDescrSpan.textContent.trim() : ''
                };
            })"""
        )

        browser.close()

    for row in rows:
        title = (row.get("title") or "").strip()
        url = (row.get("url") or "").strip()
        if not title or not url:
            continue

        extracted_job_id = _extract_job_id(url)
        job_id = extracted_job_id or title[:90]
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        location = (row.get("location") or "").strip() or None
        if not location and extracted_job_id:
            location = _fetch_location(_legacy_detail_url(extracted_job_id))

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
