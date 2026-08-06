from PIL import Image
import io

import cover_compose as cc

HOOK = {
    "headline": "THE DETAIL HIDING IN PLAIN SIGHT",
    "subtitle": "WHAT THE SUMMARY NEVER MENTIONS",
    "pill": ["Clarity", "Depth", "Craft"],
    "photo_brief": "desk scene",
    "tone": "muted_color",
}


def test_compose_cover_dimensions_and_jpeg():
    jpeg = cc.compose_cover(HOOK, photo_bytes=None)
    img = Image.open(io.BytesIO(jpeg))
    assert img.format == "JPEG"
    assert img.size == (1200, 630)


def test_pill_text_format():
    assert "✓ Clarity" in cc._pill_text(HOOK)
