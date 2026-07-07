"""
report.py
=========
Formats the gap analysis results into structured output.
Returns both a JSON-serialisable dict and a self-contained HTML string.
"""

from datetime import datetime
from typing import Any

STATUS_META = {
    "IMPLEMENTED": {"color": "#16a34a", "bg": "#f0fdf4", "icon": "✅"},
    "PARTIAL":     {"color": "#d97706", "bg": "#fffbeb", "icon": "⚠️"},
    "MISSING":     {"color": "#dc2626", "bg": "#fef2f2", "icon": "❌"},
    "UNCLEAR":     {"color": "#6b7280", "bg": "#f9fafb", "icon": "❓"},
}

PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2, "Unknown": 3}


def build_json_report(results: list[dict], repo_url: str, meta: dict = {}) -> dict:
    """Return a JSON-serialisable report dict."""
    counts = {s: 0 for s in STATUS_META}
    for r in results:
        counts[r["gap_status"]] = counts.get(r["gap_status"], 0) + 1

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "repo_url":     repo_url,
        "meta":         meta,
        "summary":      counts,
        "total":        len(results),
        "gaps":         sorted(results,
                               key=lambda x: (
                                   # Missing/Partial first, then by priority
                                   0 if x["gap_status"] in ("MISSING", "PARTIAL") else 1,
                                   PRIORITY_ORDER.get(x["priority"], 3)
                               )),
    }


def build_html_report(report: dict) -> str:
    """Render the report as a self-contained HTML page."""
    s   = report["summary"]
    total = report["total"]
    repo  = report["repo_url"]
    ts    = report["generated_at"]

    # Summary bar
    def pct(n):
        return round(n / total * 100) if total else 0

    summary_html = "".join(f"""
        <div class="stat-card" style="border-left:4px solid {STATUS_META[k]['color']}">
          <div class="stat-icon">{STATUS_META[k]['icon']}</div>
          <div class="stat-val">{v}</div>
          <div class="stat-label">{k.capitalize()}</div>
          <div class="stat-pct">{pct(v)}%</div>
        </div>""" for k, v in s.items())

    # Gap rows
    rows_html = ""
    for g in report["gaps"]:
        m = STATUS_META.get(g["gap_status"], STATUS_META["UNCLEAR"])
        labels = " ".join(f'<span class="label">{l}</span>' for l in g.get("labels", []))
        files  = ", ".join(g.get("evidence_files", [])[:4]) or "—"
        rows_html += f"""
        <tr style="background:{m['bg']}">
          <td class="td-id">{g['id']}</td>
          <td>{g['title']}</td>
          <td><span class="badge" style="color:{m['color']};border-color:{m['color']}">{m['icon']} {g['gap_status']}</span></td>
          <td>{g['jira_status']}</td>
          <td>{g['priority']}</td>
          <td class="td-reason">{g['reason']}</td>
          <td class="td-files">{files}</td>
          <td>{labels}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Product–Code Gap Report</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system,"Segoe UI",system-ui,sans-serif; font-size:14px;
          line-height:1.6; background:#f7f8fa; color:#1f2328; }}
  .container {{ max-width:1100px; margin:0 auto; padding:24px 16px; }}
  h1 {{ font-size:20px; font-weight:700; margin-bottom:4px; }}
  .meta {{ font-size:12px; color:#57606a; margin-bottom:24px; }}
  .stats {{ display:flex; gap:12px; margin-bottom:28px; flex-wrap:wrap; }}
  .stat-card {{ flex:1; min-width:120px; background:#fff; border:1px solid #e5e7eb;
                border-radius:8px; padding:14px 16px; display:flex; flex-direction:column;
                align-items:center; gap:2px; }}
  .stat-icon {{ font-size:20px; }}
  .stat-val  {{ font-size:28px; font-weight:700; }}
  .stat-label{{ font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:#57606a; }}
  .stat-pct  {{ font-size:12px; color:#57606a; }}
  table {{ width:100%; border-collapse:collapse; background:#fff;
           border:1px solid #e5e7eb; border-radius:8px; overflow:hidden; }}
  th {{ background:#f7f8fa; padding:8px 10px; text-align:left; font-size:11px;
        text-transform:uppercase; letter-spacing:.05em; color:#57606a;
        border-bottom:1px solid #e5e7eb; white-space:nowrap; }}
  td {{ padding:8px 10px; vertical-align:top; border-bottom:1px solid #f0f0f0; font-size:13px; }}
  tr:last-child td {{ border-bottom:none; }}
  .badge {{ display:inline-block; font-size:11px; font-weight:600; padding:2px 8px;
            border:1px solid; border-radius:12px; white-space:nowrap; }}
  .label {{ display:inline-block; font-size:10px; background:#e5e7eb; color:#374151;
             border-radius:4px; padding:1px 5px; margin:1px; }}
  .td-id {{ font-family:monospace; white-space:nowrap; color:#3b82d4; font-size:12px; }}
  .td-reason {{ max-width:260px; font-size:12px; color:#374151; }}
  .td-files  {{ max-width:200px; font-size:11px; color:#57606a; word-break:break-all; }}
  footer {{ margin-top:32px; padding-top:12px; border-top:1px solid #e5e7eb;
            text-align:center; font-size:12px; color:#57606a; }}
</style>
</head>
<body>
<div class="container">
  <h1>Product–Code Gap Report</h1>
  <div class="meta">Repo: <strong>{repo}</strong> &nbsp;·&nbsp; Generated: {ts} &nbsp;·&nbsp; {total} tickets analysed</div>
  <div class="stats">{summary_html}</div>
  <table>
    <thead>
      <tr>
        <th>ID</th><th>Title</th><th>Gap Status</th><th>Jira Status</th>
        <th>Priority</th><th>Bob's Reasoning</th><th>Evidence Files</th><th>Labels</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
  <footer>Made with IBM Bob</footer>
</div>
</body>
</html>"""
