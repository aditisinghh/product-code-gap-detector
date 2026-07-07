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

    path_to_file = {f["path"]: f for f in snapshot["files"]}
    top_paths = sorted(scores, key=scores.__getitem__, reverse=True)[:8]
    result = [path_to_file[p] for p in top_paths if p in path_to_file]

    # Always include the largest file (usually the main API/app file) — it
    # contains most endpoints and the keyword index often misses it.
    if snapshot["files"]:
        largest = max(snapshot["files"], key=lambda f: len(f.get("symbols", [])))
        if largest["path"] not in {f["path"] for f in result}:
            result.insert(0, largest)

    return result[:10]


def _format_evidence(files: list[dict], deps: list[str]) -> str:
    """Compact evidence: one line per file listing ALL its symbols."""
    lines = []
    for f in files:
        syms = ", ".join(f["symbols"]) or "—"
        lines.append(f"- {f['path']}: {syms}")
    if deps:
        lines.append(f"dependencies: {', '.join(deps[:20])}")
    return "\n".join(lines) if lines else "(no matching source files found)"


def _build_prompt(ticket: dict, evidence: str) -> str:
    # Extract all function names from evidence for explicit mention
    fn_names = re.findall(r"[\w]+_[\w]+|upload_\w+|get_\w+|post_\w+", evidence)
    fn_list = ", ".join(fn_names[:30]) if fn_names else "see evidence"

    return (
        f"You are reviewing source code. The following functions exist in the codebase:\n"
        f"{fn_list}\n\n"
        f"Full file evidence:\n{evidence[:1200]}\n\n"
        f"Ticket to evaluate:\n"
        f"Title: {ticket['title']}\n"
        f"Description: {ticket['description'][:250]}\n\n"
        f"IMPORTANT: If a function name in the evidence matches what the ticket describes, "
        f"classify as IMPLEMENTED. Do NOT say MISSING if a relevant function exists.\n\n"
        f"Respond with exactly two lines, no other text:\n"
        f"STATUS: IMPLEMENTED\n"
        f"REASON: [because function X exists / no matching function found]\n\n"
        f"Replace IMPLEMENTED with PARTIAL or MISSING only if truly warranted."
    )


# ── watsonx.ai call ───────────────────────────────────────────────────────────

def _ask_llm(prompt: str) -> str:
    """Call IBM Granite via watsonx.ai and return the raw generated text."""
    if not WATSONX_API_KEY:
        print("❌  IFM_TARGET_API_KEY is not set in .env")
        return "STATUS: UNCLEAR\nREASON: IFM_TARGET_API_KEY not set in .env"
    if not WATSONX_SPACE_ID:
        print("❌  IFM_TARGET_SPACE_ID is not set in .env")
        return "STATUS: UNCLEAR\nREASON: IFM_TARGET_SPACE_ID not set in .env"
    try:
        token = _get_iam_token()
        payload = json.dumps({
            "model_id":  WATSONX_MODEL_ID,
            "space_id":  WATSONX_SPACE_ID,
            "input":     prompt,
            "parameters": {
                "decoding_method": "greedy",
                "max_new_tokens":  80,
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
            raw_bytes = r.read()
        result = json.loads(raw_bytes)
        text = result["results"][0]["generated_text"].strip()
        print(f"✅  watsonx response: {text[:120]}")
        return text
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        print(f"❌  watsonx HTTP {e.code}: {body[:300]}")
        return f"STATUS: UNCLEAR\nREASON: watsonx HTTP {e.code} — {body[:200]}"
    except Exception as e:
        print(f"❌  watsonx error: {e}")
        return f"STATUS: UNCLEAR\nREASON: watsonx error — {e}"


def _parse_response(raw: str) -> tuple[str, str]:
    # Strip markdown fences and ANSI codes the model sometimes emits
    cleaned = re.sub(r"```[\s\S]*?```", "", raw)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\x1b\[[0-9;]*m", "", cleaned).strip()

    status = "UNCLEAR"
    reason = "No reasoning returned."

    status_match = re.search(r"STATUS:\s*(IMPLEMENTED|PARTIAL|MISSING|UNCLEAR)", cleaned, re.IGNORECASE)
    reason_match = re.search(r"REASON:\s*(.+)", cleaned, re.IGNORECASE)

    if status_match:
        status = status_match.group(1).upper()

    if reason_match:
        reason = reason_match.group(1).strip()
    elif cleaned and not status_match:
        # Model returned something but not in the expected format — try to infer
        lower = cleaned.lower()
        if "implement" in lower and "not" not in lower[:30]:
            status, reason = "IMPLEMENTED", cleaned[:120]
        elif "partial" in lower or "some" in lower:
            status, reason = "PARTIAL", cleaned[:120]
        elif "missing" in lower or "no " in lower or "not found" in lower:
            status, reason = "MISSING", cleaned[:120]
        else:
            reason = cleaned[:120]

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
