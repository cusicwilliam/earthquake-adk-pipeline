# USGS Earthquake Pipeline with Google ADK

An ADK workflow of three agents that loads recent earthquakes from the USGS
API, cleans them, stores the data in Google Cloud Storage and publishes an
HTML report.

1. `ingest_agent` calls `fetch_earthquakes`: downloads M2.5+ events for the
   last N days (default 30) and saves the raw JSON.
2. `transform_agent` calls `transform_events`: builds a clean events table
   and a daily summary.
3. `report_agent` calls `publish_report`: writes a few sentences of
   highlights and publishes a report with a chart and a top 10 table.

Every run is a full reload and overwrites the same files. The code is in
`quake_agent/pipeline.py` (data logic and tools) and `quake_agent/agent.py`.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # then paste a Gemini API key into GOOGLE_API_KEY
```

Get a free Gemini API key at https://aistudio.google.com/apikey. With only
the key set, files are saved to a local `data/` folder. To use Google Cloud
Storage instead, run `gcloud auth application-default login`, create a bucket
and set `GCS_BUCKET` in `.env`.

## Run

```powershell
python run_pipeline.py                        # last 30 days
python run_pipeline.py "Load the last 7 days"
adk web                                       # browser UI, pick quake_agent
```

## Output in the bucket

```
gs://YOUR_BUCKET/quakes/raw/ingest_date=YYYY-MM-DD/earthquakes.json   USGS response as returned
gs://YOUR_BUCKET/quakes/processed/events.parquet                      one row per event
gs://YOUR_BUCKET/quakes/processed/daily_summary.csv                   counts per day and band
gs://YOUR_BUCKET/quakes/report/index.html                             the report
```

Without `GCS_BUCKET` the same files go to `data/quakes/...`. A copy of the
report is always saved to `output/report.html`.
