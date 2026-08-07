"""Web search adapter for content repair grounding notes."""
from __future__ import annotations

import os
import requests

DEFAULT_URL = os.getenv("SEARCH_API_URL", "")  # vendor endpoint; set in Actions secrets


def format_notes(results):
    lines = []
    for i, r in enumerate(results or [], 1):
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        snippet = (r.get("snippet") or "").strip()
        lines.append(f"{i}. {title}\n   URL: {url}\n   {snippet}")
    return "\n".join(lines)


def search(query, *, max_results=5):
    """Return list[{title,url,snippet}]. Requires SEARCH_API_KEY (+ URL)."""
    key = os.getenv("SEARCH_API_KEY")
    url = os.getenv("SEARCH_API_URL") or DEFAULT_URL
    if not key or not url:
        raise RuntimeError("SEARCH_API_KEY and SEARCH_API_URL must be set for search")
    # Vendor-shaped POST; adapt body/parse to the chosen API at implement time
    # but keep this function's return contract stable.
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"query": query, "max_results": max_results},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    raw = data.get("results") or data.get("organic") or []
    out = []
    for item in raw[:max_results]:
        out.append({
            "title": item.get("title") or item.get("name") or "",
            "url": item.get("url") or item.get("link") or "",
            "snippet": item.get("snippet") or item.get("content") or "",
        })
    return out
