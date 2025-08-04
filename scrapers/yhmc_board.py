import hashlib, json, time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
#from utils import build_job_id

BASE_URL = "https://careers.yhmc.com/"

def fetch_jobs() -> list[dict]:
    """Return a list of job dicts normalised for downstream code."""
    resp = requests.get(BASE_URL, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    jobs = []
    for card in soup.select("div.listing"):
        title = card.select_one("h3.listing-title").get_text(strip=True)
        company = 'Yellowhouse Machinery'
        location = card.select_one("li.udf-1960635 span.value")
        salary = card.select_one("li.udf-salary span.value")
        url2 = card.select_one("a[href]")["href"]

        jobs.append(
            {
                #"id": build_job_id(title, company, location),
                "title": title,
                "company": company,
                "location": location,
                "salary": salary,
                "url": BASE_URL+url2,
                "scraped_at": datetime.utcnow().isoformat(timespec="seconds"),
                "source": "Yellowhouse",
            }
        )
    return jobs
