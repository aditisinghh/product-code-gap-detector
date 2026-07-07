# Product–Code Gap Detector

> **"Bridges the gap between what PMs think shipped and what actually shipped."**

A developer tool that compares your Jira backlog against any GitHub codebase and uses **IBM Granite via watsonx.ai** to reason about which features are implemented, partially done, or completely missing.

Built for the **Improving Your Product Lifecycle with Bob** hackathon at IBM.

---

## The Problem

In every software team there's a silent disconnect: the product backlog says a feature is *In Progress* or *Done* — but nobody has verified the code actually exists. Engineers move fast, tickets get forgotten, and partial implementations get marked complete. No existing tool closes this loop automatically.

> **Nothing asks: "Does the code actually match what was promised in the ticket?"**

---

## The Solution

The Product–Code Gap Detector:

1. **Ingests tickets** from a Jira backlog (mock JSON or real Jira REST API)
2. **Clones any GitHub repo** and extracts functions, classes, and comments via AST parsing
3. **Asks IBM Granite** (watsonx.ai) to reason over each ticket vs the codebase evidence
4. **Produces a gap report** — each ticket tagged as `IMPLEMENTED`, `PARTIAL`, `MISSING`, or `UNCLEAR` with one-line AI reasoning

The demo uses a real IBM ZAIOps dashboard backend (`api.py`) as the target codebase, with 20 tickets written directly from the actual product spec — making the gap analysis immediately meaningful.

---

## Architecture

```
Jira Backlog (mock JSON / real API)
         +
GitHub Repo (cloned via git, AST parsed)
         ↓
   ingest_jira.py  +  ingest_codebase.py
         ↓
     gap_detector.py
         ↓
   IBM Granite (watsonx.ai)  ←── prompt: ticket + function names + file evidence
         ↓
   STATUS: IMPLEMENTED / PARTIAL / MISSING
         ↓
   report.py  →  JSON + self-contained HTML report
         ↓
   app.py (FastAPI :8001)  ◀──  ui/index.html
```

---

## Project Structure

```
product-code-gap-detector/
├── README.md
├── .env.example
├── requirements.txt
├── app.py                      ← FastAPI backend (serves UI + API)
├── mock_data/
│   └── jira_backlog.json       ← 20 ZAIOps dashboard tickets (DASH-101 to DASH-120)
├── src/
│   ├── ingest_jira.py          ← loads mock JSON or real Jira REST API
│   ├── ingest_codebase.py      ← clones any GitHub repo, extracts symbols via AST
│   ├── gap_detector.py         ← calls IBM Granite to reason over tickets vs code
│   └── report.py               ← generates JSON + self-contained HTML report
└── ui/
    └── index.html              ← single-page frontend
```

---

## The 20 Mock Tickets (DASH-101 to DASH-120)

Written directly from the real ZAIOps dashboard backend spec:

| Range | Coverage |
|-------|----------|
| DASH-101 to 107 | Revenue endpoints — summary, top/negative deals, quarterly trend, IOT breakdown, customer segmentation, Excel upload |
| DASH-108 to 112 | Pipeline endpoints — won/lost opps, stage breakdown by week, YoY comparison, active KPI tiles, top current opps |
| DASH-113 to 117 | Qualtrics satisfaction — summary, distribution, by-product/region, trend, email funnel, low-sat alerts |
| DASH-118 to 120 | AI + platform — watsonx insights, product rollup, schema validation |

---

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/aditisinghh/product-code-gap-detector.git
cd product-code-gap-detector
```

### 2. Install dependencies

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env — add your watsonx and GitHub credentials
```

Required in `.env`:
```
IFM_TARGET_API_KEY=your_watsonx_api_key
IFM_TARGET_SPACE_ID=your_watsonx_space_id
IFM_TARGET_URL=https://us-south.ml.cloud.ibm.com
GITHUB_TOKEN=ghp_...   # only needed for private repos
```

### 4. Run

```bash
python app.py
```

Open **http://localhost:8001** — the UI loads with the ZAIOps API repo pre-filled.

---

## Demo Flow

1. Open **http://localhost:8001**
2. The ZAIOps API repo URL is pre-filled — click **Run Gap Analysis**
3. The backend clones the repo, extracts all function names, sends each ticket to IBM Granite
4. Results appear live — each ticket shows `IMPLEMENTED`, `PARTIAL`, or `MISSING` with AI reasoning
5. Click **Open full HTML report** for a shareable polished report
6. Swap the URL for **any other GitHub repo** — works on any codebase

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/analyze` | Start a gap analysis run |
| `GET`  | `/report/{run_id}` | Poll status / fetch JSON report |
| `GET`  | `/report/{run_id}/html` | Fetch self-contained HTML report |
| `GET`  | `/health` | Liveness check |

### Example

```bash
curl -X POST http://localhost:8001/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/aditisinghh/zaiops-dashboard-api", "use_mock": true}'
```

---

## Switching to Real Jira

Set in `.env`:
```
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=you@company.com
JIRA_API_TOKEN=your_token
```

Select **"Real Jira API"** in the UI. The mock is a drop-in replacement — identical interface.

---

## Why It Matters for the Product Lifecycle

- **PM → Engineering trust** — PMs can verify a feature shipped without reading code
- **Sprint retrospectives** — instantly see which "Done" tickets are actually done
- **Onboarding** — new engineers understand what's built vs what's planned
- **CI/CD integration** — run on every PR merge to catch regressions against the backlog
- **Language agnostic** — works on Python, TypeScript, Go, Java, Ruby, Rust

---

## Related Repos

- **[zaiops-dashboard-api](https://github.com/aditisinghh/zaiops-dashboard-api)** — ZAIOps FastAPI backend used as the demo target codebase
- **[TelosZData](https://github.com/aditisinghh/TelosZData)** — React/TypeScript frontend dashboard

---

## Roadmap

- [ ] Webhook: auto-trigger analysis on every PR merge
- [ ] Slack notification for newly detected gaps
- [ ] GitHub Actions integration
- [ ] Support Linear and GitHub Issues as ticket sources
- [ ] Historical gap trend over time

---

*Made with IBM Bob*
