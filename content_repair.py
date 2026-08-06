"""Content repair helpers — origin heuristic, junk gate, FM splice, ledger."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any


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


def _parse_mdx_text(text: str) -> tuple[dict, str]:
    import yaml  # local import: only MDX helpers need PyYAML

    if not text.startswith("---\n"):
        raise ValueError("no front-matter block at start of document")
    try:
        end = text.index("\n---\n", 4)
    except ValueError as e:
        raise ValueError("unterminated front-matter block") from e
    fm = yaml.safe_load(text[4:end]) or {}
    body = text[end + 5 :]
    return fm, body


def load_mdx(path: str) -> tuple[dict, str]:
    """Load front matter and body from an ``.mdx`` file."""
    with open(path, encoding="utf-8") as f:
        return _parse_mdx_text(f.read())


def dump_mdx(fm: dict, body: str) -> str:
    """Serialize front matter and body to MDX text."""
    import yaml  # local import: only MDX helpers need PyYAML

    fm_yaml = yaml.safe_dump(
        fm,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).rstrip("\n")
    return f"---\n{fm_yaml}\n---\n{body}"


def apply_kept_frontmatter(fm: dict, *, origin: str, image_suggestion: str) -> dict:
    """Return FM with repair stamps for kept posts; preserve existing ``source_url`` only."""
    out = dict(fm)
    out["ai"] = True
    out["origin"] = origin
    out["author"] = "Mohan Sagar"
    out["cover_status"] = "none"
    out["image_suggestion"] = image_suggestion
    return out


def _local_cover_path(blog_root: str, slug: str) -> str:
    return os.path.join(blog_root, "images", f"{slug}.jpg")


def maybe_delete_local_cover(blog_root: str, fm: dict, slug: str) -> bool:
    """Delete ``images/{slug}.jpg`` only when FM ``image`` is a local slug cover path."""
    image = str(fm.get("image") or "").strip()
    if not image or image.startswith(("http://", "https://")):
        return False
    allowed = {f"/blog-images/{slug}.jpg", f"images/{slug}.jpg"}
    if image not in allowed:
        return False
    path = _local_cover_path(blog_root, slug)
    if not os.path.isfile(path):
        return False
    os.remove(path)
    return True


def body_hash(body: str) -> str:
    """Stable hash for ledger idempotency (matches digest helper)."""
    return hashlib.md5(body.encode("utf-8")).hexdigest()


DEFAULT_LEDGER_PATH = os.path.join(os.path.dirname(__file__), "repair_ledger.json")


class Ledger:
    """Durable idempotency store keyed by slug + input body hash."""

    def __init__(self, path: str | None = None):
        self.path = path or DEFAULT_LEDGER_PATH

    def load(self) -> dict[str, Any]:
        if not os.path.isfile(self.path):
            return {}
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    def save(self, data: dict[str, Any]) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")

    def should_skip(self, slug: str, body: str, *, force: bool = False) -> bool:
        if force:
            return False
        entry = self.load().get(slug)
        if not isinstance(entry, dict):
            return False
        return entry.get("body_hash") == body_hash(body)

    def record(self, slug: str, body: str, **fields: Any) -> None:
        data = self.load()
        entry = dict(fields)
        entry["body_hash"] = body_hash(body)
        data[slug] = entry
        self.save(data)
