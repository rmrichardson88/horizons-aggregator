import json
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Horizons Job Aggregator",
    page_icon="💼",
    layout="wide",
)

DATA_FILE = Path(__file__).parents[1] / "data/latest_jobs.json"
REQUIRED_COLS = ["title", "company", "salary", "location", "url"]


@st.cache_data
def load_data() -> pd.DataFrame:
    if not DATA_FILE.exists():
        return pd.DataFrame(columns=REQUIRED_COLS)

    try:
        df = pd.read_json(DATA_FILE)
    except ValueError:
        try:
            df = pd.read_json(DATA_FILE, lines=True)
        except Exception:
            return pd.DataFrame(columns=REQUIRED_COLS)

    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = None

    if "scraped_at" in df.columns:
        df["scraped_at_dt"] = pd.to_datetime(df["scraped_at"], errors="coerce")
        df = df.sort_values("scraped_at_dt", ascending=False, na_position="last")
    return df


df = load_data()

st.title("Horizons Job Aggregator")
left, right = st.columns([1, 1])
with left:
    st.caption("Updated nightly by GitHub Actions")
with right:
    st.caption(f"Loaded **{len(df):,}** total jobs")

if df.empty:
    st.info("No jobs available yet. Come back after the next run.")
    st.stop()

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
