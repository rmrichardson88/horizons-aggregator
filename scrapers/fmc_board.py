import re
import json
from datetime import datetime, UTC
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup, Tag

BASE = "https://www.paycomonline.net"
CLIENT_KEY = "51CCB437D1A5BB8EA54B11A3C07895CA"
LIST_URL = f"{BASE}/v4/ats/web.php/jobs?clientkey={CLIENT_KEY}"
DETAIL_PATH = "/v4/ats/web.php/jobs/ViewJobDetails"
DEFAULT_STATE = "TX"  # client is FMC Services operating in TX markets per live postings


def _mk_headers(referer: str = LIST_URL) -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
        "Connection": "keep-alive",
    }


def _now_utc_iso_seconds() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")

def _parse_loc_line(text: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], str]:
    s = (text or "").strip()
    job_type, right = (p.strip() for p in s.split("|", 1)) if "|" in s else (None, s)
    dept, place = (p.strip() for p in right.split(" - ", 1)) if " - " in right else (None, right)

    city = state = postal = None
    m = re.search(r"([^,]+),\s*([A-Z]{2})(?:,\s*(\d{5}))?$", place or "")
    if m:
        city = m.group(1).strip()
        state = m.group(2)
        postal = m.group(3)

    return job_type, dept, city, state, postal, (place or s)


def _extract_job_id(url: str) -> Optional[str]:
    q = parse_qs(urlparse(url).query)
    vals = q.get("job")
    return vals[0] if vals else None


def _select_list_items(soup: BeautifulSoup):
    cards = soup.select("div.JobListing__left, li.jobInfo.JobListing, li.JobListing, li.jobListing, li[class*='JobListing']")
    if cards:
        return cards
    return soup.select("a.JobListing__container[href*='ViewJobDetails'], a[href*='ViewJobDetails?']")


def _scrape_list_page(session: requests.Session, url: str):
    resp = session.get(url, headers=_mk_headers(referer=LIST_URL), timeout=25)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    nodes = _select_list_items(soup)
    return resp.text, soup, nodes


def _compose_location(city: Optional[str], state: Optional[str], location_raw: Optional[str]) -> Optional[str]:
    if city and state:
        return f"{city}, {state}"
    return location_raw or None


def _nearest_location_text(a: Tag) -> str:
    for container in [a, a.parent, a.find_parent(["div", "li"]) or a.parent]:
        if not container:
            continue
        loc_el = container.find("span", class_=lambda c: c and "jobLocation" in c)
        if loc_el and loc_el.get_text(strip=True):
            return loc_el.get_text(" ", strip=True)
        loc_el = container.find("span", class_=lambda c: c and "JobListing__subTitle" in c)
        if loc_el and loc_el.get_text(strip=True):
            return loc_el.get_text(" ", strip=True)
    return ""


def _extract_city_from_title(title: str) -> Optional[str]:
    if not title:
        return None
    m = re.search(r"\s-\s*([^|]+?)\s*(?:Area\b|$)", title)
    if not m:
        return None
    tail = m.group(1)
    parts = re.split(r"\s*/\s*|\s*,\s*|\s+and\s+", tail)
    parts = [p.strip(" -") for p in parts if p.strip(" -")]
    return parts[0] if parts else None


