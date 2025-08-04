import hashlib, json, time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from utils import build_job_id

BASE_URL = "https://careers.yhmc.com/"

def fetch_jobs() -> list[dict]:
    """Return a list of job dicts normalised for downstream code."""
    resp = requests.get(BASE_URL, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    jobs = []
    for card in soup.select(".job-card"):
        title = card.select_one(".job-title").get_text(strip=True)
        company = card.select_one(".company").get_text(strip=True)
        location = card.select_one(".location").get_text(strip=True)
        url = card.select_one("a")["href"]
        posted = card.select_one(".date").get_text(strip=True)

        jobs.append(
            {
                "id": build_job_id(title, company, location),
                "title": title,
                "company": company,
                "location": location,
                "url": url,
                "posted": posted,
                "scraped_at": datetime.utcnow().isoformat(timespec="seconds"),
                "source": "Yellowhouse",
            }
        )
    return jobs
