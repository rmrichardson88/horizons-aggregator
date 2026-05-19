from __future__ import annotations

import html
import json
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs, urljoin

import requests
from bs4 import BeautifulSoup, Tag

try:
    from datetime import datetime, UTC
except Exception:
    from datetime import datetime, timezone as _tz
    UTC = _tz.utc


LIST_URL = "https://www.disco-inc.com/careers"
COMPANY = "DISCO Inc."
SOURCE = "DISCO Inc."


def _now_utc_iso_seconds() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _extract_striven_id(url: str) -> Optional[str]:
    """
    Extract LinkID from a Striven job URL, e.g.
    https://share.striven.com/Job?LinkID=8bafbe1e-45b9-48b2-8dd0-61701f4c077d
    -> "8bafbe1e-45b9-48b2-8dd0-61701f4c077d"
    """
    try:
        qs = parse_qs(urlparse(url).query)
        vals = qs.get("LinkID") or qs.get("linkid")
        if vals:
            return vals[0]
    except Exception:
        pass
    return None


def _clean_text(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = html.unescape(s).replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", s) or None


def _is_striven_job_href(href: Optional[str]) -> bool:
    return bool(href and "share.striven.com/Job" in href)


def _looks_like_non_title(text: str) -> bool:
    return bool(
        re.search(
            r"^(apply|available jobs?|careers?|location|job title|description|view job|learn more)$",
            text,
            re.I,
        )
    )


def _looks_like_location(text: str) -> bool:
    return bool(re.search(r"\b[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}(?:\s+\d{5})?\b", text))


def _extract_location(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    matches = re.findall(r"\b[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}(?:\s+\d{5})?\b", text)
    return _clean_text(matches[-1]) if matches else None


def _nearest_job_card(anchor: Tag) -> Optional[Tag]:
    for parent in anchor.parents:
        if not isinstance(parent, Tag):
            continue
        if parent.name not in {"article", "li", "div", "section"}:
            continue
        links = parent.find_all("a", href=_is_striven_job_href)
        text = _clean_text(parent.get_text(" ", strip=True)) or ""
        if len(links) == 1 and 0 < len(text) < 2000:
            return parent
    return None


def _last_heading_before_anchor(scope: Tag, anchor: Tag) -> Optional[str]:
    title: Optional[str] = None
    for node in scope.descendants:
        if node is anchor:
            break
        if isinstance(node, Tag) and node.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            text = _clean_text(node.get_text(" ", strip=True))
            if text and not _looks_like_non_title(text):
                title = text
    return title


def _title_from_card(card: Optional[Tag], anchor: Tag, soup: BeautifulSoup) -> Optional[str]:
    if card:
        heading = card.find(["h1", "h2", "h3", "h4", "h5", "h6"])
        title = _clean_text(heading.get_text(" ", strip=True)) if heading else None
        if title and not _looks_like_non_title(title):
            return title

        for raw in card.stripped_strings:
            text = _clean_text(raw)
            if not text or _looks_like_non_title(text) or _looks_like_location(text):
                continue
            if text == _clean_text(anchor.get_text(" ", strip=True)):
                continue
            return text

    return _last_heading_before_anchor(soup, anchor)


def _listing_details_from_anchor(anchor: Tag, soup: BeautifulSoup) -> tuple[Optional[str], Optional[str]]:
    card = _nearest_job_card(anchor)
    title = _title_from_card(card, anchor, soup)
    location = _extract_location(card.get_text(" ", strip=True) if card else None)
    return title, location


def _fetch_striven_job(url: str) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch a single Striven job page and extract (title, location).

    Priority:
    - "Job Title:" field if present
    - Otherwise, <h1> text (stripping 'Apply - ' prefix if needed)

    For location:
    - First, look for a 'Location:' label and its following line.
    - If none, we leave location as None (e.g. General Opening).
    """
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=20,
        )
        r.raise_for_status()
    except Exception:
        return None, None

    soup = BeautifulSoup(r.text, "html.parser")

    title: Optional[str] = None

    jt_label = soup.find(string=re.compile(r"^\s*Job\s+Title\s*:?\s*$", re.I))
    if jt_label:
        nxt = jt_label.find_next(string=lambda s: s and s.strip())
        if nxt:
            title = _clean_text(nxt)

    if not title:
        h1 = soup.find("h1") or soup.find("h2")
        if h1:
            htext = _clean_text(h1.get_text(" ", strip=True))
            if htext:
                title = re.sub(r"^\s*Apply\s*-\s*", "", htext, flags=re.I).strip() or htext

    location: Optional[str] = None
    loc_label = soup.find(string=re.compile(r"^\s*Location\s*:?\s*$", re.I))
    if loc_label:
        nxt = loc_label.find_next(string=lambda s: s and s.strip())
        if nxt:
            location = _clean_text(nxt)

    return title, location


def fetch_jobs() -> List[Dict[str, Optional[str]]]:
    r = requests.get(
        LIST_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": LIST_URL,
        },
        timeout=20,
    )
    r.raise_for_status()

    raw = r.text.replace("\r\n", "\n").replace("\r", "\n")
    raw = html.unescape(raw).replace("\xa0", " ")
    soup = BeautifulSoup(raw, "html.parser")

    jobs: List[Dict[str, Optional[str]]] = []

    links = soup.find_all(
        "a",
        href=lambda h: h and "share.striven.com/Job" in h,
    )

    seen_ids = set()

    for a in links:
        href = a.get("href") or ""
        href = href.strip()
        if not href:
            continue

        job_url = urljoin(LIST_URL, href)
        job_id = _extract_striven_id(job_url) or None

        if job_id and job_id in seen_ids:
            continue
        if job_id:
            seen_ids.add(job_id)

        listing_title, listing_location = _listing_details_from_anchor(a, soup)
        detail_title, detail_location = _fetch_striven_job(job_url)

        title = detail_title or listing_title
        location = detail_location or listing_location

        if not title:
            continue

        if not job_id:
            job_id = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:90]

        jobs.append(
            {
                "id": job_id,
                "title": title,
                "company": COMPANY,
                "location": location,
                "salary": None,
                "url": job_url,
                "scraped_at": _now_utc_iso_seconds(),
                "source": SOURCE,
            }
        )

    return jobs


if __name__ == "__main__":
    print(json.dumps(fetch_jobs(), ensure_ascii=False))
