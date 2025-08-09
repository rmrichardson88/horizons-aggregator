from __future__ import annotations

import html
import json
import re
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

try:
    from datetime import datetime, UTC 
except Exception: 
    from datetime import datetime, timezone as _tz
    UTC = _tz.utc 

LIST_URL = "https://www.anb.com/about-anb/careers.html"
COMPANY = "Amarillo National Bank"
SOURCE = "Amarillo National Bank"



def _now_utc_iso_seconds() -> str:

    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _slug(s: str) -> str:
    s = s.replace("\xa0", " ").strip()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _compose_location(region: Optional[str]) -> Optional[str]:
    if not region:
        return None
    if re.search(r",\s*[A-Z]{2}$", region):
        return region
    return f"{region}, TX"

BEGIN_RE = re.compile(r"\{beginAccordion[^}]*\}", re.I)
END_RE = re.compile(r"\{endAccordion\}", re.I)

ATTR_TITLE_RE = re.compile(r"(?:title|heading|label)\s*[:=]\s*(['\"])(.*?)\1", re.I)

REGION_H2_RE = re.compile(r"<h2[^>]*>(?P<txt>.*?)</h2>", re.I | re.S)
REGION_MD_RE = re.compile(r"^##\s*(?P<txt>[^\n<]+?)\s*$", re.M)

BTN_TITLE_RE = re.compile(r"<button[^>]*class=\"[^\"]*accordion-button[^\"]*\"[^>]*>(?P<t>.*?)</button>", re.I | re.S)
H3_TITLE_RE = re.compile(r"<h3[^>]*>(?P<t>.*?)</h3>", re.I | re.S)
MD_TITLE_RE = re.compile(r"^###\s*(?P<t>[^\n<]+?)\s*$", re.M)


def _nearest_region(html_text: str, begin_pos: int) -> Optional[str]:

    prev_h2s = list(REGION_H2_RE.finditer(html_text[:begin_pos]))
    if prev_h2s:
        txt = prev_h2s[-1].group("txt")
        return BeautifulSoup(txt, "html.parser").get_text(" ", strip=True)

    prev_mds = list(REGION_MD_RE.finditer(html_text[:begin_pos]))
    if prev_mds:
        return prev_mds[-1].group("txt").strip()
    return None


def _titles_from_block(block_html: str) -> List[str]:
    titles: List[str] = []

    for m in BTN_TITLE_RE.finditer(block_html):
        t = BeautifulSoup(m.group("t"), "html.parser").get_text(" ", strip=True)
        if t:
            titles.append(t)

    for m in H3_TITLE_RE.finditer(block_html):
        t = BeautifulSoup(m.group("t"), "html.parser").get_text(" ", strip=True)
        if t:
            titles.append(t)

    for m in MD_TITLE_RE.finditer(block_html):
        t = m.group("t").strip()
        if t:
            titles.append(t)

    seen = set()
    uniq = []
    for t in titles:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def fetch_jobs() -> List[Dict[str, Optional[str]]]:
    r = requests.get(
        LIST_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": LIST_URL,
        },
        timeout=20,
    )
    r.raise_for_status()

    raw = r.text.replace("\r\n", "\n").replace("\r", "\n")
    raw = html.unescape(raw).replace("\xa0", " ")

    jobs: List[Dict[str, Optional[str]]] = []

    pos = 0
    while True:
        mb = BEGIN_RE.search(raw, pos)
        if not mb:
            break
        block_start = mb.end()
        me = END_RE.search(raw, block_start)
        if not me:
            break
        block = raw[block_start:me.start()]

        begin_token = raw[mb.start():mb.end()]
        am = ATTR_TITLE_RE.search(begin_token)
        region = am.group(2).strip() if am else _nearest_region(raw, mb.start())

        titles = _titles_from_block(block)
        for title in titles:
            job_id = _slug(f"{region or 'anb'}-{title}")[:90]
            jobs.append(
                {
                    "id": job_id,
                    "title": title,
                    "company": COMPANY,
                    "location": _compose_location(region),
                    "salary": None,
                    "url": LIST_URL,
                    "scraped_at": _now_utc_iso_seconds(),
                    "source": SOURCE,
                }
            )

        pos = me.end()

    return jobs


if __name__ == "__main__":
    print(json.dumps(fetch_jobs(), ensure_ascii=False))
