from pathlib import Path

from PIL import Image

import cover_status as cs


def _write_jpeg(path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (10, 20, 30)).save(path, "JPEG")


def _write_post(root: Path, slug: str, fm_lines: list[str], body: str = "## Hi\n\ntext\n"):
    posts = root / "posts"
    posts.mkdir(parents=True, exist_ok=True)
    (root / "images").mkdir(parents=True, exist_ok=True)
    fm = "\n".join(fm_lines)
    (posts / f"{slug}.mdx").write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")


def test_wrong_size_800_not_editorial(tmp_path: Path):
    slug = "square-flux"
    _write_post(
        tmp_path,
        slug,
        [
            "title: Old",
            f"slug: {slug}",
            "date: '2025-01-01'",
            f"image: /blog-images/{slug}.jpg",
            "image_prompt: soft-focus photo of a keyboard",
            "cover_status: none",
        ],
    )
    _write_jpeg(tmp_path / "images" / f"{slug}.jpg", (800, 800))
    fm = {
        "image": f"/blog-images/{slug}.jpg",
        "image_prompt": "soft-focus photo of a keyboard",
        "cover_status": "none",
    }
    assert cs.cover_dimensions(str(tmp_path), slug) == (800, 800)
    assert cs.is_editorial_cover(fm, str(tmp_path), slug) is False
    assert cs.is_eligible(fm, str(tmp_path), slug) is True
    assert cs.selection_tier(fm, str(tmp_path), slug) == 2
    assert cs.classify_for_seed(fm, str(tmp_path), slug) == "eligible_wrong_size"


def test_wrong_size_1024_not_editorial(tmp_path: Path):
    slug = "square-1024"
    fm = {
        "image": f"/blog-images/{slug}.jpg",
        "image_prompt": "anything",
        "cover_status": "none",
    }
    _write_jpeg(tmp_path / "images" / f"{slug}.jpg", (1024, 1024))
    assert cs.is_editorial_cover(fm, str(tmp_path), slug) is False
    assert cs.classify_for_seed(fm, str(tmp_path), slug) == "eligible_wrong_size"


def test_editorial_1200x630_counts_as_editorial(tmp_path: Path):
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
    _write_jpeg(tmp_path / "images" / f"{slug}.jpg", cs.EDITORIAL_SIZE)
    fm = {
        "image": f"/blog-images/{slug}.jpg",
        "image_prompt": prompt,
        "cover_status": "none",
    }
    assert cs.is_editorial_cover(fm, str(tmp_path), slug) is True
    assert cs.is_eligible(fm, str(tmp_path), slug) is False
    assert cs.classify_for_seed(fm, str(tmp_path), slug) == "seeded_done"


def test_schematic_prompt_irrelevant_when_dimensions_wrong(tmp_path: Path):
    """Prompt denylist is gone — only pixels matter."""
    slug = "old-schematic"
    fm = {
        "image": f"/blog-images/{slug}.jpg",
        "image_prompt": "Isometric technical illustration with schematic diagram",
        "cover_status": "none",
    }
    _write_jpeg(tmp_path / "images" / f"{slug}.jpg", (800, 800))
    assert cs.is_editorial_cover(fm, str(tmp_path), slug) is False
    assert not hasattr(cs, "prompt_is_schematic")


def test_failed_always_eligible_even_with_editorial_image(tmp_path: Path):
    slug = "x"
    fm = {
        "image": "/blog-images/x.jpg",
        "image_prompt": "soft-focus photo of a laptop",
        "cover_status": "failed",
    }
    _write_jpeg(tmp_path / "images" / "x.jpg", cs.EDITORIAL_SIZE)
    assert cs.is_editorial_cover(fm, str(tmp_path), slug) is True
    assert cs.is_eligible(fm, str(tmp_path), slug) is True
    assert cs.selection_tier(fm, str(tmp_path), slug) == 0


