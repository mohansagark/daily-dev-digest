from generate_digest import build_mdx

STRAT = {"style": "energetic", "description": "Frontend"}
GEN = {"headline": "H", "subtitle": "S", "meta_description": "M", "tags": ["css"]}
VER = {"corrected_body_markdown": "## Body\n\ntext"}
ART = {"link": "http://x", "published": "Fri, 01 Aug 2025 00:00:00 +0000"}


def test_with_cover_emits_image_fields():
    cover = {"image": "/blog-images/h.jpg", "alt": "a prism", "prompt": "a prism. Avoid: x."}
    mdx = build_mdx(ART, STRAT, GEN, VER, "h", cover=cover)
    assert "image: " in mdx and "/blog-images/h.jpg" in mdx
    assert "image_alt: " in mdx and "a prism" in mdx
    assert "image_prompt: " in mdx
    assert "image_suggestion:" not in mdx          # old field is gone


def test_without_cover_emits_no_image_fields():
    mdx = build_mdx(ART, STRAT, GEN, VER, "h", cover=None)
    assert "image:" not in mdx
    assert "image_alt:" not in mdx
    assert "image_suggestion:" not in mdx
