from google.adk import Agent, Workflow

from quake_agent.pipeline import fetch_earthquakes, publish_report, transform_events

MODEL = "gemini-flash-latest"

ingest_agent = Agent(
    name="ingest_agent",
    model=MODEL,
    instruction=(
        "Call fetch_earthquakes once. Use the number of days the user asked for, or 30 if they did not give one. "
        "Then say how many events were loaded and where the raw file was saved."
    ),
    tools=[fetch_earthquakes],
)

transform_agent = Agent(
    name="transform_agent",
    model=MODEL,
    instruction=(
        "Call transform_events once. Report the number of rows it produced, "
        "and say clearly if that number is zero."
    ),
    tools=[transform_events],
)

report_agent = Agent(
    name="report_agent",
    model=MODEL,
    instruction=(
        "Stats from the transform step: {stats?}\n"
        "Write two or three plain sentences on what stood out, such as the busiest day, the largest event "
        "and the leading regions. Call publish_report with those sentences, then say where the report was saved."
    ),
    tools=[publish_report],
)

root_agent = Workflow(
    name="earthquake_pipeline",
    edges=[("START", ingest_agent, transform_agent, report_agent)],
)
