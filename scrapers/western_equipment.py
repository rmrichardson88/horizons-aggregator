from __future__ import annotations

import json
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

try:
    from datetime import datetime, UTC
except Exception:  # Python < 3.11
    from datetime import datetime, timezone as _tz
    UTC = _tz.utc


COMPANY = "Western Equipment"
SOURCE = "Western Equipment"
CLIENT_KEY = "BEC705AAE8346DB92E3A5C60250EE84C"

LIST_URL = (
    "https://www.paycomonline.net/v4/ats/web.php/jobs"
    f"?clientkey={CLIENT_KEY}"
)
PORTAL_URL = (
    "https://www.paycomonline.net/v4/ats/web.php/portal"
    f"/{CLIENT_KEY}/career-page"
)
PORTAL_JOB_URL = (
    "https://www.paycomonline.net/v4/ats/web.php/portal"
    f"/{CLIENT_KEY}/jobs"
)
PORTAL_SEARCH_URL = (
    "https://portal-applicant-tracking.us-cent.paycomonline.net"
    "/api/ats/job-posting-previews/search"
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


def _mk_headers(referer: str = PORTAL_URL) -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
    }


def _extract_session_jwt(html: str) -> Optional[str]:
    m = re.search(r'"sessionJWT"\s*:\s*"([^"]+)"', html or "")
    return m.group(1) if m else None


def _portal_search_payload(skip: int, take: int) -> dict:
    return {
        "skip": skip,
        "take": take,
        "filtersForQuery": {
            "distanceFrom": 0,
            "workEnvironments": [],
            "positionTypes": [],
            "educationLevels": [],
            "categories": [],
            "travelTypes": [],
            "shiftTypes": [],
            "otherFilters": [],
            "keywordSearchText": "",
            "location": "",
            "sortOption": "",
        },
    }


def _fetch_portal_jobs(session: requests.Session, *, page_size: int = 100) -> List[dict]:
    resp = session.get(PORTAL_URL, headers=_mk_headers(), timeout=25)
    resp.raise_for_status()

    token = _extract_session_jwt(resp.text)
    if not token:
        return []

    headers = _mk_headers(referer=PORTAL_URL)
    headers.update(
        {
            "Authorization": token,
            "Content-Type": "application/json",
            "Origin": "https://www.paycomonline.net",
            "Referer": "https://www.paycomonline.net/",
        }
    )

    records: List[dict] = []
    total: Optional[int] = None
    skip = 0
    while total is None or skip < total:
        api_resp = session.post(
            PORTAL_SEARCH_URL,
            headers=headers,
            json=_portal_search_payload(skip, page_size),
            timeout=25,
        )
        api_resp.raise_for_status()
        payload = api_resp.json()
        page_records = payload.get("jobPostingPreviews") or []
        if total is None:
            total = int(payload.get("jobPostingPreviewsCount") or len(page_records))
        if not page_records:
            break
        records.extend(page_records)
        skip += len(page_records)
        if len(page_records) < page_size:
            break

    return records


def _parse_portal_record(item: dict) -> Dict[str, Optional[str]]:
    job_id = str(item.get("jobId") or "").strip()
    title = re.sub(r"\s+", " ", str(item.get("jobTitle") or "")).strip() or None
    location = re.sub(r"\s+", " ", str(item.get("locations") or "")).strip() or None

    return {
        "id": job_id or None,
        "title": title,
        "company": COMPANY,
        "location": location,
        "salary": None,
        "url": f"{PORTAL_JOB_URL}/{job_id}" if job_id else PORTAL_URL,
        "scraped_at": _now_utc_iso_seconds(),
        "source": SOURCE,
    }


def fetch_jobs() -> List[Dict[str, Optional[str]]]:
    jobs: List[Dict[str, Optional[str]]] = []
    seen_ids: set[str] = set()

    session = requests.Session()
    try:
        for item in _fetch_portal_jobs(session):
            rec = _parse_portal_record(item)
            if rec.get("id") and rec["id"] not in seen_ids:
                jobs.append(rec)
                seen_ids.add(rec["id"])
    except requests.RequestException:
        jobs = []
        seen_ids = set()

    if jobs:
        return jobs

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

        selector = f'a[href*="/v4/ats/web.php/portal/{CLIENT_KEY}/jobs/"]'
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
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

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
