"""
ingest_jira.py
==============
Loads tickets from either:
  - A local mock JSON file (default, no credentials needed)
  - The real Jira REST API (set JIRA_* vars in .env)

Each ticket is normalised to a simple dict:
  { id, title, status, type, priority, description, labels }
"""

import json
import os
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

MOCK_PATH = Path(__file__).parent.parent / "mock_data" / "jira_backlog.json"

JIRA_BASE_URL  = os.getenv("JIRA_BASE_URL", "")
JIRA_EMAIL     = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")


def _normalise(ticket: dict) -> dict:
    """Ensure every ticket has the fields the detector expects."""
    return {
        "id":          ticket.get("id", ""),
        "title":       ticket.get("title") or ticket.get("summary", ""),
        "status":      ticket.get("status", "Unknown"),
        "type":        ticket.get("type", "Story"),
        "priority":    ticket.get("priority", "Medium"),
        "description": ticket.get("description", ""),
        "labels":      ticket.get("labels", []),
    }


def load_mock() -> list[dict]:
    """Load tickets from the bundled mock JSON file."""
    with open(MOCK_PATH) as f:
        raw = json.load(f)
    return [_normalise(t) for t in raw]


def load_jira(project_key: str, max_results: int = 50) -> list[dict]:
    """
    Fetch issues from the real Jira REST API.
    Requires JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN in .env.
    """
    if not all([JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN]):
        raise ValueError("Jira credentials not set — using mock data instead.")

    url = f"{JIRA_BASE_URL}/rest/api/3/search"
    params = {
        "jql":        f"project={project_key} ORDER BY created DESC",
        "maxResults": max_results,
        "fields":     "summary,status,issuetype,priority,description,labels",
    }
    resp = httpx.get(url, params=params,
                     auth=(JIRA_EMAIL, JIRA_API_TOKEN), timeout=15)
    resp.raise_for_status()
    issues = resp.json().get("issues", [])
    tickets = []
    for issue in issues:
        f = issue.get("fields", {})
        desc_content = f.get("description") or {}
        # Jira Cloud returns Atlassian Document Format — extract plain text
        plain = _adf_to_text(desc_content) if isinstance(desc_content, dict) else str(desc_content)
        tickets.append(_normalise({
            "id":          issue["key"],
            "title":       f.get("summary", ""),
            "status":      f.get("status", {}).get("name", ""),
            "type":        f.get("issuetype", {}).get("name", "Story"),
            "priority":    f.get("priority", {}).get("name", "Medium"),
            "description": plain,
            "labels":      f.get("labels", []),
        }))
    return tickets


def _adf_to_text(node: dict) -> str:
    """Recursively extract plain text from Atlassian Document Format."""
    if not isinstance(node, dict):
        return str(node)
    if node.get("type") == "text":
        return node.get("text", "")
    return " ".join(_adf_to_text(c) for c in node.get("content", []))


def load_tickets(use_mock: bool = True, project_key: str = "PROJ") -> list[dict]:
    """Entry point: returns ticket list from mock or real Jira."""
    if use_mock or not JIRA_API_TOKEN:
        return load_mock()
    return load_jira(project_key)
