from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

import requests

try:
    from datetime import datetime, UTC
except Exception: 
    from datetime import datetime, timezone as _tz
    UTC = _tz.utc


LIST_URL = "https://recruiting.paylocity.com/recruiting/jobs/All/0a932b3f-65a0-4207-b5be-70d84a78ecaa/Austin-Hose"
COMPANY = "Austin Hose"
SOURCE = "Austin Hose"

FEED_GUID = "0a932b3f-65a0-4207-b5be-70d84a78ecaa"
FEED_URL = f"https://recruiting.paylocity.com/recruiting/v2/api/feed/jobs/{FEED_GUID}"


def _now_utc_iso_seconds() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _slug(s: str) -> str:
    s = s.replace("\xa0", " ").strip()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _compose_location_from_feed(loc: Optional[dict]) -> Optional[str]:
    if not loc:
        return None

    city = loc.get("city") or loc.get("City")
    state = loc.get("state") or loc.get("State")
    display = (
        loc.get("locationDisplayName")
        or loc.get("LocationDisplayName")
        or loc.get("name")
        or loc.get("Name")
    )

    if city and state:
        return f"{city}, {state}"
    if display:
        return display
    return None


def fetch_jobs() -> List[Dict[str, Optional[str]]]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    r = requests.get(FEED_URL, headers=headers, timeout=20)
    r.raise_for_status()

    data = r.json()

    if isinstance(data, dict) and "jobs" in data:
        items = data["jobs"]
    elif isinstance(data, list):
        items = data
    else:
        raise RuntimeError(f"Unexpected Paylocity feed shape: {type(data)!r}")

    jobs: List[Dict[str, Optional[str]]] = []

    for item in items:
        title = item.get("title") or item.get("Title")
        if not title:
            continue

        display_url = item.get("displayUrl") or item.get("DisplayUrl")
        if not display_url:
            display_url = (
                item.get("applyUrl")
                or item.get("ApplyUrl")
                or item.get("listUrl")
                or item.get("ListUrl")
                or LIST_URL
            )

        job_id_val = item.get("jobId") or item.get("JobId")
        if job_id_val:
            base_id = f"austinhose-{job_id_val}-{title}"
        else:
            base_id = f"austinhose-{title}"

        job_id = _slug(base_id)[:90]

        loc_dict = item.get("jobLocation") or item.get("JobLocation") or {}
        location = _compose_location_from_feed(loc_dict)

        jobs.append(
            {
                "id": job_id,
                "title": title,
                "company": COMPANY,
                "location": location,
                "salary": item.get("salaryDescription") or item.get("SalaryDescription"),
                "url": display_url,
                "scraped_at": _now_utc_iso_seconds(),
                "source": SOURCE,
            }
        )

    return jobs


if __name__ == "__main__":
    print(json.dumps(fetch_jobs(), ensure_ascii=False))
