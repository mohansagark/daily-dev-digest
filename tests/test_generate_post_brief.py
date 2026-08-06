import json

import generate_digest as gd
from generate_digest import generate_post, GENERATE_KEYS

STRATEGY = {"focus": ["css", "js"], "style": "energetic", "description": "Frontend"}
ARTICLE = {"title": "T", "link": "http://x", "content": "body " * 50, "author": "A"}


def test_dry_run_has_required_keys_without_image_brief():
    out = generate_post(ARTICLE, STRATEGY, dry_run=True)
    for k in GENERATE_KEYS:
        assert k in out
    assert "image_brief" not in out


def test_image_brief_not_in_generate_keys():
    assert "image_brief" not in GENERATE_KEYS


def test_generate_template_omits_image_brief():
    assert "image_brief" not in gd.GENERATE_USER_TEMPLATE


def test_malformed_extra_image_brief_ignored(monkeypatch):
    # Extra keys from the model are fine; we no longer normalize image_brief.
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
    assert out["headline"] == "H"
    assert out.get("image_brief") == "oops"  # untouched; unused by cover path
