"""cover_status queue helpers for editorial cover self-heal.

See docs/superpowers/specs/2026-08-07-cover-self-heal-pipeline-design.md §5.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Exact Playwright compose output from cover_compose.py (COVER_W, COVER_H).
EDITORIAL_SIZE = (1200, 630)


def normalize_cover_status(raw: Any) -> str:
    """Return none|failed|done; missing/unknown → none."""
    val = str(raw or "").strip().lower()
    if val in {"none", "failed", "done"}:
        return val
    return "none"


def local_cover_path(blog_root: str, slug: str) -> str:
    return os.path.join(blog_root, "images", f"{slug}.jpg")


def has_usable_cover(fm: dict, blog_root: str, slug: str) -> bool:
    """True when FM image points at this slug's local jpg and the file exists."""
    image = str(fm.get("image") or "").strip()
    if not image:
        return False
    allowed = {f"/blog-images/{slug}.jpg", f"images/{slug}.jpg"}
    if image not in allowed:
        return False
    return os.path.isfile(local_cover_path(blog_root, slug))


def cover_dimensions(blog_root: str, slug: str) -> tuple[int, int] | None:
    """Return on-disk (width, height), or None if missing/unreadable."""
    path = local_cover_path(blog_root, slug)
    if not os.path.isfile(path):
        return None
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size
    except Exception:  # noqa: BLE001 — corrupt/unreadable → not editorial
        return None


def is_editorial_cover(fm: dict, blog_root: str, slug: str) -> bool:
    """True when on-disk cover is exactly the editorial compose size (1200×630).

    Does NOT use origin==bot or image_prompt text — those are unreliable.
    cover_status: failed eligibility short-circuit lives in is_eligible, not here.
    """
    if not has_usable_cover(fm, blog_root, slug):
        return False
    return cover_dimensions(blog_root, slug) == EDITORIAL_SIZE


def is_eligible(fm: dict, blog_root: str, slug: str) -> bool:
    """Heal enrollment per spec §5.2."""
    status = normalize_cover_status(fm.get("cover_status"))
    if status == "failed":
        return True
    return not is_editorial_cover(fm, blog_root, slug)


def selection_tier(fm: dict, blog_root: str, slug: str) -> int:
    """0=failed, 1=missing image, 2=wrong-template/unknown."""
    status = normalize_cover_status(fm.get("cover_status"))
    if status == "failed":
        return 0
    if not has_usable_cover(fm, blog_root, slug):
        return 1
    return 2


def parse_post_date(fm: dict) -> str:
    """Return YYYY-MM-DD-ish string for sorting; missing → far future so they sort last within tier? Spec says oldest first — missing date should sort as very old or last.

    Use '9999-99-99' for missing so dated posts heal first; unknown undated stay at end of tier.
    """
    raw = str(fm.get("date") or "").strip().strip("'\"")
    if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
        return raw[:10]
    return "9999-99-99"


def sort_eligible(rows: list[dict]) -> list[dict]:
    """Sort dicts with keys: slug, fm, tier, date."""
    return sorted(
        rows,
        key=lambda r: (r["tier"], r["date"], r["slug"]),
    )


def classify_for_seed(fm: dict, blog_root: str, slug: str) -> str:
    """Return seeded_done | eligible_wrong_size | eligible_missing | already_done."""
    status = normalize_cover_status(fm.get("cover_status"))
    if is_editorial_cover(fm, blog_root, slug):
        if status == "done":
            return "already_done"
        return "seeded_done"
    if not has_usable_cover(fm, blog_root, slug):
        return "eligible_missing"
    return "eligible_wrong_size"


def drop_fm_keys(lines: list[str], key_names: tuple[str, ...]) -> list[str]:
    """Remove FM keys and any indented continuation lines that follow them.

    Covers both explicit `|`/`>` block scalars (yaml_utils.yaml_safe_value)
    and PyYAML's own implicit line-wrapping of long plain scalars
    (content_repair.py's yaml.safe_dump) — neither of these FM keys is ever
    nested, so any indented line after a matched key is a continuation, not
    a sibling key.
    """
    prefixes = tuple(f"{k}:" for k in key_names)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        matched = next((p for p in prefixes if line.startswith(p)), None)
        if matched is None:
            out.append(line)
            i += 1
            continue
        i += 1
        while i < len(lines) and (
            lines[i].startswith(" ") or lines[i].startswith("\t")
        ):
            i += 1
    return out


def set_cover_status_in_fm_lines(lines: list[str], status: str) -> list[str]:
    """Insert or replace cover_status in a list of FM lines (no ---)."""
    out = drop_fm_keys(lines, ("cover_status",))
    insert_at = next(
        (i + 1 for i, l in enumerate(out) if l.startswith("author:")),
        len(out),
    )
    return out[:insert_at] + [f"cover_status: {status}"] + out[insert_at:]


def upsert_cover_fields(
    mdx_text: str,
    *,
    cover_status: str,
    image: str | None = None,
    image_alt: str | None = None,
    image_prompt: str | None = None,
) -> str:
    """Patch front-matter cover fields; body unchanged. Overwrites image* when provided."""
    if not mdx_text.startswith("---\n"):
        raise ValueError("no front-matter block at start of document")
    try:
        end = mdx_text.index("\n---\n", 4)
    except ValueError as e:
        raise ValueError("unterminated front-matter block") from e

    fm = mdx_text[4:end]
    rest = mdx_text[end:]  # \n---\n + body
    lines = fm.split("\n")

    # Drop cover_status always; also drop image* (incl. block scalars) when installing a new cover.
    drop_keys: tuple[str, ...] = ("cover_status",)
    if image is not None:
        drop_keys = ("image", "image_alt", "image_prompt", "cover_status")
    kept = drop_fm_keys(lines, drop_keys)

    from yaml_utils import yaml_safe_value

    block: list[str] = []
    if image is not None:
        # yaml_safe_value may emit a multi-line `|` block; join as FM lines.
        for key, val in (
            ("image", image),
            ("image_alt", image_alt or ""),
            ("image_prompt", image_prompt or ""),
        ):
            rendered = f"{key}: {yaml_safe_value(val)}"
            block.extend(rendered.split("\n"))
    block.append(f"cover_status: {cover_status}")

    insert_at = next(
        (i + 1 for i, l in enumerate(kept) if l.startswith("tags:")),
        None,
    )
    if insert_at is None:
        insert_at = next(
            (i for i, l in enumerate(kept) if l.startswith("source_url:")),
            len(kept),
        )

    new_fm = "\n".join(kept[:insert_at] + block + kept[insert_at:])
    return "---\n" + new_fm + rest
