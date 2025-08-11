import asyncio
import argparse
import json
import re
from typing import Dict, List, Optional

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

try:
    from datetime import datetime, UTC
except Exception: 
    from datetime import datetime, timezone as _tz
    UTC = _tz.utc

BASE = "https://tamus.wd1.myworkdayjobs.com"
SITE = "WTAMU_External"
START_URLS = [
    f"{BASE}/en-US/{SITE}/jobs",
    f"{BASE}/{SITE}/jobs",
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
    if not href:
        return page_url
    h = href.strip()
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

    u = u.split('?', 1)[0].split('#', 1)[0]
    return u


async def _click_next_or_show_more(page) -> bool:
    import re as _re
    for role in ("button", "link"):
        try:
            next_btn = page.get_by_role(role, name=_re.compile(r"Next", _re.I))
            if await next_btn.count():
                try:
                    if hasattr(next_btn, "is_disabled") and await next_btn.is_disabled():
                        pass
                    else:
                        await next_btn.first.click()
                        await page.wait_for_load_state("networkidle")
                        return True
                except Exception:
                    pass
        except Exception:
            pass
    try:
        more_btn = page.get_by_role("button", name=_re.compile(r"Show more|Load more|More jobs", _re.I))
        if await more_btn.count():
            await more_btn.first.click()
            await page.wait_for_load_state("networkidle")
            return True
    except Exception:
        pass
    return False


async def _goto_numeric_page(page, page_num: int) -> bool:
    import re as _re
    try:
        btn = page.get_by_role("button", name=_re.compile(fr"\bpage\s*{page_num}\b", _re.I))
        if await btn.count():
            b = btn.first
            try:
                await b.scroll_into_view_if_needed()
            except Exception:
                pass
            await b.click()
            try:
                await page.wait_for_load_state("networkidle")
            except Exception:
                pass
            return True
    except Exception:
        pass

    try:
        btn2 = page.locator(f'button[aria-label="page {page_num}"]')
        if await btn2.count():
            try:
                await btn2.first.scroll_into_view_if_needed()
            except Exception:
                pass
            await btn2.first.click()
            try:
                await page.wait_for_load_state("networkidle")
            except Exception:
                pass
            return True
    except Exception:
        pass

    try:
        btn3 = page.locator('button[data-uxi-widget-type="paginationPageButton"]').filter(has_text=str(page_num))
        if await btn3.count():
            try:
                await btn3.first.scroll_into_view_if_needed()
            except Exception:
                pass
            await btn3.first.click()
            try:
                await page.wait_for_load_state("networkidle")
            except Exception:
                pass
            return True
    except Exception:
        pass

    return False


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
            seen_keys = set()
            while page_num <= max_pages:
                moved_by = None
                if page_num == 1:
                    url = start
                    await page.goto(url, wait_until="networkidle")
                else:
                    if await _goto_numeric_page(page, page_num):
                        moved_by = "pager"
                        url = page.url
                    else:
                        url = f"{start}?page={page_num - 1}"
                        await page.goto(url, wait_until="networkidle")
                        moved_by = "param"
                try:
                    await page.get_by_role("button", name=re.compile("Accept|Agree|OK", re.I)).click(timeout=2500)
                except Exception:
                    pass

                if debug_html:
                    try:
                        with open(f"wtamu_debug_page{page_num}.html", "w", encoding="utf-8") as f:
                            f.write(await page.content())
                    except Exception:
                        pass

                page_jobs = await _scrape_listing_page(page, start)
                page_count = len(page_jobs)
                new = 0
                for j in page_jobs:
                    key = (j.get("id"), j.get("url"))
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    jobs.append(j)
                    new += 1
                if debug_html:
                    try:
                        print(f"[debug] page {page_num} url={url} jobs={page_count} new={new}")
                    except Exception:
                        pass
                if not page_jobs or new == 0:
                    moved = await _click_next_or_show_more(page)
                    if moved:
                        page_num += 1
                        continue
                    break
                page_num += 1
                collected = True
            if collected:
                break
        await ctx.close()
        await browser.close()

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
    try:
        loop = asyncio.get_running_loop()  
        try:
            import nest_asyncio  
            nest_asyncio.apply()
            return loop.run_until_complete(fetch_jobs_async(max_pages, headless=headless, debug_html=debug_html))
        except Exception as e:  
            raise RuntimeError(
                "Running inside an active asyncio loop. Either install 'nest-asyncio' or use 'await fetch_jobs_async(...)'."
            ) from e
    except RuntimeError:
        return asyncio.run(fetch_jobs_async(max_pages, headless=headless, debug_html=debug_html))


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="WTAMU Workday scraper (GH Actions/CLI)")
    ap.add_argument("--out", dest="outfile", help="Write JSON to this file; omit to print to stdout")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    ap.add_argument("--max-pages", type=int, default=10, help="Max pages to crawl (default: 10)")
    ap.add_argument("--headful", action="store_true", help="Show a visible browser window (default: headless)")
    ap.add_argument("--debug-html", action="store_true", help="Save wtamu_debug_pageN.html files")
    return ap.parse_known_args(argv)[0]


async def amain(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    jobs = await fetch_jobs_async(
        max_pages=args.max_pages,
        headless=not args.headful,
        debug_html=args.debug_html,
    )
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


def main(argv: Optional[List[str]] = None) -> int:
    try:
        loop = asyncio.get_running_loop()
        try:
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(amain(argv))
        except Exception as e:
            raise RuntimeError("Active asyncio loop detected. Use: await amain([...]) or install nest-asyncio.") from e
    except RuntimeError:
        return asyncio.run(amain(argv))
