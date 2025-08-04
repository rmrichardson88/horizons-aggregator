# horizons-aggregator
Pulls together job postings from several partner organizations for the Texas Panhandle

# Horizons Workforce Development — Aggregator MVP

## Data schema
| field      | type   | notes                              |
|------------|--------|------------------------------------|
| id         | str    | SHA-1 of title+company+location    |
| title      | str    |                                    |
| company    | str    |                                    |
| location   | str    | city, state                        |
| url        | str    | link to original posting           |
| posted     | str    | Raw date string from site          |
| scraped_at | str    | UTC ISO timestamp                  |
| source     | str    | job board identifier               |

## Refresh schedule
Nightly — 05:00 UTC via GitHub Actions.

## How to run locally
bash
pip install -r requirements.txt
python run_scrapers.py
streamlit run app/dashboard.py

---

## 9  Deploying the dashboard on Streamlit Cloud (≈1 minute)

1. Sign in at **https://share.streamlit.io** with your GitHub account.  
2. Click **“Create app”** → choose your new repo, default branch, and set the entry-point to `app/dashboard.py`.  
3. Hit **Deploy** – Streamlit Cloud handles the virtual env using `requirements.txt`.  
The official docs walk through the same flow if you need visuals. :contentReference[oaicite:1]{index=1}

---

### Running cost checklist

| Component            | Provider | Price |
|----------------------|----------|-------|
| GitHub repo          | GitHub   | $0 (public) |
| Nightly Action run   | GitHub   | ≤ 2,000 free minutes/mo |
| Storage (JSON)       | GitHub   | $0 (< 1 MB) |
| Streamlit Cloud app  | Streamlit| $0 (1 app limit) |

You’re now set up with a fully automated, totally free pipeline that scrapes nightly, dedupes, commits, and serves results. When the non-profit is ready to add a fancy front-end, they can consume the same `latest_jobs.json` (or swap the storage layer) without touching this foundation. Good luck!
::contentReference[oaicite:2]{index=2}
