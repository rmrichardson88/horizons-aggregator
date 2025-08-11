#!/usr/bin/env python3
"""
WTAMU Workday scraper — local CLI

Run this manually on your machine (no scheduler required).

Quick start:
  # 1) Install deps
  pip install playwright
  playwright install chromium

  # 2) In Jupyter (Option A1)
  #    from wtamu_workday_local import fetch_jobs_async
  #    jobs = await fetch_jobs_async(max_pages=5, headless=True)
  #    import pandas as pd; pd.DataFrame(jobs)[["id","title","location","url"]].head(10)

  # 3) Run it
  python wtamu_workday_local.py --out wtamu_jobs.json --pretty --max-pages 10

Options:
  --out PATH         Write results to a JSON file instead of stdout
  --pretty           Pretty-print JSON (adds indentation)
  --max-pages N      Max pages to crawl per locale (default: 10)
  --headful          Show a visible browser window (default: headless)
  --debug-html       Save the first page's HTML for troubleshooting
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Dict, List, Optional

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

try:
    from datetime import datetime, UTC  # Python 3.11+
except Exception:  # pragma: no cover
    from datetime import datetime, timezone as _tz
    UTC = _tz.utc

BASE = "https://tamus.wd1.myworkdayjobs.com"
SITE = "WTAMU_External"
START_URLS = [
    f"{BASE}/en-US/{SITE}",
    f"{BASE}/{SITE}",
]
COMPANY = "West Texas A&M University"
SOURCE = "WTAMU"
__all__ = ["fetch_jobs", "fetch_jobs_async", "COMPANY", "SOURCE"]


def _now_utc_iso_seconds() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _extract_req_id(text: str) -> Optional[str]:
    m = re.search(r"\b(R-\d+(?:-\d+)?)\b", text or "")
    return m.group(1) if m else None


def _clean_location(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    t = re.sub(r"\s+", " ", s).strip()
    t = re.sub(r"^(locations?|location)\s*", "", t, flags=re.I)
    return t or None


def _normalize_job_href(href: Optional[str], page_url: str) -> str:
    """Return a canonical, *standalone* job URL (not the sidebar route).

    Workday list pages sometimes render links that are captured by client-side
    routing (opening a sidebar on /jobs). We normalize to a full detail page:
      https://tamus.wd1.myworkdayjobs.com/en-US/WTAMU_External/job/..._R-XXXXXX

    Rules:
      - absolute http(s) => keep, strip query
      - leading "//" => prefix https
      - leading "/" => prefix BASE
      - startswith "job/" => prefix "/en-US/{SITE}/"
      - otherwise => prefix BASE + "/"
    """
    if not href:
        return page_url
    h = href.strip()
    # Strip leading './'
    if h.startswith('./'):
        h = h[2:]

    if h.startswith('http://') or h.startswith('https://'):
        u = h
    elif h.startswith('//'):
        u = 'https:' + h
    elif h.startswith('/'):
        u = BASE + h
    elif h.startswith('job/'):
        u = f"{BASE}/en-US/{SITE}/" + h
    else:
        u = f"{BASE}/" + h

    # Drop any query/hash to avoid sidebar/stateful routes
    u = u.split('?', 1)[0].split('#', 1)[0]
    return u


async def _scrape_listing_page(page, start_url: str) -> List[Dict[str, Optional[str]]]:
    jobs: List[Dict[str, Optional[str]]] = []
    try:
        await page.wait_for_selector('a[data-automation-id="jobTitle"]', timeout=20000)
    except PWTimeout:
        return jobs

    anchors = await page.query_selector_all('a[data-automation-id="jobTitle"]')
    for a in anchors:
        title = (await a.text_content() or "").strip() or None
        href = (await a.get_attribute("href") or "").strip()
        url = _normalize_job_href(href, page.url) if href else page.url

        li = await a.evaluate_handle("e => e.closest('li')")
        location = None
        req_id = None
        if li:
            loc_el = await page.evaluate_handle(
                """(el) => el.querySelector('[data-automation-id="locations"]')""",
                li,
            )
            if loc_el:
                location = (await page.evaluate("e => e.innerText", loc_el) or "").strip() or None
            sub_el = await page.evaluate_handle(
                """(el) => el.querySelector('ul[data-automation-id="subtitle"] li')""",
                li,
            )

            if sub_el:
                sub_text = (await page.evaluate("e => e.innerText", sub_el) or "").strip()
                rid = _extract_req_id(sub_text)
                if rid:
                    req_id = rid
        location = _clean_location(location)
        job_id = req_id or (href.rstrip("/").split("/")[-1] if href else None)

        jobs.append(
            {
                "id": job_id,
                "title": title,
                "company": COMPANY,
                "location": location,
                "salary": None,
                "url": url,
                "scraped_at": _now_utc_iso_seconds(),
                "source": SOURCE,
            }
        )
    return jobs


async def fetch_jobs_async(max_pages: int = 10, *, headless: bool = True, debug_html: bool = False) -> List[Dict[str, Optional[str]]]:
    jobs: List[Dict[str, Optional[str]]] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )
        )
        page = await ctx.new_page()

        collected = False
        for start in START_URLS:
            page_num = 1
            while page_num <= max_pages:
                url = start if page_num == 1 else f"{start}?page={page_num}"
                await page.goto(url, wait_until="networkidle")
                # Try to accept cookie banners if present
                try:
                    await page.get_by_role("button", name=re.compile("Accept|Agree|OK", re.I)).click(timeout=2500)
                except Exception:
                    pass

                if debug_html and page_num == 1 and not jobs:
                    # Save the raw HTML of the first page we land on for troubleshooting
                    try:
                        with open("wtamu_debug_page1.html", "w", encoding="utf-8") as f:
                            f.write(await page.content())
                    except Exception:
                        pass

                page_jobs = await _scrape_listing_page(page, start)
                if not page_jobs:
                    break
                jobs.extend(page_jobs)
                page_num += 1
                collected = True
            if collected:
                break
        await ctx.close()
        await browser.close()

    # De-duplicate by (id, url)
    seen = set()
    uniq: List[Dict[str, Optional[str]]] = []
    for j in jobs:
        key = (j.get("id"), j.get("url"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(j)
    return uniq


def fetch_jobs(max_pages: int = 10, *, headless: bool = True, debug_html: bool = False) -> List[Dict[str, Optional[str]]]:
    """Convenience sync wrapper.

    - In Terminal: just call fetch_jobs() or run the CLI (__main__).
    - In Jupyter: this will try to use an existing loop via nest-asyncio. If that
      package is not installed, prefer: ``jobs = await fetch_jobs_async(...)``.
    """
    try:
        loop = asyncio.get_running_loop()  # already running (e.g., Jupyter)
        try:
            import nest_asyncio  # type: ignore
            nest_asyncio.apply()
            return loop.run_until_complete(fetch_jobs_async(max_pages, headless=headless, debug_html=debug_html))
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Running inside an active asyncio loop. Either install 'nest-asyncio' or use 'await fetch_jobs_async(...)'."
            ) from e
    except RuntimeError:
        # No running loop — safe to start one
        return asyncio.run(fetch_jobs_async(max_pages, headless=headless, debug_html=debug_html))




    if args.outfile:
        with open(args.outfile, "w", encoding="utf-8") as f:
            if args.pretty:
                json.dump(jobs, f, ensure_ascii=False, indent=2)
            else:
                json.dump(jobs, f, ensure_ascii=False)
    else:
        if args.pretty:
            print(json.dumps(jobs, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(jobs, ensure_ascii=False))
    return 0
