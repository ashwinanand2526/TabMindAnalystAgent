"""Extension Bridge — FastAPI server connecting the Chrome extension to the S8 agent.

Endpoints:
    GET  /health                  liveness probe (used by extension to check if server is up)
    POST /analyze-tabs            accept tab payloads, launch Executor, return session_id
    GET  /stream/{session_id}     SSE stream of per-node events (node_started, node_complete, done)
    GET  /result/{session_id}     final formatted answer + comparison + verdict JSON

Run:
    uv run python extension_bridge.py
    # or
    python extension_bridge.py

The server listens on localhost:7861.  The Chrome extension calls /health first;
if that fails it launches this server via the packaged native-messaging host or a
shell command, then retries /health until it responds.

CORS: only localhost origins are allowed (the extension popup is chrome-extension://...
which the browser treats as a privileged origin, but we still restrict to localhost for
safety when called from regular pages during development).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ── path setup ────────────────────────────────────────────────────────────────
# The bridge lives in the same `code/` directory as flow.py so all imports
# resolve naturally once we ensure the directory is on sys.path.
CODE_DIR = Path(__file__).parent
sys.path.insert(0, str(CODE_DIR))

# Load .env so OPENAI_API_KEY / ANTHROPIC_API_KEY / TAVILY_API_KEY are available
from dotenv import load_dotenv
load_dotenv(CODE_DIR / ".env")

from flow import Executor  # noqa: E402  (must come after sys.path and dotenv)

# ── app setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Tab Researcher Bridge",
    description="Local FastAPI server bridging the Chrome extension to the S8 growing-graph agent",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # extension popup origin varies; restrict if needed
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── in-memory session store ───────────────────────────────────────────────────
# Maps session_id → {"status": "running"|"done"|"error",
#                    "events": [...],
#                    "result": str | None,
#                    "answer_json": dict | None}
_sessions: dict[str, dict] = {}
_sessions_lock = asyncio.Lock()


# ── request / response models ─────────────────────────────────────────────────

class TabPayload(BaseModel):
    url: str
    title: str
    html: str                     # raw HTML or markdown already extracted by content_script.js


class AnalyzeRequest(BaseModel):
    tabs: list[TabPayload]
    focus: str = "balanced"       # "price" | "specs" | "reviews" | "balanced"
    session_id: str | None = None


class AnalyzeResponse(BaseModel):
    session_id: str
    status: str


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_query(req: AnalyzeRequest) -> str:
    """Convert tab payloads into a structured query string for flow.py's Executor.

    The Planner reads this query and emits tab_reader nodes (one per tab),
    then comparator → verdict → formatter.  The tab HTML is embedded in the
    query so it arrives as USER_QUERY in every tab_reader's INPUTS block.
    """
    tab_lines = []
    for i, tab in enumerate(req.tabs, 1):
        # Truncate HTML to avoid blowing the planner's context window.
        # The tab_reader skill will see the full content via INPUTS when the
        # Planner routes USER_QUERY → tab_reader nodes.
        html_preview = tab.html[:500].replace("\n", " ")
        tab_lines.append(
            f"TAB_{i}: title={tab.title!r} url={tab.url!r} "
            f"html_preview={html_preview!r}"
        )

    tabs_block = "\n".join(tab_lines)
    full_html_blocks = "\n\n".join(
        f"=== TAB_{i} FULL CONTENT ===\n{tab.html[:8000]}"
        for i, tab in enumerate(req.tabs, 1)
    )

    return (
        f"Compare the following {len(req.tabs)} browser tabs. "
        f"Focus dimension: {req.focus}. "
        f"For each tab use the tab_reader skill to extract a structured record, "
        f"then use comparator to build a scored matrix, "
        f"then use verdict to pick the best option with reason and caveats. "
        f"Output a clear summary with the comparison table and final recommendation.\n\n"
        f"TAB SUMMARIES:\n{tabs_block}\n\n"
        f"FULL TAB CONTENT:\n{full_html_blocks}"
    )


async def _emit(sid: str, event_type: str, data: dict) -> None:
    """Append an SSE event to the session's event queue."""
    async with _sessions_lock:
        if sid in _sessions:
            _sessions[sid]["events"].append({
                "type": event_type,
                "ts": time.time(),
                **data,
            })


