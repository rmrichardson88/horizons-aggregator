from __future__ import annotations

import json
import os
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

FEED_GUID = os.environ.get("0a932b3f-65a0-4207-b5be-70d84a78ecaa", "").strip()


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


def _fetch_feed(url: str) -> List[dict]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()

    if isinstance(data, dict):
        if "jobs" in data and isinstance(data["jobs"], list):
            return data["jobs"]
        if "Jobs" in data and isinstance(data["Jobs"], list):
            return data["Jobs"]
        print(f"[Austin Hose] Unexpected feed shape: keys={list(data.keys())}")
        return []

    if isinstance(data, list):
        return data

    print(f"[Austin Hose] Unexpected top-level JSON type: {type(data)!r}")
    return []


def fetch_jobs() -> List[Dict[str, Optional[str]]]:
    if not FEED_GUID:
        print("[Austin Hose] FEED_GUID not set; set AUSTIN_HOSE_FEED_GUID env var.")
        return []

    v2_url = f"https://recruiting.paylocity.com/recruiting/v2/api/feed/jobs/{FEED_GUID}"
    jobs_raw: List[dict] = []
    try:
        jobs_raw = _fetch_feed(v2_url)
    except Exception as e:
        print(f"[Austin Hose] V2 feed failed ({e!r}), trying V1...")

    if not jobs_raw:
        v1_url = f"https://recruiting.paylocity.com/recruiting/api/feed/jobs/{FEED_GUID}"
        try:
            jobs_raw = _fetch_feed(v1_url)
        except Exception as e:
            print(f"[Austin Hose] V1 feed failed ({e!r}).")
            return []

    if not jobs_raw:
        print("[Austin Hose] Feed returned zero jobs.")
        return []

    jobs: List[Dict[str, Optional[str]]] = []

    for item in jobs_raw:
        title = (
            item.get("title")
            or item.get("Title")
            or item.get("jobTitle")
            or item.get("JobTitle")
        )
        if not title:
            continue

        display_url = (
            item.get("displayUrl")
            or item.get("DisplayUrl")
            or item.get("applyUrl")
            or item.get("ApplyUrl")
            or item.get("listUrl")
            or item.get("ListUrl")
            or LIST_URL
        )

        job_id_val = (
            item.get("jobId")
            or item.get("JobId")
            or item.get("id")
            or item.get("Id")
        )
        base_id = f"austinhose-{job_id_val}-{title}" if job_id_val else f"austinhose-{title}"
        job_id = _slug(base_id)[:90]

        loc_dict = (
            item.get("jobLocation")
            or item.get("JobLocation")
            or item.get("location")
            or item.get("Location")
            or {}
        )
        location = _compose_location_from_feed(loc_dict)

        salary = (
            item.get("salaryDescription")
            or item.get("SalaryDescription")
            or item.get("salary")
            or item.get("Salary")
        )

        jobs.append(
            {
                "id": job_id,
                "title": title,
                "company": COMPANY,
                "location": location,
                "salary": salary,
                "url": display_url,
                "scraped_at": _now_utc_iso_seconds(),
                "source": SOURCE,
            }
        )

    print(f"[Austin Hose] Parsed {len(jobs)} jobs from feed.")
    return jobs


if __name__ == "__main__":
    print(json.dumps(fetch_jobs(), ensure_ascii=False))
