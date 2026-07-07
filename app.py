"""
app.py
======
FastAPI backend for the Product–Code Gap Detector.

Endpoints:
  POST /analyze          — run a full analysis (clones repo, loads tickets, calls Bob)
  GET  /report/{run_id}  — fetch a completed report as JSON
  GET  /report/{run_id}/html — fetch the HTML report
  GET  /health           — liveness check

Runs on http://localhost:8001 (different port from the dashboard to avoid conflicts).
"""

import asyncio
import uuid
from typing import Optional

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.gap_detector import analyze
from src.ingest_codebase import snapshot
from src.ingest_jira import load_tickets
from src.report import build_html_report, build_json_report

app = FastAPI(title="Product–Code Gap Detector", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory run store (replace with Redis/DB for production)
_runs: dict[str, dict] = {}


class AnalyzeRequest(BaseModel):
    repo_url:    str
    use_mock:    bool = True          # False = real Jira API
    jira_project: Optional[str] = "PROJ"
    ticket_ids:  Optional[list[str]] = None  # None = all tickets


class RunStatus(BaseModel):
    run_id:  str
    status:  str   # pending | running | done | error
    message: Optional[str] = None


# ── Background task ───────────────────────────────────────────────────────────

def _run_analysis(run_id: str, req: AnalyzeRequest):
    try:
        _runs[run_id]["status"] = "running"
        _runs[run_id]["message"] = "Loading tickets…"

        tickets = load_tickets(use_mock=req.use_mock, project_key=req.jira_project or "PROJ")
        if req.ticket_ids:
            tickets = [t for t in tickets if t["id"] in req.ticket_ids]

        _runs[run_id]["message"] = f"Cloning / updating repo: {req.repo_url}"
        snap = snapshot(req.repo_url)

        _runs[run_id]["message"] = f"Asking Bob to analyse {len(tickets)} ticket(s)…"
        results = analyze(tickets, snap)

        report = build_json_report(results, req.repo_url, meta={"tickets": len(tickets)})
        _runs[run_id].update({
            "status":  "done",
            "message": f"Analysis complete — {len(results)} tickets processed.",
            "report":  report,
            "html":    build_html_report(report),
        })
    except Exception as e:
        _runs[run_id].update({"status": "error", "message": str(e)})


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/analyze", response_model=RunStatus)
def start_analysis(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    """
    Kick off an analysis run. Returns a run_id immediately.
    Poll GET /report/{run_id} until status == 'done'.
    """
    run_id = str(uuid.uuid4())[:8]
    _runs[run_id] = {"status": "pending", "message": "Queued…"}
    background_tasks.add_task(_run_analysis, run_id, req)
    return RunStatus(run_id=run_id, status="pending", message="Analysis started.")


@app.get("/report/{run_id}")
def get_report(run_id: str):
    """Poll for status or fetch the completed JSON report."""
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run["status"] != "done":
        return {"run_id": run_id, "status": run["status"], "message": run.get("message")}
    return {"run_id": run_id, "status": "done", **run["report"]}


@app.get("/report/{run_id}/html", response_class=HTMLResponse)
def get_report_html(run_id: str):
    """Return the self-contained HTML report."""
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run["status"] != "done":
        return HTMLResponse(f"<p>Run {run_id} is {run['status']}: {run.get('message')}</p>",
                            status_code=202)
    return HTMLResponse(run["html"])


@app.get("/health")
def health():
    return {"status": "ok", "runs": len(_runs)}


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=True)
