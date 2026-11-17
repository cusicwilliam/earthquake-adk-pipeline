import html
import io
import json
import os
from datetime import datetime, timedelta, timezone
from string import Template

import pandas as pd
import requests
from google.adk.tools import ToolContext
from google.cloud import storage

USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
MIN_MAGNITUDE = 2.5
TIMEOUT_SECONDS = 30
RAW_PATH = "quakes/raw/ingest_date={date}/earthquakes.json"
EVENTS_PATH = "quakes/processed/events.parquet"
SUMMARY_PATH = "quakes/processed/daily_summary.csv"
REPORT_PATH = "quakes/report/index.html"
LOCAL_REPORT = "output/report.html"
BANDS = ["minor", "light", "moderate", "strong"]


# With GCS_BUCKET set, files go to that bucket. Without it, they go to a local data/ folder.
def location(path):
    bucket = os.getenv("GCS_BUCKET")
    return f"gs://{bucket}/{path}" if bucket else os.path.join("data", path)


def save(path, data):
    if os.getenv("GCS_BUCKET"):
        storage.Client().bucket(os.environ["GCS_BUCKET"]).blob(path).upload_from_string(data)
        return
    os.makedirs(os.path.dirname(location(path)), exist_ok=True)
    with open(location(path), "wb") as f:
        f.write(data.encode("utf-8") if isinstance(data, str) else data)


def load(path):
    if os.getenv("GCS_BUCKET"):
        return storage.Client().bucket(os.environ["GCS_BUCKET"]).blob(path).download_as_bytes()
    with open(location(path), "rb") as f:
        return f.read()


def parse_region(place):
    if not isinstance(place, str) or not place.strip():
        return "Unknown"
    if " of " in place:
        return place.split(" of ", 1)[1].strip() or "Unknown"
    return place.split(",")[-1].strip() or "Unknown"


def mag_band(magnitude):
    if magnitude < 4.0:
        return "minor"
    if magnitude < 5.0:
        return "light"
    if magnitude < 6.0:
        return "moderate"
    return "strong"


