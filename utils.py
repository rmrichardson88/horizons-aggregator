import hashlib
import json
import os
import pathlib

try:
    from datetime import datetime, UTC
except Exception:
    from datetime import datetime, timezone as _tz
    UTC = _tz.utc

DATA_PATH = pathlib.Path(
    os.environ.get("JOB_DATA_PATH") or os.environ.get("OUTPUT_PATH") or "data/latest_jobs.json"
)


def build_job_id(title: str, company: str, location: str) -> str:
    key = f"{title}|{company}|{location}"
    return hashlib.sha1(key.encode()).hexdigest()


def now_utc_iso_seconds() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def load_previous_jobs() -> list[dict]:
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text())
    return []


def load_previous() -> dict[str, dict]:
    if DATA_PATH.exists():
        return {item["id"]: item for item in load_previous_jobs()}
    return {}


def save_latest(jobs: list[dict]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(jobs, indent=2, ensure_ascii=False))
