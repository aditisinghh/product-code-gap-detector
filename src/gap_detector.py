"""
gap_detector.py
===============
The core reasoning engine. For each ticket, it builds a focused prompt
containing the ticket details + relevant codebase evidence, then asks
watsonx.ai (IBM Granite) to classify the implementation status.

Status values:
  IMPLEMENTED  — clear evidence the feature exists in code
  PARTIAL      — some code exists but the ticket description isn't fully covered
  MISSING      — no matching code evidence found
  UNCLEAR      — not enough signal to decide

Requires in .env:
  IFM_TARGET_API_KEY
  IFM_TARGET_SPACE_ID
  IFM_TARGET_URL      (optional, defaults to us-south)
"""

import json
import os
import re
import textwrap
import urllib.parse
import urllib.request
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

WATSONX_API_KEY  = os.getenv("IFM_TARGET_API_KEY", "")
WATSONX_SPACE_ID = os.getenv("IFM_TARGET_SPACE_ID", "")
WATSONX_URL      = os.getenv("IFM_TARGET_URL", "https://us-south.ml.cloud.ibm.com")
WATSONX_MODEL_ID = "ibm/granite-3-8b-instruct"

VALID_STATUSES = {"IMPLEMENTED", "PARTIAL", "MISSING", "UNCLEAR"}

_iam_token: Optional[str] = None


def _get_iam_token() -> str:
    global _iam_token
    if _iam_token:
        return _iam_token
    data = urllib.parse.urlencode({
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey": WATSONX_API_KEY,
    }).encode()
    req = urllib.request.Request(
        "https://iam.cloud.ibm.com/identity/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        _iam_token = json.loads(r.read())["access_token"]
    return _iam_token


# ── Codebase indexing (keyword → files) ──────────────────────────────────────

def _build_index(snapshot: dict) -> dict[str, list[str]]:
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


# ── watsonx.ai call ───────────────────────────────────────────────────────────

def _ask_llm(prompt: str) -> str:
    """Call IBM Granite via watsonx.ai and return the raw generated text."""
    if not WATSONX_API_KEY or not WATSONX_SPACE_ID:
        return "STATUS: UNCLEAR\nREASON: IFM_TARGET_API_KEY or IFM_TARGET_SPACE_ID not set in .env"
    try:
        token   = _get_iam_token()
        payload = json.dumps({
            "model_id":  WATSONX_MODEL_ID,
            "space_id":  WATSONX_SPACE_ID,
            "input":     prompt,
            "parameters": {
                "decoding_method": "greedy",
                "max_new_tokens":  120,
                "stop_sequences":  ["\n\n"],
            },
        }).encode()
        req = urllib.request.Request(
            f"{WATSONX_URL}/ml/v1/text/generation?version=2023-05-29",
            data=payload,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
        return result["results"][0]["generated_text"].strip()
    except Exception as e:
        return f"STATUS: UNCLEAR\nREASON: watsonx error — {e}"


def _parse_response(raw: str) -> tuple[str, str]:
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
    index   = _build_index(snapshot)
    results = []
    for ticket in tickets:
        rel_files  = _relevant_files(ticket, snapshot, index)
        evidence   = _format_evidence(rel_files, snapshot.get("dependencies", []))
        prompt     = _build_prompt(ticket, evidence)
        raw        = _ask_llm(prompt)
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
