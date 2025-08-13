import json
from pathlib import Path

import pandas as pd
import streamlit as st
import time
import requests

st.set_page_config(
    page_title="Horizons Job Aggregator",
    page_icon="💼",
    layout="wide",
)

# --- Data locations ---
DATA_FILE = Path(__file__).parents[1] / "data/latest_jobs.json"  # local fallback (repo file)
REQUIRED_COLS = ["title", "company", "salary", "location", "url"]

# Prefer remote raw URL so the app updates without redeploys.
# Set this in Streamlit secrets: REMOTE_RAW_URL: https://raw.githubusercontent.com/<user>/<repo>/<branch>/data/latest_jobs.json
REMOTE_RAW_URL = st.secrets.get("REMOTE_RAW_URL", "")
DEFAULT_DATA_MODE = "remote" if REMOTE_RAW_URL else "local"


# ---------- Fresh loaders ----------

def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=REQUIRED_COLS)


def _safe_read_json(path: Path) -> pd.DataFrame:
    # Try standard JSON array
    try:
        return pd.read_json(path)
    except ValueError:
        # Fallback: JSON lines
        try:
            return pd.read_json(path, lines=True)
        except Exception:
            return _empty_df()


def _safe_read_json_str(s: str) -> pd.DataFrame:
    try:
        data = json.loads(s)
        if isinstance(data, list):
            return pd.DataFrame(data)
    except Exception:
        pass
    try:
        from io import StringIO
        return pd.read_json(StringIO(s), lines=True)
    except Exception:
        return _empty_df()


@st.cache_data(ttl=86400, show_spinner=False)
def _load_remote_json(url: str, cache_bust: int) -> pd.DataFrame:
    headers = {"Cache-Control": "no-cache"}
    r = requests.get(url, params={"t": cache_bust}, headers=headers, timeout=15)
    r.raise_for_status()
    return _safe_read_json_str(r.text)


@st.cache_data(show_spinner=False)
def _load_local_json(path_str: str, mtime_ns: int) -> pd.DataFrame:
    """Read JSON using file path and modification time as the cache key.
    Any time the file changes on disk (new commit), cache invalidates.
    """
    p = Path(path_str)
    if not p.exists():
        return _empty_df()

    df = _safe_read_json(p)

    # Ensure required columns exist
    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = None

    # Optional: sort by latest scrape time if present
    if "scraped_at" in df.columns:
        df["scraped_at_dt"] = pd.to_datetime(df["scraped_at"], errors="coerce")
        df = df.sort_values("scraped_at_dt", ascending=False, na_position="last")

    return df


def _get_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


# --------------- UI Header + Data Source ---------------
left_hdr, right_hdr = st.columns([1, 1])
with left_hdr:
    st.title("Horizons Job Aggregator")
with right_hdr:
    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

_default_index = 0 if DEFAULT_DATA_MODE == "remote" else 1
DATA_MODE = st.sidebar.radio("Data source", ["remote", "local"], index=_default_index)

# --------------- Load Data ---------------
if DATA_MODE == "remote":
    if not REMOTE_RAW_URL:
        st.sidebar.warning("REMOTE_RAW_URL not set in secrets; using local file instead.")
        DATA_MODE = "local"

if DATA_MODE == "local":
    mtime_ns = _get_mtime_ns(DATA_FILE)
    df = _load_local_json(str(DATA_FILE), mtime_ns)
else:
    try:
        cb = int(time.time() // 86400)  # refresh at most once per minute
        df = _load_remote_json(REMOTE_RAW_URL, cb)
    except Exception as e:
        st.sidebar.error(f"Remote fetch failed: {e}. Falling back to local file.")
        mtime_ns = _get_mtime_ns(DATA_FILE)
        df = _load_local_json(str(DATA_FILE), mtime_ns)

# Header captions
left, right = st.columns([1, 1])
with left:
    if DATA_MODE == "remote":
        st.caption("Reading from GitHub Raw (auto-refresh once a day)")
    else:
        st.caption("Reading local repo file (auto-refresh on commit)")
with right:
    st.caption(f"Loaded **{len(df):,}** total jobs")

if df.empty:
    st.info("No jobs available yet. Come back after the next run.")
    st.stop()

# Show last updated info
if "scraped_at" in df.columns and not df["scraped_at"].dropna().empty:
    try:
        last = pd.to_datetime(df["scraped_at"], errors="coerce").max()
        if pd.notna(last):
            st.caption(f"Most recent scrape timestamp in data: {last.strftime('%Y-%m-%d %H:%M')}")
    except Exception:
        pass

# ---------------- Filters ----------------
col1, col2, col3 = st.columns(3)
with col1:
    kw = st.text_input("Keyword", "")
with col2:
    companies = [""] + sorted([str(c) for c in df["company"].dropna().unique()], key=str.lower)
    company = st.selectbox("Company", companies, index=0)
with col3:
    city_state = st.text_input("City / State", "")

mask = pd.Series(True, index=df.index)
if kw:
    mask &= df["title"].astype(str).str.contains(kw, case=False, na=False)
if company:
    mask &= df["company"].astype(str).eq(company)
if city_state:
    mask &= df["location"].astype(str).str.contains(city_state, case=False, na=False)

filtered = df.loc[mask, REQUIRED_COLS]

if filtered.empty:
    st.warning("No results match your filters.")
    st.stop()

st.dataframe(
    filtered,
    use_container_width=True,
    hide_index=True,
    column_config={
        "title": st.column_config.TextColumn("Job Title"),
        "company": st.column_config.TextColumn("Company"),
        "salary": st.column_config.TextColumn("Salary"),
        "location": st.column_config.TextColumn("Location"),
        "url": st.column_config.LinkColumn(
            "Link",
            help="Open the job posting",
            display_text="Open",
        ),
    },
)