def _job_location_from_detail_html(html: str) -> Optional[str]:
    if not html:
        return None
    h = re.sub(r"\s+", " ", html)
    m = re.search(r"Job\s*Location[^<]{0,80}?([A-Za-z .'-]+,\s*[A-Z]{2})(?:\s*,\s*\d{5})?", h, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"Job\s*Location[^<]{0,120}?(?:-\s*[A-Za-z .'-]+\s-\s*)?([A-Za-z .'-]+,\s*[A-Z]{2})", h, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    return None


def _fetch_detail(session: requests.Session, job_id: str) -> Tuple[Optional[str], Optional[str]]:
    url = f"{BASE}{DETAIL_PATH}?clientkey={CLIENT_KEY}&job={job_id}"
    resp = session.get(url, headers=_mk_headers(referer=LIST_URL), timeout=25)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    h1 = soup.select_one("h1, h2, #content h1, [role='heading']")
    title = h1.get_text(strip=True) if h1 else None
    return title, resp.text


def _parse_card(session: requests.Session, card: Tag) -> Dict[str, Optional[str]]:
    a = card if getattr(card, "name", None) == "a" else (
        card.select_one("a.JobListing__container[href]") or card.select_one("a[href*='ViewJobDetails']")
    )
    if not a:
        return {}

    abs_url = urljoin(BASE, a.get("href", ""))
    job_id = _extract_job_id(abs_url)

    title_el = None
    if getattr(card, "select_one", None):
        title_el = card.select_one("span.jobInfoLine.jobTitle, span.jobTitle, [role='heading']")
    if not title_el and getattr(a, "select_one", None):
        title_el = a.select_one("span.jobInfoLine.jobTitle, span.jobTitle, [role='heading']")
    title = (title_el.get_text(strip=True) if title_el else a.get_text(strip=True)) or None

    loc_text = _nearest_location_text(a)
    _, _, city, state, _, location_raw = _parse_loc_line(loc_text)

    detail_title = None
    detail_html = None
    if not (city and state):
        try:
            detail_title, detail_html = _fetch_detail(session, job_id) if job_id else (None, None)
        except requests.RequestException:
            detail_title, detail_html = None, None
        if detail_html:
            loc_near_label = _job_location_from_detail_html(detail_html)
            if loc_near_label:
                _, _, c2, s2, _, location_raw2 = _parse_loc_line(loc_near_label)
                if c2 and s2:
                    city, state, location_raw = c2, s2, location_raw2

    if not (city and state):
        city_from_title = _extract_city_from_title(title or detail_title or "")
        if city_from_title:
            city, state = city_from_title, DEFAULT_STATE
            location_raw = f"{city}, {state}"

    return {
        "id": job_id,
        "title": title or detail_title,
        "company": "FMC",
        "location": _compose_location(city, state, location_raw or loc_text),
        "salary": None,
        "url": abs_url,
        "scraped_at": _now_utc_iso_seconds(),
        "source": "FMC",
    }


def fetch_jobs(max_pages: int = 10) -> List[Dict[str, Optional[str]]]:
    session = requests.Session()
    out: List[Dict[str, Optional[str]]] = []
    seen_ids: set[str] = set()

    page = 1
    while page <= max_pages:
        url = LIST_URL if page == 1 else f"{LIST_URL}&page={page}"
        html, soup, nodes = _scrape_list_page(session, url)

        if not nodes:
            job_ids = list(set(re.findall(r"ViewJobDetails[^\"'>]+?job=(\d+)", html or "")))
            for jid in job_ids:
                if jid in seen_ids:
                    continue
                try:
                    detail_title, detail_html = _fetch_detail(session, jid)
                except requests.RequestException:
                    continue
                loc_near_label = _job_location_from_detail_html(detail_html or "")
                city = state = None
                location_raw = None
                if loc_near_label:
                    _, _, c2, s2, _, location_raw = _parse_loc_line(loc_near_label)
                    city, state = c2, s2
                if not (city and state):
                    c_from_title = _extract_city_from_title(detail_title or "")
                    if c_from_title:
                        city, state = c_from_title, DEFAULT_STATE
                        location_raw = f"{city}, {state}"
                out.append({
                    "id": jid,
                    "title": detail_title,
                    "company": "FMC",
                    "location": _compose_location(city, state, location_raw),
                    "salary": None,
                    "url": f"{BASE}{DETAIL_PATH}?clientkey={CLIENT_KEY}&job={jid}",
                    "scraped_at": _now_utc_iso_seconds(),
                    "source": "FMC",
                })
                seen_ids.add(jid)
            break

        added = 0
        for node in nodes:
            rec = _parse_card(session, node)
            if rec and rec.get("id") and rec["id"] not in seen_ids:
                out.append(rec)
                seen_ids.add(rec["id"])
                added += 1

        if added == 0:
            break
        page += 1

    return out


if __name__ == "__main__":
    data = fetch_jobs()
    print(json.dumps(data, indent=2))
