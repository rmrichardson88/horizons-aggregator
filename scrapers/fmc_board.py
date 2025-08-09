import json
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

BASE = "https://www.paycomonline.net"
CLIENT_KEY = "51CCB437D1A5BB8EA54B11A3C07895CA"
LIST_URL = f"{BASE}/v4/ats/web.php/jobs?clientkey={CLIENT_KEY}"
DETAIL_PATH = "/v4/ats/web.php/jobs/ViewJobDetails"


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
    }

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
    lis = soup.select("li.jobInfo.JobListing")
    if lis:
        return lis
    alt = soup.select("li.JobListing, li.jobListing, li[class*='JobListing']")
    if alt:
        return alt
    return soup.select("a.JobListing__container[href*='ViewJobDetails'], a[href*='ViewJobDetails?']")

def _scrape_list_page(session: requests.Session, url: str):
    resp = session.get(url, headers=_mk_headers(referer=LIST_URL), timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    nodes = _select_list_items(soup)
    return resp.text, soup, nodes

def _parse_card(card) -> Dict[str, Optional[str]]:
    a = card if getattr(card, "name", None) == "a" else (
        card.select_one("a.JobListing__container[href]") or card.select_one("a[href*='ViewJobDetails']")
    )
    if not a:
        return {}

    abs_url = urljoin(BASE, a.get("href", ""))
    job_id = _extract_job_id(abs_url)

    title_el = (card.select_one("span.jobInfoLine.jobTitle") if getattr(card, "name", None) != "a" else None) or a
    title = title_el.get_text(strip=True)

    loc_el = card.select_one("span.jobInfoLine.jobLocation") if getattr(card, "select_one", None) else None
    loc_text = loc_el.get_text(" ", strip=True) if loc_el else ""
    job_type, dept, city, state, postal, location_raw = _parse_loc_line(loc_text)

    desc_el = card.select_one("span.jobInfoLine.jobDescription") if getattr(card, "select_one", None) else None
    snippet = (desc_el.get_text(" ", strip=True) if desc_el else "").strip()

    return {
        "source": "paycom",
        "company": "FMC",
        "job_id": job_id,
        "title": title,
        "url": abs_url,
        "job_type": job_type,
        "department": dept,
        "city": city,
        "state": state,
        "postal_code": postal,
        "location_raw": location_raw,
        "description_snippet": snippet[:400],
    }

def _find_job_ids_in_html(html: str) -> List[str]:
    return list(set(re.findall(r"ViewJobDetails[^\"'>]+?job=(\d+)", html or "")))

def _text_after_label(soup: BeautifulSoup, label: str) -> str:
    node = soup.find(string=re.compile(rf"^{re.escape(label)}\\b", re.I))
    if not node:
        return ""
    parent = node.parent
    if parent:
        sib = parent.find_next_sibling()
        if sib:
            return sib.get_text(" ", strip=True)
    nxt = node.find_next(string=True)
    return (nxt or "").strip()


def _fetch_minimal_from_detail(session: requests.Session, job_id: str) -> Optional[Dict[str, Optional[str]]]:
    url = f"{BASE}{DETAIL_PATH}?clientkey={CLIENT_KEY}&job={job_id}"
    try:
        resp = session.get(url, headers=_mk_headers(referer=LIST_URL), timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    h1 = soup.select_one("h1, h2, #content h1")
    title = h1.get_text(strip=True) if h1 else None

    loc_raw = _text_after_label(soup, "Job Location")
    job_type = _text_after_label(soup, "Position Type") or None

    _, dept, city, state, postal, location_raw = _parse_loc_line(loc_raw)

    return {
        "source": "paycom",
        "company": "FMC",
        "job_id": job_id,
        "title": title,
        "url": url,
        "job_type": job_type,
        "department": dept,
        "city": city,
        "state": state,
        "postal_code": postal,
        "location_raw": location_raw or loc_raw,
        "description_snippet": "",
    }


def fetch_jobs(max_pages: int = 10) -> List[Dict[str, Optional[str]]]:
    session = requests.Session()
    out: List[Dict[str, Optional[str]]] = []

    page = 1
    while page <= max_pages:
        url = LIST_URL if page == 1 else f"{LIST_URL}&page={page}"
        html, soup, nodes = _scrape_list_page(session, url)

        if not nodes:
            job_ids = _find_job_ids_in_html(html)
            for jid in job_ids:
                rec = _fetch_minimal_from_detail(session, jid)
                if rec:
                    out.append(rec)
            break

        for node in nodes:
            rec = _parse_card(node)
            if rec:
                out.append(rec)

        page += 1

    return out


if __name__ == "__main__":
    print(json.dumps(fetch_jobs(), ensure_ascii=False))
