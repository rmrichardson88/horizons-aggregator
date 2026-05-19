from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from utils import DATA_PATH, build_job_id, load_previous_jobs, now_utc_iso_seconds, save_latest


logger = logging.getLogger("horizons.scrapers")


@dataclass(frozen=True)
class ScraperSpec:
    module: str
    source: str


SCRAPERS = [
    ScraperSpec("scrapers.wtamu_board", "WTAMU"),
    ScraperSpec("scrapers.ttuhsc_board", "TTUHSC"),
    ScraperSpec("scrapers.fmc_board", "FMC"),
    ScraperSpec("scrapers.anb_board", "Amarillo National Bank"),
    ScraperSpec("scrapers.yhmc_board", "Yellowhouse"),
    ScraperSpec("scrapers.austin_hose_scraper", "Austin Hose"),
    ScraperSpec("scrapers.sage_oil_vac_board", "Sage Oil Vac"),
    ScraperSpec("scrapers.talon_lpe_board", "Talon/LPE"),
    ScraperSpec("scrapers.western_equipment", "Western Equipment"),
    ScraperSpec("scrapers.disco_inc", "DISCO Inc."),
]

CORE_FIELDS = ("id", "title", "company", "location", "salary", "url", "scraped_at", "source")


def _configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )


def _warn(message: str) -> None:
    logger.warning(message)
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        print(f"::warning::{message}", file=sys.stderr)


def _previous_jobs_for_source(previous: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    return [job for job in previous if job.get("source") == source]


def _normalize_job(job: dict[str, Any], default_source: str) -> dict[str, Any]:
    normalized = {field: job.get(field) for field in CORE_FIELDS}
    normalized.update({k: v for k, v in job.items() if k not in normalized})

    normalized["source"] = normalized.get("source") or default_source
    normalized["scraped_at"] = normalized.get("scraped_at") or now_utc_iso_seconds()

    if not normalized.get("id"):
        title = str(normalized.get("title") or "")
        company = str(normalized.get("company") or normalized["source"] or "")
        location = str(normalized.get("location") or normalized.get("url") or "")
        normalized["id"] = build_job_id(title, company, location)

    return normalized


def _dedupe_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any, Any]] = set()
    deduped: list[dict[str, Any]] = []
    for job in jobs:
        key = (job.get("source"), job.get("id"), job.get("url"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(job)
    return deduped


def _parse_scraper_filter(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def _matches_filter(spec: ScraperSpec, filters: set[str]) -> bool:
    if not filters:
        return True
    short_name = spec.module.rsplit(".", 1)[-1].lower()
    source = spec.source.lower()
    module = spec.module.lower()
    return any(item in {short_name, source, module} for item in filters)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Horizons job board scrapers.")
    parser.add_argument(
        "--scrapers",
        help="Comma-separated scraper filter by module short name, full module, or source.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run scrapers and print a summary without writing the output JSON.",
    )
    parser.add_argument(
        "--fail-on-scraper-error",
        action="store_true",
        help="Return a non-zero exit code if any individual scraper fails.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    scraper_filters = _parse_scraper_filter(args.scrapers)
    scraper_specs = [spec for spec in SCRAPERS if _matches_filter(spec, scraper_filters)]
    if not scraper_specs:
        raise SystemExit("No scrapers matched the requested filter.")

    previous = load_previous_jobs()
    all_jobs: list[dict[str, Any]] = []
    failures: list[str] = []
    successful_scrapers = 0

    logger.info("running %s scraper(s)", len(scraper_specs))

    for spec in scraper_specs:
        try:
            scraper = import_module(spec.module)
            fetched = scraper.fetch_jobs()
            if fetched is None:
                fetched = []
            if not isinstance(fetched, list):
                raise TypeError(f"fetch_jobs() returned {type(fetched).__name__}, expected list")

            source = getattr(scraper, "SOURCE", spec.source)
            all_jobs.extend(_normalize_job(job, source) for job in fetched if isinstance(job, dict))
            successful_scrapers += 1
            logger.info("%s: %s jobs", spec.source, len(fetched))
        except Exception as exc:
            failures.append(spec.source)
            previous_jobs = _previous_jobs_for_source(previous, spec.source)
            if previous_jobs:
                all_jobs.extend(
                    _normalize_job(job, spec.source) for job in previous_jobs if isinstance(job, dict)
                )
            exc_text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            fallback = f"; kept {len(previous_jobs)} previous jobs" if previous_jobs else ""
            _warn(f"{spec.source} scraper failed{fallback}: {exc_text}")

    all_jobs = _dedupe_jobs(all_jobs)
    all_jobs.sort(key=lambda j: j["scraped_at"], reverse=True)

    if args.dry_run:
        logger.info("dry run complete: %s jobs collected; output not written", len(all_jobs))
    else:
        save_latest(all_jobs)
        logger.info("wrote %s jobs to %s", len(all_jobs), DATA_PATH)

    if failures:
        _warn(f"{len(failures)} scraper(s) failed: {', '.join(failures)}")

    if successful_scrapers == 0:
        raise SystemExit("All scrapers failed; leaving stale fallback data is not enough for a healthy run.")

    if failures and args.fail_on_scraper_error:
        raise SystemExit(f"{len(failures)} scraper(s) failed: {', '.join(failures)}")

    if not all_jobs:
        raise SystemExit("No jobs were collected.")

if __name__ == "__main__":
    main()
