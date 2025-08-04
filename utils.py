import hashlib, json, pathlib

DATA_PATH = pathlib.Path("data/latest_jobs.json")

def build_job_id(title: str, company: str, location: str) -> str:
    key = f"{title}|{company}|{location}"
    return hashlib.sha1(key.encode()).hexdigest()

def load_previous() -> dict[str, dict]:
    if DATA_PATH.exists():
        return {item["id"]: item for item in json.loads(DATA_PATH.read_text())}
    return {}

def save_latest(jobs: list[dict]) -> None:
    DATA_PATH.write_text(json.dumps(jobs, indent=2, ensure_ascii=False))
