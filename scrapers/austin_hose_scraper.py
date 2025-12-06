from __future__ import annotations

import html
import json
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    from datetime import datetime, UTC
except Exception:
    from datetime import datetime, timezone as _tz
    UTC = _tz.utc


LIST_URL = "https://recruiting.paylocity.com/recruiting/jobs/All/0a932b3f-65a0-4207-b5be-70d84a78ecaa/Austin-Hose"
COMPANY = "Austin Hose"
SOURCE = "Austin Hose"


def _now_utc_iso_seconds() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _slug(s: str) -> str:
    s = s.replace("\xa0", " ").strip()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def fetch_jobs() -> List[Dict[str, Optional[str]]]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": LIST_URL,
    }

    r = requests.get(LIST_URL, headers=headers, timeout=20)
    r.raise_for_status()

    raw = r.text.replace("\r\n", "\n").replace("\r", "\n")
    raw = html.unescape(raw).replace("\xa0", " ")

    if "In order to use this site, it is necessary to enable JavaScript." in raw:
        raise RuntimeError(
            "Paylocity returned the JavaScript/unsupported-browser page; "
            "try running this scraper from a different IP or updating headers."
        )

    soup = BeautifulSoup(raw, "html.parser")

    jobs: List[Dict[str, Optional[str]]] = []

    rows = soup.select("div.row.job-listing-job-item")
    for row in rows:
        title_a = row.select_one(".job-title-column .job-item-title a")
        if not title_a:
            continue

        title = title_a.get_text(" ", strip=True)
        if not title:
            continue

        href = (title_a.get("href") or "").strip()
        if href:
            url = urljoin(LIST_URL, href)
        else:
            url = LIST_URL

        loc_el = row.select_one(".location-column span")
        location = loc_el.get_text(" ", strip=True) if loc_el else None
        if location == "":
            location = None

        job_id_match = re.search(r"/Details/(\d+)", href)
        numeric_id = job_id_match.group(1) if job_id_match else None

        if numeric_id:
            job_id = _slug(f"austinhose-{numeric_id}-{title}")[:90]
        else:
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