def test_missing_image_not_editorial():
    fm = {"cover_status": "none"}
    assert cs.is_editorial_cover(fm, "/tmp", "nope") is False
    assert cs.selection_tier(fm, "/tmp", "nope") == 1
    assert cs.classify_for_seed(fm, "/tmp", "nope") == "eligible_missing"


def test_already_done_bucket(tmp_path: Path):
    slug = "done-post"
    fm = {
        "image": f"/blog-images/{slug}.jpg",
        "cover_status": "done",
    }
    _write_jpeg(tmp_path / "images" / f"{slug}.jpg", cs.EDITORIAL_SIZE)
    assert cs.classify_for_seed(fm, str(tmp_path), slug) == "already_done"
    assert cs.is_eligible(fm, str(tmp_path), slug) is False


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


def test_upsert_replaces_multiline_image_prompt_without_orphans():
    mdx = """---
title: T
tags: ["a"]
image: /blog-images/t.jpg
image_alt: old
image_prompt: |
  line one of brief
  line two of brief
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
        image_prompt="single line brief",
    )
    assert "line one of brief" not in out
    assert "line two of brief" not in out
    assert "single line brief" in out
    assert "cover_status: done" in out
    # cover_status must be a plain scalar, not polluted by orphan continuations
    fm = out.split("---\n", 2)[1]
    status_line = next(l for l in fm.split("\n") if l.startswith("cover_status:"))
    assert status_line.strip() == "cover_status: done"


def test_upsert_roundtrips_multiline_prompt_then_overwrite():
    mdx = """---
title: T
tags: ["a"]
author: Mohan Sagar
cover_status: none
---
body
"""
    mid = cs.upsert_cover_fields(
        mdx,
        cover_status="done",
        image="/blog-images/t.jpg",
        image_alt="alt",
        image_prompt="first line\nsecond line",
    )
    assert "image_prompt: |" in mid
    assert "  first line" in mid
    out = cs.upsert_cover_fields(
        mid,
        cover_status="done",
        image="/blog-images/t.jpg",
        image_alt="alt2",
        image_prompt="replacement only",
    )
    assert "first line" not in out
    assert "second line" not in out
    assert "replacement only" in out


def test_upsert_seed_does_not_splice_into_block_tags_list():
    """Regression: seed inserted cover_status between tags: and - items."""
    import yaml

    mdx = """---
title: T
tags:
- llm
- open-source
- commercial
image: /blog-images/t.jpg
image_prompt: soft-focus photo
author: Mohan Sagar
---
body
"""
    out = cs.upsert_cover_fields(mdx, cover_status="done")
    fm = yaml.safe_load(out.split("---\n", 2)[1])
    assert fm["cover_status"] == "done"
    assert fm["tags"] == ["llm", "open-source", "commercial"]
    # cover_status must not sit between tags: and the first list item
    fm_text = out.split("---\n", 2)[1]
    tags_i = fm_text.index("tags:\n")
    first_item_i = fm_text.index("\n- llm")
    status_i = fm_text.index("cover_status:")
    assert not (tags_i < status_i < first_item_i)


def test_upsert_strips_pyyaml_implicit_line_wrap_without_orphans():
    """content_repair.py writes FM via yaml.safe_dump, which line-wraps long
    plain scalars with no `|`/`>` marker — drop_fm_keys must still treat the
    indented continuation as part of the value, not leave it as an orphan
    line that YAML then folds into the next key's scalar."""
    import yaml

    mdx = """---
title: T
tags: ["a"]
image: /blog-images/t.jpg
image_alt: old
image_prompt: An off-center soft-focus editorial photograph of a vintage analog computer
  terminal glowing warmly in a dim room, shot on 35mm film with shallow depth of field
  and visible grain texture throughout the frame
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
        image_prompt="single line brief",
    )
    assert "terminal glowing" not in out
    assert "single line brief" in out
    fm = yaml.safe_load(out.split("---\n", 2)[1])
    assert fm["cover_status"] == "done"