async def _run_agent(sid: str, query: str) -> None:
    """Run the Executor in the background and update the session store."""
    try:
        def on_event(nid: str, event_type: str, data: dict) -> None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_emit(sid, event_type, {"node_id": nid, **data}))
            except RuntimeError:
                pass

        executor = Executor(on_node_event=on_event)
        answer = await executor.run(query, session_id=sid)

        # Parse the answer — if it's JSON, pull out comparison/verdict sub-dicts.
        answer_json: dict = {}
        try:
            answer_json = json.loads(answer)
        except (json.JSONDecodeError, TypeError):
            answer_json = {"final_answer": answer}

        async with _sessions_lock:
            _sessions[sid]["status"] = "done"
            _sessions[sid]["result"] = answer
            _sessions[sid]["answer_json"] = answer_json
            _sessions[sid]["events"].append({
                "type": "done",
                "ts": time.time(),
                "answer": answer[:2000],
            })
    except Exception as exc:  # noqa: BLE001
        async with _sessions_lock:
            if sid in _sessions:
                _sessions[sid]["status"] = "error"
                _sessions[sid]["error"] = str(exc)
                _sessions[sid]["events"].append({
                    "type": "error",
                    "ts": time.time(),
                    "message": str(exc),
                })


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    """Liveness probe. The Chrome extension polls this before sending /analyze-tabs."""
    return {"status": "ok", "service": "tab-researcher-bridge", "version": "1.0.0"}


@app.post("/analyze-tabs", response_model=AnalyzeResponse)
async def analyze_tabs(req: AnalyzeRequest) -> AnalyzeResponse:
    """Accept tab payloads and start the agent asynchronously.

    Returns a session_id immediately. The caller should then connect to
    GET /stream/{session_id} for live events or poll GET /result/{session_id}.
    """
    if not req.tabs:
        raise HTTPException(status_code=400, detail="tabs list must not be empty")
    if len(req.tabs) > 6:
        raise HTTPException(status_code=400, detail="maximum 6 tabs per comparison")

    sid = req.session_id or f"s8-{uuid.uuid4().hex[:8]}"
    query = _build_query(req)

    async with _sessions_lock:
        _sessions[sid] = {
            "status": "running",
            "events": [],
            "result": None,
            "answer_json": None,
            "error": None,
            "query": query,
            "tabs": [t.model_dump(exclude={"html"}) for t in req.tabs],
            "focus": req.focus,
            "started_at": time.time(),
        }

    # Fire and forget — the client streams progress via SSE.
    asyncio.create_task(_run_agent(sid, query))

    return AnalyzeResponse(session_id=sid, status="running")


@app.get("/stream/{session_id}")
async def stream_events(session_id: str) -> StreamingResponse:
    """Server-Sent Events stream of agent progress for a session.

    Events are JSON objects with a `type` field:
      node_started   → {"type": "node_started", "node_id": "n:2", "skill": "tab_reader"}
      node_complete  → {"type": "node_complete", "node_id": "n:2", "skill": "tab_reader", "elapsed_s": 3.1}
      node_failed    → {"type": "node_failed", ...}
      done           → {"type": "done", "answer": "..."}
      error          → {"type": "error", "message": "..."}
    """
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")

    async def event_generator() -> AsyncIterator[str]:
        sent = 0
        while True:
            async with _sessions_lock:
                session = _sessions.get(session_id)
                if session is None:
                    break
                events = session["events"]
                new_events = events[sent:]
                status = session["status"]

            for ev in new_events:
                yield f"data: {json.dumps(ev)}\n\n"
                sent += 1

            if status in ("done", "error") and sent >= len(events):
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",         # disable nginx buffering if behind proxy
        },
    )


@app.get("/result/{session_id}")
async def get_result(session_id: str) -> dict:
    """Return the final answer and structured comparison for a completed session."""
    async with _sessions_lock:
        session = _sessions.get(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")

    status = session["status"]
    if status == "running":
        return {
            "session_id": session_id,
            "status": "running",
            "elapsed_s": round(time.time() - session["started_at"], 1),
        }
    if status == "error":
        raise HTTPException(
            status_code=500,
            detail={"session_id": session_id, "error": session.get("error")},
        )

    answer_json = session.get("answer_json") or {}
    return {
        "session_id": session_id,
        "status": "done",
        "elapsed_s": round(time.time() - session["started_at"], 1),
        "focus": session.get("focus", "balanced"),
        "tabs": session.get("tabs", []),
        "answer": session.get("result", ""),
        "comparison": answer_json.get("comparison"),
        "verdict": answer_json.get("verdict"),
        "final_answer": answer_json.get("final_answer") or session.get("result", ""),
    }


@app.get("/sessions")
async def list_sessions() -> dict:
    """Debug endpoint: list all active/recent sessions."""
    async with _sessions_lock:
        summary = {
            sid: {
                "status": s["status"],
                "focus": s.get("focus"),
                "tab_count": len(s.get("tabs", [])),
                "elapsed_s": round(time.time() - s["started_at"], 1),
            }
            for sid, s in _sessions.items()
        }
    return {"sessions": summary, "count": len(summary)}


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("BRIDGE_PORT", 7861))
    print(f"[bridge] Tab Researcher bridge starting on http://localhost:{port}")
    print(f"[bridge] Health check: http://localhost:{port}/health")
    uvicorn.run(
        "extension_bridge:app",
        host="127.0.0.1",
        port=port,
        reload=False,
        log_level="info",
    )
