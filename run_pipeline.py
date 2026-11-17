"""Run the earthquake workflow once. Usage: python run_pipeline.py ["Load the last 7 days"]"""

import asyncio
import sys

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from quake_agent.agent import root_agent


async def main(text):
    sessions = InMemorySessionService()
    session = await sessions.create_session(app_name="quakes", user_id="user")
    runner = Runner(app_name="quakes", node=root_agent, session_service=sessions)
    message = types.Content(role="user", parts=[types.Part(text=text)])
    async for event in runner.run_async(user_id="user", session_id=session.id, new_message=message):
        for call in event.get_function_calls():
            print(f"[{event.author}] {call.name}({call.args})")
        if event.is_final_response() and event.content and event.content.parts:
            print(f"[{event.author}] {event.content.parts[0].text}\n")


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main(" ".join(sys.argv[1:]) or "Run the earthquake pipeline for the last 30 days."))
