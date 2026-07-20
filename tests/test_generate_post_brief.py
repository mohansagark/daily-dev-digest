from generate_digest import generate_post, GENERATE_KEYS

STRATEGY = {"focus": ["css", "js"], "style": "energetic", "description": "Frontend"}
ARTICLE = {"title": "T", "link": "http://x", "content": "body " * 50, "author": "A"}


def test_dry_run_includes_image_brief_dict():
    out = generate_post(ARTICLE, STRATEGY, dry_run=True)
    assert isinstance(out["image_brief"], dict)
    assert out["image_brief"].get("subject")            # mock provides a subject


def test_image_brief_not_hard_required():
    # image_brief must stay OUT of the fail-loud required keys.
    assert "image_brief" not in GENERATE_KEYS
