from importlib import import_module
from pathlib import Path
from utils import load_previous, save_latest

SCRAPER_MODULES = [
    "scrapers.yhmc_board",
    # "scrapers.other_board",
]

def main() -> None:
    prev = load_previous()
    seen_ids = set(prev)
    fresh = []

    for mod_path in SCRAPER_MODULES:
        scraper = import_module(mod_path)
        for job in scraper.fetch_jobs():
            if job["id"] not in seen_ids:
                fresh.append(job)
                seen_ids.add(job["id"])

    if fresh or not prev:
        # Replace entire file with newest snapshot (simplest logic)
        save_latest(sorted(fresh + list(prev.values()), key=lambda j: j["posted"], reverse=True))

if __name__ == "__main__":
    main()
