from datetime import datetime
from urllib.parse import urljoin, urlparse
import re
import requests
from bs4 import BeautifulSoup
from utils import build_job_id

BASE_URL = "https://careers.yhmc.com"

def normalize_href(href: str) -> tuple[str, str]:
    """Return `(absolute_url, slug)` normalized for hashing & display."""
    abs_url = urljoin(BASE_URL + "/", href.lstrip("/"))

    path = urlparse(abs_url).path.lstrip("/")
    return abs_url, path

def extract_udf_fields(card: BeautifulSoup) -> dict[str, str]:

    fields: dict[str, str] = {}

    for li in card.select("div.udf li"):
        label_el = li.select_one("span.label")
        value_el = li.select_one("span.value")
        if label_el and value_el:
            label = label_el.get_text(strip=True).rstrip(":").lower()
            fields[label] = value_el.get_text(strip=True)

    return fields


def fallback_location(card: BeautifulSoup) -> str | None:
    """Attempt to recover a location when the facts table is missing."""
    snippet = card.select_one("div.listing-snippet")
    if not snippet:
        return None

    text = snippet.get_text(" ", strip=True)
    m = re.search(r"\bat our ([A-Za-z .'-]+?,?\s+[A-Z]{2}) location\b", text)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_jobs() -> list[dict]:
    """Scrape the Yellowhouse Machinery career site and return a list of jobs."""
    resp = requests.get(BASE_URL + "/", timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    jobs: list[dict] = []

    for card in soup.select("div.listing"):
        title_el = card.select_one("h3.listing-title")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)

        meta = extract_udf_fields(card)
        location = meta.get("hiring location") or fallback_location(card) or ""
        salary = meta.get("pay", "")

        link_el = card.select_one("a[href]")
        abs_url, slug = normalize_href(link_el["href"] if link_el else title)

        job_id = build_job_id(slug, title, location)

        jobs.append(
            {
                "id": job_id,
                "title": title,
                "company": "Yellowhouse Machinery",
                "location": location,
                "salary": salary,
                "url": abs_url,
                "scraped_at": datetime.utcnow().isoformat(timespec="seconds"),
                "source": "Yellowhouse",
            }
        )

    return jobs
