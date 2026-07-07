"""
gap_detector.py
===============
The core reasoning engine. For each ticket, it builds a focused prompt
containing the ticket details + relevant codebase evidence, then asks Bob
(via its HTTP API) to classify the implementation status.

Status values:
  IMPLEMENTED  — clear evidence the feature exists in code
  PARTIAL      — some code exists but the ticket description isn't fully covered
  MISSING      — no matching code evidence found
  UNCLEAR      — not enough signal to decide

Bob is called via its local API (default: http://localhost:11434/api/generate,
compatible with Ollama's format which Bob exposes). Update BOB_API_URL in .env
to point at your Bob MCP endpoint if it differs.
"""

import os
import re
import textwrap
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

BOB_API_URL = os.getenv("BOB_API_URL", "http://localhost:11434")
BOB_MODEL   = os.getenv("BOB_MODEL", "granite3-dense:8b")

VALID_STATUSES = {"IMPLEMENTED", "PARTIAL", "MISSING", "UNCLEAR"}


# ── Codebase indexing (keyword → files) ──────────────────────────────────────

def _build_index(snapshot: dict) -> dict[str, list[str]]:
    """
    Build a reverse index: keyword → [file paths that mention it].
    Lowercased; used to quickly surface relevant files for each ticket.
    """
    index: dict[str, list[str]] = {}
    for file in snapshot["files"]:
        words = set()
        for sym in file.get("symbols", []):
            words.update(re.findall(r"[a-z]+", sym.lower()))
        for txt in file.get("docstrings", []) + file.get("comments", []):
            words.update(re.findall(r"[a-z]{3,}", txt.lower()))
        for word in words:
            index.setdefault(word, []).append(file["path"])
    return index


def _relevant_files(ticket: dict, snapshot: dict, index: dict) -> list[dict]:
    """Return the top-10 most relevant files for a given ticket."""
    # Extract keywords from ticket title + description
    text = f"{ticket['title']} {ticket['description']}".lower()
    keywords = set(re.findall(r"[a-z]{3,}", text))

    # Score files by keyword hit count
    scores: dict[str, int] = {}
    for kw in keywords:
        for path in index.get(kw, []):
            scores[path] = scores.get(path, 0) + 1

    top_paths = sorted(scores, key=scores.__getitem__, reverse=True)[:10]
    path_to_file = {f["path"]: f for f in snapshot["files"]}
    return [path_to_file[p] for p in top_paths if p in path_to_file]


def _format_evidence(files: list[dict], deps: list[str]) -> str:
    """Format codebase evidence as compact text for the prompt."""
    lines = []
    for f in files:
        syms = ", ".join(f["symbols"][:15]) or "—"
        docs = " | ".join(f["docstrings"][:3])
        cmts = " | ".join(f["comments"][:5])
        lines.append(f"  FILE: {f['path']}")
        lines.append(f"    symbols   : {syms}")
        if docs:
            lines.append(f"    docstrings: {docs[:200]}")
        if cmts:
            lines.append(f"    comments  : {cmts[:200]}")
    if deps:
        lines.append(f"  DEPENDENCIES: {', '.join(deps[:30])}")
    return "\n".join(lines) if lines else "  (no matching source files found)"


def _build_prompt(ticket: dict, evidence: str) -> str:
    return textwrap.dedent(f"""
        You are a senior engineer reviewing whether a product feature has been implemented.

        TICKET
        ------
        ID         : {ticket['id']}
        Title      : {ticket['title']}
        Status     : {ticket['status']}
        Priority   : {ticket['priority']}
        Description: {ticket['description'][:500]}

        CODEBASE EVIDENCE
        -----------------
        {evidence}

        TASK
        ----
        Based ONLY on the evidence above, classify this ticket as exactly one of:
          IMPLEMENTED — the feature clearly exists in the codebase
          PARTIAL     — some relevant code exists but the feature is incomplete
          MISSING     — no matching implementation found
          UNCLEAR     — not enough evidence to decide

        Then write ONE sentence (max 20 words) explaining your reasoning.

        Respond in this exact format (nothing else):
        STATUS: <IMPLEMENTED|PARTIAL|MISSING|UNCLEAR>
        REASON: <one sentence>
    """).strip()


# ── Bob API call ──────────────────────────────────────────────────────────────

def _ask_bob(prompt: str) -> str:
    """
    Call Bob's HTTP API and return the raw generated text.
    Compatible with Ollama-style /api/generate endpoint.
    Adjust the payload structure if your Bob endpoint differs.
    """
    try:
        resp = httpx.post(
            f"{BOB_API_URL}/api/generate",
            json={
                "model":  BOB_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0, "num_predict": 120},
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except httpx.ConnectError:
        # Bob not running locally — return a deterministic fallback
        # so the rest of the pipeline still works during development
        return "STATUS: UNCLEAR\nREASON: Bob API is not reachable; check BOB_API_URL in .env"
    except Exception as e:
        return f"STATUS: UNCLEAR\nREASON: Bob API error — {e}"


def _parse_response(raw: str) -> tuple[str, str]:
    """Extract STATUS and REASON from Bob's response."""
    status = "UNCLEAR"
    reason = raw.strip()

    status_match = re.search(r"STATUS:\s*(IMPLEMENTED|PARTIAL|MISSING|UNCLEAR)", raw, re.IGNORECASE)
    reason_match = re.search(r"REASON:\s*(.+)", raw, re.IGNORECASE)

    if status_match:
        status = status_match.group(1).upper()
    if reason_match:
        reason = reason_match.group(1).strip()

    return status, reason


# ── Public API ────────────────────────────────────────────────────────────────

def analyze(tickets: list[dict], snapshot: dict) -> list[dict]:
    """
    For each ticket, find relevant code evidence, ask Bob, and return results.

    Returns a list of gap records:
    {
      id, title, status (jira), priority, labels,
      gap_status: IMPLEMENTED | PARTIAL | MISSING | UNCLEAR,
      reason: str,
      evidence_files: [str, ...]
    }
    """
    index   = _build_index(snapshot)
    results = []

    for ticket in tickets:
        rel_files = _relevant_files(ticket, snapshot, index)
        evidence  = _format_evidence(rel_files, snapshot.get("dependencies", []))
        prompt    = _build_prompt(ticket, evidence)
        raw       = _ask_bob(prompt)
        gap_status, reason = _parse_response(raw)

        results.append({
            "id":             ticket["id"],
            "title":          ticket["title"],
            "jira_status":    ticket["status"],
            "priority":       ticket["priority"],
            "labels":         ticket["labels"],
            "gap_status":     gap_status,
            "reason":         reason,
            "evidence_files": [f["path"] for f in rel_files],
        })

    return results
