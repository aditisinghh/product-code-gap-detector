# Prompt & Bob Usage

We built the Product–Code Gap Detector using Bob as our primary development assistant — from scaffolding the codebase to debugging the LLM reasoning engine.

---

## Stage 1 — Building the Project with Bob

### Scaffolding the full project structure

We described the architecture we had in mind and Bob generated the complete project — all source files, mock data, FastAPI backend, and frontend in one session.

**Prompt:**
> Build a Product–Code Gap Detector. It should ingest a Jira backlog and clone any GitHub repo, then use an LLM to compare each ticket against the codebase and output IMPLEMENTED / PARTIAL / MISSING per ticket. FastAPI backend, single-page HTML frontend, GitHub URL configurable at runtime.

---

### Generating the mock Jira backlog from our real spec

We pointed Bob at our actual dashboard backend spec and asked it to write 20 realistic tickets that map 1:1 to what we built — making the demo immediately meaningful.

**Prompt:**
> Replace the generic mock tickets with real tickets that match what my ZAIOps dashboard actually does. Use what you know from my api.py and BACKEND_SPEC.md — every endpoint should have a corresponding ticket.

**Result:** Bob generated 20 tickets (DASH-101 to DASH-120) covering revenue endpoints, pipeline endpoints, Qualtrics satisfaction, and the watsonx AI insights endpoint.

---

### Setting up GitHub repos and credentials

Bob guided the full GitHub setup — initialising repos, fixing permission errors, handling token scopes, and pushing three separate repos.

**Prompts:**
> `error: src refspec main does not match any` — how do I push my project to GitHub?

> `refusing to allow a Personal Access Token to create or update workflow without workflow scope` — what do I do?

---

### Serving the frontend from FastAPI

The UI couldn't open as a `file://` URL due to CORS. Bob updated `app.py` to mount `StaticFiles` and serve the frontend directly from the FastAPI server at `http://localhost:8001`.

**Prompt:**
> I can't open ui/index.html directly in the browser — it won't connect to the API.

---

## Stage 2 — LLM Reasoning & Debugging

### The gap analysis prompt — sent to IBM Granite per ticket at runtime

For each ticket, the detector builds a prompt with the ticket description and codebase evidence (function names extracted via Python AST), then Granite classifies it as IMPLEMENTED, PARTIAL, MISSING, or UNCLEAR.

**Prompt structure sent to Granite:**
```
You are reviewing source code. The following functions exist in the codebase:
upload_workbook, get_top_deals, get_negative_deals, get_revenue_summary ...

Full file evidence:
- api.py: upload_workbook, get_top_deals, get_revenue_summary, ...

Ticket: Excel workbook upload — ingest sheets into PostgreSQL
Description: POST /upload accepts a multipart Excel file. Each sheet becomes a PostgreSQL table...

IMPORTANT: If a function name in the evidence matches what the ticket describes, classify as IMPLEMENTED.

Respond with exactly two lines:
STATUS: IMPLEMENTED
REASON: [one sentence]
```

**Example Granite response:**
```
STATUS: IMPLEMENTED
REASON: upload_workbook function exists in api.py and handles multipart Excel ingestion into PostgreSQL.
```

---

### Diagnosing empty responses from watsonx

Every ticket was showing `UNCLEAR` with no reasoning. Bob identified the root cause — a `stop_sequences: ["\n\n"]` config that matched the prompt itself and cut off all output before generation started.

**Prompt:**
> Everything is showing as UNCLEAR and the terminal shows "✅ watsonx response:" with nothing after it. What's wrong?

**Bob's diagnosis:**
> The `stop_sequences: ["\n\n"]` is matching inside the prompt itself before the model generates anything. Remove it and the model will return full output.

---

### Fixing evidence retrieval

Tickets were showing `MISSING` even when the function existed. Bob diagnosed that the keyword indexer wasn't reliably surfacing `api.py`, and added logic to always include the largest file in the evidence for every ticket.

**Prompt:**
> The Excel upload ticket still shows MISSING even though upload_workbook clearly exists in api.py. Why is it not seeing it?

**Bob's fix:** Always inject the file with the most symbols into the evidence regardless of keyword score — so `api.py` is always in every ticket's context.

---

### Writing all documentation

Bob wrote the full README, `.env.example`, architecture diagram, demo flow, and this document.

**Prompt:**
> Update the README to include the problem statement, architecture, 20 ticket table, quick start, demo flow, and links to all three repos.

---

## Verdict Labels

Each ticket receives one of four labels from IBM Granite:

| Label | Meaning |
|-------|---------|
| `IMPLEMENTED` | Clear matching function or module found in codebase |
| `PARTIAL` | Some relevant code exists but feature is incomplete |
| `MISSING` | No matching implementation found |
| `UNCLEAR` | Not enough evidence to decide |
