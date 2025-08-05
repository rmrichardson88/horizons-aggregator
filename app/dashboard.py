import json, pandas as pd, streamlit as st
from pathlib import Path

DATA_FILE = Path(__file__).parents[1] / "data/latest_jobs.json"

@st.cache_data
def load_data():
    if DATA_FILE.exists():
        return pd.read_json(DATA_FILE)
    return pd.DataFrame(columns=["title","company","salary","location","url"])

df = load_data()

st.title("Horizons Job Aggregator")
st.caption("Updated nightly by GitHub Actions")

col1, col2, col3 = st.columns(3)
with col1:
    kw = st.text_input("Keyword")
with col2:
    company = st.selectbox("Company", [""] + sorted(df["company"].unique()))
with col3:
    city_state = st.text_input("City / State")

mask = (
    df["title"].str.contains(kw, case=False, na=False) if kw else True
) & (
    df["company"].eq(company) if company else True
) & (
    df["location"].str.contains(city_state, case=False, na=False) if city_state else True
)

st.dataframe(df[mask][["title","company","salary","location","url"]])
