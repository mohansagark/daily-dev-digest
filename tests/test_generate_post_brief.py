import json

import generate_digest as gd
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


def test_non_dict_image_brief_normalized_to_empty(monkeypatch):
    # LLM #1 returns all hard-required keys but a malformed (non-dict)
    # image_brief; generate_post must soft-normalize it to {} rather than fail.
    raw = json.dumps({
        "headline": "H",
        "subtitle": "S",
        "meta_description": "M",
        "tags": ["css", "js"],
        "image_brief": "oops",
        "body_markdown": "## Body\n\ntext",
    })
    monkeypatch.setattr(gd.bedrock_client, "converse", lambda *a, **k: raw)
    out = generate_post(ARTICLE, STRATEGY, dry_run=False)
    assert isinstance(out["image_brief"], dict)
    assert out["image_brief"] == {}
