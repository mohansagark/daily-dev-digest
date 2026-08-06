"""Content repair helpers — origin heuristic and junk delete gate."""

from __future__ import annotations


def _non_empty(value) -> bool:
    return bool(str(value or "").strip())


def detect_origin(fm: dict) -> str:
    """Return ``bot`` when both ``image`` and ``image_prompt`` are present; else ``scraper``."""
    if _non_empty(fm.get("image")) and _non_empty(fm.get("image_prompt")):
        return "bot"
    return "scraper"


def should_delete(verdict: str, confidence: str) -> bool:
    """Delete only high-confidence junk (spec §6 delete policy)."""
    return verdict == "junk" and confidence == "high"
