import os
from pathlib import Path

import cover_status as cs


def _write_post(root: Path, slug: str, fm_lines: list[str], body: str = "## Hi\n\ntext\n"):
    posts = root / "posts"
    posts.mkdir(parents=True, exist_ok=True)
    (root / "images").mkdir(parents=True, exist_ok=True)
    fm = "\n".join(fm_lines)
    (posts / f"{slug}.mdx").write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")


def test_schematic_prompt_not_editorial(tmp_path: Path):
    slug = "old-schematic"
    _write_post(
        tmp_path,
        slug,
        [
            "title: Old",
            "slug: old-schematic",
            "date: '2025-01-01'",
            "image: /blog-images/old-schematic.jpg",
            "image_prompt: Isometric technical illustration with schematic diagram and layered depth",
            "cover_status: none",
        ],
    )
    (tmp_path / "images" / f"{slug}.jpg").write_bytes(b"\xff\xd8\xfffake")
    fm = {
        "image": "/blog-images/old-schematic.jpg",
        "image_prompt": "Isometric technical illustration with schematic diagram and layered depth",
        "cover_status": "none",
    }
    assert cs.prompt_is_schematic(fm["image_prompt"])
    assert cs.is_editorial_cover(fm, str(tmp_path), slug) is False
    assert cs.is_eligible(fm, str(tmp_path), slug) is True
    assert cs.selection_tier(fm, str(tmp_path), slug) == 2


def test_editorial_photo_brief_counts_as_done_signal(tmp_path: Path):
    slug = "nav-llm"
    prompt = "An off-center, soft-focus image of a vintage analog computer"
    _write_post(
        tmp_path,
        slug,
        [
            "title: Nav",
            f"slug: {slug}",
            "date: '2025-08-07'",
            f"image: /blog-images/{slug}.jpg",
            f"image_prompt: {prompt}",
            "cover_status: none",
        ],
    )
    (tmp_path / "images" / f"{slug}.jpg").write_bytes(b"\xff\xd8\xfffake")
    fm = {
        "image": f"/blog-images/{slug}.jpg",
        "image_prompt": prompt,
        "cover_status": "none",
    }
    assert cs.is_editorial_cover(fm, str(tmp_path), slug) is True
    assert cs.is_eligible(fm, str(tmp_path), slug) is False
    assert cs.classify_for_seed(fm, str(tmp_path), slug) == "seeded_done"


def test_failed_always_eligible_even_with_image(tmp_path: Path):
    slug = "x"
    fm = {
        "image": "/blog-images/x.jpg",
        "image_prompt": "soft-focus photo of a laptop",
        "cover_status": "failed",
    }
    (tmp_path / "images").mkdir(parents=True, exist_ok=True)
    (tmp_path / "images" / "x.jpg").write_bytes(b"\xff\xd8\xfffake")
    assert cs.is_eligible(fm, str(tmp_path), slug) is True
    assert cs.selection_tier(fm, str(tmp_path), slug) == 0


def test_missing_image_tier():
    fm = {"cover_status": "none"}
    assert cs.selection_tier(fm, "/tmp", "nope") == 1


def test_sort_tiers_then_date():
    rows = [
        {"slug": "b", "tier": 2, "date": "2025-01-01"},
        {"slug": "a", "tier": 0, "date": "2025-06-01"},
        {"slug": "c", "tier": 1, "date": "2024-01-01"},
        {"slug": "d", "tier": 0, "date": "2025-01-01"},
    ]
    ordered = [r["slug"] for r in cs.sort_eligible(rows)]
    assert ordered == ["d", "a", "c", "b"]


def test_upsert_sets_failed_without_touching_image():
    mdx = """---
title: T
tags: ["a"]
image: /blog-images/t.jpg
image_alt: alt
image_prompt: prompt here
source_url: https://example.com
author: Mohan Sagar
cover_status: none
---
## Body

text
"""
    out = cs.upsert_cover_fields(mdx, cover_status="failed")
    assert "cover_status: failed" in out
    assert "image: /blog-images/t.jpg" in out
    assert "## Body" in out


def test_upsert_overwrites_image_on_success():
    mdx = """---
title: T
tags: ["a"]
image: /blog-images/t.jpg
image_alt: old
image_prompt: old prompt isometric schematic
author: Mohan Sagar
cover_status: none
---
body
"""
    out = cs.upsert_cover_fields(
        mdx,
        cover_status="done",
        image="/blog-images/t.jpg",
        image_alt="new alt",
        image_prompt="soft-focus photo brief",
    )
    assert "cover_status: done" in out
    assert "new alt" in out
    assert "soft-focus photo brief" in out
    assert "isometric" not in out
