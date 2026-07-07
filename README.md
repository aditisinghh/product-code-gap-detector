# Product–Code Gap Detector

> **"Bridges the gap between what PMs think shipped and what actually shipped."**

A developer tool that compares your Jira backlog against any GitHub codebase and uses **Bob (IBM's AI assistant)** to reason about which features are implemented, partially done, or completely missing.

Built for the *Improving Your Product Lifecycle with Bob* hackathon.

---

## What it does

1. **Ingests tickets** from a mock Jira backlog (or the real Jira REST API)
2. **Clones any GitHub repo** and extracts symbols, docstrings, and comments via AST
3. **Asks Bob** to compare each ticket against codebase evidence
4. **Produces a gap report** — each ticket tagged as `IMPLEMENTED`, `PARTIAL`, `MISSING`, or `UNCLEAR` with Bob's one-line reasoning

---

## Architecture

```
Jira tickets (mock or real)
        +
GitHub repo (cloned locally)
        ↓
  ingest_jira.py  +  ingest_codebase.py
        ↓
    gap_detector.py  ──▶  Bob API  (LLM reasoning)
        ↓
    report.py  ──▶  JSON + self-contained HTML report
        ↓
    app.py (FastAPI)  ◀──  ui/index.html
```

---

## Quick start

### 1. Install dependencies

```bash
cd product-code-gap-detector
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set BOB_API_URL to your Bob endpoint
```

### 3. Run the API server

```bash
python app.py
# → http://localhost:8001
```

### 4. Open the UI

Open `ui/index.html` in your browser (or serve it with any static server).

---

## Switching to real Jira

Set these in `.env`:

```
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=you@company.com
JIRA_API_TOKEN=your_api_token
```

Then select **"Real Jira API"** in the UI dropdown. The code shape is identical — the mock is a drop-in replacement.

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/analyze` | Start a gap analysis run |
| `GET`  | `/report/{run_id}` | Poll status / fetch JSON report |
| `GET`  | `/report/{run_id}/html` | Fetch self-contained HTML report |
| `GET`  | `/health` | Liveness check |

### Example request

```bash
curl -X POST http://localhost:8001/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/tiangolo/fastapi", "use_mock": true}'
```

---

## Project structure

```
product-code-gap-detector/
├── README.md
├── .env.example
├── requirements.txt
├── app.py                      ← FastAPI backend
├── mock_data/
│   └── jira_backlog.json       ← 10 realistic mock Jira tickets
├── src/
│   ├── ingest_jira.py          ← loads mock OR real Jira
│   ├── ingest_codebase.py      ← clones repo, extracts AST symbols
│   ├── gap_detector.py         ← calls Bob to reason over tickets vs code
│   └── report.py               ← generates JSON + HTML report
└── ui/
    └── index.html              ← single-page frontend
```

---

## Roadmap

- [ ] Webhook: auto-trigger analysis on every PR merge
- [ ] Slack notification for newly detected gaps
- [ ] GitHub Actions integration
- [ ] Support Linear and GitHub Issues as ticket sources
- [ ] Historical gap trend over time

---

*Made with IBM Bob*
