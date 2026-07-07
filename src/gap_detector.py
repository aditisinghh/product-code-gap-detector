"""
gap_detector.py
===============
The core reasoning engine. For each ticket, it builds a focused prompt
containing the ticket details + relevant codebase evidence, then asks
Bob Shell (IBM Bob) to classify the implementation status.

Status values:
  IMPLEMENTED  — clear evidence the feature exists in code
  PARTIAL      — some code exists but the ticket description isn't fully covered
  MISSING      — no matching code evidence found
  UNCLEAR      — not enough signal to decide

Requires in .env:
  BOBSHELL_API_KEY  — API key from internal.bob.ibm.com (Scope: Inference)

Bob Shell must be installed:
  curl -fsSL https://bob.ibm.com/download/bobshell.sh | bash
"""

import os
import re
import subprocess
import textwrap
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

BOBSHELL_API_KEY = os.getenv("BOBSHELL_API_KEY", "")

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
    text = f"{ticket['title']} {ticket['description']}".lower()
    keywords = set(re.findall(r"[a-z]{3,}", text))

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


# ── Bob Shell call ────────────────────────────────────────────────────────────

def _ask_bob(prompt: str) -> str:
    """
    Call Bob Shell as a subprocess with the API key.
    bob --auth-method api-key -p "<prompt>"
    """
    if not BOBSHELL_API_KEY:
        return "STATUS: UNCLEAR\nREASON: BOBSHELL_API_KEY not set in .env"

    env = os.environ.copy()
    env["BOBSHELL_API_KEY"] = BOBSHELL_API_KEY

    try:
        result = subprocess.run(
            ["bob", "--auth-method", "api-key", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        output = result.stdout.strip()
        if not output and result.stderr:
            return f"STATUS: UNCLEAR\nREASON: Bob Shell error — {result.stderr.strip()[:200]}"
        return output
    except FileNotFoundError:
        return (
            "STATUS: UNCLEAR\n"
            "REASON: Bob Shell not installed — run: "
            "curl -fsSL https://bob.ibm.com/download/bobshell.sh | bash"
        )
    except subprocess.TimeoutExpired:
        return "STATUS: UNCLEAR\nREASON: Bob Shell timed out after 60s"
    except Exception as e:
        return f"STATUS: UNCLEAR\nREASON: Bob Shell error — {e}"


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
        rel_files  = _relevant_files(ticket, snapshot, index)
        evidence   = _format_evidence(rel_files, snapshot.get("dependencies", []))
        prompt     = _build_prompt(ticket, evidence)
        raw        = _ask_bob(prompt)
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