def fetch_earthquakes(days_back: int, tool_context: ToolContext) -> dict:
    """Download earthquakes of magnitude 2.5+ from the last days_back days from USGS and save the raw JSON to GCS.

    Args:
        days_back: Number of days to load. Use 30 if the user did not ask for a number.
    """
    now = datetime.now(timezone.utc)
    params = {
        "format": "geojson",
        "minmagnitude": MIN_MAGNITUDE,
        "orderby": "time",
        "starttime": (now - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime": now.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    response = requests.get(USGS_URL, params=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    path = RAW_PATH.format(date=now.strftime("%Y-%m-%d"))
    save(path, response.content)
    tool_context.state["raw_path"] = path
    return {"event_count": len(response.json()["features"]), "raw_path": location(path)}


def transform_events(tool_context: ToolContext) -> dict:
    """Clean the raw earthquake file, write events.parquet and daily_summary.csv, and return headline stats."""
    raw = json.loads(load(tool_context.state["raw_path"]))
    rows = []
    for feature in raw["features"]:
        props = feature.get("properties") or {}
        lon, lat, depth = ((feature.get("geometry") or {}).get("coordinates") or [None] * 3)[:3]
        rows.append({
            "event_id": feature.get("id"),
            "event_time": props.get("time"),
            "magnitude": props.get("mag"),
            "place": props.get("place"),
            "latitude": lat,
            "longitude": lon,
            "depth_km": depth,
        })
    events = pd.DataFrame(rows, columns=["event_id", "event_time", "magnitude", "place", "latitude", "longitude", "depth_km"])
    events = events.dropna(subset=["event_id", "event_time", "magnitude"]).drop_duplicates("event_id")
    events["event_time"] = pd.to_datetime(events["event_time"].astype("int64"), unit="ms", utc=True)
    events["event_date"] = events["event_time"].dt.strftime("%Y-%m-%d")
    events["magnitude"] = events["magnitude"].astype(float)
    events["mag_band"] = events["magnitude"].map(mag_band)
    events["region"] = events["place"].map(parse_region)
    events = events[["event_id", "event_time", "event_date", "magnitude", "mag_band", "place",
                     "region", "latitude", "longitude", "depth_km"]]

    daily = events.groupby("event_date").agg(
        event_count=("event_id", "size"),
        max_magnitude=("magnitude", "max"),
        avg_depth_km=("depth_km", "mean"),
    ).round(2)
    # One column per band, with zeros for bands that had no events that day.
    bands = events.pivot_table(index="event_date", columns="mag_band", values="event_id", aggfunc="size")
    daily = daily.join(bands.reindex(columns=BANDS).fillna(0).astype(int)).reset_index()

    buffer = io.BytesIO()
    events.to_parquet(buffer, index=False)
    save(EVENTS_PATH, buffer.getvalue())
    save(SUMMARY_PATH, daily.to_csv(index=False))

    stats = {"rows": len(events), "days": len(daily)}
    if not events.empty:
        busiest = daily.loc[daily["event_count"].idxmax()]
        largest = events.loc[events["magnitude"].idxmax()]
        stats["busiest_day"] = {"date": str(busiest["event_date"]), "events": int(busiest["event_count"])}
        stats["largest_event"] = {"magnitude": float(largest["magnitude"]), "place": largest["place"],
                                  "time": largest["event_time"].strftime("%Y-%m-%d %H:%M UTC")}
        stats["top_regions"] = {k: int(v) for k, v in events["region"].value_counts().head(5).items()}
    # Saved to state so report_agent's instruction can include it.
    tool_context.state["stats"] = stats
    return stats


REPORT_TEMPLATE = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Earthquake Report</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 960px; margin: 0 auto; padding: 24px 16px; color: #222; }
h1 { margin-bottom: 4px; }
.meta { color: #666; margin-top: 0; }
.chart { position: relative; height: 320px; margin: 24px 0; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #ddd; }
td.num { text-align: right; }
</style>
</head>
<body>
<h1>Earthquake Report</h1>
<p class="meta">Run time: $run_time. USGS events of magnitude 2.5 and above, $first_date to $last_date (UTC).</p>
<p>$highlights</p>
<h2>Events per day</h2>
<div class="chart"><canvas id="daily"></canvas></div>
<h2>10 largest events</h2>
<table>
<tr><th>Time (UTC)</th><th>Magnitude</th><th>Place</th><th>Depth km</th></tr>
$table_rows
</table>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
new Chart(document.getElementById("daily"), {
  type: "bar",
  data: {labels: $labels, datasets: [{label: "Events", data: $counts, backgroundColor: "#2a78d6"}]},
  options: {maintainAspectRatio: false, plugins: {legend: {display: false}}}
});
</script>
</body>
</html>
""")


def publish_report(highlights: str) -> dict:
    """Build the HTML report from the processed files, save it to output/report.html and upload it to GCS.

    Args:
        highlights: Two or three plain-text sentences on what stood out in the data.
    """
    events = pd.read_parquet(io.BytesIO(load(EVENTS_PATH)))
    daily = pd.read_csv(io.BytesIO(load(SUMMARY_PATH)))

    largest = events.sort_values("magnitude", ascending=False).head(10)
    table_rows = "\n".join(
        f"<tr><td>{row.event_time:%Y-%m-%d %H:%M}</td><td class='num'>{row.magnitude:.1f}</td>"
        f"<td>{html.escape(str(row.place))}</td><td class='num'>{row.depth_km:.1f}</td></tr>"
        for row in largest.itertuples()
    )
    page = REPORT_TEMPLATE.substitute(
        run_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        first_date=daily["event_date"].min(),
        last_date=daily["event_date"].max(),
        highlights=html.escape(highlights),
        table_rows=table_rows,
        labels=json.dumps(daily["event_date"].tolist()),
        counts=json.dumps(daily["event_count"].tolist()),
    )

    os.makedirs(os.path.dirname(LOCAL_REPORT), exist_ok=True)
    with open(LOCAL_REPORT, "w", encoding="utf-8") as f:
        f.write(page)
    save(REPORT_PATH, page)
    return {"report_uri": location(REPORT_PATH), "local_path": LOCAL_REPORT}
