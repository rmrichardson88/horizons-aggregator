from importlib import import_module
from pathlib import Path
from utils import load_previous, save_latest

SCRAPER_MODULES = [
    "scrapers.yhmc_board",
    #"scrapers.sage_oil_vac_board",
    "scrapers.fmc_board"
    # "scrapers.other_board",
]

def main() -> None:
    all_jobs = []

    for mod_path in SCRAPER_MODULES:
        scraper = import_module(mod_path)
        all_jobs.extend(scraper.fetch_jobs())

    all_jobs.sort(key=lambda j: j["scraped_at"], reverse=True)

    save_latest(all_jobs)

if __name__ == "__main__":
    main()
