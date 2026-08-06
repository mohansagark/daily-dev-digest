import content_repair as cr
import repair_prompts as rp


def test_origin_bot_requires_image_and_prompt():
    assert cr.detect_origin({"image": "/blog-images/x.jpg", "image_prompt": "desk"}) == "bot"
    assert cr.detect_origin({"image": "/blog-images/x.jpg"}) == "scraper"
    assert cr.detect_origin({}) == "scraper"


def test_delete_only_high_junk():
    assert cr.should_delete("junk", "high") is True
    assert cr.should_delete("junk", "medium") is False
    assert cr.should_delete("rewrite", "high") is False


def test_generate_prompt_has_no_source_url_slot():
    assert "SOURCE_URL" not in rp.GENERATE_USER_TEMPLATE
    assert "always attribute the original source" not in rp.GENERATE_SYSTEM_PROMPT.lower()
