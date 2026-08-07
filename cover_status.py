"""cover_status queue helpers for editorial cover self-heal.

See docs/superpowers/specs/2026-08-07-cover-self-heal-pipeline-design.md §5.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Old schematic / isometric FLUX briefs (wrong template for heal enrollment).
SCHEMATIC_DENYLIST = (
    "isometric",
    "schematic",
    "node diagram",
    "geometric forms",
    "layered depth",
    "precise geometric",
    "clean linework",
)


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


def prompt_is_schematic(image_prompt: str) -> bool:
    blob = (image_prompt or "").lower()
    return any(token in blob for token in SCHEMATIC_DENYLIST)


def is_editorial_cover(fm: dict, blog_root: str, slug: str) -> bool:
    """True when the post already has an acceptable editorial (non-schematic) cover.

    Does NOT use origin==bot — that only means image+image_prompt exist.
    """
    status = normalize_cover_status(fm.get("cover_status"))
    if status == "done":
        return True
    if not has_usable_cover(fm, blog_root, slug):
        return False
    prompt = str(fm.get("image_prompt") or "")
    if prompt_is_schematic(prompt):
        return False
    if prompt.strip():
        return True
    return False


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
    """Return seeded_done | eligible_schematic | eligible_missing | eligible_unknown | already_done."""
    status = normalize_cover_status(fm.get("cover_status"))
    if status == "done":
        return "already_done"
    if is_editorial_cover(fm, blog_root, slug):
        return "seeded_done"
    if not has_usable_cover(fm, blog_root, slug):
        return "eligible_missing"
    if prompt_is_schematic(str(fm.get("image_prompt") or "")):
        return "eligible_schematic"
    return "eligible_unknown"


def set_cover_status_in_fm_lines(lines: list[str], status: str) -> list[str]:
    """Insert or replace cover_status in a list of FM lines (no ---)."""
    out = []
    seen = False
    for line in lines:
        if line.startswith("cover_status:"):
            if not seen:
                out.append(f"cover_status: {status}")
                seen = True
            continue
        out.append(line)
    if not seen:
        # Prefer after author:, else end
        insert_at = next(
            (i + 1 for i, l in enumerate(out) if l.startswith("author:")),
            len(out),
        )
        out = out[:insert_at] + [f"cover_status: {status}"] + out[insert_at:]
    return out


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

    # Drop cover_status always; also drop image* when installing a new cover.
    skip_prefixes: tuple[str, ...] = ("cover_status:",)
    if image is not None:
        skip_prefixes = (
            "image:",
            "image_alt:",
            "image_prompt:",
            "cover_status:",
        )
    kept = [l for l in lines if not any(l.startswith(p) for p in skip_prefixes)]

    from yaml_utils import yaml_safe_value

    block: list[str] = []
    if image is not None:
        block.extend(
            [
                f"image: {yaml_safe_value(image)}",
                f"image_alt: {yaml_safe_value(image_alt or '')}",
                f"image_prompt: {yaml_safe_value(image_prompt or '')}",
            ]
        )
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
