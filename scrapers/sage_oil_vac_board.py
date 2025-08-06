from datetime import datetime
from urllib.parse import urljoin, urlparse
import re
import requests
from bs4 import BeautifulSoup
from utils import build_job_id

BASE_URL = "https://sageoilvac.isolvedhire.com"
LIST_URL = f"{BASE_URL}/jobs/"

def normalize_href(href: str) -> tuple[str, str]:
    """Return `(absolute_url, slug)` normalized for hashing & display."""
    abs_url = urljoin(BASE_URL + "/", href.lstrip("/"))
    path = urlparse(abs_url).path.lstrip("/")
    return abs_url, path

def clean_location(text: str) -> str:
    m = re.search(r"([A-Za-z .'-]+?,?\s+[A-Z]{2})(?:,\s*USA)?$", text)
    return m.group(1) if m else text.strip()

def fetch_jobs() -> list[dict]:
    resp = requests.get(LIST_URL, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    jobs: list[dict] = []

    for card in soup.select("div.bdb1"):
        anchor = card.select_one("a.job-name")
        if not anchor:
            continue
        title = anchor.get_text(strip=True)
        abs_url, slug = normalize_href(anchor["href"])

        span_texts = [
            s.get_text(strip=True)
            for s in card.select("div.w-card__content span")
            if s.get_text(strip=True) and s.get_text(strip=True) != "|"
        ]

        location_raw = span_texts[0] if len(span_texts) >= 1 else ""
        location = clean_location(location_raw) if location_raw else ""
        employment_type = span_texts[1] if len(span_texts) >= 2 else ""
        salary = span_texts[2] if len(span_texts) >= 3 else ""

        posted_span = card.select_one("div.pt1 span")
        posted = (
            posted_span.get_text(strip=True).replace("Posted:", "").strip()
            if posted_span
            else ""
        )

        job_id = build_job_id(slug, title, location)

        jobs.append(
            {
                "id": job_id,
                "title": title,
                "company": "Sage Oil Vac",
                "location": location,
                "employment_type": employment_type,
                "salary": salary,
                "posted": posted,
                "url": abs_url,
                "scraped_at": datetime.utcnow().isoformat(timespec="seconds"),
                "source": "Sage Oil Vac",
            }
        )

    return jobs
