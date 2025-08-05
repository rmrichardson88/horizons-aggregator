from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from utils import build_job_id

BASE_URL = "https://careers.yhmc.com/"

def fetch_jobs() -> list[dict]:
    resp = requests.get(BASE_URL, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    jobs = []
    for card in soup.select("div.listing"):
        title = card.select_one("h3.listing-title").get_text(strip=True)
        company = "Yellowhouse Machinery"

        loc_el = card.select_one("li.udf-1960635 span.value")
        location = loc_el.get_text(strip=True) if loc_el else ""

        sal_el = card.select_one("li.udf-salary span.value")
        salary = sal_el.get_text(strip=True) if sal_el else ""

        link_el = card.select_one("a[href]")
        url_abs = urljoin(BASE_URL, link_el["href"]) if link_el else ""

        slug = link_el["href"].split("?")[0] if link_el else title
        job_id = build_job_id(slug, title, location)

        jobs.append({
            "id": job_id,
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "url": url_abs,
            "scraped_at": datetime.utcnow().isoformat(timespec="seconds"),
            "source": "Yellowhouse",
        })
    return jobs
