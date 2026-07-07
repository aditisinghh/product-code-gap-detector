"""
ingest_codebase.py
==================
Clones (or reuses a cached clone of) any public GitHub repo and extracts
a structured snapshot of the codebase for the gap detector:

  - File tree (filtered to source files)
  - Function / class names per file (Python AST; filename-only for others)
  - Inline comments and docstrings (strong signals for feature intent)
  - requirements.txt / package.json dependencies
"""

import ast
import os
import re
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

CACHE_DIR = Path(os.getenv("REPO_CACHE_DIR", "./repo_cache"))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# File extensions to inspect
SOURCE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rb", ".rs"}
SKIP_DIRS   = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}


def _repo_slug(url: str) -> str:
    """Turn a GitHub URL into a safe directory name."""
    path = urlparse(url).path.strip("/")
    return re.sub(r"[^a-zA-Z0-9_-]", "_", path)


def clone_or_update(repo_url: str) -> Path:
    """Clone a repo the first time; pull on subsequent calls."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    slug = _repo_slug(repo_url)
    dest = CACHE_DIR / slug

    # Inject token for private repos
    auth_url = repo_url
    if GITHUB_TOKEN and "github.com" in repo_url:
        auth_url = repo_url.replace("https://", f"https://{GITHUB_TOKEN}@")

    if dest.exists():
        subprocess.run(["git", "-C", str(dest), "pull", "--ff-only"],
                       capture_output=True, timeout=60)
    else:
        subprocess.run(["git", "clone", "--depth=1", auth_url, str(dest)],
                       check=True, capture_output=True, timeout=120)
    return dest


# ── Python-specific extraction ────────────────────────────────────────────────

def _extract_python(path: Path) -> dict:
    """Parse a Python file and return symbols + docstrings."""
    try:
        source = path.read_text(errors="ignore")
        tree   = ast.parse(source)
    except SyntaxError:
        return {"symbols": [], "docstrings": [], "comments": []}

    symbols   = []
    docstrings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
            doc = ast.get_docstring(node)
            if doc:
                docstrings.append(doc[:300])

    # Inline comments
    comments = re.findall(r"#\s*(.+)", source)
    return {
        "symbols":    symbols,
        "docstrings": docstrings[:10],
        "comments":   comments[:20],
    }


def _extract_generic(path: Path) -> dict:
    """For non-Python files: extract function/class names via regex and comments."""
    try:
        source = path.read_text(errors="ignore")
    except Exception:
        return {"symbols": [], "docstrings": [], "comments": []}

    # JS/TS/Go/Java function/class patterns
    symbols = re.findall(
        r"(?:function|def|class|func|public|private|export\s+(?:default\s+)?(?:function|class))\s+([A-Za-z_]\w*)",
        source
    )
    comments = re.findall(r"(?://|#)\s*(.+)", source)
    return {
        "symbols":    list(dict.fromkeys(symbols))[:40],
        "docstrings": [],
        "comments":   comments[:20],
    }


# ── Dependency extraction ─────────────────────────────────────────────────────

def _load_deps(root: Path) -> list[str]:
    deps = []
    req = root / "requirements.txt"
    if req.exists():
        deps += [l.split("==")[0].split(">=")[0].strip()
                 for l in req.read_text().splitlines() if l.strip() and not l.startswith("#")]
    pkg = root / "package.json"
    if pkg.exists():
        import json
        try:
            data = json.loads(pkg.read_text())
            deps += list(data.get("dependencies", {}).keys())
            deps += list(data.get("devDependencies", {}).keys())
        except Exception:
            pass
    return deps


# ── Main entry point ──────────────────────────────────────────────────────────

def snapshot(repo_url: str) -> dict:
    """
    Clone the repo and return a structured snapshot:
    {
      "repo_url": ...,
      "files": [
        { "path": "...", "symbols": [...], "docstrings": [...], "comments": [...] }
      ],
      "dependencies": [...],
      "file_tree": [...]
    }
    """
    root  = clone_or_update(repo_url)
    files = []
    tree  = []

    for p in sorted(root.rglob("*")):
        # Skip hidden / build dirs
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if not p.is_file():
            continue

        rel = str(p.relative_to(root))
        tree.append(rel)

        if p.suffix in SOURCE_EXTS and p.stat().st_size < 200_000:
            if p.suffix == ".py":
                info = _extract_python(p)
            else:
                info = _extract_generic(p)
            files.append({"path": rel, **info})

    return {
        "repo_url":     repo_url,
        "files":        files,
        "dependencies": _load_deps(root),
        "file_tree":    tree[:200],   # cap for prompt size
    }
